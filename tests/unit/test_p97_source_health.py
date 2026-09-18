"""P9.7 — source health + alertas de fuentes.

Cubre: checks de salud de fuentes (refresh/required/parse/checkpoints),
alertas SOURCE_* en el outbox, UNCHANGED no alerta, run sin sources no
limpia alertas abiertas, required vs optional.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from ca_es.ops_alerts import outbox_all
from ca_es.ops_dag import run_ops
from ca_es.ops_health import compute_health
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
            "Dividends", "CapitalIncreases", "Splits", "Mergers",
            "OtherPayments", "NewListings", "Delistings",
            "PublicOfferings", "TakeoverBids"):
        routes[f"{BME_API}/{kind}"] = json.dumps(
            rows_by_kind.get(kind, [])).encode()
    return routes


def _w(root: Path, name: str, doc: dict) -> str:
    p = root / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return str(p)


def _env(tmp_path, *, required=False, sources_extra=None):
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
            **(sources_extra or {}),
            "adapters": {
                "bme_growth": {
                    "adapter": "bme",
                    "source_id": "BME_GROWTH",
                    "surface_id": "CORPORATE_ACTIONS",
                    "enabled": True, "required": required}}},
    }
    return cfg, OpsState(tmp_path / "state").init()


def _checks(health: dict) -> dict:
    return {c["name"]: c for c in health["checks"]}


def _health(env_state, cfg):
    with env_state.open() as conn:
        return compute_health(
            env_state, conn, cfg, input_docs={},
            as_of=AS_OF, now=f"{AS_OF}T08:00:00Z")


def _alerts(state) -> list[dict]:
    with state.open() as conn:
        return outbox_all(conn)


def _categories(state) -> set[str]:
    return {r["category"] for r in _alerts(state)}


# ------------------------------------------------------------------
# health checks
# ------------------------------------------------------------------

def test_health_sources_not_configured(tmp_path):
    cfg, state = _env(tmp_path)
    cfg["sources"] = {"enabled": False}
    checks = _checks(_health(state, cfg))
    assert checks["source_refresh"]["status"] == "INFO"
    assert checks["source_refresh"]["detail"] == "NOT_CONFIGURED"
    assert "source_required" not in checks


def test_health_no_refresh_yet_degraded(tmp_path):
    cfg, state = _env(tmp_path)
    checks = _checks(_health(state, cfg))
    assert checks["source_refresh"]["status"] == "DEGRADED"
    assert checks["source_refresh"]["detail"] == "NO_REFRESH_YET"


def test_health_successful_refresh_ok(tmp_path):
    cfg, state = _env(tmp_path)
    routes = _bme_routes({"CapitalIncreases": [BME_ROW]})
    run_ops(cfg, state, AS_OF,
            source_fetchers={"bme_growth": fake_fetcher(routes)})
    checks = _checks(_health(state, cfg))
    assert checks["source_refresh"]["status"] == "OK"
    assert checks["source_refresh"]["detail"]["status"] in (
        "SUCCESS", "UNCHANGED")
    assert checks["source_required"]["status"] == "OK"
    assert checks["source_parse_failures"]["status"] == "OK"


def test_health_required_source_failure_fails(tmp_path):
    cfg, state = _env(tmp_path, required=True)
    routes = _bme_routes({"CapitalIncreases": [BME_ROW]})
    for url in list(routes):
        routes[url] = ConnectionError("OUTAGE")
    run_ops(cfg, state, AS_OF,
            source_fetchers={"bme_growth": fake_fetcher(routes)})
    health = _health(state, cfg)
    checks = _checks(health)
    # fallos por categoria -> discovery.error -> PARTIAL por fuente
    assert checks["source_refresh"]["status"] == "DEGRADED"
    assert checks["source_required"]["status"] == "FAILED"
    assert checks["source_required"]["detail"]["degraded"] == [
        "BME_GROWTH/CORPORATE_ACTIONS"]
    assert health["status"] == "FAILED"


def test_health_optional_source_failure_degrades(tmp_path):
    cfg, state = _env(tmp_path, required=False)
    routes = _bme_routes({"CapitalIncreases": [BME_ROW]})
    for url in list(routes):
        routes[url] = ConnectionError("OUTAGE")
    run_ops(cfg, state, AS_OF,
            source_fetchers={"bme_growth": fake_fetcher(routes)})
    checks = _checks(_health(state, cfg))
    assert checks["source_refresh"]["status"] == "DEGRADED"
    assert checks["source_required"]["status"] == "OK"


def test_health_parse_failure_degrades(tmp_path):
    """Doc con latest != chosen cuyo blob no parsea: health DEGRADED
    en source_parse_failures, chosen previo intacto."""
    cfg, state = _env(tmp_path)
    bad = state.store_blob(b"this is not a parseable bme row")
    good = state.store_blob(b"{}")
    with state.open() as conn:
        state.upsert_source_document(conn, {
            "source_id": "BME_GROWTH",
            "surface_id": "CORPORATE_ACTIONS",
            "source_document_id": "BMEG-TEST-1",
            "first_seen_at": "2026-09-10T00:00:00Z",
            "last_seen_at": "2026-09-15T00:00:00Z",
            "latest_content_sha256": bad["sha256"],
            "chosen_content_sha256": good["sha256"],
            "latest_locator": "x", "metadata": {}})
        conn.commit()
    routes = _bme_routes({})  # no redescubre el doc roto
    run_ops(cfg, state, AS_OF,
            source_fetchers={"bme_growth": fake_fetcher(routes)})
    checks = _checks(_health(state, cfg))
    assert checks["source_parse_failures"]["status"] == "DEGRADED"
    assert checks["source_parse_failures"]["detail"]["count"] == 1
    with state.open() as conn:
        row = state.get_source_document(
            conn, "BME_GROWTH", "BMEG-TEST-1")
    assert row["chosen_content_sha256"] == good["sha256"]


def test_health_stale_checkpoint(tmp_path):
    cfg, state = _env(tmp_path)
    cfg["health"] = {"source_checkpoint_max_age_days": 3}
    routes = _bme_routes({"CapitalIncreases": [BME_ROW]})
    run_ops(cfg, state, AS_OF,
            source_fetchers={"bme_growth": fake_fetcher(routes)})
    with state.open() as conn:
        conn.execute(
            "UPDATE source_checkpoints SET updated_at=?",
            ("2026-08-01T00:00:00Z",))
        conn.commit()
    checks = _checks(_health(state, cfg))
    assert checks["source_checkpoints"]["status"] == "DEGRADED"
    assert checks["source_checkpoints"]["detail"]["age_days"] > 3


# ------------------------------------------------------------------
# alertas
# ------------------------------------------------------------------

def test_alert_source_refresh_failed(tmp_path):
    """Fuente policy-gated (REFERENCE_ONLY) -> FAILED sin fetch."""
    cfg, state = _env(tmp_path)
    cfg["sources"]["adapters"] = {
        "iberclear": {
            "adapter": "bme",
            "source_id": "IBERCLEAR",
            "surface_id": "SETTLEMENT",
            "enabled": True, "required": False}}
    run_ops(cfg, state, AS_OF,
            source_fetchers={"iberclear": fake_fetcher({})})
    rows = [r for r in _alerts(state)
            if r["category"] == "SOURCE_REFRESH_FAILED"]
    assert len(rows) == 1
    assert rows[0]["subject_key"] == "IBERCLEAR/SETTLEMENT"
    assert rows[0]["state"] == "OPEN"


def test_alert_partial(tmp_path):
    """Discovery con error aislado -> PARTIAL -> alerta."""
    cfg, state = _env(tmp_path)
    routes = _bme_routes({"CapitalIncreases": [BME_ROW]})
    for url in list(routes):
        routes[url] = ConnectionError("OUTAGE")
    m = run_ops(cfg, state, AS_OF,
                source_fetchers={"bme_growth": fake_fetcher(routes)})
    steps = {s["step_id"]: s for s in m["steps"]}
    doc = state.get_artifact(steps["source_refresh"]["output_sha256"])
    sr = doc["source_results"][0]
    assert sr["status"] == "PARTIAL"
    rows = [r for r in _alerts(state)
            if r["category"] == "SOURCE_PARTIAL"]
    assert len(rows) == 1
    assert rows[0]["subject_key"] == "BME_GROWTH/CORPORATE_ACTIONS"


def test_alert_parse_failed(tmp_path):
    cfg, state = _env(tmp_path)
    bad = state.store_blob(b"not parseable")
    with state.open() as conn:
        state.upsert_source_document(conn, {
            "source_id": "BME_GROWTH",
            "surface_id": "CORPORATE_ACTIONS",
            "source_document_id": "BMEG-BAD-1",
            "first_seen_at": "2026-09-10T00:00:00Z",
            "last_seen_at": "2026-09-15T00:00:00Z",
            "latest_content_sha256": bad["sha256"],
            "latest_locator": "x", "metadata": {}})
        conn.commit()
    routes = _bme_routes({})
    run_ops(cfg, state, AS_OF,
            source_fetchers={"bme_growth": fake_fetcher(routes)})
    rows = [r for r in _alerts(state)
            if r["category"] == "SOURCE_PARSE_FAILED"]
    assert len(rows) == 1
    assert rows[0]["subject_key"] == "BMEG-BAD-1"


def test_alert_content_changed(tmp_path):
    cfg, state = _env(tmp_path)
    routes = _bme_routes({"CapitalIncreases": [BME_ROW]})
    fetchers = {"bme_growth": fake_fetcher(routes)}
    run_ops(cfg, state, AS_OF, source_fetchers=fetchers)
    row2 = dict(BME_ROW, disbursement="3.5")
    routes2 = _bme_routes({"CapitalIncreases": [row2]})
    run_ops(cfg, state, AS_OF,
            source_fetchers={"bme_growth": fake_fetcher(routes2)})
    rows = [r for r in _alerts(state)
            if r["category"] == "SOURCE_CONTENT_CHANGED"]
    assert len(rows) == 1
    payload = json.loads(rows[0]["payload_json"])
    assert payload["from"] != payload["to"]
    assert "not a source error" in payload["notice"]


def test_alert_stale_checkpoint(tmp_path):
    cfg, state = _env(tmp_path,
                      sources_extra={"stale_after_days": 3})
    routes = _bme_routes({"CapitalIncreases": [BME_ROW]})
    fetchers = {"bme_growth": fake_fetcher(routes)}
    run_ops(cfg, state, AS_OF, source_fetchers=fetchers)
    with state.open() as conn:
        conn.execute(
            "UPDATE source_checkpoints SET updated_at=?",
            ("2026-08-01T00:00:00Z",))
        conn.commit()
    run_ops(cfg, state, AS_OF, source_fetchers=fetchers)
    # el run2 re-advance el checkpoint -> no stale; forzar de nuevo
    with state.open() as conn:
        conn.execute(
            "UPDATE source_checkpoints SET updated_at=?",
            ("2026-08-01T00:00:00Z",))
        conn.commit()
    # tercera run sin fetchers reales exitosos: checkpoint no avanza
    routes_bad = _bme_routes({})
    for url in list(routes_bad):
        routes_bad[url] = ConnectionError("DOWN")
    run_ops(cfg, state, AS_OF,
            source_fetchers={"bme_growth": fake_fetcher(routes_bad)})
    rows = [r for r in _alerts(state)
            if r["category"] == "SOURCE_STALE"]
    assert len(rows) == 1
    assert rows[0]["subject_key"] == "BME_GROWTH/CORPORATE_ACTIONS"


def test_unchanged_run_no_source_alerts(tmp_path):
    cfg, state = _env(tmp_path)
    routes = _bme_routes({"CapitalIncreases": [BME_ROW]})
    fetchers = {"bme_growth": fake_fetcher(routes)}
    run_ops(cfg, state, AS_OF, source_fetchers=fetchers)
    run_ops(cfg, state, AS_OF, source_fetchers=fetchers)
    cats = _categories(state)
    # primer run puede tener CONTENT_CHANGED? No: primer chosen ->
    # promotion from=None no alerta. Ninguna alerta SOURCE_*.
    assert not (cats & {
        "SOURCE_REFRESH_FAILED", "SOURCE_PARTIAL",
        "SOURCE_PARSE_FAILED", "SOURCE_STALE"})


def test_recovery_clears_source_alert(tmp_path):
    """Outage -> SOURCE_PARTIAL OPEN; siguiente run OK -> CLEARED."""
    cfg, state = _env(tmp_path)
    bad_routes = _bme_routes({})
    for url in list(bad_routes):
        bad_routes[url] = ConnectionError("OUTAGE")
    run_ops(cfg, state, AS_OF,
            source_fetchers={"bme_growth": fake_fetcher(bad_routes)})
    assert "SOURCE_PARTIAL" in _categories(state)
    ok_routes = _bme_routes({"CapitalIncreases": [BME_ROW]})
    run_ops(cfg, state, AS_OF,
            source_fetchers={"bme_growth": fake_fetcher(ok_routes)})
    rows = [r for r in _alerts(state)
            if r["category"] == "SOURCE_PARTIAL"]
    assert rows[0]["state"] == "CLEARED"


def test_run_without_sources_keeps_open_alerts(tmp_path):
    """Un run sin sources no limpia alertas de fuente abiertas."""
    cfg, state = _env(tmp_path)
    bad_routes = _bme_routes({})
    for url in list(bad_routes):
        bad_routes[url] = ConnectionError("OUTAGE")
    run_ops(cfg, state, AS_OF,
            source_fetchers={"bme_growth": fake_fetcher(bad_routes)})
    assert "SOURCE_PARTIAL" in _categories(state)
    cfg2 = json.loads(json.dumps(cfg))
    cfg2["sources"] = {"enabled": False}
    run_ops(cfg2, state, AS_OF)
    rows = [r for r in _alerts(state)
            if r["category"] == "SOURCE_PARTIAL"]
    assert rows[0]["state"] == "OPEN"
