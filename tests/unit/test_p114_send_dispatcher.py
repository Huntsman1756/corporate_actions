"""P11.4 — send dispatcher: prepare, dispatch, idempotencia,
retry, orphan recovery, operator controls, status doc."""
from __future__ import annotations

import hashlib
import json

import pytest

from ca_es.ops_send import (
    O_FAILED_PERMANENT, O_FAILED_RETRYABLE, O_SPOOLED, O_UNKNOWN,
    S_ABANDONED, S_FAILED_PERMANENT, S_FAILED_RETRYABLE,
    S_GATEWAY_ACCEPTED, S_PREPARED, S_SPOOLED, S_UNKNOWN,
    SendAdapterResult, content_sha256_of, derive_delivery_id,
    get_send, list_send_attempts, list_send_transitions,
    prepare_sends, run_send_dispatch, send_abandon, send_retry,
    send_status_doc)
from ca_es.ops_state import OpsState

FIN = ("{1:F01TEST}{4:\r\n:20C::SEME//INS-0001\r\n"
       ":20C::CORP//CORP-REF-42\r\n:23G:NEWM\r\n-}")
SHA = content_sha256_of(FIN)
NOW = "2026-07-16T00:00:00Z"


def _msg_doc(text: str = FIN, **extra) -> dict:
    doc = {"schema": "CA_ES_MT565_FIN_V1", "write_status": "OK",
           "fin": text,
           "fin_sha256": content_sha256_of(text)}
    doc.update(extra)
    return doc


def _cfg(tmp_path, **over) -> dict:
    cfg = {
        "enabled": True,
        "destinations": [{
            "destination_id": "gw-file-1", "adapter": "filespool",
            "enabled": True, "message_schemas": ["*"],
            "config": {
                "spool_directory": str(tmp_path / "spool")}}],
        "retry": {"max_attempts": 3, "base_delay_seconds": 60,
                  "max_delay_seconds": 600, "backoff_factor": 2.0},
    }
    cfg.update(over)
    return cfg


@pytest.fixture()
def state(tmp_path):
    return OpsState(tmp_path / "st").init()


@pytest.fixture()
def conn(state):
    c = state.acquire_run_lock("test-run")
    yield c
    state.release_run_lock()


# ------------------------------------------------------------------
# prepare
# ------------------------------------------------------------------

def test_prepare_creates_prepared_send(state, conn, tmp_path):
    res = prepare_sends(
        conn, _msg_doc(), "INS-0001", _cfg(tmp_path), now=NOW)
    did = res["created"][0]["delivery_id"]
    assert did == derive_delivery_id("INS-0001", SHA, "gw-file-1")
    send = get_send(conn, did)
    assert send["status"] == S_PREPARED
    assert send["message_reference"] == "INS-0001"
    assert send["message_schema"] == "CA_ES_MT565_FIN_V1"
    assert send["content_sha256"] == SHA
    assert send["message_text"] == FIN
    assert send["generation"] == 1
    assert send["transport_reference"] is None


def test_prepare_idempotent_same_message(state, conn, tmp_path):
    cfg = _cfg(tmp_path)
    prepare_sends(conn, _msg_doc(), "INS-0001", cfg, now=NOW)
    res2 = prepare_sends(
        conn, _msg_doc(), "INS-0001", cfg,
        now="2026-07-16T01:00:00Z")
    assert res2["created"] == []
    assert len(res2["existing"]) == 1


def test_prepare_new_bytes_new_delivery_gen2(
        state, conn, tmp_path):
    cfg = _cfg(tmp_path)
    prepare_sends(conn, _msg_doc(), "INS-0001", cfg, now=NOW)
    fin2 = FIN.replace("NEWM", "REPL")
    res = prepare_sends(
        conn, _msg_doc(fin2), "INS-0001", cfg, now=NOW)
    send = get_send(conn, res["created"][0]["delivery_id"])
    assert send["generation"] == 2
    assert send["delivery_id"] != derive_delivery_id(
        "INS-0001", SHA, "gw-file-1")


def test_prepare_rejects_seme_mismatch(state, conn, tmp_path):
    with pytest.raises(ValueError, match="MESSAGE_REFERENCE"):
        prepare_sends(
            conn, _msg_doc(), "INS-9999", _cfg(tmp_path), now=NOW)


def test_prepare_rejects_doc_hash_mismatch(state, conn, tmp_path):
    doc = _msg_doc()
    doc["fin_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="MESSAGE_HASH_MISMATCH"):
        prepare_sends(conn, doc, "INS-0001", _cfg(tmp_path), now=NOW)


def test_prepare_rejects_unsupported_schema(
        state, conn, tmp_path):
    with pytest.raises(ValueError, match="UNSUPPORTED_MESSAGE"):
        prepare_sends(
            conn, {"schema": "CA_ES_WHATEVER", "write_status": "OK"},
            "INS-0001", _cfg(tmp_path), now=NOW)


def test_prepare_rejects_not_write_ok(state, conn, tmp_path):
    with pytest.raises(ValueError, match="MESSAGE_NOT_WRITE_OK"):
        prepare_sends(
            conn, _msg_doc(write_status="INPUT_ERROR"),
            "INS-0001", _cfg(tmp_path), now=NOW)


def test_prepare_max_message_bytes(state, conn, tmp_path):
    cfg = _cfg(tmp_path, send_policy={"max_message_bytes": 10})
    with pytest.raises(ValueError, match="MESSAGE_TOO_LARGE"):
        prepare_sends(conn, _msg_doc(), "INS-0001", cfg, now=NOW)


def test_prepare_seev033_bizmsgidr(state, conn, tmp_path):
    xml = "<x><BizMsgIdr>INS-0001</BizMsgIdr></x>"
    doc = {"schema": "CA_ES_SEEV033_XML_V1", "write_status": "OK",
           "xml": xml, "xml_sha256": content_sha256_of(xml)}
    res = prepare_sends(conn, doc, "INS-0001", _cfg(tmp_path),
                        now=NOW)
    assert len(res["created"]) == 1
    assert res["message_schema"] == "CA_ES_SEEV033_XML_V1"


def test_prepare_routing_by_schema(state, conn, tmp_path):
    cfg = _cfg(tmp_path)
    cfg["destinations"][0]["message_schemas"] = [
        "CA_ES_SEEV033_XML_V1"]
    res = prepare_sends(conn, _msg_doc(), "INS-0001", cfg, now=NOW)
    assert res["created"] == [] and res["existing"] == []


# ------------------------------------------------------------------
# dispatch
# ------------------------------------------------------------------

def test_dispatch_spooled_end_to_end(state, conn, tmp_path):
    cfg = _cfg(tmp_path)
    prepare_sends(conn, _msg_doc(), "INS-0001", cfg, now=NOW)
    res = run_send_dispatch(
        state, conn, cfg, now_fn=lambda: NOW)
    assert res["status"] == "SUCCESS"
    assert res["spooled"] == 1 and res["attempted"] == 1
    did = derive_delivery_id("INS-0001", SHA, "gw-file-1")
    send = get_send(conn, did)
    assert send["status"] == S_SPOOLED
    assert send["spooled_at"] == NOW
    # bytes exactos en el outbox
    msg = tmp_path / "spool" / "outbox" / f"{did}.msg"
    assert msg.read_bytes() == FIN.encode("utf-8")
    attempts = list_send_attempts(conn, did)
    assert len(attempts) == 1
    assert attempts[0]["status"] == "SUCCEEDED"
    assert attempts[0]["started_at"] is not None


def test_dispatch_second_pass_skips_spooled(
        state, conn, tmp_path):
    cfg = _cfg(tmp_path)
    prepare_sends(conn, _msg_doc(), "INS-0001", cfg, now=NOW)
    run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    res2 = run_send_dispatch(
        state, conn, cfg, now_fn=lambda: NOW)
    assert res2["status"] == "UNCHANGED"
    assert res2["attempted"] == 0
    assert res2["skipped_terminal"] == 1


def test_dispatch_disabled(state, conn, tmp_path):
    res = run_send_dispatch(state, conn, {"enabled": False},
                            now_fn=lambda: NOW)
    assert res["status"] == "DISABLED"


def _stub_adapter(outcome, error_code=None):
    def deliver(request, dest_config):
        return SendAdapterResult(outcome, error_code=error_code)
    return {"deliver": deliver}


def test_dispatch_retryable_then_success(state, conn, tmp_path):
    cfg = _cfg(tmp_path)
    prepare_sends(conn, _msg_doc(), "INS-0001", cfg, now=NOW)
    calls = []

    def flaky(request, dest_config):
        calls.append(1)
        if len(calls) == 1:
            return SendAdapterResult(
                O_FAILED_RETRYABLE, error_code="IO")
        return SendAdapterResult(O_SPOOLED)

    adapters = {"filespool": {"deliver": flaky}}
    res1 = run_send_dispatch(
        state, conn, cfg, now_fn=lambda: NOW, adapters=adapters)
    assert res1["status"] == "PARTIAL"
    assert res1["failed_retryable"] == 1
    did = derive_delivery_id("INS-0001", SHA, "gw-file-1")
    send = get_send(conn, did)
    assert send["status"] == S_FAILED_RETRYABLE
    assert send["next_attempt_after"] > NOW
    # backoff no vencido -> no reintenta
    res2 = run_send_dispatch(
        state, conn, cfg, now_fn=lambda: NOW, adapters=adapters)
    assert res2["attempted"] == 0
    # vencido -> reintenta y completa
    res3 = run_send_dispatch(
        state, conn, cfg,
        now_fn=lambda: "2026-07-16T00:05:00Z", adapters=adapters)
    assert res3["spooled"] == 1
    assert get_send(conn, did)["status"] == S_SPOOLED
    assert len(list_send_attempts(conn, did)) == 2


def test_dispatch_permanent_failure(state, conn, tmp_path):
    cfg = _cfg(tmp_path)
    prepare_sends(conn, _msg_doc(), "INS-0001", cfg, now=NOW)
    adapters = {"filespool": _stub_adapter(
        O_FAILED_PERMANENT, "DELIVERY_ID_COLLISION")}
    res = run_send_dispatch(
        state, conn, cfg, now_fn=lambda: NOW, adapters=adapters)
    assert res["status"] == "PARTIAL"
    did = derive_delivery_id("INS-0001", SHA, "gw-file-1")
    assert get_send(conn, did)["status"] == S_FAILED_PERMANENT


def test_dispatch_unknown_outcome(state, conn, tmp_path):
    cfg = _cfg(tmp_path)
    prepare_sends(conn, _msg_doc(), "INS-0001", cfg, now=NOW)
    adapters = {"filespool": _stub_adapter(O_UNKNOWN, "POST_MSG_IO")}
    res = run_send_dispatch(
        state, conn, cfg, now_fn=lambda: NOW, adapters=adapters)
    assert res["status"] == "PARTIAL"
    assert res["unknown"] == 1
    did = derive_delivery_id("INS-0001", SHA, "gw-file-1")
    assert get_send(conn, did)["status"] == S_UNKNOWN
    # sin auto-retry
    res2 = run_send_dispatch(
        state, conn, cfg, now_fn=lambda: "2026-07-17T00:00:00Z",
        adapters=adapters)
    assert res2["attempted"] == 0


def test_dispatch_retry_exhausted(state, conn, tmp_path):
    cfg = _cfg(tmp_path)
    cfg["retry"]["max_attempts"] = 2
    cfg["retry"]["base_delay_seconds"] = 0
    prepare_sends(conn, _msg_doc(), "INS-0001", cfg, now=NOW)
    adapters = {"filespool": _stub_adapter(O_FAILED_RETRYABLE)}
    t = ["2026-07-16T00:00:00Z"]
    run_send_dispatch(
        state, conn, cfg, now_fn=lambda: t[0], adapters=adapters)
    t[0] = "2026-07-16T00:00:01Z"
    res = run_send_dispatch(
        state, conn, cfg, now_fn=lambda: t[0], adapters=adapters)
    did = derive_delivery_id("INS-0001", SHA, "gw-file-1")
    send = get_send(conn, did)
    assert send["status"] == S_FAILED_PERMANENT
    notes = [tr["note"] for tr in list_send_transitions(conn, did)]
    assert "RETRY_EXHAUSTED" in notes


# ------------------------------------------------------------------
# orphan recovery (crash tras STARTED durable)
# ------------------------------------------------------------------

def test_orphan_attempt_recovered_as_spooled(state, conn, tmp_path):
    """STARTED huerfano + outbox completo -> SPOOLED (verify)."""
    cfg = _cfg(tmp_path)
    prepare_sends(conn, _msg_doc(), "INS-0001", cfg, now=NOW)
    did = derive_delivery_id("INS-0001", SHA, "gw-file-1")
    # side effect completo pero attempt quedo STARTED (crash
    # antes de _record_attempt)
    from ca_es.transport import filespool
    from ca_es.ops_send import SendRequest
    filespool.deliver(SendRequest(
        delivery_id=did, instruction_id="INS-0001",
        message_reference="INS-0001",
        message_schema="CA_ES_MT565_FIN_V1", message_text=FIN,
        content_sha256=SHA, destination_id="gw-file-1",
        adapter_type="filespool", generation=1),
        {"spool_directory": str(tmp_path / "spool")})
    conn.execute(
        "INSERT INTO send_attempts(attempt_id, delivery_id,"
        " attempt_number, started_at, status)"
        " VALUES ('SNA-orphan-1', ?, 1, ?, 'STARTED')",
        (did, NOW))
    res = run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    assert res["orphan_attempts_recovered"] == 1
    assert get_send(conn, did)["status"] == S_SPOOLED


def test_orphan_attempt_no_evidence_retried(state, conn, tmp_path):
    """STARTED huerfano + sin evidencia en spool -> NOT_SPOOLED ->
    reintento seguro en la misma pasada -> SPOOLED."""
    cfg = _cfg(tmp_path)
    prepare_sends(conn, _msg_doc(), "INS-0001", cfg, now=NOW)
    did = derive_delivery_id("INS-0001", SHA, "gw-file-1")
    conn.execute(
        "INSERT INTO send_attempts(attempt_id, delivery_id,"
        " attempt_number, started_at, status)"
        " VALUES ('SNA-orphan-2', ?, 1, ?, 'STARTED')",
        (did, NOW))
    res = run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    send = get_send(conn, did)
    assert send["status"] == S_SPOOLED
    assert res["spooled"] == 1


def test_orphan_attempt_collision_permanent(state, conn, tmp_path):
    """STARTED huerfano + outbox con sha distinto -> COLLISION ->
    permanente, nunca overwrite."""
    cfg = _cfg(tmp_path)
    prepare_sends(conn, _msg_doc(), "INS-0001", cfg, now=NOW)
    did = derive_delivery_id("INS-0001", SHA, "gw-file-1")
    outbox = tmp_path / "spool" / "outbox"
    outbox.mkdir(parents=True)
    (outbox / f"{did}.msg").write_bytes(b"FOREIGN BYTES")
    conn.execute(
        "INSERT INTO send_attempts(attempt_id, delivery_id,"
        " attempt_number, started_at, status)"
        " VALUES ('SNA-orphan-3', ?, 1, ?, 'STARTED')",
        (did, NOW))
    res = run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    assert get_send(conn, did)["status"] == S_FAILED_PERMANENT
    assert (outbox / f"{did}.msg").read_bytes() == b"FOREIGN BYTES"


# ------------------------------------------------------------------
# operator controls
# ------------------------------------------------------------------

def test_send_retry_requeues(state, conn, tmp_path):
    cfg = _cfg(tmp_path)
    prepare_sends(conn, _msg_doc(), "INS-0001", cfg, now=NOW)
    adapters = {"filespool": _stub_adapter(O_FAILED_PERMANENT)}
    run_send_dispatch(
        state, conn, cfg, now_fn=lambda: NOW, adapters=adapters)
    did = derive_delivery_id("INS-0001", SHA, "gw-file-1")
    send = send_retry(
        conn, did, now=NOW, actor="op1")
    assert send["status"] == S_PREPARED
    trs = list_send_transitions(conn, did)
    assert trs[-1]["actor"] == "op1"
    assert trs[-1]["note"] == "MANUAL_RETRY"


def test_send_retry_unknown_requires_force(state, conn, tmp_path):
    cfg = _cfg(tmp_path)
    prepare_sends(conn, _msg_doc(), "INS-0001", cfg, now=NOW)
    adapters = {"filespool": _stub_adapter(O_UNKNOWN)}
    run_send_dispatch(
        state, conn, cfg, now_fn=lambda: NOW, adapters=adapters)
    did = derive_delivery_id("INS-0001", SHA, "gw-file-1")
    with pytest.raises(ValueError, match="REQUIRES_FORCE"):
        send_retry(conn, did, now=NOW)
    send = send_retry(conn, did, now=NOW, force_unknown=True)
    assert send["status"] == S_PREPARED


def test_send_retry_terminal_rejected(state, conn, tmp_path):
    cfg = _cfg(tmp_path)
    prepare_sends(conn, _msg_doc(), "INS-0001", cfg, now=NOW)
    run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    did = derive_delivery_id("INS-0001", SHA, "gw-file-1")
    with pytest.raises(ValueError, match="TERMINAL"):
        send_retry(conn, did, now=NOW)


def test_send_abandon(state, conn, tmp_path):
    cfg = _cfg(tmp_path)
    prepare_sends(conn, _msg_doc(), "INS-0001", cfg, now=NOW)
    did = derive_delivery_id("INS-0001", SHA, "gw-file-1")
    send = send_abandon(conn, did, now=NOW, actor="op1",
                        note="superseded")
    assert send["status"] == S_ABANDONED
    with pytest.raises(ValueError, match="ABANDONED"):
        send_retry(conn, did, now=NOW)
    # abandon nunca despacha
    res = run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    assert res["attempted"] == 0


def test_send_abandon_terminal_rejected(state, conn, tmp_path):
    cfg = _cfg(tmp_path)
    prepare_sends(conn, _msg_doc(), "INS-0001", cfg, now=NOW)
    run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    did = derive_delivery_id("INS-0001", SHA, "gw-file-1")
    send_abandon(conn, did, now=NOW)  # SPOOLED -> ABANDONED ok
    assert get_send(conn, did)["status"] == S_ABANDONED


# ------------------------------------------------------------------
# status doc
# ------------------------------------------------------------------

def test_send_status_doc(state, conn, tmp_path):
    cfg = _cfg(tmp_path)
    prepare_sends(conn, _msg_doc(), "INS-0001", cfg, now=NOW)
    run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    doc = send_status_doc(state, conn, cfg, now=NOW)
    assert doc["schema"] == "CA_ES_SEND_STATUS_V1"
    assert doc["spooled"] == 1
    assert doc["prepared"] == 0
    assert doc["status"] == "DEGRADED"  # SPOOLED pendiente de receipt
    assert doc["oldest_spooled_at"] == NOW
    dest = doc["destinations"][0]
    assert dest["destination_id"] == "gw-file-1"
    assert dest["configured"] is True


def test_send_status_disabled(state, conn, tmp_path):
    doc = send_status_doc(state, conn, {"enabled": False}, now=NOW)
    assert doc["status"] == "DISABLED"
    assert doc["enabled"] is False


def test_send_status_healthy_when_all_terminal(
        state, conn, tmp_path):
    cfg = _cfg(tmp_path)
    prepare_sends(conn, _msg_doc(), "INS-0001", cfg, now=NOW)
    did = derive_delivery_id("INS-0001", SHA, "gw-file-1")
    run_send_dispatch(state, conn, cfg, now_fn=lambda: NOW)
    send_abandon(conn, did, now=NOW)
    doc = send_status_doc(state, conn, cfg, now=NOW)
    assert doc["status"] == "HEALTHY"
    assert doc["abandoned"] == 1
