"""P9.9 — live smoke opt-in contra fuentes OPERATIONALIZABLE.

Solo se ejecuta con ``--live`` (o ``CA_ES_LIVE_SMOKE=1``). Nunca en
CI normal: depende de la disponibilidad real de CNMV/BME/Portfolio.

Registra SOLO metadatos seguros (ids, hashes, counts, statuses) —
nunca bytes raw, que son LOCAL_ONLY por policy.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from ca_es.ops_state import OpsState
from ca_es.sources.live import bme, cnmv, portfolio
from ca_es.sources.live.bme import BmeAdapter
from ca_es.sources.live.cnmv import CnmvAdapter
from ca_es.sources.live.portfolio import PortfolioAdapter

pytestmark = pytest.mark.live

NET = {"timeout": 60, "retries": 2,
       "politeness": 0.4, "max_bytes": 32 * 1024 * 1024}
MAX_DOCS = 3

_REPORT: dict = {}


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat(
    ).replace("+00:00", "Z")


def _sample_fetch(state, discovery, fetch):
    """Fetch byte-exacto de una muestra acotada -> blob store."""
    fetched = []
    for doc in discovery.documents[:MAX_DOCS]:
        payload = doc.inline_content
        if payload is None and doc.locator:
            payload = fetch(doc.locator, referer=doc.locator).content
        if payload is None:
            continue
        blob = state.store_blob(payload)
        assert state.get_blob(blob["sha256"]) == payload
        fetched.append({
            "source_document_id": doc.source_document_id,
            "content_sha256": blob["sha256"],
            "byte_length": blob["byte_length"],
        })
    return fetched


def test_live_bme(tmp_path):
    fetch = bme.live_fetcher(**NET)
    discovery = BmeAdapter().discover(fetch)
    _REPORT["BME_GROWTH"] = {
        "complete": discovery.complete,
        "pages_fetched": discovery.pages_fetched,
        "documents": len(discovery.documents),
        "error": discovery.error,
    }
    assert discovery.complete, discovery.error
    state = OpsState(tmp_path / "state").init()
    _REPORT["BME_GROWTH"]["sample"] = _sample_fetch(
        state, discovery, fetch)


def test_live_portfolio(tmp_path):
    fetch = portfolio.live_fetcher(**NET)
    discovery = PortfolioAdapter().discover(fetch)
    _REPORT["PORTFOLIO_STOCK_EXCHANGE"] = {
        "complete": discovery.complete,
        "pages_fetched": discovery.pages_fetched,
        "documents": len(discovery.documents),
        "error": discovery.error,
    }
    assert discovery.complete, discovery.error
    state = OpsState(tmp_path / "state").init()
    _REPORT["PORTFOLIO_STOCK_EXCHANGE"]["sample"] = _sample_fetch(
        state, discovery, fetch)


@pytest.mark.parametrize("portal", ["oir", "ip"])
def test_live_cnmv(tmp_path, portal):
    fetch = cnmv.live_fetcher(portal, **NET)
    hasta = datetime.now(UTC).date()
    desde = hasta - timedelta(days=31)
    discovery = CnmvAdapter(portal).discover(
        fetch, desde=desde.isoformat(), hasta=hasta.isoformat())
    _REPORT[f"CNMV/{portal.upper()}"] = {
        "complete": discovery.complete,
        "pages_fetched": discovery.pages_fetched,
        "documents": len(discovery.documents),
        "dropped_no_identity": discovery.dropped_no_identity,
        "error": discovery.error,
    }
    assert discovery.complete, discovery.error
    state = OpsState(tmp_path / "state").init()
    _REPORT[f"CNMV/{portal.upper()}"]["sample"] = _sample_fetch(
        state, discovery, fetch)


def test_zzz_report(tmp_path, capsys):
    """Ultimo test (orden alfabético): emite el reporte seguro."""
    report = {
        "schema": "CA_ES_LIVE_SMOKE_REPORT_V1",
        "generated_at": _now(),
        "sources": _REPORT,
    }
    path = tmp_path / "live-smoke-report.json"
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    with capsys.disabled():
        print("\n" + json.dumps(report, indent=2, sort_keys=True))
    assert path.is_file()
