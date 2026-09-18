"""P10 — CLI: alert-deliver, delivery-status, delivery-show,
delivery-retry, delivery-abandon."""
from __future__ import annotations

import json

from ca_es.cli import main
from ca_es.ops_alerts import apply_alerts
from ca_es.ops_state import OpsState
from ca_es.semantic_hash import semantic_sha256

NOW = "2026-09-18T10:00:00Z"


def _seed(state):
    payload = {"canonical_event_id": "EV-1", "deadline_type": "T",
               "deadline_date": "2026-09-20", "action_status": "OVERDUE",
               "days_until": -2}
    cand = {
        "alert_key": "DEADLINE_OVERDUE|dk1",
        "category": "DEADLINE_OVERDUE",
        "subject_type": "deadline", "subject_key": "dk1",
        "payload": payload, "evidence_refs": [],
        "semantic_sha256": semantic_sha256(payload)}
    with state.open() as conn:
        apply_alerts(conn, [cand], "r1", set(), now=NOW)


def _write_cfg(tmp_path, delivery):
    cfg = {"schema": "CA_ES_OPS_CONFIG_V1",
           "action_queue": {"window_days": 30, "due_soon_days": 7},
           "delivery": delivery}
    path = tmp_path / "ops.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


def _file_delivery(tmp_path):
    return {"enabled": True, "destinations": [{
        "destination_id": "f1", "adapter": "file", "enabled": True,
        "categories": ["*"],
        "config": {"directory": str(tmp_path / "dlv")}}]}


def test_alert_deliver_and_status(tmp_path, capsys):
    state_dir = tmp_path / "st"
    state = OpsState(state_dir).init()
    _seed(state)
    cfg = _write_cfg(tmp_path, _file_delivery(tmp_path))
    rc = main(["alert-deliver", "--state", str(state_dir),
               "--config", str(cfg)])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == "CA_ES_ALERT_DELIVERY_RESULT_V1"
    assert doc["status"] == "SUCCESS"
    assert doc["succeeded"] == 1

    rc = main(["delivery-status", "--state", str(state_dir),
               "--config", str(cfg)])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == "CA_ES_DELIVERY_STATUS_V1"
    assert doc["status"] == "HEALTHY"
    assert doc["delivered"] == 1


def test_alert_deliver_disabled_config(tmp_path, capsys):
    state_dir = tmp_path / "st"
    state = OpsState(state_dir).init()
    _seed(state)
    cfg = _write_cfg(tmp_path, {"enabled": False})
    rc = main(["alert-deliver", "--state", str(state_dir),
               "--config", str(cfg)])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["status"] == "DISABLED"


def test_alert_deliver_invalid_config_fail_closed(tmp_path, capsys):
    state_dir = tmp_path / "st"
    OpsState(state_dir).init()
    cfg = _write_cfg(tmp_path, {"enabled": True, "bogus": 1})
    rc = main(["alert-deliver", "--state", str(state_dir),
               "--config", str(cfg)])
    assert rc == 2
    doc = json.loads(capsys.readouterr().out)
    assert "unknown_key" in doc["status"]


def test_delivery_show(tmp_path, capsys):
    state_dir = tmp_path / "st"
    state = OpsState(state_dir).init()
    _seed(state)
    cfg = _write_cfg(tmp_path, _file_delivery(tmp_path))
    main(["alert-deliver", "--state", str(state_dir),
          "--config", str(cfg)])
    capsys.readouterr()
    with state.open() as conn:
        dk = conn.execute(
            "SELECT delivery_key FROM deliveries").fetchone()[0]
    rc = main(["delivery-show", "--state", str(state_dir),
               "--delivery-key", dk])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == "CA_ES_DELIVERY_SHOW_V1"
    assert doc["delivery"]["delivery_key"] == dk
    assert doc["attempts"][0]["status"] == "SUCCEEDED"
    assert doc["transitions"]


def test_delivery_show_not_found(tmp_path, capsys):
    state_dir = tmp_path / "st"
    OpsState(state_dir).init()
    rc = main(["delivery-show", "--state", str(state_dir),
               "--delivery-key", "DLV-nope"])
    assert rc == 2
    doc = json.loads(capsys.readouterr().out)
    assert doc["status"] == "DELIVERY_NOT_FOUND"


def test_delivery_retry_and_abandon_cli(tmp_path, capsys):
    state_dir = tmp_path / "st"
    state = OpsState(state_dir).init()
    _seed(state)
    # destino webhook sin URL -> fallo permanente (fail closed)
    cfg = _write_cfg(tmp_path, {
        "enabled": True, "destinations": [{
            "destination_id": "w", "adapter": "webhook",
            "enabled": True, "categories": ["*"], "config": {}}]})
    rc = main(["alert-deliver", "--state", str(state_dir),
               "--config", str(cfg)])
    assert rc == 2  # PARTIAL -> exit 2
    capsys.readouterr()
    with state.open() as conn:
        dk = conn.execute(
            "SELECT delivery_key FROM deliveries").fetchone()[0]
    # retry manual
    rc = main(["delivery-retry", "--state", str(state_dir),
               "--delivery-key", dk, "--actor", "op-cli"])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["status"] == "REQUEUED"
    assert doc["delivery"]["status"] == "PENDING"
    # abandon terminal
    rc = main(["delivery-abandon", "--state", str(state_dir),
               "--delivery-key", dk, "--note", "superseded"])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["delivery"]["status"] == "ABANDONED"
    # ya no reintenta
    rc = main(["delivery-retry", "--state", str(state_dir),
               "--delivery-key", dk])
    assert rc == 2
    doc = json.loads(capsys.readouterr().out)
    assert "ABANDONED" in doc["status"]


def test_delivery_retry_unknown_requires_force(tmp_path, capsys):
    state_dir = tmp_path / "st"
    state = OpsState(state_dir).init()
    _seed(state)
    # siembra directa de una entrega UNKNOWN
    with state.open() as conn:
        conn.execute(
            "INSERT INTO deliveries"
            " (delivery_key, alert_key, alert_state,"
            "  destination_id, adapter_type, generation, status,"
            "  first_created_at) VALUES (?,?,?,?,?,?,?,?)",
            ("DLV-x", "DEADLINE_OVERDUE|dk1", "OPEN", "w", "webhook",
             1, "UNKNOWN_OUTCOME", NOW))
    rc = main(["delivery-retry", "--state", str(state_dir),
               "--delivery-key", "DLV-x"])
    assert rc == 2
    doc = json.loads(capsys.readouterr().out)
    assert "REQUIRES_FORCE" in doc["status"]
    rc = main(["delivery-retry", "--state", str(state_dir),
               "--delivery-key", "DLV-x", "--force-unknown"])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["delivery"]["status"] == "PENDING"


def test_ops_status_includes_delivery_block(tmp_path, capsys):
    state_dir = tmp_path / "st"
    state = OpsState(state_dir).init()
    _seed(state)
    cfg = _write_cfg(tmp_path, _file_delivery(tmp_path))
    main(["alert-deliver", "--state", str(state_dir),
          "--config", str(cfg)])
    capsys.readouterr()
    rc = main(["ops-status", "--state", str(state_dir)])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["delivery"]["status"] == "HEALTHY"
    assert doc["delivery"]["delivered"] == 1
