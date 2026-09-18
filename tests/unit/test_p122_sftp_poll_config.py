"""P12.2/P12.11/P12.12 — polling SFTP (NAK, conflicto, keep,
archive-failure, unknown delivery) + validate_send_config para
los adapters sftp y mq (host verification, credenciales env-only,
claves secretas, dispositions, campos desconocidos).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

paramiko = pytest.importorskip("paramiko")

from test_p121_sftp_adapter import (  # noqa: E402
    FIN, NOW, PW, SHA, SFTPLab, _cfg, _prepared_send)
from ca_es.ops_config import validate_send_config  # noqa: E402
from ca_es.ops_send import (  # noqa: E402
    S_GATEWAY_ACCEPTED, S_GATEWAY_REJECTED, S_SPOOLED,
    get_send, run_send_poll)
from ca_es.ops_state import OpsState  # noqa: E402


@pytest.fixture()
def lab(tmp_path):
    root = tmp_path / "remote"
    root.mkdir()
    lab = SFTPLab(root)
    yield lab
    lab.stop()


@pytest.fixture(autouse=True)
def _pw_env(monkeypatch):
    monkeypatch.setenv("CA_ES_TEST_SFTP_PW", PW)


def _send_cfg(lab, tmp_path, **over):
    return {"enabled": True, "destinations": [{
        "destination_id": "gw-sftp-1", "adapter": "sftp",
        "enabled": True, "message_schemas": ["*"],
        "config": _cfg(lab, tmp_path, **over)}]}


def _remote_receipt(lab, did, kind, doc):
    rdir = lab.root / "receipts"
    rdir.mkdir(exist_ok=True)
    p = rdir / f"{did}.{kind}.json"
    p.write_text(doc if isinstance(doc, str)
                 else json.dumps(doc), encoding="utf-8")
    return p


def _ack(did, **over):
    d = {"schema": "CA_ES_TRANSPORT_RECEIPT_V1", "delivery_id": did,
         "content_sha256": SHA, "status": "ACCEPTED",
         "gateway_reference": "GW-1", "received_at": NOW,
         "reason": None}
    d.update(over)
    return d


def _nak(did, **over):
    d = _ack(did, status="REJECTED", reason="F16",
             gateway_reference="GW-2")
    d.update(over)
    return d


def _poll_setup(tmp_path, lab):
    state = OpsState(tmp_path / "st").init()
    conn = state.acquire_run_lock("t")
    did, send_cfg = _prepared_send(conn, tmp_path, lab)
    conn.execute(
        "UPDATE sends SET status=? WHERE delivery_id=?",
        (S_SPOOLED, did))
    return state, conn, did, send_cfg


# ------------------------------------------------------------------
# polling remoto: NAK / conflicto / keep / archive-failure / unknown
# ------------------------------------------------------------------

def test_remote_nak_receipt_rejects(tmp_path, lab):
    state, conn, did, send_cfg = _poll_setup(tmp_path, lab)
    try:
        _remote_receipt(lab, did, "nak", _nak(did))
        out = run_send_poll(state, conn, send_cfg)
        assert out["status"] == "SUCCESS"
        send = get_send(conn, did)
        assert send["status"] == S_GATEWAY_REJECTED
        assert send["transport_reference"] == "GW-2"
    finally:
        state.release_run_lock()


def test_remote_conflicting_ack_and_nak_quarantined(tmp_path, lab):
    state, conn, did, send_cfg = _poll_setup(tmp_path, lab)
    try:
        _remote_receipt(lab, did, "ack", _ack(did))
        _remote_receipt(lab, did, "nak", _nak(did))
        out = run_send_poll(state, conn, send_cfg)
        assert out["quarantined"] == 2
        assert out["ingested"] == 0
        # nunca se inventa precedencia; estado legitimo intacto
        assert get_send(conn, did)["status"] == S_SPOOLED
        # evidencia remota conservada (no archivada, no borrada)
        rdir = lab.root / "receipts"
        assert (rdir / f"{did}.ack.json").is_file()
        assert (rdir / f"{did}.nak.json").is_file()
    finally:
        state.release_run_lock()


def test_remote_receipt_unknown_delivery_quarantined(tmp_path, lab):
    state, conn, did, send_cfg = _poll_setup(tmp_path, lab)
    try:
        other = "SND-" + "b" * 64
        _remote_receipt(lab, other, "ack", _ack(other))
        out = run_send_poll(state, conn, send_cfg)
        assert out["quarantined"] == 1
        assert out["ingested"] == 0
    finally:
        state.release_run_lock()


def test_keep_disposition_leaves_remote_receipt(tmp_path, lab):
    state = OpsState(tmp_path / "st").init()
    conn = state.acquire_run_lock("t")
    try:
        send_cfg = _send_cfg(
            lab, tmp_path, remote_receipt_disposition="keep")
        doc = {"schema": "CA_ES_MT565_FIN_V1", "write_status": "OK",
               "fin": FIN, "fin_sha256": SHA}
        from ca_es.ops_send import prepare_sends
        res = prepare_sends(conn, doc, "INS-0001", send_cfg, now=NOW)
        did = res["created"][0]["delivery_id"]
        conn.execute(
            "UPDATE sends SET status=? WHERE delivery_id=?",
            (S_SPOOLED, did))
        _remote_receipt(lab, did, "ack", _ack(did))
        out = run_send_poll(state, conn, send_cfg)
        assert out["ingested"] == 1
        # disposition=keep: el remoto queda donde el gateway lo dejo
        assert (lab.root / "receipts" / f"{did}.ack.json").is_file()
        assert not (lab.root / "receipts" / "processed").exists()
        # pero el ledger ya lo registro — segundo poll no re-ingiere
        out2 = run_send_poll(state, conn, send_cfg)
        assert out2["ingested"] == 0
    finally:
        state.release_run_lock()


def test_archive_failure_keeps_ingestion(tmp_path, lab, monkeypatch):
    from ca_es.transport import sftp as sftp_adapter
    monkeypatch.setattr(
        sftp_adapter, "archive_remote_receipt",
        lambda cfg, name: (_ for _ in ()).throw(IOError("down")))
    state, conn, did, send_cfg = _poll_setup(tmp_path, lab)
    try:
        _remote_receipt(lab, did, "ack", _ack(did))
        out = run_send_poll(state, conn, send_cfg)
        # archive best-effort: la ingestion local ya es evidencia
        assert out["ingested"] == 1
        assert get_send(conn, did)["status"] == S_GATEWAY_ACCEPTED
    finally:
        state.release_run_lock()


def test_remote_duplicate_receipt_idempotent(tmp_path, lab):
    state, conn, did, send_cfg = _poll_setup(tmp_path, lab)
    try:
        _remote_receipt(lab, did, "ack", _ack(did))
        out1 = run_send_poll(state, conn, send_cfg)
        assert out1["ingested"] == 1
        # el gateway vuelve a depositar el MISMO receipt
        _remote_receipt(lab, did, "ack", _ack(did))
        out2 = run_send_poll(state, conn, send_cfg)
        assert out2["ingested"] == 0
        assert get_send(conn, did)["status"] == S_GATEWAY_ACCEPTED
    finally:
        state.release_run_lock()


# ------------------------------------------------------------------
# validate_send_config: sftp
# ------------------------------------------------------------------

def _base_dest(adapter, config):
    return {"enabled": True, "destinations": [{
        "destination_id": "d1", "adapter": adapter,
        "enabled": True, "message_schemas": ["*"],
        "config": config}]}


def _sftp_cfg(**over):
    cfg = {
        "host": "sftp.example.test", "username": "svc",
        "password_env": "SFTP_PW",
        "host_key_fingerprint": "a" * 64,
        "remote_outbox": "/out", "remote_receipts": "/rcpts",
        "local_receipt_staging": "/tmp/stage"}
    cfg.update(over)
    return cfg


def test_sftp_config_valid_minimal():
    validate_send_config(_base_dest("sftp", _sftp_cfg()))


def test_sftp_config_requires_host_verification():
    cfg = _sftp_cfg()
    del cfg["host_key_fingerprint"]
    with pytest.raises(ValueError, match="missing_host_verification"):
        validate_send_config(_base_dest("sftp", cfg))
    # known_hosts_path es la otra via valida
    cfg["known_hosts_path"] = "/etc/ssh/known_hosts"
    validate_send_config(_base_dest("sftp", cfg))


def test_sftp_config_requires_username():
    cfg = _sftp_cfg()
    del cfg["username"]
    with pytest.raises(ValueError, match="missing_username"):
        validate_send_config(_base_dest("sftp", cfg))
    cfg["username_env"] = "SFTP_USER"
    validate_send_config(_base_dest("sftp", cfg))


def test_sftp_config_requires_auth():
    cfg = _sftp_cfg()
    del cfg["password_env"]
    with pytest.raises(ValueError, match="missing_auth"):
        validate_send_config(_base_dest("sftp", cfg))
    cfg["private_key_path"] = "/home/svc/.ssh/id_rsa"
    validate_send_config(_base_dest("sftp", cfg))


def test_sftp_config_rejects_inline_password():
    cfg = _sftp_cfg()
    cfg["password"] = "nope"
    with pytest.raises(ValueError, match="secretish"):
        validate_send_config(_base_dest("sftp", cfg))


def test_sftp_config_rejects_inline_private_key_material():
    cfg = _sftp_cfg()
    cfg["private_key_pem"] = "-----BEGIN"
    with pytest.raises(ValueError):
        validate_send_config(_base_dest("sftp", cfg))


def test_sftp_config_rejects_bad_disposition():
    cfg = _sftp_cfg(remote_receipt_disposition="delete")
    with pytest.raises(
            ValueError, match="remote_receipt_disposition"):
        validate_send_config(_base_dest("sftp", cfg))


def test_sftp_config_rejects_bad_port_and_timeouts():
    for k in ("port", "connect_timeout_seconds",
              "operation_timeout_seconds"):
        with pytest.raises(ValueError):
            validate_send_config(
                _base_dest("sftp", _sftp_cfg(**{k: 0})))


def test_sftp_config_rejects_unknown_keys():
    cfg = _sftp_cfg(strict_host_key_checking="no",
                    auto_add_policy=True)
    with pytest.raises(ValueError, match="unknown_key"):
        validate_send_config(_base_dest("sftp", cfg))


# ------------------------------------------------------------------
# validate_send_config: mq
# ------------------------------------------------------------------

def _mq_cfg(**over):
    cfg = {
        "queue_manager": "QM1", "channel": "DEV.APP.SVRCONN",
        "connection_name": "mq.example.test(1414)",
        "request_queue": "DEV.QUEUE.1"}
    cfg.update(over)
    return cfg


def test_mq_config_valid_minimal():
    validate_send_config(_base_dest("mq", _mq_cfg()))


def test_mq_config_missing_required_fields():
    for key in ("queue_manager", "channel", "connection_name",
                "request_queue"):
        cfg = _mq_cfg()
        del cfg[key]
        with pytest.raises(ValueError, match="missing"):
            validate_send_config(_base_dest("mq", cfg))


def test_mq_config_env_credentials_ok():
    cfg = _mq_cfg(username_env="MQ_USER", password_env="MQ_PASS",
                  ssl_cipher_spec="TLS_RSA_WITH_AES_256_CBC_SHA256",
                  key_repository="/var/mqm/ssl/key")
    validate_send_config(_base_dest("mq", cfg))


def test_mq_config_rejects_inline_password():
    cfg = _mq_cfg(password="secret")
    with pytest.raises(ValueError, match="secretish"):
        validate_send_config(_base_dest("mq", cfg))


def test_mq_config_rejects_unknown_keys():
    cfg = _mq_cfg(ccdt_url="file:///x", api_key="k")
    with pytest.raises(ValueError):
        validate_send_config(_base_dest("mq", cfg))


def test_unknown_adapter_rejected():
    with pytest.raises(ValueError, match="adapter"):
        validate_send_config(
            _base_dest("carrier-pigeon", {"x": 1}))
