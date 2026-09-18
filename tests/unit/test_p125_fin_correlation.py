"""P12.5 — FIN service ACK/NAK ingestion: correlacion determinista
MIR+SEME contra el send ledger, transiciones SWIFT_ACKED/NAKED,
conflictos preservados, quarantine fail-closed.

Los tests operan sobre el doc CA_ES_FIN_SERVICE_RECEIPT_V1 ya
extraido por el adapter JVM — el parseo Prowide real se cubre en
test_p125_fin_service_adapter (job JVM).
"""
from __future__ import annotations

import pytest

from ca_es.ops_fin import (
    R_CONFLICTING, R_QUARANTINED, R_SWIFT_ACK, R_SWIFT_NAK,
    ingest_fin_service_doc, mir_of)
from ca_es.ops_send import (
    S_GATEWAY_ACCEPTED, S_PREPARED, S_SPOOLED, S_SWIFT_ACKED,
    S_SWIFT_NAKED, content_sha256_of, get_send,
    list_send_receipts, list_send_transitions, prepare_sends)
from ca_es.ops_state import OpsState

LT = "TESTES00XXXX"  # 12 chars
SESS, SEQ = "1234", "000079"
SEME = "INS-0001"
NOW = "2026-07-16T00:00:00Z"

FIN = (f"{{1:F01{LT}{SESS}{SEQ}}}"
       "{4:\r\n:20C::SEME//INS-0001\r\n"
       ":20C::CORP//CORP-REF-42\r\n:23G:NEWM\r\n-}")
SHA = content_sha256_of(FIN)


def _msg_doc(text: str = FIN) -> dict:
    return {"schema": "CA_ES_MT565_FIN_V1", "write_status": "OK",
            "fin": text, "fin_sha256": content_sha256_of(text)}


def _cfg(tmp_path, dest="gw-file-1") -> dict:
    return {"enabled": True, "destinations": [{
        "destination_id": dest, "adapter": "filespool",
        "enabled": True, "message_schemas": ["*"],
        "config": {"spool_directory": str(tmp_path / "spool")}}]}


@pytest.fixture()
def state(tmp_path):
    return OpsState(tmp_path / "st").init()


@pytest.fixture()
def conn(state):
    c = state.acquire_run_lock("test-run")
    yield c
    state.release_run_lock()


def _receipt(*, ack=True, mir=(LT, SESS, SEQ), seme=SEME,
             error=None, embedded=True, sha="r" * 64) -> dict:
    doc = {
        "schema": "CA_ES_FIN_SERVICE_RECEIPT_V1",
        "input_sha256": sha,
        "parse_status": "OK",
        "service_id": "21",
        "is_ack": ack,
        "is_nack": not ack,
        "field_177": "2607160901",
        "field_451": "0" if ack else "1",
        "field_405": error,
        "field_108": None,
        "mur": None,
        "embedded_copy": {
            "present": embedded,
            "sha256": "e" * 64,
            "mir_lt": mir[0], "mir_session": mir[1],
            "mir_sequence": mir[2],
            "message_type": "565",
            "seme": seme,
        } if embedded else {"present": False},
    }
    return doc


def _prepare(conn, tmp_path, text=FIN, dest="gw-file-1") -> str:
    res = prepare_sends(conn, _msg_doc(text), SEME,
                        _cfg(tmp_path, dest), now=NOW)
    return res["created"][0]["delivery_id"]


def _set_status(conn, did, status):
    conn.execute("UPDATE sends SET status=? WHERE delivery_id=?",
                 (status, did))


# ------------------------------------------------------------------
# MIR extraction
# ------------------------------------------------------------------

def test_mir_of_extracts_block1_fields():
    assert mir_of(FIN) == (LT, SESS, SEQ)


def test_mir_of_simplified_block1_returns_none():
    assert mir_of("{1:F01TEST}{4:\n:20:X\n-}") is None
    assert mir_of("not fin at all") is None
    assert mir_of(None) is None


# ------------------------------------------------------------------
# BOUND: ACK / NAK
# ------------------------------------------------------------------

def test_ack_binds_and_transitions_to_swift_acked(
        state, conn, tmp_path):
    did = _prepare(conn, tmp_path)
    _set_status(conn, did, S_SPOOLED)
    res = ingest_fin_service_doc(
        conn, _receipt(ack=True), receipt_sha="a" * 64,
        source="FILE_INGEST:ack.fin", now=NOW)
    assert res["result"] == R_SWIFT_ACK
    assert res["delivery_id"] == did
    send = get_send(conn, did)
    assert send["status"] == S_SWIFT_ACKED
    receipts = list_send_receipts(conn, did)
    assert receipts[-1]["status"] == R_SWIFT_ACK
    assert receipts[-1]["source_path"] == "FILE_INGEST:ack.fin"
    assert '"status":"SWIFT_ACK"' in send["external_receipt_json"]


def test_nak_binds_and_transitions_to_swift_naked(
        state, conn, tmp_path):
    did = _prepare(conn, tmp_path)
    _set_status(conn, did, S_SPOOLED)
    res = ingest_fin_service_doc(
        conn, _receipt(ack=False, error="T33002"),
        receipt_sha="b" * 64, source="FILE_INGEST:nak.fin", now=NOW)
    assert res["result"] == R_SWIFT_NAK
    send = get_send(conn, did)
    assert send["status"] == S_SWIFT_NAKED
    assert list_send_receipts(conn, did)[-1]["reason"] == "T33002"


def test_gateway_accepted_can_still_receive_network_evidence(
        state, conn, tmp_path):
    did = _prepare(conn, tmp_path)
    _set_status(conn, did, S_GATEWAY_ACCEPTED)
    res = ingest_fin_service_doc(
        conn, _receipt(ack=True), receipt_sha="c" * 64,
        source="FILE_INGEST:ack.fin", now=NOW)
    assert res["result"] == R_SWIFT_ACK
    assert get_send(conn, did)["status"] == S_SWIFT_ACKED


# ------------------------------------------------------------------
# correlation failures
# ------------------------------------------------------------------

def test_ack_unknown_mir_no_match(state, conn, tmp_path):
    _prepare(conn, tmp_path)
    res = ingest_fin_service_doc(
        conn, _receipt(mir=("OTHERES00XXX", SESS, SEQ)),
        receipt_sha="d" * 64, source="FILE_INGEST:ack.fin", now=NOW)
    assert res["result"] == "QUARANTINED:NO_MATCH"
    assert res["delivery_id"] is None


def test_missing_embedded_copy_quarantined(state, conn, tmp_path):
    did = _prepare(conn, tmp_path)
    _set_status(conn, did, S_SPOOLED)
    res = ingest_fin_service_doc(
        conn, _receipt(embedded=False), receipt_sha="e" * 64,
        source="FILE_INGEST:ack.fin", now=NOW)
    assert res["result"] == "QUARANTINED:NO_CORRELATION_EVIDENCE"
    assert get_send(conn, did)["status"] == S_SPOOLED


def test_seme_mismatch_is_conflicting(state, conn, tmp_path):
    did = _prepare(conn, tmp_path)
    _set_status(conn, did, S_SPOOLED)
    res = ingest_fin_service_doc(
        conn, _receipt(seme="INS-DIFFERENT"), receipt_sha="f" * 64,
        source="FILE_INGEST:ack.fin", now=NOW)
    assert res["result"] == "CONFLICTING:SEME_MISMATCH"
    assert res["delivery_id"] == did
    # el send conserva su estado — evidencia conflictiva preservada
    assert get_send(conn, did)["status"] == S_SPOOLED
    assert list_send_receipts(conn, did)[-1]["status"] \
        == R_CONFLICTING


def test_ambiguous_mir_across_destinations(state, conn, tmp_path):
    """Dos sends con el mismo MIR+SEME (multi-destino, mismos
    bytes) -> AMBIGUOUS, ambos registrados, ninguno transiciona."""
    cfg = {"enabled": True, "destinations": [
        {"destination_id": "gw-a", "adapter": "filespool",
         "enabled": True, "message_schemas": ["*"],
         "config": {"spool_directory": str(tmp_path / "a")}},
        {"destination_id": "gw-b", "adapter": "filespool",
         "enabled": True, "message_schemas": ["*"],
         "config": {"spool_directory": str(tmp_path / "b")}}]}
    res = prepare_sends(conn, _msg_doc(), SEME, cfg, now=NOW)
    ids = [c["delivery_id"] for c in res["created"]]
    for did in ids:
        _set_status(conn, did, S_SPOOLED)
    out = ingest_fin_service_doc(
        conn, _receipt(), receipt_sha="9" * 64,
        source="FILE_INGEST:ack.fin", now=NOW)
    assert out["result"] == "QUARANTINED:AMBIGUOUS"
    for did in ids:
        assert get_send(conn, did)["status"] == S_SPOOLED
        assert list_send_receipts(conn, did)[-1][
            "quarantine_reason"] == "AMBIGUOUS"


# ------------------------------------------------------------------
# state rules
# ------------------------------------------------------------------

def test_ack_on_prepared_send_quarantined(state, conn, tmp_path):
    """Nunca se spooleo -> una evidencia de red es imposible."""
    did = _prepare(conn, tmp_path)
    res = ingest_fin_service_doc(
        conn, _receipt(), receipt_sha="1" * 64,
        source="FILE_INGEST:ack.fin", now=NOW)
    assert res["result"].startswith("QUARANTINED:UNEXPECTED_STATE")
    assert get_send(conn, did)["status"] == S_PREPARED


def test_duplicate_receipt_idempotent(state, conn, tmp_path):
    did = _prepare(conn, tmp_path)
    _set_status(conn, did, S_SPOOLED)
    ingest_fin_service_doc(conn, _receipt(), receipt_sha="2" * 64,
                           source="FILE_INGEST:a.fin", now=NOW)
    res = ingest_fin_service_doc(
        conn, _receipt(), receipt_sha="2" * 64,
        source="FILE_INGEST:a.fin", now=NOW)
    assert res["result"].startswith("DUPLICATE:")
    assert get_send(conn, did)["status"] == S_SWIFT_ACKED


def test_ack_then_nak_conflict_preserved(state, conn, tmp_path):
    """ACK y NAK para el mismo delivery: la segunda evidencia se
    registra CONFLICTING; el send conserva la primera. Sin
    precedencia inventada."""
    did = _prepare(conn, tmp_path)
    _set_status(conn, did, S_SPOOLED)
    ingest_fin_service_doc(conn, _receipt(ack=True),
                           receipt_sha="3" * 64,
                           source="FILE_INGEST:a.fin", now=NOW)
    res = ingest_fin_service_doc(
        conn, _receipt(ack=False, error="T33"),
        receipt_sha="4" * 64, source="FILE_INGEST:n.fin", now=NOW)
    assert res["result"] == "CONFLICTING:OPPOSING_NETWORK_EVIDENCE"
    send = get_send(conn, did)
    assert send["status"] == S_SWIFT_ACKED
    statuses = [r["status"] for r in list_send_receipts(conn, did)]
    assert statuses == [R_SWIFT_ACK, R_CONFLICTING]


def test_nak_then_ack_conflict_preserved(state, conn, tmp_path):
    did = _prepare(conn, tmp_path)
    _set_status(conn, did, S_SPOOLED)
    ingest_fin_service_doc(conn, _receipt(ack=False),
                           receipt_sha="5" * 64,
                           source="FILE_INGEST:n.fin", now=NOW)
    res = ingest_fin_service_doc(
        conn, _receipt(ack=True), receipt_sha="6" * 64,
        source="FILE_INGEST:a.fin", now=NOW)
    assert res["result"] == "CONFLICTING:OPPOSING_NETWORK_EVIDENCE"
    assert get_send(conn, did)["status"] == S_SWIFT_NAKED


def test_same_kind_receipt_reconfirms(state, conn, tmp_path):
    """Segundo ACK distinto para el mismo delivery: se registra
    como evidencia adicional sin transicion."""
    did = _prepare(conn, tmp_path)
    _set_status(conn, did, S_SPOOLED)
    ingest_fin_service_doc(conn, _receipt(), receipt_sha="7" * 64,
                           source="FILE_INGEST:a1.fin", now=NOW)
    res = ingest_fin_service_doc(
        conn, _receipt(), receipt_sha="8" * 64,
        source="FILE_INGEST:a2.fin", now=NOW)
    assert res["result"] == "RECONFIRMED:SWIFT_ACK"
    assert len(list_send_receipts(conn, did)) == 2


# ------------------------------------------------------------------
# malformed docs
# ------------------------------------------------------------------

def test_wrong_schema_quarantined(state, conn):
    res = ingest_fin_service_doc(
        conn, {"schema": "WRONG"}, receipt_sha="0" * 64,
        source="FILE_INGEST:x.fin", now=NOW)
    assert res["result"] == "QUARANTINED:WRONG_SCHEMA"


def test_parse_error_quarantined(state, conn):
    res = ingest_fin_service_doc(
        conn, {"schema": "CA_ES_FIN_SERVICE_RECEIPT_V1",
               "parse_status": "PARSE_ERROR", "is_ack": False,
               "is_nack": False},
        receipt_sha="0" * 64, source="FILE_INGEST:x.fin", now=NOW)
    assert res["result"] == "QUARANTINED:PARSE_ERROR"


def test_transitions_audited(state, conn, tmp_path):
    did = _prepare(conn, tmp_path)
    _set_status(conn, did, S_SPOOLED)
    ingest_fin_service_doc(conn, _receipt(), receipt_sha="a" * 64,
                           source="FILE_INGEST:a.fin", now=NOW)
    transitions = list_send_transitions(conn, did)
    assert transitions[-1]["from_status"] == S_SPOOLED
    assert transitions[-1]["to_status"] == S_SWIFT_ACKED
    assert transitions[-1]["actor"] == "send-ingest-fin"
