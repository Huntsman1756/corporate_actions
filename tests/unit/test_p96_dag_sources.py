"""P9.6 — integracion source_refresh/canon_refresh en el DAG P7.

Cubre: orden de steps, canon acumulado inyectado como input efectivo,
SKIPPED_UNCHANGED downstream cuando la evidencia no cambia, fuente en
caida no bloquea el run, sources disabled = no-op exitoso.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from ca_es.ops_dag import run_ops
from ca_es.ops_state import OpsState

REPO = Path(__file__).resolve().parents[2]
CANON = REPO / "g3/input/canon.json"
POLICY = REPO / "docs/sources/source-policy.json"
AS_OF = "2026-09-16"

RULES = {"schema": "CA_ES_DEADLINE_RULES_V1", "rules": [{
    "rule_id": "R1", "deadline_type": "RESPONSE_DEADLINE",
    "source_field": "date.payment_date", "business_days_offset": -1,
    "calendar_id": "TARGET2"}]}
CALS = {"schema": "CA_ES_CALENDARS_V1", "calendars": [{
    "calendar_id": "TARGET2", "business_week": [0, 1, 2, 3, 4],
    "holidays": []}]}
POSITIONS = {"schema": "CA_ES_POSITIONS_V1", "as_of": "2026-05-04",
             "positions": [{"account_id": "A001",
                            "isin": "ES0105561007",
                            "quantity": "100",
                            "as_of": "2026-05-04"}]}

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
            "CapitalIncreases", "CapitalReductions", "Dividends",
            "DividendOptions", "Distributions", "Exchanges", "Meetings",
            "Splits", "Takeovers"):
        routes[f"{BME_API}/{kind}"] = json.dumps(
            rows_by_kind.get(kind, [])).encode()
    return routes


def _w(root: Path, name: str, doc: dict) -> str:
    p = root / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return str(p)


@pytest.fixture()
def env(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    cfg = {
        "schema": "CA_ES_OPS_CONFIG_V1",
        "inputs": {
            "canon": {"path": str(CANON), "required": True},
            "source_policy": {"path": str(POLICY), "required": True},
            "deadline_rules": {"path": _w(inputs, "rules.json", RULES),
                               "required": True},
            "calendars": {"path": _w(inputs, "cals.json", CALS),
                          "required": True},
            "positions": {"path": _w(inputs, "pos.json", POSITIONS)},
            "cash_movements": {"path": _w(inputs, "movs.json", {
                "schema": "CA_ES_CASH_MOVEMENTS_V2",
                "movements": []})},
        },
        "action_queue": {"window_days": 30, "due_soon_days": 7},
        "sources": {
            "enabled": True,
            "adapters": {
                "bme_growth": {
                    "adapter": "bme",
                    "source_id": "BME_GROWTH",
                    "surface_id": "CORPORATE_ACTIONS",
                    "enabled": True, "required": False}}},
    }
    state = OpsState(tmp_path / "state").init()
    return {"cfg": cfg, "state": state, "inputs": inputs}


def _steps(manifest):
    return {s["step_id"]: s for s in manifest["steps"]}


def test_dag_order_includes_source_and_canon_refresh(env):
    routes = _bme_routes({"CapitalIncreases": [BME_ROW]})
    m = run_ops(env["cfg"], env["state"], AS_OF,
                source_fetchers={"bme_growth": fake_fetcher(routes)})
    ids = [s["step_id"] for s in m["steps"]]
    assert ids[:4] == [
        "validate_inputs", "source_refresh",
        "canon_refresh", "process_inbox"]
    assert m["run_status"] == "SUCCEEDED"


def test_accumulated_canon_injected_and_downstream_succeeds(env):
    routes = _bme_routes({"CapitalIncreases": [BME_ROW]})
    m = run_ops(env["cfg"], env["state"], AS_OF,
                source_fetchers={"bme_growth": fake_fetcher(routes)})
    steps = _steps(m)
    assert steps["source_refresh"]["status"] == "SUCCEEDED"
    assert steps["canon_refresh"]["status"] == "SUCCEEDED"
    cr_doc = steps["canon_refresh"]["output_sha256"]
    assert cr_doc
    # el canon acumulado sustituye al input canon efectivo: los
    # pasos downstream consumen el canon nuevo sin bloquearse
    assert steps["compute_deadlines"]["status"] == "SUCCEEDED"
    assert steps["morning_brief_v2"]["status"] == "SUCCEEDED"
    assert steps["entitlements"]["status"] == "SUCCEEDED"


def test_second_run_downstream_skipped_unchanged(env):
    routes = _bme_routes({"CapitalIncreases": [BME_ROW]})
    fetchers = {"bme_growth": fake_fetcher(routes)}
    run_ops(env["cfg"], env["state"], AS_OF,
            source_fetchers=fetchers)
    m2 = run_ops(env["cfg"], env["state"], AS_OF,
                 source_fetchers=fetchers)
    steps = _steps(m2)
    for sid in ("compute_deadlines", "build_action_queue",
                "morning_brief_v2", "entitlements"):
        assert steps[sid]["status"] == "SKIPPED_UNCHANGED", sid
    # canon_refresh hace early-return sin rebuild: el canon artifact
    # referenciado es el MISMO entre runs
    cr1 = env["state"].get_artifact(
        steps["canon_refresh"]["output_sha256"])
    assert cr1["refresh_status"] == "UNCHANGED"
    assert cr1["canon_artifact_sha256"]


def test_source_outage_does_not_block_run(env):
    """Todas las fuentes caidas: refresh PARTIAL pero el run sigue —
    canon se reconstruye sobre evidencia durable (aunque vacia) y
    los pasos downstream no se bloquean."""
    routes = _bme_routes({"CapitalIncreases": [BME_ROW]})
    for url in list(routes):
        routes[url] = ConnectionError("OUTAGE")
    m = run_ops(env["cfg"], env["state"], AS_OF,
                source_fetchers={"bme_growth": fake_fetcher(routes)})
    steps = _steps(m)
    assert steps["source_refresh"]["status"] == "SUCCEEDED"
    doc = env["state"].get_artifact(
        steps["source_refresh"]["output_sha256"])
    assert doc["status"] in ("PARTIAL", "FAILED")
    assert steps["canon_refresh"]["status"] == "SUCCEEDED"
    assert steps["compute_deadlines"]["status"] == "SUCCEEDED"
    assert m["run_status"] == "SUCCEEDED"


def test_sources_disabled_is_successful_noop(env):
    env["cfg"]["sources"] = {"enabled": False}
    m = run_ops(env["cfg"], env["state"], AS_OF)
    steps = _steps(m)
    assert steps["source_refresh"]["status"] == "SUCCEEDED"
    doc = env["state"].get_artifact(
        steps["source_refresh"]["output_sha256"])
    assert doc["enabled"] is False
    assert doc["status"] == "UNCHANGED"
    assert m["run_status"] == "SUCCEEDED"


def test_missing_policy_blocks_acquisition_not_run(tmp_path, env):
    cfg = dict(env["cfg"])
    cfg["inputs"] = {k: v for k, v in env["cfg"]["inputs"].items()
                     if k != "source_policy"}
    m = run_ops(cfg, env["state"], AS_OF)
    steps = _steps(m)
    assert steps["source_refresh"]["status"] == "BLOCKED"
    # canon_refresh tampoco puede correr sin policy path: BLOCKED,
    # pero el resto del DAG sigue sobre el canon de config
    assert steps["canon_refresh"]["status"] == "BLOCKED"
    assert steps["compute_deadlines"]["status"] == "SUCCEEDED"
