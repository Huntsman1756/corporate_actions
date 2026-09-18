"""P12.1/P12.2/P12.11 — SFTP adapter contra un servidor SSH/SFTP
REAL in-process (Paramiko server-side — mismo wire protocol, no
mock de transporte). Cubre commit atomico remoto, idempotencia,
collision, host-key pinning, fases de fallo, verify() y receipt
polling end-to-end por run_send_poll.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import threading
from pathlib import Path

import pytest

paramiko = pytest.importorskip("paramiko")

from ca_es.ops_send import (
    O_FAILED_PERMANENT, O_FAILED_RETRYABLE, O_SPOOLED, O_UNKNOWN,
    S_GATEWAY_ACCEPTED, S_SPOOLED, SendRequest, content_sha256_of,
    derive_delivery_id, get_send, prepare_sends, run_send_poll)
from ca_es.ops_state import OpsState
from ca_es.transport import sftp as sftp_adapter

FIN = ("{1:F01TESTES00XXXX1234000079}{4:\r\n"
       ":20C::SEME//INS-0001\r\n-}")
SHA = content_sha256_of(FIN)
NOW = "2026-07-16T00:00:00Z"
USER = "tester"
PW = "s3cret-not-persisted"


def _request(delivery_id="SND-" + "a" * 64, text=FIN):
    return SendRequest(
        delivery_id=delivery_id,
        instruction_id="INS-0001",
        message_reference="INS-0001",
        message_schema="CA_ES_MT565_FIN_V1",
        message_text=text,
        content_sha256=content_sha256_of(text),
        destination_id="gw-sftp-1",
        adapter_type="sftp",
        generation=1)


# ------------------------------------------------------------------
# servidor SFTP real in-process (paramiko server-side)
# ------------------------------------------------------------------

class _StubServer(paramiko.ServerInterface):
    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_auth_password(self, username, password):
        if username == USER and password == PW:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_auth_publickey(self, username, key):
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password,publickey"


class _StubSFTPServer(paramiko.SFTPServerInterface):
    """SFTP server sobre el filesystem local, rooted en tmp."""
    ROOT = Path(".")

    def _real(self, path):
        p = (self.ROOT / path.lstrip("/")).resolve()
        if not str(p).startswith(str(self.ROOT.resolve())):
            return self.ROOT  # path traversal -> fuera de root
        return p

    def list_folder(self, path):
        real = self._real(path)
        try:
            out = []
            for name in os.listdir(real):
                attr = paramiko.SFTPAttributes.from_stat(
                    os.stat(real / name))
                attr.filename = name
                out.append(attr)
            return out
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def stat(self, path):
        try:
            return paramiko.SFTPAttributes.from_stat(
                os.stat(self._real(path)))
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def lstat(self, path):
        return self.stat(path)

    def open(self, path, flags, attr):
        real = self._real(path)
        try:
            binary = getattr(os, "O_BINARY", 0)
            if flags & os.O_WRONLY:
                if flags & os.O_APPEND:
                    o = os.O_WRONLY | os.O_CREAT | os.O_APPEND
                elif flags & os.O_TRUNC:
                    o = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                else:
                    o = os.O_WRONLY | os.O_CREAT
            elif flags & os.O_RDWR:
                if flags & os.O_APPEND:
                    o = os.O_RDWR | os.O_CREAT | os.O_APPEND
                else:
                    o = os.O_RDWR | os.O_CREAT
            else:
                o = os.O_RDONLY
            fd = os.open(real, o | binary, 0o666)
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)
        if flags & (os.O_WRONLY | os.O_RDWR) == os.O_WRONLY:
            mode = "ab" if flags & os.O_APPEND else "wb"
        elif flags & os.O_RDWR:
            mode = "a+b" if flags & os.O_APPEND else "r+b"
        else:
            mode = "rb"
        try:
            f = os.fdopen(fd, mode)
        except OSError as e:
            os.close(fd)
            return paramiko.SFTPServer.convert_errno(e.errno)
        handle = paramiko.SFTPHandle(flags)
        handle.filename = str(real)
        handle.readfile = f
        handle.writefile = f
        return handle

    def remove(self, path):
        try:
            os.remove(self._real(path))
            return paramiko.SFTP_OK
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def rename(self, oldpath, newpath):
        try:
            os.replace(self._real(oldpath), self._real(newpath))
            return paramiko.SFTP_OK
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def mkdir(self, path, attr):
        try:
            os.mkdir(self._real(path))
            return paramiko.SFTP_OK
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def rmdir(self, path):
        try:
            os.rmdir(self._real(path))
            return paramiko.SFTP_OK
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)


class SFTPLab:
    """Servidor SSH/SFTP real escuchando en 127.0.0.1:puerto."""

    def __init__(self, root: Path):
        self.root = root
        self.host_key = paramiko.RSAKey.generate(2048)
        self.fingerprint = hashlib.sha256(
            self.host_key.asbytes()).hexdigest()
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET,
                             socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.sock.settimeout(0.3)
        self.port = self.sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        _StubSFTPServer.ROOT = self.root
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                t = paramiko.Transport(conn)
                t.add_server_key(self.host_key)
                t.set_subsystem_handler(
                    "sftp", paramiko.SFTPServer, _StubSFTPServer)
                t.start_server(server=_StubServer())
            except Exception:  # noqa: BLE001 — conexion muerta
                continue

    def stop(self):
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass
        self._thread.join(timeout=3)


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


def _cfg(lab, tmp_path, **over) -> dict:
    cfg = {
        "host": "127.0.0.1", "port": lab.port,
        "username": USER,
        "password_env": "CA_ES_TEST_SFTP_PW",
        "host_key_fingerprint": lab.fingerprint,
        "remote_outbox": "/outbox",
        "remote_receipts": "/receipts",
        "local_receipt_staging": str(tmp_path / "staging"),
        "connect_timeout_seconds": 10,
        "operation_timeout_seconds": 10,
    }
    cfg.update(over)
    return cfg


# ------------------------------------------------------------------
# deliver: commit remoto atomico
# ------------------------------------------------------------------

def test_deliver_uploads_exact_bytes_and_meta(lab, tmp_path):
    res = sftp_adapter.deliver(_request(), _cfg(lab, tmp_path))
    assert res.outcome == O_SPOOLED
    req = _request()
    msg = lab.root / "outbox" / f"{req.delivery_id}.msg"
    meta = lab.root / "outbox" / f"{req.delivery_id}.meta.json"
    assert msg.read_bytes() == FIN.encode("utf-8")
    doc = json.loads(meta.read_text(encoding="utf-8"))
    assert doc["schema"] == "CA_ES_SEND_META_V1"
    assert doc["content_sha256"] == SHA
    ev = res.receipt
    assert ev["transport_evidence"] == "REMOTE_PERSISTED"
    assert ev["read_back_sha256"] == SHA
    assert ev["remote_size"] == len(FIN.encode("utf-8"))


def test_deliver_replay_is_idempotent(lab, tmp_path):
    cfg = _cfg(lab, tmp_path)
    sftp_adapter.deliver(_request(), cfg)
    res = sftp_adapter.deliver(_request(), cfg)
    assert res.outcome == O_SPOOLED
    assert res.receipt["replayed"] is True
    # un unico par msg/meta — sin duplicados remotos
    outbox = lab.root / "outbox"
    assert len(list(outbox.glob("*.msg"))) == 1
    assert len(list(outbox.glob("*.meta.json"))) == 1


def test_deliver_hash_binding_fails_before_network(lab, tmp_path):
    req = _request()
    req.content_sha256 = "0" * 64  # ledger mintio
    res = sftp_adapter.deliver(req, _cfg(lab, tmp_path))
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "CONTENT_HASH_MISMATCH"
    assert not (lab.root / "outbox").exists()


def test_deliver_collision_remote_different_bytes(lab, tmp_path):
    req = _request()
    outbox = lab.root / "outbox"
    outbox.mkdir()
    (outbox / f"{req.delivery_id}.msg").write_bytes(b"foreign")
    (outbox / f"{req.delivery_id}.meta.json").write_text(json.dumps(
        {"schema": "CA_ES_SEND_META_V1",
         "content_sha256": "f" * 64}), encoding="utf-8")
    res = sftp_adapter.deliver(req, _cfg(lab, tmp_path))
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "DELIVERY_ID_COLLISION"


def test_deliver_completes_orphan_msg(lab, tmp_path):
    """Crash remoto anterior: .msg correcto, .meta ausente ->
    completa el commit sin re-upload."""
    req = _request()
    outbox = lab.root / "outbox"
    outbox.mkdir()
    (outbox / f"{req.delivery_id}.msg").write_bytes(
        FIN.encode("utf-8"))
    res = sftp_adapter.deliver(req, _cfg(lab, tmp_path))
    assert res.outcome == O_SPOOLED
    assert res.receipt["completed_orphan"] is True
    assert (outbox / f"{req.delivery_id}.meta.json").is_file()


# ------------------------------------------------------------------
# fallos por fase
# ------------------------------------------------------------------

def test_connect_refused_is_retryable(tmp_path):
    cfg = {"host": "127.0.0.1", "port": 9,  # discard: cerrado
           "username": USER, "password_env": "CA_ES_TEST_SFTP_PW",
           "host_key_fingerprint": "0" * 64,
           "remote_outbox": "/outbox", "remote_receipts": "/r",
           "local_receipt_staging": str(tmp_path / "s"),
           "connect_timeout_seconds": 3}
    res = sftp_adapter.deliver(_request(), cfg)
    assert res.outcome == O_FAILED_RETRYABLE
    assert res.error_code == "CONNECT_FAILED"


def test_wrong_host_key_fingerprint_permanent(lab, tmp_path):
    res = sftp_adapter.deliver(
        _request(), _cfg(lab, tmp_path,
                         host_key_fingerprint="0" * 64))
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "AUTH_FAILED"


def test_wrong_password_permanent(lab, tmp_path, monkeypatch):
    monkeypatch.setenv("CA_ES_TEST_SFTP_PW", "wrong")
    res = sftp_adapter.deliver(_request(), _cfg(lab, tmp_path))
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "AUTH_FAILED"


def test_post_msg_failure_is_unknown(lab, tmp_path, monkeypatch):
    """Fallo tras rename del .msg (meta) -> UNKNOWN; verify() lo
    resuelve despues."""
    real = sftp_adapter._put_atomic
    calls = {"n": 0}

    def boom(sftp, data, final):
        calls["n"] += 1
        if calls["n"] == 2:  # meta
            raise IOError("simulated post-msg failure")
        return real(sftp, data, final)

    monkeypatch.setattr(sftp_adapter, "_put_atomic", boom)
    res = sftp_adapter.deliver(_request(), _cfg(lab, tmp_path))
    assert res.outcome == O_UNKNOWN
    # el .msg SI quedo comprometido — verify() debe verlo
    req = _request()
    assert (lab.root / "outbox" /
            f"{req.delivery_id}.msg").is_file()


def test_password_never_in_evidence(lab, tmp_path):
    res = sftp_adapter.deliver(_request(), _cfg(lab, tmp_path))
    assert PW not in json.dumps(res.receipt or {})


# ------------------------------------------------------------------
# verify()
# ------------------------------------------------------------------

def test_verify_committed(lab, tmp_path):
    cfg = _cfg(lab, tmp_path)
    req = _request()
    sftp_adapter.deliver(req, cfg)
    assert sftp_adapter.verify(req, cfg) == "SPOOLED"


def test_verify_absent(lab, tmp_path):
    assert sftp_adapter.verify(
        _request(), _cfg(lab, tmp_path)) == "NOT_SPOOLED"


def test_verify_orphan_msg_not_spooled(lab, tmp_path):
    req = _request()
    outbox = lab.root / "outbox"
    outbox.mkdir()
    (outbox / f"{req.delivery_id}.msg").write_bytes(
        FIN.encode("utf-8"))
    assert sftp_adapter.verify(
        req, _cfg(lab, tmp_path)) == "NOT_SPOOLED"


def test_verify_collision(lab, tmp_path):
    req = _request()
    outbox = lab.root / "outbox"
    outbox.mkdir()
    (outbox / f"{req.delivery_id}.msg").write_bytes(b"foreign")
    assert sftp_adapter.verify(
        req, _cfg(lab, tmp_path)) == "COLLISION"


def test_verify_server_down_is_unknown(tmp_path):
    cfg = {"host": "127.0.0.1", "port": 9,
           "username": USER, "password_env": "CA_ES_TEST_SFTP_PW",
           "host_key_fingerprint": "0" * 64,
           "remote_outbox": "/o", "remote_receipts": "/r",
           "local_receipt_staging": str(tmp_path / "s"),
           "connect_timeout_seconds": 3}
    assert sftp_adapter.verify(_request(), cfg) == "UNKNOWN"


# ------------------------------------------------------------------
# receipt polling end-to-end (P12.2)
# ------------------------------------------------------------------

def _prepared_send(conn, tmp_path, lab):
    cfg = {"enabled": True, "destinations": [{
        "destination_id": "gw-sftp-1", "adapter": "sftp",
        "enabled": True, "message_schemas": ["*"],
        "config": _cfg(lab, tmp_path)}]}
    doc = {"schema": "CA_ES_MT565_FIN_V1", "write_status": "OK",
           "fin": FIN, "fin_sha256": SHA}
    res = prepare_sends(conn, doc, "INS-0001", cfg, now=NOW)
    return res["created"][0]["delivery_id"], cfg


def test_remote_receipt_poll_ingests_and_archives(
        tmp_path, lab):
    state = OpsState(tmp_path / "st").init()
    conn = state.acquire_run_lock("t")
    try:
        did, send_cfg = _prepared_send(conn, tmp_path, lab)
        conn.execute(
            "UPDATE sends SET status=? WHERE delivery_id=?",
            (S_SPOOLED, did))
        # el "gateway" deposita un receipt remoto
        rdir = lab.root / "receipts"
        rdir.mkdir(exist_ok=True)
        (rdir / f"{did}.ack.json").write_text(json.dumps({
            "schema": "CA_ES_TRANSPORT_RECEIPT_V1",
            "delivery_id": did, "content_sha256": SHA,
            "status": "ACCEPTED", "gateway_reference": "GW-99",
            "received_at": NOW, "reason": None}), encoding="utf-8")

        out = run_send_poll(state, conn, send_cfg)
        assert out["status"] == "SUCCESS"
        assert out["ingested"] == 1
        send = get_send(conn, did)
        assert send["status"] == S_GATEWAY_ACCEPTED
        assert send["transport_reference"] == "GW-99"
        # archive: el receipt remoto paso a processed/
        assert (rdir / "processed" / f"{did}.ack.json").is_file()
        assert not (rdir / f"{did}.ack.json").exists()
    finally:
        state.release_run_lock()


def test_remote_malformed_receipt_quarantined(tmp_path, lab):
    state = OpsState(tmp_path / "st").init()
    conn = state.acquire_run_lock("t")
    try:
        did, send_cfg = _prepared_send(conn, tmp_path, lab)
        conn.execute(
            "UPDATE sends SET status=? WHERE delivery_id=?",
            (S_SPOOLED, did))
        rdir = lab.root / "receipts"
        rdir.mkdir(exist_ok=True)
        (rdir / f"{did}.ack.json").write_text(
            "{not json", encoding="utf-8")
        out = run_send_poll(state, conn, send_cfg)
        assert out["quarantined"] == 1
        assert get_send(conn, did)["status"] == S_SPOOLED
        # evidencia remota conservada (nunca borrada)
        assert (rdir / f"{did}.ack.json").is_file()
        # copia local en quarantine
        staging = Path(_cfg(lab, tmp_path)["local_receipt_staging"])
        assert list((staging / "quarantine").glob("*"))
    finally:
        state.release_run_lock()


def test_poll_idempotent_second_run(tmp_path, lab):
    state = OpsState(tmp_path / "st").init()
    conn = state.acquire_run_lock("t")
    try:
        did, send_cfg = _prepared_send(conn, tmp_path, lab)
        conn.execute(
            "UPDATE sends SET status=? WHERE delivery_id=?",
            (S_SPOOLED, did))
        rdir = lab.root / "receipts"
        rdir.mkdir(exist_ok=True)
        (rdir / f"{did}.ack.json").write_text(json.dumps({
            "schema": "CA_ES_TRANSPORT_RECEIPT_V1",
            "delivery_id": did, "content_sha256": SHA,
            "status": "ACCEPTED"}), encoding="utf-8")
        run_send_poll(state, conn, send_cfg)
        out = run_send_poll(state, conn, send_cfg)
        assert out["ingested"] == 0
        assert get_send(conn, did)["status"] == S_GATEWAY_ACCEPTED
    finally:
        state.release_run_lock()


def test_poll_network_error_is_technical(tmp_path):
    """Server caido -> poll_errors, jamas rechazo de negocio."""
    state = OpsState(tmp_path / "st").init()
    conn = state.acquire_run_lock("t")
    try:
        cfg = {"enabled": True, "destinations": [{
            "destination_id": "gw-dead", "adapter": "sftp",
            "enabled": True, "message_schemas": ["*"],
            "config": {
                "host": "127.0.0.1", "port": 9, "username": USER,
                "password_env": "CA_ES_TEST_SFTP_PW",
                "host_key_fingerprint": "0" * 64,
                "remote_outbox": "/o", "remote_receipts": "/r",
                "local_receipt_staging": str(tmp_path / "s"),
                "connect_timeout_seconds": 3}}]}
        out = run_send_poll(state, conn, cfg)
        assert out["status"] == "POLL_ERROR"
        assert out["poll_errors"] == 1
    finally:
        state.release_run_lock()
