"""P10.4 — FILE adapter: atomic write, idempotencia por
delivery_key, collision fail-closed."""
from __future__ import annotations

import json

from ca_es.delivery.file_adapter import deliver
from ca_es.ops_delivery import (
    DeliveryRequest, O_FAILED_PERMANENT, O_SUCCEEDED)


def _request(payload: dict | None = None,
             delivery_key: str = "DLV-abc") -> DeliveryRequest:
    doc = payload or {"schema": "CA_ES_ALERT_DELIVERY_PAYLOAD_V1",
                      "alert_key": "DEADLINE_OVERDUE|dk1",
                      "category": "DEADLINE_OVERDUE"}
    return DeliveryRequest(
        delivery_key=delivery_key, alert_key=doc["alert_key"],
        alert_semantic_sha256="aa", alert_state="OPEN",
        adapter_type="file", destination_id="d1", generation=1,
        payload_schema="CA_ES_ALERT_DELIVERY_PAYLOAD_V1",
        payload=doc, created_at="2026-09-18T00:00:00Z",
        payload_bytes=json.dumps(
            doc, sort_keys=True, separators=(",", ":")).encode())


def test_successful_delivery_atomic(tmp_path):
    req = _request()
    res = deliver(req, {"directory": str(tmp_path / "d1")})
    assert res.outcome == O_SUCCEEDED
    target = tmp_path / "d1" / "DLV-abc.json"
    assert target.is_file()
    assert json.loads(target.read_bytes()) == req.payload
    assert res.receipt["sha256"]
    assert not list((tmp_path / "d1").glob(".tmp-*"))


def test_same_delivery_twice_idempotent(tmp_path):
    req = _request()
    cfg = {"directory": str(tmp_path / "d1")}
    first = deliver(req, cfg)
    second = deliver(req, cfg)
    assert first.outcome == O_SUCCEEDED
    assert second.outcome == O_SUCCEEDED
    assert second.receipt["idempotent_replay"] is True


def test_same_key_different_bytes_collision(tmp_path):
    cfg = {"directory": str(tmp_path / "d1")}
    deliver(_request(), cfg)
    other = _request(payload={
        "schema": "CA_ES_ALERT_DELIVERY_PAYLOAD_V1",
        "alert_key": "DEADLINE_OVERDUE|dk1",
        "category": "DEADLINE_OVERDUE",
        "details": {"changed": True}})
    res = deliver(other, cfg)
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "DELIVERY_KEY_COLLISION"


def test_missing_directory_config_fails_closed():
    res = deliver(_request(), {})
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "DESTINATION_NO_DIRECTORY"


def test_unwritable_path_fails_closed(tmp_path):
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("x")
    res = deliver(_request(), {"directory": str(blocker / "sub")})
    assert res.outcome == O_FAILED_PERMANENT


def test_windows_friendly_layout(tmp_path):
    """El path usa delivery_key (DLV-hex) — sin caracteres ilegales
    aunque alert_key contenga '|' u otros."""
    req = _request(delivery_key="DLV-" + "ab" * 32)
    res = deliver(req, {"directory": str(tmp_path / "d")})
    assert res.outcome == O_SUCCEEDED
    assert (tmp_path / "d" / f"{req.delivery_key}.json").is_file()
