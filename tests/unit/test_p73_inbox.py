"""P7.3 — inbox MT/MX: dedup exacta/semantica, crash-safety,
deteccion por contenido, sin datos crudos en state."""
import json
from pathlib import Path

import pytest

from ca_es.ops_inbox import (
    DUPLICATE_SEMANTIC,
    EXACT_DUPLICATE,
    FAILED,
    PROCESSED,
    detect_family,
    process_inbox,
    semantic_fingerprint,
)
from ca_es.ops_state import OpsState
from ca_es.semantic_hash import byte_sha256

NOW = "2026-09-16T08:00:00Z"
FIN = b"{1:F01TEST}{4:{16R:GENL}{20C::SEME//REF1{16S:GENL}}"
XML = b'<?xml version="1.0"?><Document><CorpActnNtfctn/></Document>'


def _facts(mid="MT564", items=None, status="OK",
           family="ISO_15022_MT"):
    return {
        "schema_version": "CA_ES_SWIFT_MT_FACTS_V1",
        "standard_family": family,
        "message_identifier": mid,
        "parse_status": status,
        "generated_at": NOW,
        "input_sha256": "x",
        "facts": items or [],
    }


def _fact(path, value, tag="20C", qual="SEME", seq="GENL", occ=0):
    return {"field_path": path, "value": value, "source_tag": tag,
            "source_qualifier": qual, "sequence": seq,
            "occurrence": occ}


BASE_FACTS = [
    _fact("MT564.GENL.20C:SEME.reference", "SEME-1"),
    _fact("MT564.GENL.20C:CORP.reference", "CORP-9", qual="CORP"),
    _fact("MT564.GENL.23G.function", "NEWM", tag="23G", qual=None),
]


@pytest.fixture()
def env(tmp_path):
    state = OpsState(tmp_path / "state").init()
    inbox = tmp_path / "inbox"
    (inbox / "incoming").mkdir(parents=True)
    return state, inbox


def _drop(inbox: Path, name: str, data: bytes) -> Path:
    p = inbox / "incoming" / name
    p.write_bytes(data)
    return p


def _run(state, inbox, parser, **kw):
    conn = state._connect()
    try:
        doc = process_inbox(state, conn, inbox, run_id="r1",
                            parse_fn=parser, now=NOW, **kw)
        conn.commit()
        return doc
    finally:
        conn.close()


def _msgs(state):
    with state.open() as conn:
        rows = conn.execute(
            "SELECT * FROM inbox_messages ORDER BY received_at"
        ).fetchall()
    return [dict(r) for r in rows]


def test_detect_family_by_content_not_extension():
    assert detect_family(FIN) == "ISO_15022_MT"
    assert detect_family(XML) == "ISO_20022_MX"
    assert detect_family(b"   \n  <Doc/>") == "ISO_20022_MX"
    assert detect_family(b"") is None


def test_new_mt_message_processed(env):
    state, inbox = env
    _drop(inbox, "a.fin", FIN)
    parser = lambda fam, raw: (_facts(items=BASE_FACTS), 0)
    doc = _run(state, inbox, parser)
    m = doc["messages"][0]
    assert m["processing_status"] == PROCESSED
    assert m["message_identifier"] == "MT564"
    assert m["semantic_fingerprint"]
    assert not (inbox / "incoming/a.fin").exists()
    assert (inbox / "processed/a.fin").exists()
    msgs = _msgs(state)
    assert len(msgs) == 1
    assert msgs[0]["processing_status"] == PROCESSED
    # blob raw byte-exacto preservado
    sha = byte_sha256(FIN)
    blob = state.root / "blobs" / sha[:2] / f"{sha}.bin"
    assert blob.read_bytes() == FIN


def test_exact_duplicate_not_reprocessed(env):
    state, inbox = env
    calls = []
    parser = lambda fam, raw: (
        calls.append(raw) or (_facts(items=BASE_FACTS), 0))
    _drop(inbox, "a.fin", FIN)
    _run(state, inbox, parser)
    assert len(calls) == 1
    _drop(inbox, "b.fin", FIN)  # mismos bytes, otro nombre
    doc = _run(state, inbox, parser)
    assert doc["messages"][0]["processing_status"] == \
        EXACT_DUPLICATE
    assert len(calls) == 1  # no se re-parsea
    assert len(_msgs(state)) == 1
    assert (inbox / "processed/b.fin").exists()


def test_semantic_duplicate_different_bytes(env):
    state, inbox = env
    # mismos facts de negocio, bytes distintos (otro header FIN)
    fin2 = FIN.replace(b"F01TEST", b"F01OTRO")
    parser = lambda fam, raw: (_facts(items=BASE_FACTS), 0)
    _drop(inbox, "a.fin", FIN)
    _run(state, inbox, parser)
    _drop(inbox, "b.fin", fin2)
    doc = _run(state, inbox, parser)
    assert doc["messages"][0]["processing_status"] == \
        DUPLICATE_SEMANTIC
    msgs = _msgs(state)
    assert len(msgs) == 2  # ambas observaciones preservadas
    dups = [m for m in msgs
            if m["duplicate_status"] == "SEMANTIC"]
    assert len(dups) == 1


def test_different_business_facts_not_collapsed(env):
    state, inbox = env
    fin2 = FIN.replace(b"REF1", b"REF2")
    def parser(fam, raw):
        items = BASE_FACTS if b"REF1" in raw else [
            _fact("MT564.GENL.20C:SEME.reference", "SEME-2"),
            *BASE_FACTS[1:]]
        return _facts(items=items), 0
    _drop(inbox, "a.fin", FIN)
    _drop(inbox, "b.fin", fin2)
    doc = _run(state, inbox, parser)
    statuses = [m["processing_status"] for m in doc["messages"]]
    assert statuses == [PROCESSED, PROCESSED]


def test_parse_error_moves_to_failed(env):
    state, inbox = env
    _drop(inbox, "bad.fin", FIN)
    parser = lambda fam, raw: (
        _facts(status="PARSE_ERROR", items=[]), 2)
    doc = _run(state, inbox, parser)
    assert doc["messages"][0]["processing_status"] == FAILED
    assert (inbox / "failed/bad.fin").exists()
    msgs = _msgs(state)
    assert msgs[0]["processing_status"] == FAILED
    assert msgs[0]["semantic_fingerprint"] is None


def test_adapter_unavailable_marks_failed(env):
    state, inbox = env
    from ca_es.swift_mt import AdapterUnavailable
    _drop(inbox, "a.fin", FIN)
    def parser(fam, raw):
        raise AdapterUnavailable("jar no encontrado")
    doc = _run(state, inbox, parser)
    assert doc["messages"][0]["processing_status"] == FAILED
    assert (inbox / "failed/a.fin").exists()


def test_xml_routed_to_mx_parser(env):
    state, inbox = env
    seen = []
    def parser(fam, raw):
        seen.append(fam)
        return _facts(mid="seev.031.002.10",
                      family="ISO_20022_MX",
                      items=[_fact("/Doc/Evt/Id", "EV-1",
                                   tag=None, qual=None,
                                   seq=None)]), 0
    _drop(inbox, "n.fin", XML)  # extension .fin, contenido XML
    doc = _run(state, inbox, parser)
    assert seen == ["ISO_20022_MX"]
    assert doc["messages"][0]["message_identifier"] == \
        "seev.031.002.10"


def test_crash_between_commit_and_move_recovers(env):
    state, inbox = env
    parser = lambda fam, raw: (_facts(items=BASE_FACTS), 0)
    p = _drop(inbox, "a.fin", FIN)
    # simula crash post-commit: fila ya existe, fichero sigue
    conn = state._connect()
    conn.execute(
        "INSERT INTO inbox_messages(input_sha256, processing_status)"
        " VALUES (?, 'PROCESSED')", (byte_sha256(FIN),))
    conn.commit()
    conn.close()
    doc = _run(state, inbox, parser)
    assert doc["messages"][0]["processing_status"] == \
        EXACT_DUPLICATE
    assert not p.exists()
    assert (inbox / "processed/a.fin").exists()


def test_no_raw_content_in_db(env):
    state, inbox = env
    parser = lambda fam, raw: (_facts(items=BASE_FACTS), 0)
    _drop(inbox, "a.fin", FIN)
    _run(state, inbox, parser)
    with state.open() as conn:
        for table in ("inbox_messages", "inbox_observations"):
            rows = conn.execute(
                f"SELECT * FROM {table}").fetchall()
            for row in rows:
                for v in dict(row).values():
                    if isinstance(v, str):
                        assert "F01TEST" not in v
                        assert "SEME//" not in v


def test_semantic_fingerprint_policy():
    doc = _facts(items=BASE_FACTS)
    fp = semantic_fingerprint(doc)
    assert fp
    # execution metadata no afecta
    doc2 = dict(doc)
    doc2["generated_at"] = "2030-01-01T00:00:00Z"
    doc2["input_sha256"] = "otro"
    assert semantic_fingerprint(doc2) == fp
    # fact distinto -> fingerprint distinto
    doc3 = _facts(items=[*BASE_FACTS,
                         _fact("x", "y")])
    assert semantic_fingerprint(doc3) != fp
    # sin parse OK -> sin fingerprint
    assert semantic_fingerprint(_facts(status="PARSE_ERROR")) \
        is None
