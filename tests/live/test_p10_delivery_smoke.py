"""P10.15 — live smoke opt-in de alert delivery.

Solo con ``--live`` (o ``CA_ES_LIVE_SMOKE=1``). FILE adapter es
suficiente para smoke determinista. Webhook live solo si
``CA_ES_TEST_WEBHOOK_URL`` esta definido (endpoint de test del
operador — nunca datos de negocio, siempre alerta sintetica).

Registra SOLO metadatos seguros.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import pytest

from ca_es.ops_alerts import apply_alerts
from ca_es.ops_delivery import list_attempts, list_deliveries
from ca_es.ops_state import OpsState
from ca_es.semantic_hash import semantic_sha256

pytestmark = pytest.mark.live


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat(
    ).replace("+00:00", "Z")


def _synthetic_alert():
    payload = {"canonical_event_id": "SMOKE-EV-1",
               "deadline_type": "RESPONSE_DEADLINE",
               "deadline_date": "2099-01-01",
               "action_status": "DUE_SOON", "days_until": 7}
    return {
        "alert_key": "DEADLINE_DUE_SOON|smoke-p10",
        "category": "DEADLINE_DUE_SOON",
        "subject_type": "deadline", "subject_key": "smoke-p10",
        "payload": payload, "evidence_refs": [],
        "semantic_sha256": semantic_sha256(payload)}


def _deliver(state, cfg):
    from ca_es.ops_delivery import run_alert_deliver
    conn = state.acquire_run_lock("smoke-deliver")
    try:
        doc = run_alert_deliver(state, conn, cfg)
        state.checkpoint()
    finally:
        state.release_run_lock()
    return doc


def test_file_delivery_smoke(tmp_path):
    """Smoke determinista: seed alerta sintetica -> file -> 2a
    pasada sin duplicado."""
    state = OpsState(tmp_path / "st").init()
    with state.open() as conn:
        apply_alerts(conn, [_synthetic_alert()], "smoke-r1", set(),
                     now=_now())
    cfg = {"enabled": True, "destinations": [{
        "destination_id": "smoke-file", "adapter": "file",
        "enabled": True, "categories": ["*"],
        "config": {"directory": str(tmp_path / "dlv")}}]}
    doc1 = _deliver(state, cfg)
    assert doc1["status"] == "SUCCESS"
    assert doc1["succeeded"] == 1
    files = list((tmp_path / "dlv").glob("DLV-*.json"))
    assert len(files) == 1
    doc2 = _deliver(state, cfg)
    assert doc2["attempted"] == 0
    assert doc2["skipped_delivered"] == 1


def test_webhook_delivery_smoke(tmp_path):
    """Solo si CA_ES_TEST_WEBHOOK_URL definido; alerta sintetica,
    nunca datos de negocio."""
    url = os.environ.get("CA_ES_TEST_WEBHOOK_URL")
    if not url:
        pytest.skip("CA_ES_TEST_WEBHOOK_URL no definido")
    state = OpsState(tmp_path / "st").init()
    with state.open() as conn:
        apply_alerts(conn, [_synthetic_alert()], "smoke-r1", set(),
                     now=_now())
    cfg = {"enabled": True, "destinations": [{
        "destination_id": "smoke-hook", "adapter": "webhook",
        "enabled": True, "categories": ["*"],
        "config": {"url": url, "timeout_seconds": 15,
                   "allow_insecure_http": True}}]}
    doc = _deliver(state, cfg)
    assert doc["attempted"] == 1
    with state.open() as conn:
        d = list_deliveries(conn)[0]
        attempts = list_attempts(conn, d["delivery_key"])
        # reporta solo metadatos seguros
        print(json.dumps({
            "delivery_status": d["status"],
            "attempt_status": attempts[-1]["status"],
            "error_code": attempts[-1]["error_code"]}))
    assert doc["succeeded"] == 1 or doc["failed_retryable"] == 1, \
        f"unexpected delivery outcome: {doc}"
