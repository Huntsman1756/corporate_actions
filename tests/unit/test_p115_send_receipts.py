"""P11.5 — receipt ingestion: correlacion, transiciones GATEWAY_*,
quarantine de malformed/duplicados/conflictivos, evidencia externa.

Los receipts son artefactos EXTERNOS: los tests los escriben a mano
en receipts/ como haria un consumidor externo real.
"""
from __future__ import annotations

import json

import pytest

from ca_es.ops_send import (
    S_GATEWAY_ACCEPTED, S_GATEWAY_REJECTED, S_SPOOLED,
    SCHEMA_TRANSPORT_RECEIPT, content_sha256_of,
    derive_delivery_id, get_send, list_send_receipts,
    list_send_transitions, prepare_sends, run_send_dispatch)
from ca_es.ops_state import OpsState

FIN = "{1:F01TEST}{4:\r\n:20C::SEME//INS-0001\r\n-}"
SHA = content_sha256_of(FIN)
NOW = "2026-07-16T00:00:00Z"


def _cfg(tmp_path) -> dict:
    return {
        "enabled": True,
        "destinations": [{
            "destination_id": "gw-file-1", "adapter": "filespool",
            "enabled": True, "message_schemas": ["*"],
            "config": {
                "spool_directory": str(tmp_path / "spool")}}],
        "retry": {"max_attempts": 3},
    }


@pytest.fixture()
def spooled_send(tmp_path):
    """State con un send ya SPOOLED. Devuelve (state, conn, did,
    receipts_dir, quarantine_dir)."""
    state = OpsState(tmp_path / "st").init()
    cfg = _cfg(tmp_path)
    conn = state.acquire_run_lock("test-run")
    prepare_sends(
        conn,
        {"schema": "CA_ES_MT565_FIN_V1", "write_status": "OK",
         "fin": FIN},
        "INS-0001", cfg, now=NOW)
    run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    did = derive_delivery_id("INS-0001", SHA, "gw-file-1")
    receipts = tmp_path / "spool" / "receipts"
    quarantine = tmp_path / "spool" / "quarantine"
    yield state, conn, cfg, did, receipts, quarantine
    state.release_run_lock()


def _receipt(did: str, status: str = "ACCEPTED",
             sha: str = SHA, **extra) -> dict:
    doc = {"schema": SCHEMA_TRANSPORT_RECEIPT,
           "delivery_id": did, "content_sha256": sha,
           "status": status,
           "gateway_reference": "SAA-REF-1",
           "received_at": "2026-07-16T01:00:00Z", "reason": None}
    doc.update(extra)
    return doc


def _write(receipts_dir, did: str, kind: str, doc) -> object:
    receipts_dir.mkdir(parents=True, exist_ok=True)
    p = receipts_dir / f"{did}.{kind}.json"
    if isinstance(doc, str):
        p.write_text(doc, encoding="utf-8")
    else:
        p.write_text(json.dumps(doc), encoding="utf-8")
    return p


# ------------------------------------------------------------------
# happy path
# ------------------------------------------------------------------

def test_ack_receipt_accepted(spooled_send):
    state, conn, cfg, did, receipts, _ = spooled_send
    _write(receipts, did, "ack", _receipt(did))
    res = run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    assert res["receipts_ingested"] == 1
    send = get_send(conn, did)
    assert send["status"] == S_GATEWAY_ACCEPTED
    assert send["transport_reference"] == "SAA-REF-1"
    ext = json.loads(send["external_receipt_json"])
    assert ext["schema"] == SCHEMA_TRANSPORT_RECEIPT
    assert ext["status"] == "ACCEPTED"
    # fichero movido a processed/, nunca borrado
    assert (receipts / "processed" / f"{did}.ack.json").exists()
    rec = list_send_receipts(conn, did)
    assert len(rec) == 1
    assert rec[0]["status"] == "ACCEPTED"
    assert rec[0]["quarantine_reason"] is None


def test_nak_receipt_rejected(spooled_send):
    state, conn, cfg, did, receipts, _ = spooled_send
    _write(receipts, did, "nak",
           _receipt(did, status="REJECTED",
                    reason="CHECKSUM_MISMATCH"))
    res = run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    send = get_send(conn, did)
    assert send["status"] == S_GATEWAY_REJECTED
    rec = list_send_receipts(conn, did)
    assert rec[0]["status"] == "REJECTED"
    assert rec[0]["reason"] == "CHECKSUM_MISMATCH"


def test_receipt_not_business_status(spooled_send):
    """GATEWAY_ACCEPTED es transporte, NO status de negocio:
    el send nunca toca instruction status (P5.6)."""
    state, conn, cfg, did, receipts, _ = spooled_send
    _write(receipts, did, "ack", _receipt(did))
    run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    send = get_send(conn, did)
    # transport_reference poblado; el campo de status es de
    # TRANSPORTE, separado del lifecycle MT567/seev.034
    assert send["status"] == S_GATEWAY_ACCEPTED
    assert "instruction_status" not in send


# ------------------------------------------------------------------
# quarantine
# ------------------------------------------------------------------

def test_malformed_json_quarantined(spooled_send):
    state, conn, cfg, did, receipts, quarantine = spooled_send
    _write(receipts, did, "ack", "{not json")
    res = run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    assert res["receipts_quarantined"] == 1
    assert res["receipts_ingested"] == 0
    assert get_send(conn, did)["status"] == S_SPOOLED
    qfiles = list(quarantine.iterdir())
    assert len(qfiles) == 1
    rec = list_send_receipts(conn, did)
    assert rec[0]["status"] == "QUARANTINED"
    assert rec[0]["quarantine_reason"] == "MALFORMED_RECEIPT"


def test_wrong_schema_quarantined(spooled_send):
    state, conn, cfg, did, receipts, quarantine = spooled_send
    doc = _receipt(did)
    doc["schema"] = "something-else@9"
    _write(receipts, did, "ack", doc)
    run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    rec = list_send_receipts(conn, did)
    assert rec[0]["quarantine_reason"] == "WRONG_SCHEMA"


def test_id_mismatch_quarantined(spooled_send):
    state, conn, cfg, did, receipts, quarantine = spooled_send
    doc = _receipt(did)
    doc["delivery_id"] = "SND-different"
    _write(receipts, did, "ack", doc)
    run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    rec = list_send_receipts(conn, did)
    assert rec[0]["quarantine_reason"] == "ID_MISMATCH"
    assert get_send(conn, did)["status"] == S_SPOOLED


def test_status_suffix_mismatch_quarantined(spooled_send):
    state, conn, cfg, did, receipts, quarantine = spooled_send
    # .ack.json pero status REJECTED dentro
    _write(receipts, did, "ack", _receipt(did, status="REJECTED"))
    run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    rec = list_send_receipts(conn, did)
    assert rec[0]["quarantine_reason"] == "STATUS_SUFFIX_MISMATCH"


def test_unknown_delivery_quarantined(spooled_send):
    state, conn, cfg, did, receipts, quarantine = spooled_send
    foreign = "SND-" + "ab" * 32
    _write(receipts, foreign, "ack", _receipt(foreign))
    run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    recs = [r for r in list_send_receipts(conn, foreign)]
    assert recs[0]["quarantine_reason"] == "UNKNOWN_DELIVERY"


def test_hash_mismatch_quarantined(spooled_send):
    state, conn, cfg, did, receipts, quarantine = spooled_send
    _write(receipts, did, "ack", _receipt(did, sha="0" * 64))
    run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    rec = list_send_receipts(conn, did)
    assert rec[0]["quarantine_reason"] == "HASH_MISMATCH"
    assert get_send(conn, did)["status"] == S_SPOOLED


def test_ack_and_nak_conflict_both_quarantined(spooled_send):
    state, conn, cfg, did, receipts, quarantine = spooled_send
    _write(receipts, did, "ack", _receipt(did))
    _write(receipts, did, "nak",
           _receipt(did, status="REJECTED"))
    res = run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    assert res["receipts_quarantined"] == 2
    assert get_send(conn, did)["status"] == S_SPOOLED
    qnames = sorted(p.name for p in quarantine.iterdir())
    assert len(qnames) == 2
    reasons = {r["quarantine_reason"]
               for r in list_send_receipts(conn, did)}
    assert reasons == {"CONFLICTING_RECEIPTS"}


def test_duplicate_byte_identical_receipt_consumed(spooled_send):
    """Re-ingesta del MISMO receipt byte-identico tras
    GATEWAY_ACCEPTED -> consume idempotente, sin transicion."""
    state, conn, cfg, did, receipts, _ = spooled_send
    doc = _receipt(did)
    _write(receipts, did, "ack", doc)
    run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    assert get_send(conn, did)["status"] == S_GATEWAY_ACCEPTED
    # el consumidor externo re-deposita el mismo fichero
    _write(receipts, did, "ack", doc)
    res = run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    send = get_send(conn, did)
    assert send["status"] == S_GATEWAY_ACCEPTED
    assert res["receipts_quarantined"] == 0
    # consumido a processed (sobrescribe nombre idempotente)
    assert (receipts / "processed" / f"{did}.ack.json").exists()
    # solo UNA fila de receipt registrada (la primera)
    assert len(list_send_receipts(conn, did)) == 1


def test_conflicting_second_receipt_quarantined(spooled_send):
    """Receipt DISTINTO para un send ya GATEWAY_ACCEPTED ->
    UNEXPECTED_STATE -> quarantine."""
    state, conn, cfg, did, receipts, quarantine = spooled_send
    _write(receipts, did, "ack", _receipt(did))
    run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    _write(receipts, did, "ack",
           _receipt(did, gateway_reference="OTHER-REF"))
    res = run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    assert res["receipts_quarantined"] == 1
    send = get_send(conn, did)
    # el primer receipt legitimo se mantiene
    assert send["status"] == S_GATEWAY_ACCEPTED
    assert send["transport_reference"] == "SAA-REF-1"
    recs = list_send_receipts(conn, did)
    assert len(recs) == 2
    assert recs[1]["quarantine_reason"] == "UNEXPECTED_STATE"


def test_receipt_for_prepared_send_quarantined(tmp_path):
    """Receipt para un send PREPARED (nunca spooleado) ->
    UNEXPECTED_STATE."""
    state = OpsState(tmp_path / "st").init()
    cfg = _cfg(tmp_path)
    conn = state.acquire_run_lock("t")
    try:
        prepare_sends(
            conn,
            {"schema": "CA_ES_MT565_FIN_V1", "write_status": "OK",
             "fin": FIN},
            "INS-0001", cfg, now=NOW)
        did = derive_delivery_id("INS-0001", SHA, "gw-file-1")
        receipts = tmp_path / "spool" / "receipts"
        _write(receipts, did, "ack", _receipt(did))
        run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
        rec = list_send_receipts(conn, did)
        assert rec[0]["quarantine_reason"] == "UNEXPECTED_STATE"
        # la transicion GATEWAY_* nunca ocurre desde PREPARED;
        # el send puede spoolearse despues en la misma pasada
        assert get_send(conn, did)["status"] != S_GATEWAY_ACCEPTED
    finally:
        state.release_run_lock()


def test_non_receipt_files_ignored(spooled_send):
    """Ficheros ajenos en receipts/ no se procesan ni cuarentean."""
    state, conn, cfg, did, receipts, quarantine = spooled_send
    receipts.mkdir(parents=True, exist_ok=True)
    (receipts / "README.txt").write_text("not a receipt")
    (receipts / "random.json").write_text("{}")
    res = run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    assert res["receipts_quarantined"] == 0
    assert (receipts / "README.txt").exists()
