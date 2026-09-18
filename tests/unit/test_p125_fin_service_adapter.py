"""P12.5 — integracion real: fichero FIN service -> adapter JVM
(Prowide) -> correlacion en el send ledger -> SWIFT_ACKED/NAKED.

Corre en el job `jvm` de CI (requiere el fatJar construido).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ca_es.ops_fin import ingest_fin_service_file, parse_fin_service
from ca_es.ops_send import (
    S_SPOOLED, S_SWIFT_ACKED, S_SWIFT_NAKED, content_sha256_of,
    get_send, prepare_sends)
from ca_es.ops_state import OpsState
from ca_es.swift_mt import AdapterUnavailable, default_adapter_jar

LT = "TESTES00XXXX"
SESS, SEQ = "1234", "000079"
SEME = "INS-0001"
NOW = "2026-07-16T00:00:00Z"

ORIG_FIN = (f"{{1:F01{LT}{SESS}{SEQ}}}{{2:I565BANKGB2LXXXXN}}"
            "{4:\n:16R:GENL\n:20C::SEME//INS-0001\n"
            ":20C::CORP//CORP-REF-42\n:23G:NEWM\n:16S:GENL\n-}")

ACK = ("{1:F21LITEBEBBAXXX0066000080}"
       "{4:{177:2607160901}{451:0}}" + ORIG_FIN
       + "{5:{CHK:7602B010CF31}{TNG:}}")

NAK = ("{1:F21LITEBEBBAXXX0066000081}"
       "{4:{177:2607160902}{451:1}{405:T33002}}" + ORIG_FIN
       + "{5:{CHK:7602B010CF32}{TNG:}}")


@pytest.fixture()
def jar():
    j = default_adapter_jar()
    if not j.is_file():
        raise AdapterUnavailable("adapter jar no encontrado")
    return j


@pytest.fixture()
def conn(tmp_path):
    state = OpsState(tmp_path / "st").init()
    c = state.acquire_run_lock("test-run")
    yield c
    state.release_run_lock()


def _prepare(conn, tmp_path):
    cfg = {"enabled": True, "destinations": [{
        "destination_id": "gw-file-1", "adapter": "filespool",
        "enabled": True, "message_schemas": ["*"],
        "config": {"spool_directory": str(tmp_path / "spool")}}]}
    doc = {"schema": "CA_ES_MT565_FIN_V1", "write_status": "OK",
           "fin": ORIG_FIN, "fin_sha256": content_sha256_of(ORIG_FIN)}
    res = prepare_sends(conn, doc, SEME, cfg, now=NOW)
    return res["created"][0]["delivery_id"]


def test_finsvc_parses_real_ack(jar):
    doc, code = parse_fin_service(ACK.encode("utf-8"), jar=jar)
    assert code == 0
    assert doc["schema"] == "CA_ES_FIN_SERVICE_RECEIPT_V1"
    assert doc["is_ack"] is True
    assert doc["field_451"] == "0"
    copy = doc["embedded_copy"]
    assert copy["present"] is True
    assert copy["mir_lt"] == LT
    assert copy["seme"] == SEME


def test_finsvc_parses_real_nak(jar):
    doc, code = parse_fin_service(NAK.encode("utf-8"), jar=jar)
    assert code == 0
    assert doc["is_nack"] is True
    assert doc["field_405"] == "T33002"


def test_full_leg_ack_flows_to_swift_acked(conn, tmp_path, jar):
    """LEG F1: MT565 -> FIN ACK -> correlacion -> SWIFT_ACKED."""
    did = _prepare(conn, tmp_path)
    conn.execute("UPDATE sends SET status=? WHERE delivery_id=?",
                 (S_SPOOLED, did))
    ack_file = tmp_path / "ack.fin"
    ack_file.write_text(ACK, encoding="utf-8")
    res = ingest_fin_service_file(conn, ack_file, jar=jar, now=NOW)
    assert res["result"] == "SWIFT_ACK"
    assert res["delivery_id"] == did
    assert get_send(conn, did)["status"] == S_SWIFT_ACKED


def test_full_leg_nak_flows_to_swift_naked(conn, tmp_path, jar):
    """LEG F2: MT565 -> FIN NAK -> correlacion -> SWIFT_NAKED."""
    did = _prepare(conn, tmp_path)
    conn.execute("UPDATE sends SET status=? WHERE delivery_id=?",
                 (S_SPOOLED, did))
    nak_file = tmp_path / "nak.fin"
    nak_file.write_text(NAK, encoding="utf-8")
    res = ingest_fin_service_file(conn, nak_file, jar=jar, now=NOW)
    assert res["result"] == "SWIFT_NAK"
    assert get_send(conn, did)["status"] == S_SWIFT_NAKED


def test_service_message_for_unknown_send(conn, tmp_path, jar):
    """LEG F3: ACK para un MIR que no existe -> NO_MATCH."""
    _prepare(conn, tmp_path)
    foreign = ("{1:F21LITEBEBBAXXX0066000080}"
               "{4:{177:2607160901}{451:0}}"
               "{1:F01OTHERES00XXX9999888888}{2:I565BANKGB2LXXXXN}"
               "{4:\n:20C::SEME//NOPE\n-}"
               "{5:{CHK:7602B010CF33}{TNG:}}")
    f = tmp_path / "other.fin"
    f.write_text(foreign, encoding="utf-8")
    res = ingest_fin_service_file(conn, f, jar=jar, now=NOW)
    assert res["result"] == "QUARANTINED:NO_MATCH"
