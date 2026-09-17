"""P5.5 — MT565 projection + writer JVM (docs/p5/p55-scope.md)."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ca_es.mt565 import (
    ENVELOPE_SCHEMA,
    FIN_SCHEMA,
    PROJ_NOT_SERIALIZABLE,
    PROJ_SERIALIZABLE,
    PROJECTION_SCHEMA,
    mt565_project,
    write_mt565,
)
from ca_es.swift_mt import AdapterUnavailable, default_adapter_jar

REPO = Path(__file__).resolve().parents[2]
FIXTURE_FIN = (
    REPO / "adapters" / "iso-adapter-jvm" / "src" / "test"
    / "resources" / "mt564-volu.fin"
)


def _fact(seq, tag, qual, value, label="value"):
    return {
        "message_identifier": "MT564",
        "field_path": f"MT564.{seq}.{tag}:{qual}.{label}" if qual
        else f"MT564.{seq}.{tag}.{label}",
        "value": value,
        "source_tag": tag,
        "source_qualifier": qual,
        "sequence": seq,
        "occurrence": 0,
        "evidence_locator": "block4.tag[0]",
        "input_sha256": "f" * 64,
    }


def _facts(*facts):
    return {
        "schema_version": "CA_ES_SWIFT_MT_FACTS_V1",
        "generated_at": "2026-09-18T00:00:00Z",
        "standard_family": "ISO15022",
        "standard_release": "SRU2025",
        "release_state_as_of": "2026-09-16",
        "library": "prowide-core",
        "library_version": "SRU2025-10.3.19",
        "adapter_version": "0.1.0",
        "message_identifier": "MT564",
        "input_sha256": "f" * 64,
        "parse_status": "OK",
        "detail": None,
        "facts": list(facts),
    }


def _good_facts():
    return _facts(
        _fact("GENL", "20C", "SEME", "REFSEME004"),
        _fact("GENL", "20C", "CORP", "CORP-REF-42"),
        _fact("GENL", "22F", "CAEV", "VOLU"),
    )


def _instruction(**over):
    doc = {
        "schema": "CA_ES_ELECTION_INSTRUCTION_V1",
        "generated_at": "2026-09-18T00:00:00Z",
        "instruction_id": "INS-0001",
        "canonical_event_id": "evt-001",
        "account_id": "ACC-01",
        "isin": "ES0105448007",
        "option_key": "opt-001",
        "option_identifier": "001",
        "option_code_raw": "CASH",
        "option_kind": "CASH",
        "requested_quantity": "12500",
        "eligible_quantity": "12500",
        "instruction_status": "READY",
        "reasons": [],
        "actor": "ops",
        "instructed_at": "2026-09-18T09:00:00Z",
        "source_canon_logical_sha256": "c" * 64,
        "source_positions_logical_sha256": "p" * 64,
        "source_message_input_sha256": "f" * 64,
        "eligibility_key": "evt-001|ACC-01|opt-001",
        "eligibility_rule_id": "rule-1",
        "evidence": {},
    }
    doc.update(over)
    return doc


def _envelope(**over):
    doc = {
        "schema": ENVELOPE_SCHEMA,
        "sender_bic": "BANKESMMAXX",
        "receiver_bic": "BANKDEFFXXX",
        "session_number": "0000",
        "sequence_number": "000005",
        "priority": "N",
    }
    doc.update(over)
    return doc


def _values(doc, tag):
    return [f["value"] for f in doc["fields"] if f["tag"] == tag]


# 1. happy path
def test_ready_serializable_exact_fields():
    doc = mt565_project(
        _instruction(), _good_facts(), _envelope(), now="N"
    )
    assert doc["schema"] == PROJECTION_SCHEMA
    assert doc["projection_status"] == PROJ_SERIALIZABLE
    assert doc["reasons"] == []
    assert doc["source_instruction_id"] == "INS-0001"
    assert doc["canonical_event_id"] == "evt-001"
    assert doc["source_message_input_sha256"] == "f" * 64
    assert doc["envelope"]["sender_lt"] == "BANKESMMAXXX"
    assert doc["envelope"]["receiver_lt"] == "BANKDEFFXXXX"

    tags = [(f["tag"], f["value"]) for f in doc["fields"]]
    assert tags == [
        ("16R", "GENL"),
        ("20C", ":SEME//INS-0001"),
        ("20C", ":CORP//CORP-REF-42"),
        ("23G", "NEWM"),
        ("22F", ":CAEV//VOLU"),
        ("16R", "LINK"),
        ("13A", ":LINK//564"),
        ("20C", ":RELA//REFSEME004"),
        ("16S", "LINK"),
        ("16S", "GENL"),
        ("16R", "USECU"),
        ("35B", "ISIN ES0105448007"),
        ("16R", "ACCTINFO"),
        ("97A", ":SAFE//ACC-01"),
        ("16S", "ACCTINFO"),
        ("16S", "USECU"),
        ("16R", "CAINST"),
        ("13A", ":CAON//001"),
        ("22F", ":CAOP//CASH"),
        ("36B", ":QINS//UNIT/12500,"),
        ("16S", "CAINST"),
    ]
    assert all("source" in f for f in doc["fields"])


# 2. not ready
def test_not_ready_is_not_serializable():
    doc = mt565_project(
        _instruction(instruction_status="INDETERMINATE"),
        _good_facts(), _envelope(), now="N",
    )
    assert doc["projection_status"] == PROJ_NOT_SERIALIZABLE
    assert "INSTRUCTION_NOT_READY" in doc["reasons"]
    assert doc["fields"] == []


# 3. facts binding mismatch -> fail closed
def test_facts_mismatch_fails_closed():
    with pytest.raises(ValueError, match="INSTRUCTION_FACTS_MISMATCH"):
        mt565_project(
            _instruction(source_message_input_sha256="0" * 64),
            _good_facts(), _envelope(), now="N",
        )


# 4. facts not MT564
def test_non_mt564_facts_unsupported():
    facts = _good_facts()
    facts["message_identifier"] = "MT566"
    for f in facts["facts"]:
        f["message_identifier"] = "MT566"
    doc = mt565_project(
        _instruction(), facts, _envelope(), now="N"
    )
    assert "UNSUPPORTED_MESSAGE_TYPE" in doc["reasons"]


# 5. unsupported option kind
def test_unsupported_option_kind():
    doc = mt565_project(
        _instruction(option_kind="UNSUPPORTED", option_code_raw="MPUT"),
        _good_facts(), _envelope(), now="N",
    )
    assert "UNSUPPORTED_OPTION_KIND" in doc["reasons"]


# 6. missing / conflicting sourced facts
def test_missing_corp_seme_caev():
    doc = mt565_project(_instruction(), _facts(), _envelope(), now="N")
    assert doc["projection_status"] == PROJ_NOT_SERIALIZABLE
    assert "MISSING_CORP_REFERENCE" in doc["reasons"]
    assert "MISSING_SOURCE_SEME" in doc["reasons"]
    assert "MISSING_CAEV" in doc["reasons"]


def test_conflicting_corp():
    facts = _good_facts()
    facts["facts"].append(_fact("GENL", "20C", "CORP", "OTHER-REF"))
    doc = mt565_project(_instruction(), facts, _envelope(), now="N")
    assert "CONFLICTING_CORP_REFERENCE" in doc["reasons"]


def test_conflicting_seme():
    facts = _good_facts()
    facts["facts"].append(_fact("GENL", "20C", "SEME", "SEME-2"))
    doc = mt565_project(_instruction(), facts, _envelope(), now="N")
    assert "CONFLICTING_SOURCE_SEME" in doc["reasons"]


# missing instruction fields
def test_missing_instruction_field():
    doc = mt565_project(
        _instruction(isin=None), _good_facts(), _envelope(), now="N"
    )
    assert "MISSING_INSTRUCTION_FIELD:isin" in doc["reasons"]


def test_invalid_requested_quantity():
    doc = mt565_project(
        _instruction(requested_quantity="abc"),
        _good_facts(), _envelope(), now="N",
    )
    assert "INVALID_REQUESTED_QUANTITY" in doc["reasons"]
    doc = mt565_project(
        _instruction(requested_quantity="0"),
        _good_facts(), _envelope(), now="N",
    )
    assert "INVALID_REQUESTED_QUANTITY" in doc["reasons"]


# 7. envelope validation fail-closed
@pytest.mark.parametrize(
    "patch",
    [
        {"sender_bic": "BAD"},
        {"receiver_bic": "toolongtoolong"},
        {"session_number": "000"},
        {"sequence_number": "00005"},
        {"priority": "X"},
        {"sender_bic": None},
    ],
)
def test_invalid_envelope_fields_raise(patch):
    with pytest.raises(ValueError, match="INVALID_ENVELOPE_FIELD"):
        mt565_project(
            _instruction(), _good_facts(), _envelope(**patch), now="N"
        )


def test_wrong_schemas_fail_closed():
    with pytest.raises(ValueError, match="INVALID_INSTRUCTION"):
        mt565_project({"schema": "X"}, _good_facts(), _envelope())
    with pytest.raises(ValueError, match="INVALID_SWIFT_FACTS"):
        mt565_project(_instruction(), {"schema": "X"}, _envelope())
    with pytest.raises(ValueError, match="INVALID_ENVELOPE"):
        mt565_project(_instruction(), _good_facts(), {"schema": "X"})


# 8. quantity -> SWIFT comma
def test_quantity_decimal_comma():
    doc = mt565_project(
        _instruction(requested_quantity="12500.5"),
        _good_facts(), _envelope(), now="N",
    )
    assert ":QINS//UNIT/12500,5" in _values(doc, "36B")


def test_bic8_padded_to_lt12():
    doc = mt565_project(
        _instruction(), _good_facts(),
        _envelope(sender_bic="BANKESMM", receiver_bic="BANKDEFF"),
        now="N",
    )
    assert doc["envelope"]["sender_lt"] == "BANKESMMXXXX"
    assert doc["envelope"]["receiver_lt"] == "BANKDEFFXXXX"


# 9. determinism + no mutation
def test_deterministic_and_no_mutation():
    ins, facts, env = _instruction(), _good_facts(), _envelope()
    ins0, facts0, env0 = (
        copy.deepcopy(ins), copy.deepcopy(facts), copy.deepcopy(env)
    )
    a = mt565_project(ins, facts, env, now="N")
    b = mt565_project(
        _instruction(), _good_facts(), _envelope(), now="N"
    )
    assert a == b
    assert ins == ins0 and facts == facts0 and env == env0


requires_jar = pytest.mark.skipif(
    not default_adapter_jar().is_file(),
    reason="adapter jar no construido",
)


# 10. e2e: project -> write -> FIN real
@requires_jar
def test_e2e_project_write_roundtrip(tmp_path):
    doc = mt565_project(
        _instruction(), _good_facts(), _envelope(), now="N"
    )
    assert doc["projection_status"] == PROJ_SERIALIZABLE
    fin_doc, code = write_mt565(doc)
    assert code == 0
    assert fin_doc["schema_version"] == FIN_SCHEMA
    assert fin_doc["write_status"] == "OK"
    fin = fin_doc["fin"]
    assert "{1:F01BANKESMMAXXX0000000005}" in fin
    assert "I565BANKDEFFXXXXN" in fin
    for expected in (
        ":20C::SEME//INS-0001",
        ":20C::CORP//CORP-REF-42",
        ":23G:NEWM",
        ":22F::CAEV//VOLU",
        ":13A::LINK//564",
        ":20C::RELA//REFSEME004",
        ":35B:ISIN ES0105448007",
        ":97A::SAFE//ACC-01",
        ":13A::CAON//001",
        ":22F::CAOP//CASH",
        ":36B::QINS//UNIT/12500,",
    ):
        assert expected in fin, expected

    # determinismo del FIN
    fin_doc2, code2 = write_mt565(
        mt565_project(_instruction(), _good_facts(), _envelope(), now="N")
    )
    assert code2 == 0
    assert fin_doc2["fin"] == fin
    assert fin_doc2["fin_sha256"] == fin_doc["fin_sha256"]


@requires_jar
def test_e2e_not_serializable_rejected_by_writer():
    doc = mt565_project(
        _instruction(instruction_status="INDETERMINATE"),
        _good_facts(), _envelope(), now="N",
    )
    fin_doc, code = write_mt565(doc)
    assert code == 2
    assert fin_doc["write_status"] == "INPUT_ERROR"


@requires_jar
def test_cli_project_and_write(tmp_path, monkeypatch, capsys):
    from ca_es.cli import main

    ins_p = tmp_path / "ins.json"
    facts_p = tmp_path / "facts.json"
    env_p = tmp_path / "env.json"
    ins_p.write_text(json.dumps(_instruction()))
    facts_p.write_text(json.dumps(_good_facts()))
    env_p.write_text(json.dumps(_envelope()))

    code = main([
        "mt565-project",
        "--instruction", str(ins_p),
        "--facts", str(facts_p),
        "--envelope", str(env_p),
        "--now", "N",
    ])
    assert code == 0
    proj = json.loads(capsys.readouterr().out)
    assert proj["projection_status"] == "SERIALIZABLE"

    proj_p = tmp_path / "proj.json"
    proj_p.write_text(json.dumps(proj))
    code = main(["mt565-write", "--projection", str(proj_p)])
    assert code == 0
    fin_doc = json.loads(capsys.readouterr().out)
    assert fin_doc["write_status"] == "OK"
    assert ":22F::CAOP//CASH" in fin_doc["fin"]
