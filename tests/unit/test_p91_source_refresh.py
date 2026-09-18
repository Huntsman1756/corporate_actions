"""P9.1/P9.2 — tests del orquestador run_source_refresh.

Fetcher inyectable: nada de red. Cubre discovery+fetch+persistencia,
dedup por bytes, CONTENT_CHANGED, DISCOVERY_ONLY, PARTIAL sin avance
de checkpoint y aislamiento de fallos por fuente.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from ca_es.ops_sources import run_source_refresh
from ca_es.ops_state import OpsState
from ca_es.sources.live.bme import BmeAdapter
from ca_es.sources.live.portfolio import PortfolioAdapter


@dataclass
class FakeResp:
    content: bytes
    status: int = 200
    media_type: str = "application/pdf"
    url: str = ""


def fake_fetcher(routes: dict[str, object], calls: list | None = None):
    def fetch(url: str, referer: str | None = None) -> FakeResp:
        if calls is not None:
            calls.append(url)
        value = routes.get(url)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise ConnectionError(f"NO_ROUTE:{url}")
        return FakeResp(content=value, url=url)
    return fetch


BME_API = ("https://apiweb.bolsasymercados.es/Market/v1/"
           "EQ/CorporateActions")


def _bme_routes(rows_by_kind: dict[str, list[dict]]) -> dict:
    routes = {}
    for kind in (
            "CapitalIncreases", "CapitalReductions", "Dividends",
            "DividendOptions", "Distributions", "Exchanges", "Meetings",
            "Splits", "Takeovers"):
        routes[f"{BME_API}/{kind}"] = json.dumps(
            rows_by_kind.get(kind, [])).encode()
    return routes


def _cfg(**adapter_overrides):
    adapters = {
        "bme_growth": {
            "adapter": "bme",
            "source_id": "BME_GROWTH",
            "surface_id": "CORPORATE_ACTIONS",
            "enabled": True, "required": False,
        },
    }
    adapters.update(adapter_overrides)
    return {"enabled": True, "adapters": adapters}


def test_refresh_new_document_persists_blob_obs_doc_checkpoint(
        tmp_path):
    state = OpsState(tmp_path / "st").init()
    routes = _bme_routes({"Dividends": [
        {"ISIN": "ES0100000001", "FechaPago": "2026-10-15",
         "Emisor": "AAA", "Importe": "0.5"},
    ]})
    with state.open() as conn:
        doc = run_source_refresh(
            state, conn, _cfg(),
            fetchers={"bme_growth": fake_fetcher(routes)},
            now="2026-10-01T09:00:00Z")
    assert doc["contract"] == "CA_ES_SOURCE_REFRESH_V1"
    assert doc["status"] == "SUCCESS"
    sr = doc["source_results"][0]
    assert sr["new_documents"] == 1
    assert sr["checkpoint_advanced"] is True

    with state.open() as conn:
        d = state.get_source_document(
            conn, "BME_GROWTH", "BMEG-Dividends-ES0100000001-2026-10-15")
        assert d is not None
        assert d["latest_content_sha256"]
        assert d["chosen_content_sha256"] is None
        payload = state.get_blob(d["latest_content_sha256"])
        assert json.loads(payload)["ISIN"] == "ES0100000001"
        obs = state.list_source_observations(
            conn, source_id="BME_GROWTH")
        assert len(obs) == 1
        assert obs[0]["change_status"] == "NEW_DOCUMENT"
        cp = state.get_checkpoint(
            conn, "BME_GROWTH", "CORPORATE_ACTIONS")
        assert cp is not None
        assert cp["cursor"]["documents_seen"] == 1
        refresh = state.latest_source_refresh(conn)
        assert refresh["refresh_id"] == doc["refresh_id"]


def test_second_refresh_same_bytes_no_duplicate_observation_id(
        tmp_path):
    state = OpsState(tmp_path / "st").init()
    routes = _bme_routes({"Dividends": [
        {"ISIN": "ES0100000001", "FechaPago": "2026-10-15"},
    ]})
    with state.open() as conn:
        doc1 = run_source_refresh(
            state, conn, _cfg(),
            fetchers={"bme_growth": fake_fetcher(routes)},
            now="2026-10-01T09:00:00Z")
        doc2 = run_source_refresh(
            state, conn, _cfg(),
            fetchers={"bme_growth": fake_fetcher(routes)},
            now="2026-10-02T09:00:00Z")
        assert doc2["refresh_id"] != doc1["refresh_id"]
        obs = state.list_source_observations(
            conn, source_id="BME_GROWTH")
        assert len(obs) == 2
        assert obs[1]["change_status"] == "SAME_BYTES"
        d = state.get_source_document(
            conn, "BME_GROWTH", "BMEG-Dividends-ES0100000001-2026-10-15")
        assert d["last_seen_at"] == "2026-10-02T09:00:00Z"
        assert d["first_seen_at"] == "2026-10-01T09:00:00Z"


def test_changed_bytes_same_identity_marks_content_changed(tmp_path):
    state = OpsState(tmp_path / "st").init()
    rows_v1 = [{"ISIN": "ES0100000001", "FechaPago": "2026-10-15",
                "Importe": "0.5"}]
    rows_v2 = [{"ISIN": "ES0100000001", "FechaPago": "2026-10-15",
                "Importe": "0.6"}]
    with state.open() as conn:
        run_source_refresh(
            state, conn, _cfg(),
            fetchers={"bme_growth": fake_fetcher(
                _bme_routes({"Dividends": rows_v1}))},
            now="2026-10-01T09:00:00Z")
        run_source_refresh(
            state, conn, _cfg(),
            fetchers={"bme_growth": fake_fetcher(
                _bme_routes({"Dividends": rows_v2}))},
            now="2026-10-02T09:00:00Z")
        obs = state.list_source_observations(
            conn, source_id="BME_GROWTH")
        assert [o["change_status"] for o in obs] == [
            "NEW_DOCUMENT", "CONTENT_CHANGED"]
        assert obs[0]["content_sha256"] != obs[1]["content_sha256"]
        d = state.get_source_document(
            conn, "BME_GROWTH", "BMEG-Dividends-ES0100000001-2026-10-15")
        # latest = bytes nuevos; chosen permanece sin promover.
        assert d["latest_content_sha256"] == obs[1]["content_sha256"]
        assert d["chosen_content_sha256"] is None
        # ambos blobs conservados — nunca overwrite
        assert state.get_blob(obs[0]["content_sha256"])
        assert state.get_blob(obs[1]["content_sha256"])


def test_fetch_failure_marks_partial_and_freezes_checkpoint(tmp_path):
    state = OpsState(tmp_path / "st").init()
    routes = _bme_routes({"Dividends": [
        {"ISIN": "ES0100000001", "FechaPago": "2026-10-15"},
    ]})
    # BME usa inline_content — para simular fetch failure usamos un
    # adapter cuyo discovery falla a mitad (kind roto).
    routes[f"{BME_API}/Takeovers"] = ConnectionError("BOOM")
    with state.open() as conn:
        doc = run_source_refresh(
            state, conn, _cfg(),
            fetchers={"bme_growth": fake_fetcher(routes)},
            now="2026-10-01T09:00:00Z")
    sr = doc["source_results"][0]
    assert sr["status"] == "PARTIAL"
    assert sr["pagination_complete"] is False
    assert sr["checkpoint_advanced"] is False
    with state.open() as conn:
        assert state.get_checkpoint(
            conn, "BME_GROWTH", "CORPORATE_ACTIONS") is None


def test_document_fetch_failure_keeps_checkpoint(tmp_path):
    """Un doc descubierto cuyo fetch falla => PARTIAL, sin avance."""
    state = OpsState(tmp_path / "st").init()
    index = b'<a href="/markets/portfolio-market/PROD">P</a>'
    product = b'<a href="https://api.portfolio.exchange/poex/document/4733">d</a>'
    routes = {
        "https://www.portfolio.exchange/markets/portfolio-market":
            index,
        "https://www.portfolio.exchange/markets/portfolio-market/PROD":
            product,
        "https://api.portfolio.exchange/poex/document/4733":
            ConnectionError("RESET"),
    }
    cfg = _cfg(portfolio={
        "adapter": "portfolio",
        "source_id": "PORTFOLIO_STOCK_EXCHANGE",
        "surface_id": "PORTFOLIO_MARKET",
        "enabled": True, "required": False,
    })
    cfg["adapters"].pop("bme_growth")
    with state.open() as conn:
        doc = run_source_refresh(
            state, conn, cfg,
            fetchers={"portfolio": fake_fetcher(routes)},
            now="2026-10-01T09:00:00Z")
    sr = doc["source_results"][0]
    assert sr["status"] == "PARTIAL"
    assert sr["fetch_failures"] == 1
    assert sr["checkpoint_advanced"] is False
    with state.open() as conn:
        obs = state.list_source_observations(
            conn, source_id="PORTFOLIO_STOCK_EXCHANGE")
        assert obs[0]["change_status"] == "FETCH_FAILED"
        assert state.get_checkpoint(
            conn, "PORTFOLIO_STOCK_EXCHANGE",
            "PORTFOLIO_MARKET") is None


def test_known_document_not_refetched_marks_discovery_only(tmp_path):
    state = OpsState(tmp_path / "st").init()
    index = b'<a href="/markets/portfolio-market/PROD">P</a>'
    product = b'<a href="https://api.portfolio.exchange/poex/document/4733">d</a>'
    routes = {
        "https://www.portfolio.exchange/markets/portfolio-market":
            index,
        "https://www.portfolio.exchange/markets/portfolio-market/PROD":
            product,
        "https://api.portfolio.exchange/poex/document/4733": b"%PDF",
    }
    cfg = _cfg(portfolio={
        "adapter": "portfolio",
        "source_id": "PORTFOLIO_STOCK_EXCHANGE",
        "surface_id": "PORTFOLIO_MARKET",
        "enabled": True, "required": False,
    })
    cfg["adapters"].pop("bme_growth")
    calls: list = []
    with state.open() as conn:
        run_source_refresh(
            state, conn, cfg,
            fetchers={"portfolio": fake_fetcher(routes, calls)},
            now="2026-10-01T09:00:00Z")
        calls.clear()
        run_source_refresh(
            state, conn, cfg,
            fetchers={"portfolio": fake_fetcher(routes, calls)},
            now="2026-10-02T09:00:00Z")
        # segundo refresh: doc conocido no se re-descarga
        assert "https://api.portfolio.exchange/poex/document/4733" \
            not in calls
        obs = state.list_source_observations(
            conn, source_id="PORTFOLIO_STOCK_EXCHANGE")
        assert [o["change_status"] for o in obs] == [
            "NEW_DOCUMENT", "DISCOVERY_ONLY"]


def test_source_failure_isolated(tmp_path):
    """Una fuente FAILED no contamina las demas."""
    state = OpsState(tmp_path / "st").init()
    bme_routes = _bme_routes({"Dividends": [
        {"ISIN": "ES0100000001", "FechaPago": "2026-10-15"}]})
    portfolio_routes = {
        "https://www.portfolio.exchange/markets/portfolio-market":
            ConnectionError("DOWN"),
    }
    cfg = _cfg(portfolio={
        "adapter": "portfolio",
        "source_id": "PORTFOLIO_STOCK_EXCHANGE",
        "surface_id": "PORTFOLIO_MARKET",
        "enabled": True, "required": False,
    })
    with state.open() as conn:
        doc = run_source_refresh(
            state, conn, cfg,
            fetchers={
                "bme_growth": fake_fetcher(bme_routes),
                "portfolio": fake_fetcher(portfolio_routes)},
            now="2026-10-01T09:00:00Z")
    statuses = {r["source_id"]: r["status"]
                for r in doc["source_results"]}
    assert statuses["BME_GROWTH"] == "SUCCESS"
    assert statuses["PORTFOLIO_STOCK_EXCHANGE"] == "PARTIAL"
    assert doc["status"] == "PARTIAL"
    with state.open() as conn:
        assert state.get_source_document(
            conn, "BME_GROWTH",
            "BMEG-Dividends-ES0100000001-2026-10-15") is not None


def test_no_sources_configured_is_unchanged_not_blocked(tmp_path):
    state = OpsState(tmp_path / "st").init()
    with state.open() as conn:
        doc = run_source_refresh(
            state, conn, {"enabled": True, "adapters": {}},
            fetchers={}, now="2026-10-01T09:00:00Z")
    assert doc["status"] == "UNCHANGED"
    assert doc["source_results"] == []


def test_policy_inactive_source_not_acquired(tmp_path):
    state = OpsState(tmp_path / "st").init()
    routes = _bme_routes({"Dividends": [
        {"ISIN": "ES0100000001", "FechaPago": "2026-10-15"}]})
    calls: list = []
    policy = {"sources": {"BME_GROWTH": {
        "ingestion_status": "SUSPENDED"}}}
    with state.open() as conn:
        doc = run_source_refresh(
            state, conn, _cfg(), policy=policy,
            fetchers={"bme_growth": fake_fetcher(routes, calls)},
            now="2026-10-01T09:00:00Z")
    assert doc["source_results"][0]["status"] == "FAILED"
    assert "POLICY_INGESTION_STATUS" in doc["source_results"][0]["error"]
    assert calls == []


def test_adapter_classes_exposed():
    assert BmeAdapter().surface_id == "CORPORATE_ACTIONS"
    assert PortfolioAdapter().surface_id == "PORTFOLIO_MARKET"
