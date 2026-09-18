"""P11 — CLI: send-prepare, send-dispatch, send-status, send-show,
send-retry, send-abandon, bloque send en ops-status."""
from __future__ import annotations

import hashlib
import json

from ca_es.cli import main
from ca_es.ops_send import content_sha256_of
from ca_es.ops_state import OpsState

FIN = "{1:F01TEST}{4:\r\n:20C::SEME//INS-0001\r\n-}"
SHA = content_sha256_of(FIN)


def _write_cfg(tmp_path, send):
    cfg = {"schema": "CA_ES_OPS_CONFIG_V1",
           "action_queue": {"window_days": 30, "due_soon_days": 7},
           "send": send}
    path = tmp_path / "ops.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


def _write_msg(tmp_path):
    doc = {"schema": "CA_ES_MT565_FIN_V1", "write_status": "OK",
           "fin": FIN, "fin_sha256": SHA}
    path = tmp_path / "msg.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _send_cfg(tmp_path):
    return {"enabled": True, "destinations": [{
        "destination_id": "gw-1", "adapter": "filespool",
        "enabled": True, "message_schemas": ["*"],
        "config": {"spool_directory": str(tmp_path / "spool")}}],
        "retry": {"max_attempts": 3}}


def _did(tmp_path, state_dir):
    with OpsState(state_dir).open() as conn:
        return conn.execute(
            "SELECT delivery_id FROM sends").fetchone()[0]


def test_send_prepare_dispatch_status(tmp_path, capsys):
    state_dir = tmp_path / "st"
    OpsState(state_dir).init()
    cfg = _write_cfg(tmp_path, _send_cfg(tmp_path))
    msg = _write_msg(tmp_path)

    rc = main(["send-prepare", "--state", str(state_dir),
               "--config", str(cfg), "--message", str(msg),
               "--instruction-id", "INS-0001"])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == "CA_ES_SEND_PREPARE_RESULT_V1"
    assert len(doc["created"]) == 1
    did = doc["created"][0]["delivery_id"]

    # re-prepare idempotente
    rc = main(["send-prepare", "--state", str(state_dir),
               "--config", str(cfg), "--message", str(msg),
               "--instruction-id", "INS-0001"])
    doc = json.loads(capsys.readouterr().out)
    assert doc["created"] == [] and len(doc["existing"]) == 1

    rc = main(["send-dispatch", "--state", str(state_dir),
               "--config", str(cfg)])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == "CA_ES_SEND_RESULT_V1"
    assert doc["status"] == "SUCCESS"
    assert doc["spooled"] == 1
    assert (tmp_path / "spool" / "outbox" / f"{did}.msg").exists()

    rc = main(["send-status", "--state", str(state_dir),
               "--config", str(cfg)])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == "CA_ES_SEND_STATUS_V1"
    assert doc["spooled"] == 1


def test_send_prepare_seme_mismatch_fail_closed(tmp_path, capsys):
    state_dir = tmp_path / "st"
    OpsState(state_dir).init()
    cfg = _write_cfg(tmp_path, _send_cfg(tmp_path))
    msg = _write_msg(tmp_path)
    rc = main(["send-prepare", "--state", str(state_dir),
               "--config", str(cfg), "--message", str(msg),
               "--instruction-id", "INS-9999"])
    assert rc == 2
    doc = json.loads(capsys.readouterr().out)
    assert "MESSAGE_REFERENCE_MISMATCH" in doc["status"]


def test_send_dispatch_invalid_config_fail_closed(tmp_path, capsys):
    state_dir = tmp_path / "st"
    OpsState(state_dir).init()
    bad = _send_cfg(tmp_path)
    bad["bogus_key"] = 1
    cfg = _write_cfg(tmp_path, bad)
    rc = main(["send-dispatch", "--state", str(state_dir),
               "--config", str(cfg)])
    assert rc == 2
    doc = json.loads(capsys.readouterr().out)
    assert "unknown_key" in doc["status"]


def test_send_show(tmp_path, capsys):
    state_dir = tmp_path / "st"
    OpsState(state_dir).init()
    cfg = _write_cfg(tmp_path, _send_cfg(tmp_path))
    msg = _write_msg(tmp_path)
    main(["send-prepare", "--state", str(state_dir),
          "--config", str(cfg), "--message", str(msg),
          "--instruction-id", "INS-0001"])
    main(["send-dispatch", "--state", str(state_dir),
          "--config", str(cfg)])
    capsys.readouterr()
    did = _did(tmp_path, state_dir)
    rc = main(["send-show", "--state", str(state_dir),
               "--delivery-id", did])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == "CA_ES_SEND_SHOW_V1"
    assert doc["send"]["delivery_id"] == did
    assert doc["send"]["message_text"] == FIN
    assert doc["attempts"][0]["status"] == "SUCCEEDED"
    assert doc["transitions"]


def test_send_show_not_found(tmp_path, capsys):
    state_dir = tmp_path / "st"
    OpsState(state_dir).init()
    rc = main(["send-show", "--state", str(state_dir),
               "--delivery-id", "SND-nope"])
    assert rc == 2
    doc = json.loads(capsys.readouterr().out)
    assert doc["status"] == "SEND_NOT_FOUND"


def test_send_retry_and_abandon_cli(tmp_path, capsys):
    state_dir = tmp_path / "st"
    OpsState(state_dir).init()
    cfg = _write_cfg(tmp_path, _send_cfg(tmp_path))
    msg = _write_msg(tmp_path)
    main(["send-prepare", "--state", str(state_dir),
          "--config", str(cfg), "--message", str(msg),
          "--instruction-id", "INS-0001"])
    capsys.readouterr()
    did = _did(tmp_path, state_dir)
    # retry sobre PREPARED -> REQUEUED (sigue PREPARED)
    rc = main(["send-retry", "--state", str(state_dir),
               "--delivery-id", did, "--actor", "op-cli"])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["status"] == "REQUEUED"
    # abandon
    rc = main(["send-abandon", "--state", str(state_dir),
               "--delivery-id", did, "--note", "superseded"])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["send"]["status"] == "ABANDONED"
    # ya no reintenta
    rc = main(["send-retry", "--state", str(state_dir),
               "--delivery-id", did])
    assert rc == 2
    doc = json.loads(capsys.readouterr().out)
    assert "ABANDONED" in doc["status"]


def test_ops_status_includes_send_block(tmp_path, capsys):
    state_dir = tmp_path / "st"
    OpsState(state_dir).init()
    cfg = _write_cfg(tmp_path, _send_cfg(tmp_path))
    msg = _write_msg(tmp_path)
    main(["send-prepare", "--state", str(state_dir),
          "--config", str(cfg), "--message", str(msg),
          "--instruction-id", "INS-0001"])
    main(["send-dispatch", "--state", str(state_dir),
          "--config", str(cfg)])
    capsys.readouterr()
    rc = main(["ops-status", "--state", str(state_dir)])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["send"]["status"] == "DEGRADED"
    assert doc["send"]["spooled"] == 1
