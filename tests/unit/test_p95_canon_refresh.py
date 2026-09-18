"""P9.5 — tests del canon refresh sobre evidencia acumulada.

Invariantes cubiertas: promocion chosen<-latest, parse failure
preserva chosen, canon = evidencia durable (no la descarga de hoy),
UNCHANGED cuando el conjunto no cambia, diff de eventos.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from ca_es.ops_canon import run_canon_refresh
from ca_es.ops_sources import run_source_refresh
from ca_es.ops_state import OpsState
from ca_es.sources.live.bme import frame_row_bytes

REPO = Path(__file__).resolve().parents[2]
POLICY = REPO / "docs" / "sources" / "source-policy.json"

BME_API = ("https://apiweb.bolsasymercados.es/Market/v1/"
           "EQ/CorporateActions")


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


def _bme_routes(rows_by_kind: dict[str, list[dict]]) -> dict:
    routes = {}
    for kind in (
            "CapitalIncreases", "CapitalReductions", "Dividends",
            "DividendOptions", "Distributions", "Exchanges", "Meetings",
            "Splits", "Takeovers"):
        routes[f"{BME_API}/{kind}"] = json.dumps(
            rows_by_kind.get(kind, [])).encode()
    return routes


BME_ROW = {
    "isin": "ES0105561007",
    "issuerName": "PARLEM TELECOM COMPANYIA DE TELECOMUNICA",
    "admissionDate": "20250113",
    "disbursement": "3.3795",
    "newShares": 5,
    "oldShares": 100,
    "shares": 899250,
    "typeDescription": "CON PRIMA",
    "observations": "AMPL. CAPITAL COMPENSACION CREDITO DIC 24",
    "currency": "EUR",
}

CFG = {"enabled": True, "adapters": {
    "bme_growth": {
        "adapter": "bme", "source_id": "BME_GROWTH",
        "surface_id": "CORPORATE_ACTIONS",
        "enabled": True, "required": False}}}


def _refresh(state, conn, routes, now):
    return run_source_refresh(
        state, conn, CFG,
        fetchers={"bme_growth": fake_fetcher(routes)}, now=now)


def test_first_canon_refresh_promotes_and_builds(tmp_path):
    state = OpsState(tmp_path / "st").init()
    routes = _bme_routes({"CapitalIncreases": [BME_ROW]})
    with state.open() as conn:
        refresh = _refresh(
            state, conn, routes, "2026-10-01T09:00:00Z")
        doc = run_canon_refresh(
            state, conn, policy_path=POLICY,
            source_refresh_id=refresh["refresh_id"],
            now="2026-10-01T09:05:00Z")
    assert doc["schema"] == "CA_ES_CANON_REFRESH_V1"
    assert doc["refresh_status"] == "SUCCESS"
    assert doc["previous_canon_logical_sha256"] is None
    assert doc["new_canon_logical_sha256"]
    assert doc["documents_considered"] == 1
    assert doc["documents_new"] == 1
    assert doc["parse_promotions"][0]["from"] is None
    assert doc["events_added"]
    with state.open() as conn:
        d = state.get_source_document(
            conn, "BME_GROWTH",
            "BMEG-CapitalIncreases-ES0105561007-2025-01-13")
        assert d["chosen_content_sha256"] == d["latest_content_sha256"]
        canon = state.get_artifact(doc["canon_artifact_sha256"])
        assert canon["canon_version"] == "CA_ES_OPERATIONAL_CANON_V1"
        assert canon["corpus_id"] == "live-accumulated"
        assert canon["events"]


def test_identical_rebuild_is_unchanged(tmp_path):
    """Evidencia inalterada => UNCHANGED sin re-ejecutar el pipeline;
    el canon artifact es el MISMO (mismo input ref downstream =>
    SKIPPED_UNCHANGED en el DAG) pero el doc es nuevo y veraz para
    esta invocacion."""
    state = OpsState(tmp_path / "st").init()
    routes = _bme_routes({"CapitalIncreases": [BME_ROW]})
    with state.open() as conn:
        _refresh(state, conn, routes, "2026-10-01T09:00:00Z")
        first = run_canon_refresh(
            state, conn, policy_path=POLICY,
            now="2026-10-01T09:05:00Z")
        second = run_canon_refresh(
            state, conn, policy_path=POLICY,
            now="2026-10-02T09:05:00Z")
    assert second["refresh_status"] == "UNCHANGED"
    assert "EVIDENCE_SET_IDENTICAL" in second["reasons"]
    assert (second["canon_artifact_sha256"]
            == first["canon_artifact_sha256"])
    assert (second["new_canon_logical_sha256"]
            == first["new_canon_logical_sha256"])
    assert second["canon_refresh_id"] != first["canon_refresh_id"]
    assert second["events_added"] == []
    assert second["events_changed"] == []


def test_parse_failure_preserves_chosen_and_canon(tmp_path):
    """latest no parseable: chosen intacto, canon sigue usando la
    evidencia buena previa — nunca 'latest bytes win'."""
    state = OpsState(tmp_path / "st").init()
    routes = _bme_routes({"CapitalIncreases": [BME_ROW]})
    doc_id = "BMEG-CapitalIncreases-ES0105561007-2025-01-13"
    with state.open() as conn:
        _refresh(state, conn, routes, "2026-10-01T09:00:00Z")
        first = run_canon_refresh(
            state, conn, policy_path=POLICY,
            now="2026-10-01T09:05:00Z")
        good_sha = state.get_source_document(
            conn, "BME_GROWTH", doc_id)["chosen_content_sha256"]
        # La fuente cambia los bytes a algo que NO parsea.
        bad = state.store_blob(b"NOT JSON AT ALL {{{")
        d = state.get_source_document(conn, "BME_GROWTH", doc_id)
        state.upsert_source_document(conn, {
            **{k: d[k] for k in (
                "source_id", "surface_id", "source_document_id")},
            "latest_content_sha256": bad["sha256"],
            "last_seen_at": "2026-10-02T09:00:00Z"})
        second = run_canon_refresh(
            state, conn, policy_path=POLICY,
            now="2026-10-02T09:05:00Z")
    assert second["documents_failed"] == 1
    assert second["parse_failures"][0]["document_id"] == doc_id
    assert "PARSE_FAILURES_PRESENT" in second["reasons"]
    # canon identico: la evidencia buena previa sigue en pie
    assert (second["new_canon_logical_sha256"]
            == first["new_canon_logical_sha256"])
    with state.open() as conn:
        d = state.get_source_document(conn, "BME_GROWTH", doc_id)
        assert d["chosen_content_sha256"] == good_sha
        assert d["latest_content_sha256"] == bad["sha256"]
        pr = conn.execute(
            "SELECT parse_status FROM source_parse_results"
            " WHERE source_document_id=? AND content_sha256=?",
            (doc_id, bad["sha256"])).fetchone()
        assert pr["parse_status"] == "PARSE_FAILED"


def test_new_document_produces_canon_delta(tmp_path):
    state = OpsState(tmp_path / "st").init()
    row2 = dict(BME_ROW, isin="ES0200000001",
                issuerName="OTRA SOCIMI SA")
    with state.open() as conn:
        _refresh(state, conn, _bme_routes(
            {"CapitalIncreases": [BME_ROW]}), "2026-10-01T09:00:00Z")
        first = run_canon_refresh(
            state, conn, policy_path=POLICY,
            now="2026-10-01T09:05:00Z")
        _refresh(state, conn, _bme_routes(
            {"CapitalIncreases": [BME_ROW, row2]}),
            "2026-10-02T09:00:00Z")
        second = run_canon_refresh(
            state, conn, policy_path=POLICY,
            now="2026-10-02T09:05:00Z")
    assert second["refresh_status"] == "SUCCESS"
    assert second["documents_new"] == 1
    assert len(second["events_added"]) == 1
    assert (second["new_canon_logical_sha256"]
            != first["new_canon_logical_sha256"])
    assert second["events_unchanged"] == first["events_added"]


def test_changed_document_rebuilds_canon(tmp_path):
    """CONTENT_CHANGED que parsea OK: chosen promociona y el canon
    refleja el cambio via la maquinaria de revisiones."""
    state = OpsState(tmp_path / "st").init()
    row_v2 = dict(BME_ROW, disbursement="4.0000")
    doc_id = "BMEG-CapitalIncreases-ES0105561007-2025-01-13"
    with state.open() as conn:
        _refresh(state, conn, _bme_routes(
            {"CapitalIncreases": [BME_ROW]}), "2026-10-01T09:00:00Z")
        first = run_canon_refresh(
            state, conn, policy_path=POLICY,
            now="2026-10-01T09:05:00Z")
        _refresh(state, conn, _bme_routes(
            {"CapitalIncreases": [row_v2]}), "2026-10-02T09:00:00Z")
        second = run_canon_refresh(
            state, conn, policy_path=POLICY,
            now="2026-10-02T09:05:00Z")
    assert second["documents_changed"] == 1
    with state.open() as conn:
        d = state.get_source_document(conn, "BME_GROWTH", doc_id)
        assert d["chosen_content_sha256"] == d["latest_content_sha256"]
        canon = state.get_artifact(second["canon_artifact_sha256"])
        # El doc sigue siendo uno; los facts se adjudican por
        # revisiones/provenance, no por overwrite.
        assert canon["events"]


def test_canon_uses_accumulated_evidence_not_todays_fetch(tmp_path):
    """Regla de caida: un refresh posterior sin novedades no vacia el
    canon — se reconstruye sobre TODA la evidencia durable."""
    state = OpsState(tmp_path / "st").init()
    with state.open() as conn:
        _refresh(state, conn, _bme_routes(
            {"CapitalIncreases": [BME_ROW]}), "2026-10-01T09:00:00Z")
        first = run_canon_refresh(
            state, conn, policy_path=POLICY,
            now="2026-10-01T09:05:00Z")
        # Segundo refresh: la fuente devuelve enumeracion vacia
        # (documento ausente en ESTE snapshot NO = desaparicion).
        _refresh(state, conn, _bme_routes({}), "2026-10-03T09:00:00Z")
        second = run_canon_refresh(
            state, conn, policy_path=POLICY,
            now="2026-10-03T09:05:00Z")
    assert second["refresh_status"] == "UNCHANGED"
    assert (second["new_canon_logical_sha256"]
            == first["new_canon_logical_sha256"])
    # el canon persistido sigue teniendo los eventos de la evidencia
    # acumulada — no se vacio por la enumeracion vacia de hoy
    with state.open() as conn:
        canon = state.get_artifact(second["canon_artifact_sha256"])
        assert canon["events"]


def test_empty_state_produces_empty_canon(tmp_path):
    state = OpsState(tmp_path / "st").init()
    with state.open() as conn:
        doc = run_canon_refresh(
            state, conn, policy_path=POLICY,
            now="2026-10-01T09:05:00Z")
    assert doc["refresh_status"] == "SUCCESS"
    assert doc["documents_considered"] == 0
    canon = state.get_artifact(doc["canon_artifact_sha256"])
    assert canon["events"] == []
