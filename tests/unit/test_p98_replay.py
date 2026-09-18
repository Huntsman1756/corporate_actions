"""P9.8 — backfill / replay determinista sobre evidencia almacenada.

Cubre: replay sobre chosen (sin red, sin mutacion, determinista),
filtros por fuente y ventana de fechas, ops-source-status, e
idempotencia de ops-canon-refresh.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from ca_es.ops_canon import replay_canon, run_canon_refresh
from ca_es.ops_read import ops_source_status_doc
from ca_es.ops_sources import run_source_refresh
from ca_es.ops_state import OpsState

REPO = Path(__file__).resolve().parents[2]
POLICY = REPO / "docs/sources/source-policy.json"
NOW = "2026-09-16T09:00:00Z"

BME_API = ("https://apiweb.bolsasymercados.es/Market/v1/"
           "EQ/CorporateActions")
BME_ROW = {
    "isin": "ES0105561007",
    "issuerName": "PARLEM TELECOM COMPANYIA DE TELECOMUNICA",
    "admissionDate": "20250113",
    "disbursement": "3.3795",
    "newShares": 5, "oldShares": 100, "shares": 899250,
    "typeDescription": "CON PRIMA",
    "observations": "AMPL. CAPITAL",
    "currency": "EUR",
}

SOURCES_CFG = {"enabled": True, "adapters": {
    "bme_growth": {
        "adapter": "bme", "source_id": "BME_GROWTH",
        "surface_id": "CORPORATE_ACTIONS",
        "enabled": True, "required": False}}}


@dataclass
class FakeResp:
    content: bytes
    status: int = 200
    media_type: str = "application/json"
    url: str = ""


def fake_fetcher(routes: dict):
    def fetch(url: str, referer: str | None = None) -> FakeResp:
        value = routes.get(url)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise ConnectionError(f"NO_ROUTE:{url}")
        return FakeResp(content=value, url=url)
    return fetch


def _bme_routes(rows_by_kind):
    routes = {}
    for kind in (
            "Dividends", "CapitalIncreases", "Splits", "Mergers",
            "OtherPayments", "NewListings", "Delistings",
            "PublicOfferings", "TakeoverBids"):
        routes[f"{BME_API}/{kind}"] = json.dumps(
            rows_by_kind.get(kind, [])).encode()
    return routes


@pytest.fixture()
def env(tmp_path):
    state = OpsState(tmp_path / "state").init()
    routes = _bme_routes({"CapitalIncreases": [BME_ROW]})
    with state.open() as conn:
        run_source_refresh(
            state, conn, SOURCES_CFG,
            fetchers={"bme_growth": fake_fetcher(routes)}, now=NOW)
        run_canon_refresh(state, conn, policy_path=POLICY, now=NOW)
        conn.commit()
    return state


def test_replay_deterministic_same_evidence(env):
    with env.open() as conn:
        r1 = replay_canon(env, conn, policy_path=POLICY, now=NOW)
        r2 = replay_canon(env, conn, policy_path=POLICY, now=NOW)
    assert r1["schema"] == "CA_ES_SOURCE_REPLAY_V1"
    assert r1["documents"] == 1
    assert (r1["canon"]["logical_sha256"]
            == r2["canon"]["logical_sha256"])
    assert len(r1["canon"]["events"]) >= 1


def test_replay_no_mutation(env):
    """Replay no promueve, no escribe state_meta ni artefactos."""
    with env.open() as conn:
        before_meta = conn.execute(
            "SELECT key, value FROM state_meta").fetchall()
        before_obs = conn.execute(
            "SELECT COUNT(*) c FROM source_observations").fetchone()["c"]
        before_art = conn.execute(
            "SELECT COUNT(*) c FROM artifacts").fetchone()["c"]
        replay_canon(env, conn, policy_path=POLICY, now=NOW)
        after_meta = conn.execute(
            "SELECT key, value FROM state_meta").fetchall()
        assert [(r["key"], r["value"]) for r in after_meta] == [
            (r["key"], r["value"]) for r in before_meta]
        assert conn.execute(
            "SELECT COUNT(*) c FROM source_observations"
        ).fetchone()["c"] == before_obs
        assert conn.execute(
            "SELECT COUNT(*) c FROM artifacts"
        ).fetchone()["c"] == before_art


def test_replay_window_filter(env):
    """Ventana que excluye la fecha del doc -> canon vacio."""
    with env.open() as conn:
        in_window = replay_canon(
            env, conn, policy_path=POLICY,
            from_date="2025-01-01", to_date="2025-12-31", now=NOW)
        out_window = replay_canon(
            env, conn, policy_path=POLICY,
            from_date="2026-01-01", to_date="2026-12-31", now=NOW)
    assert in_window["documents"] == 1
    assert out_window["documents"] == 0
    assert in_window["canon"]["logical_sha256"] != \
        out_window["canon"]["logical_sha256"]


def test_replay_source_filter(env):
    with env.open() as conn:
        none = replay_canon(
            env, conn, policy_path=POLICY,
            source_id="CNMV", now=NOW)
    assert none["documents"] == 0
    assert none["canon"]["events"] == []


def test_replay_equals_current_canon(env):
    """Replay sobre TODO el chosen reproduce el canon apuntado."""
    from ca_es.ops_canon import get_state_meta, _META_CANON_LOGICAL
    with env.open() as conn:
        doc = replay_canon(env, conn, policy_path=POLICY, now=NOW)
        current = get_state_meta(conn, _META_CANON_LOGICAL)
    assert doc["canon"]["logical_sha256"] == current


def test_source_status_doc(env):
    with env.open() as conn:
        doc = ops_source_status_doc(env, conn)
    assert doc["schema"] == "CA_ES_SOURCE_STATUS_V1"
    assert doc["latest_refresh"]["status"] in (
        "SUCCESS", "UNCHANGED")
    src = doc["sources"][0]
    assert src["source_id"] == "BME_GROWTH"
    assert src["documents"] == 1
    assert src["with_chosen"] == 1
    assert src["divergent_latest"] == 0
    assert src["checkpoint"]["updated_at"]


def test_canon_refresh_idempotent_second_run(env):
    with env.open() as conn:
        doc = run_canon_refresh(env, conn, policy_path=POLICY,
                                now="2026-09-16T10:00:00Z")
    assert doc["refresh_status"] == "UNCHANGED"
    assert doc["reasons"] == ["EVIDENCE_SET_IDENTICAL"]


def test_cli_source_status_and_replay(tmp_path, env, capsys):
    from ca_es.cli import main

    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps({
        "schema": "CA_ES_OPS_CONFIG_V1",
        "inputs": {"source_policy": {"path": str(POLICY)}}}),
        encoding="utf-8")
    rc = main(["ops-source-status", "--state", str(env.root)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "CA_ES_SOURCE_STATUS_V1"
    out_path = tmp_path / "canon.json"
    rc = main(["ops-source-replay", "--state", str(env.root),
               "--config", str(cfg_path), "--out", str(out_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["documents"] == 1
    canon = json.loads(out_path.read_text(encoding="utf-8"))
    assert canon["logical_sha256"] == out["canon_logical_sha256"]
