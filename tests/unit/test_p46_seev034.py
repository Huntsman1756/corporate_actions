"""P4.6 — seev.034 status binding (docs/p4/p46-seev034-scope.md)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ca_es.mx_facts import FACTS_SCHEMA, parse_mx
from ca_es.mx_status import (
    AMBIGUOUS,
    BOUND,
    INSUFFICIENT_IDENTITY,
    NO_MATCH,
    STATUS_DOC_SCHEMA,
    bind_mx_instruction_status,
)
from ca_es.swift_mt import default_adapter_jar

REPO = Path(__file__).resolve().parents[2]
FIXTURE_XML = (
    REPO / "adapters" / "iso-adapter-jvm" / "src" / "test"
    / "resources" / "seev034-002.xml"
)
MID = "seev.034.002.15"
DOC = "/Document/CorpActnInstrStsAdvc"


def _fact(path, value, occ=0, sts=None):
    loc_path = path
    if sts is not None:
        loc_path = path.replace("/InstrPrcgSts/", f"/InstrPrcgSts[{sts}]/")
    return {
        "message_identifier": MID,
        "model_path": path,
        "value": value,
        "occurrence": occ,
        "evidence_locator": f"element:{loc_path}",
        "input_sha256": "6" * 64,
    }


def _facts_doc(*facts, mid=MID, parse_status="PARSE_OK"):
    return {
        "schema_version": FACTS_SCHEMA,
        "generated_at": "2026-09-18T00:00:00Z",
        "message_identifier": mid,
        "input_sha256": "6" * 64,
        "parse_status": parse_status,
        "facts": list(facts),
    }


def _status_facts(instr_id="INS-0001", choice="AccptdForFrthrPrcg",
                  reason_leaf="NoSpcfdRsn", reason_val="NORE",
                  narrative=None):
    facts = [
        _fact(f"{DOC}/InstrId/Id", instr_id),
        _fact(f"{DOC}/CorpActnGnlInf/CorpActnEvtId", "CORP-REF-42"),
        _fact(f"{DOC}/CorpActnGnlInf/EvtTp/Cd", "DVCA"),
    ]
    sub = {"AccptdForFrthrPrcg": "AccptdRsn", "Rjctd": "RjctdRsn",
           "Pdg": "PdgRsn", "DfltActn": "DfltActnRsn"}.get(choice, "Rsn")
    if reason_leaf:
        facts.append(_fact(
            f"{DOC}/InstrPrcgSts/{choice}/{sub}/{reason_leaf}",
            reason_val, sts=0,
        ))
    else:
        facts.append(_fact(
            f"{DOC}/InstrPrcgSts/{choice}/Qty/Unit", "1000", sts=0,
        ))
    if narrative:
        facts.append(_fact(
            f"{DOC}/InstrPrcgSts/{choice}/{sub}/Rsn/AddtlRsnInf",
            narrative, sts=0,
        ))
    return facts


def _instruction(iid="INS-0001"):
    return {
        "schema": "CA_ES_ELECTION_INSTRUCTION_V1",
        "instruction_id": iid,
        "canonical_event_id": "evt-1",
        "source_canon_logical_sha256": "a" * 64,
        "source_positions_logical_sha256": "b" * 64,
        "source_message_input_sha256": "c" * 64,
        "status": "READY",
        "fields": {},
    }


def test_bound_accepted():
    doc = bind_mx_instruction_status(
        _facts_doc(*_status_facts()), _instruction()
    )
    assert doc["schema"] == STATUS_DOC_SCHEMA
    assert doc["instruction_binding_status"] == BOUND
    assert doc["canonical_event_id"] == "evt-1"
    st = doc["statuses"][0]
    assert st["normalized_status"] == "ACCEPTED"
    assert st["status_code_raw"] == "AccptdForFrthrPrcg"
    assert st["reason_code_raw"] == "NORE"
    assert st["reason_qualifier"] == "NoSpcfdRsn"
    assert doc["source_message_identifier"] == MID


def test_rejected_pending_default():
    for choice, norm in [("Rjctd", "REJECTED"), ("Pdg", "PENDING"),
                         ("DfltActn", "DEFAULT_ACTION_APPLIED")]:
        doc = bind_mx_instruction_status(
            _facts_doc(*_status_facts(choice=choice)),
            _instruction(),
        )
        assert doc["statuses"][0]["normalized_status"] == norm


def test_unsupported_choice_preserved_raw():
    doc = bind_mx_instruction_status(
        _facts_doc(*_status_facts(choice="PrtrySts", reason_leaf=None)),
        _instruction(),
    )
    st = doc["statuses"][0]
    assert st["normalized_status"] == "UNSUPPORTED"
    assert st["status_code_raw"] == "PrtrySts"


def test_no_match():
    doc = bind_mx_instruction_status(
        _facts_doc(*_status_facts()), _instruction("OTHER-ID")
    )
    assert doc["instruction_binding_status"] == NO_MATCH
    assert doc["canonical_event_id"] is None


def test_insufficient_identity():
    facts = [f for f in _status_facts() if "/InstrId/" not in f["model_path"]]
    doc = bind_mx_instruction_status(_facts_doc(*facts), _instruction())
    assert doc["instruction_binding_status"] == INSUFFICIENT_IDENTITY


def test_ambiguous_multiple_ids():
    facts = _status_facts() + [_fact(f"{DOC}/InstrId/Id", "INS-9999", occ=1)]
    doc = bind_mx_instruction_status(_facts_doc(*facts), _instruction())
    assert doc["instruction_binding_status"] == AMBIGUOUS


def test_multiple_status_occurrences():
    facts = _status_facts() + [
        _fact(f"{DOC}/InstrPrcgSts/Pdg/PdgRsn/NoSpcfdRsn", "NORE", sts=1),
    ]
    doc = bind_mx_instruction_status(_facts_doc(*facts), _instruction())
    assert len(doc["statuses"]) == 2
    assert [s["normalized_status"] for s in doc["statuses"]] == [
        "ACCEPTED", "PENDING",
    ]


def test_wrong_message():
    with pytest.raises(ValueError, match="EXPECTED_SEEV034"):
        bind_mx_instruction_status(
            _facts_doc(*_status_facts(), mid="seev.031.002.15"),
            _instruction(),
        )
    with pytest.raises(ValueError, match="EXPECTED_PARSE_OK"):
        bind_mx_instruction_status(
            _facts_doc(*_status_facts(), parse_status="PARSE_ERROR"),
            _instruction(),
        )
    with pytest.raises(ValueError, match="INVALID_INSTRUCTION_DOCUMENT"):
        bind_mx_instruction_status(_facts_doc(*_status_facts()), {})


def test_narrative_reason():
    doc = bind_mx_instruction_status(
        _facts_doc(*_status_facts(
            choice="Rjctd", narrative="duplicate instruction",
        )),
        _instruction(),
    )
    st = doc["statuses"][0]
    assert st["reason_narrative"] == "duplicate instruction"


def test_e2e_seev034_parity():
    """seev.034 real -> facts -> BOUND+ACCEPTED, paridad con MT567 PACK."""
    jar = default_adapter_jar()
    if not jar.is_file():
        pytest.skip("adapter jar no construido")
    xml = FIXTURE_XML.read_bytes()
    facts_doc, rc = parse_mx(xml)
    assert rc == 0
    assert facts_doc["message_identifier"] == "seev.034.002.15"
    doc = bind_mx_instruction_status(facts_doc, _instruction())
    assert doc["instruction_binding_status"] == BOUND
    assert doc["statuses"][0]["normalized_status"] == "ACCEPTED"
    json.dumps(doc)


def test_e2e_mt567_vs_seev034_equivalence():
    """MT567 IPRC//PACK y seev.034 AccptdForFrthrPrcg -> mismo normalized."""
    jar = default_adapter_jar()
    if not jar.is_file():
        pytest.skip("adapter jar no construido")
    from ca_es.instruction_status import bind_instruction_status
    from ca_es.swift_mt import parse_mt

    fin = (
        REPO / "adapters" / "iso-adapter-jvm" / "src" / "test"
        / "resources" / "mt567-inst.fin"
    ).read_text(encoding="utf-8")
    mt_doc, rc = parse_mt(fin)
    assert rc == 0
    mt_status = bind_instruction_status(mt_doc, _instruction())
    xml = FIXTURE_XML.read_bytes()
    mx_doc, _ = parse_mx(xml)
    mx_status = bind_mx_instruction_status(mx_doc, _instruction())
    assert (
        mt_status["instruction_binding_status"]
        == mx_status["instruction_binding_status"]
        == BOUND
    )
    assert (
        mt_status["statuses"][0]["normalized_status"]
        == mx_status["statuses"][0]["normalized_status"]
        == "ACCEPTED"
    )
