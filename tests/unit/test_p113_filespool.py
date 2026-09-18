"""P11.3 — FileSpoolTransport: escritura atomica, idempotencia,
collision fail-closed, verify() post-crash, layout del spool."""
from __future__ import annotations

import json
from pathlib import Path

from ca_es.ops_send import (
    O_FAILED_PERMANENT, O_FAILED_RETRYABLE, O_SPOOLED,
    SCHEMA_SEND_META, SendRequest, V_COLLISION, V_NOT_SPOOLED,
    V_SPOOLED, content_sha256_of, derive_delivery_id)
from ca_es.transport import filespool

FIN = "{1:F01TEST}{4:\r\n:20C::SEME//INS-0001\r\n:23G:NEWM\r\n-}"
SHA = content_sha256_of(FIN)
DID = derive_delivery_id("INS-0001", SHA, "gw-1")


def _req(delivery_id: str = DID, text: str = FIN,
         sha: str = SHA) -> SendRequest:
    return SendRequest(
        delivery_id=delivery_id, instruction_id="INS-0001",
        message_reference="INS-0001",
        message_schema="CA_ES_MT565_FIN_V1",
        message_text=text, content_sha256=sha,
        destination_id="gw-1", adapter_type="filespool",
        generation=1)


def _cfg(tmp_path) -> dict:
    return {"spool_directory": str(tmp_path / "spool")}


def test_deliver_creates_msg_and_meta(tmp_path):
    res = filespool.deliver(_req(), _cfg(tmp_path))
    assert res.outcome == O_SPOOLED
    outbox = tmp_path / "spool" / "outbox"
    msg = outbox / f"{DID}.msg"
    meta = outbox / f"{DID}.meta.json"
    assert msg.read_bytes() == FIN.encode("utf-8")
    doc = json.loads(meta.read_text(encoding="utf-8"))
    assert doc["schema"] == SCHEMA_SEND_META
    assert doc["delivery_id"] == DID
    assert doc["content_sha256"] == SHA
    assert doc["message_reference"] == "INS-0001"
    # dirs auxiliares creados
    assert (tmp_path / "spool" / "receipts").is_dir()
    assert (tmp_path / "spool" / "quarantine").is_dir()


def test_deliver_idempotent_replay_same_bytes(tmp_path):
    cfg = _cfg(tmp_path)
    r1 = filespool.deliver(_req(), cfg)
    r2 = filespool.deliver(_req(), cfg)
    assert r1.outcome == r2.outcome == O_SPOOLED
    assert r2.receipt["replayed"] is True
    outbox = tmp_path / "spool" / "outbox"
    assert len(list(outbox.iterdir())) == 2


def test_deliver_collision_same_id_different_bytes(tmp_path):
    cfg = _cfg(tmp_path)
    filespool.deliver(_req(), cfg)
    other = FIN + "\r\n:70E::ADTX//DIFFERENT"
    res = filespool.deliver(
        _req(text=other, sha=content_sha256_of(other)), cfg)
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "DELIVERY_ID_COLLISION"
    # bytes originales intactos — nunca overwrite silencioso
    msg = tmp_path / "spool" / "outbox" / f"{DID}.msg"
    assert msg.read_bytes() == FIN.encode("utf-8")


def test_deliver_orphan_msg_completed_by_meta(tmp_path):
    """Crash entre .msg y .meta: siguiente intento mismo sha
    completa el commit en lugar de fallar."""
    cfg = _cfg(tmp_path)
    outbox = tmp_path / "spool" / "outbox"
    outbox.mkdir(parents=True)
    (outbox / f"{DID}.msg").write_bytes(FIN.encode("utf-8"))
    res = filespool.deliver(_req(), cfg)
    assert res.outcome == O_SPOOLED
    assert res.receipt["completed_orphan"] is True
    assert (outbox / f"{DID}.meta.json").exists()


def test_deliver_orphan_msg_different_bytes_collision(tmp_path):
    cfg = _cfg(tmp_path)
    outbox = tmp_path / "spool" / "outbox"
    outbox.mkdir(parents=True)
    (outbox / f"{DID}.msg").write_bytes(b"OTHER BYTES")
    res = filespool.deliver(_req(), cfg)
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "DELIVERY_ID_COLLISION"
    assert (outbox / f"{DID}.msg").read_bytes() == b"OTHER BYTES"


def test_deliver_missing_spool_directory_permanent(tmp_path):
    res = filespool.deliver(_req(), {})
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "MISSING_SPOOL_DIRECTORY"


def test_deliver_ledger_hash_mismatch_permanent(tmp_path):
    """message_text no casa con el content_sha256 declarado ->
    el adapter NO escribe nada (hash binding)."""
    res = filespool.deliver(
        _req(sha="0" * 64), _cfg(tmp_path))
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "CONTENT_HASH_MISMATCH"
    assert not (tmp_path / "spool" / "outbox").exists()


def test_deliver_unwritable_spool_retryable(tmp_path):
    """IO en el write de .msg (pre-commit) -> retryable."""
    # spool_directory apunta a un fichero, no a un dir
    bad = tmp_path / "afile"
    bad.write_text("x")
    res = filespool.deliver(
        _req(), {"spool_directory": str(bad / "sub")})
    assert res.outcome == O_FAILED_PERMANENT  # mkdir no creable


def test_verify_states(tmp_path):
    cfg = _cfg(tmp_path)
    req = _req()
    # nada -> NOT_SPOOLED
    assert filespool.verify(req, cfg) == V_NOT_SPOOLED
    # solo .msg mismo sha -> NOT_SPOOLED (commit incompleto,
    # reintento seguro)
    outbox = tmp_path / "spool" / "outbox"
    outbox.mkdir(parents=True)
    (outbox / f"{DID}.msg").write_bytes(FIN.encode("utf-8"))
    assert filespool.verify(req, cfg) == V_NOT_SPOOLED
    # .msg sha distinto -> COLLISION
    (outbox / f"{DID}.msg").write_bytes(b"OTHER")
    assert filespool.verify(req, cfg) == V_COLLISION
    # ciclo completo -> SPOOLED
    (outbox / f"{DID}.msg").write_bytes(FIN.encode("utf-8"))
    filespool.deliver(req, cfg)
    assert filespool.verify(req, cfg) == V_SPOOLED


def test_verify_meta_collision(tmp_path):
    cfg = _cfg(tmp_path)
    filespool.deliver(_req(), cfg)
    meta = tmp_path / "spool" / "outbox" / f"{DID}.meta.json"
    doc = json.loads(meta.read_text())
    doc["content_sha256"] = "f" * 64
    meta.write_text(json.dumps(doc))
    assert filespool.verify(_req(), cfg) == V_COLLISION


def test_no_tmp_files_left(tmp_path):
    """tmp limpiado tras write exitoso."""
    filespool.deliver(_req(), _cfg(tmp_path))
    outbox = tmp_path / "spool" / "outbox"
    assert [p.name for p in outbox.iterdir()
            if p.name.endswith(".tmp")] == []


def test_concurrent_delivers_same_id(tmp_path):
    """N entregas concurrentes del mismo delivery_id+mismos bytes.

    Propiedades: nunca corrupcion ni colision para bytes identicos;
    bajo contencion el adapter puede devolver FAILED_RETRYABLE u
    UNKNOWN (rename exclusivo en Windows) — el dispatcher reintenta
    y CONVERGE a un unico msg+meta con los bytes exactos.
    """
    import threading

    cfg = _cfg(tmp_path)
    results = []
    errors = []

    def work():
        try:
            results.append(filespool.deliver(_req(), cfg).outcome)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    # nunca PERMANENT ni COLLISION para bytes identicos
    assert all(o in (O_SPOOLED, O_FAILED_RETRYABLE, "UNKNOWN")
               for o in results)
    # convergencia: reintentos hasta SPOOLED
    for _ in range(20):
        res = filespool.deliver(_req(), cfg)
        if res.outcome == O_SPOOLED:
            break
    assert res.outcome == O_SPOOLED
    # verify() post-contienda confirma el commit
    assert filespool.verify(_req(), cfg) == V_SPOOLED
    outbox = tmp_path / "spool" / "outbox"
    names = sorted(p.name for p in outbox.iterdir())
    assert names == [f"{DID}.meta.json", f"{DID}.msg"]
    assert (outbox / f"{DID}.msg").read_bytes() == \
        FIN.encode("utf-8")
