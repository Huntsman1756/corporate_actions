"""P5.6 — MT567 status/advice binding (docs/p5/p56-scope.md)."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ca_es.instruction_status import (
    AMBIGUOUS,
    BOUND,
    INSUFFICIENT_IDENTITY,
    NO_MATCH,
    STATUS_DOC_SCHEMA,
    bind_instruction_status,
)
from ca_es.swift_mt import default_adapter_jar, parse_mt

REPO = Path(__file__).resolve().parents[2]
FIXTURE_FIN = (
    REPO / "adapters" / "iso-adapter-jvm" / "src" / "test"
    / "resources" / "mt567-inst.fin"
)


def _fact(seq, tag, qual, value, occ=0, idx=0):
    return {
        "message_identifier": "MT567",
        "field_path": (
            f"MT567.{seq.replace('/', '.')}.{tag}:{qual}"
            if qual else f"MT567.{seq.replace('/', '.')}.{tag}"
        ) + (f"[{occ}]" if occ else "") + ".value",
        "value": value,
        "source_tag": tag,
        "source_qualifier": qual,
        "sequence": seq,
        "occurrence": occ,
        "evidence_locator": f"block4.tag[{idx}]",
        "input_sha256": "5" * 64,
    }


def _facts_doc(*facts, mt="MT567"):
    return {
        "schema_version": "CA_ES_SWIFT_MT_FACTS_V1",
        "generated_at": "2026-09-18T00:00:00Z",
        "message_identifier": mt,
        "input_sha256": "5" * 64,
        "parse_status": "OK",
        "facts": list(facts),
    }


def _inst_facts(prev="INS-0001", code="PACK", qual="IPRC",
                function="INST", with_reas=True):
    facts = [
        _fact("GENL", "20C", "SEME", "STAT-0001", idx=1),
        _fact("GENL", "23G", None, function, idx=2),
        _fact("GENL", "20C", "CORP", "CORP-REF-42", idx=3),
        _fact("GENL/LINK", "13A", "LINK", "565", idx=5),
    ]
    idx = 6
    if prev is not None:
        facts.append(_fact("GENL/LINK", "20C", "PREV", prev, idx=idx))
        idx += 1
    if code is not None:
        facts.append(
            _fact("GENL/STAT", "25D", qual, code, idx=idx))
        idx += 1
    if with_reas:
        facts += [
            _fact("GENL/STAT/REAS", "24B", "NARR", "CONF", idx=idx),
            _fact("GENL/STAT/REAS", "70D", "REAS",
                  "instruction accepted", idx=idx + 1),
        ]
    return _facts_doc(*facts)


def _instruction(**over):
    doc = {
        "schema": "CA_ES_ELECTION_INSTRUCTION_V1",
        "instruction_id": "INS-0001",
        "canonical_event_id": "evt-001",
        "instruction_status": "READY",
        "source_canon_logical_sha256": "c" * 64,
        "source_positions_logical_sha256": "p" * 64,
        "source_message_input_sha256": "f" * 64,
    }
    doc.update(over)
    return doc


# 1. valid MT567 binds
def test_valid_mt567_binds():
    doc = bind_instruction_status(
        _inst_facts(), _instruction(), now="N"
    )
    assert doc["schema"] == STATUS_DOC_SCHEMA
    assert doc["instruction_binding_status"] == BOUND
    assert doc["instruction_id"] == "INS-0001"
    assert doc["canonical_event_id"] == "evt-001"
    assert doc["source_canon_logical_sha256"] == "c" * 64
    assert doc["source_message_input_sha256"] == "f" * 64
    assert doc["source_positions_logical_sha256"] == "p" * 64
    assert doc["message_function"] == "INST"
    assert doc["reasons"] == []
    s = doc["statuses"][0]
    assert s["status_qualifier"] == "IPRC"
    assert s["status_code_raw"] == "PACK"
    assert s["normalized_status"] == "ACCEPTED"
    assert s["reason_code_raw"] == "CONF"
    assert s["reason_qualifier"] == "NARR"
    assert s["reason_narrative"] == "instruction accepted"
    assert s["provenance"]


# 2. unknown reference
def test_no_match():
    doc = bind_instruction_status(
        _inst_facts(prev="OTHER-REF"), _instruction(), now="N"
    )
    assert doc["instruction_binding_status"] == NO_MATCH
    assert doc["canonical_event_id"] is None


# 3. multi-PREV containing target -> AMBIGUOUS
def test_ambiguous_multi_prev():
    facts = _inst_facts()
    facts["facts"].insert(
        6, _fact("GENL/LINK", "20C", "PREV", "INS-OTHER",
                 occ=1, idx=7)
    )
    doc = bind_instruction_status(facts, _instruction(), now="N")
    assert doc["instruction_binding_status"] == AMBIGUOUS


# 4. no PREV -> INSUFFICIENT_IDENTITY
def test_insufficient_identity():
    doc = bind_instruction_status(
        _inst_facts(prev=None), _instruction(), now="N"
    )
    assert doc["instruction_binding_status"] == INSUFFICIENT_IDENTITY
    assert doc["canonical_event_id"] is None


# 5. known status whitelist
@pytest.mark.parametrize(
    "code,normalized",
    [
        ("PACK", "ACCEPTED"),
        ("REJT", "REJECTED"),
        ("PEND", "PENDING"),
        ("DFLA", "DEFAULT_ACTION_APPLIED"),
    ],
)
def test_status_whitelist(code, normalized):
    doc = bind_instruction_status(
        _inst_facts(code=code), _instruction(), now="N"
    )
    assert doc["statuses"][0]["normalized_status"] == normalized


# 6. unknown status / other qualifier preserved raw
def test_unknown_status_preserved():
    doc = bind_instruction_status(
        _inst_facts(code="XTRA"), _instruction(), now="N"
    )
    s = doc["statuses"][0]
    assert s["normalized_status"] == "UNSUPPORTED"
    assert s["status_code_raw"] == "XTRA"

    doc = bind_instruction_status(
        _inst_facts(qual="CPRC", code="CAND"), _instruction(), now="N"
    )
    s = doc["statuses"][0]
    assert s["normalized_status"] == "UNSUPPORTED"
    assert s["status_qualifier"] == "CPRC"


# 7. function != INST
def test_function_not_inst():
    doc = bind_instruction_status(
        _inst_facts(function="CAST"), _instruction(), now="N"
    )
    assert "MESSAGE_FUNCTION_NOT_INST" in doc["reasons"]


# 8. multi-STAT positional REAS grouping
def test_multi_stat_grouping():
    facts = [
        _fact("GENL", "23G", None, "INST", idx=0),
        _fact("GENL/LINK", "20C", "PREV", "INS-0001", idx=1),
        _fact("GENL/STAT", "25D", "IPRC", "REJT", occ=0, idx=2),
        _fact("GENL/STAT/REAS", "24B", "REJT", "BADD", idx=3),
        _fact("GENL/STAT", "25D", "IPRC", "PACK", occ=1, idx=6),
        _fact("GENL/STAT/REAS", "70D", "REAS", "ok", idx=7),
    ]
    doc = bind_instruction_status(
        _facts_doc(*facts), _instruction(), now="N"
    )
    assert len(doc["statuses"]) == 2
    s0, s1 = doc["statuses"]
    assert s0["status_code_raw"] == "REJT"
    assert s0["normalized_status"] == "REJECTED"
    assert s0["reason_code_raw"] == "BADD"
    assert s0["reason_narrative"] is None
    assert s1["status_code_raw"] == "PACK"
    assert s1["normalized_status"] == "ACCEPTED"
    assert s1["reason_code_raw"] is None
    assert s1["reason_narrative"] == "ok"


# 9. non-MT567 fail closed
def test_non_mt567_fails_closed():
    facts = _inst_facts()
    facts["message_identifier"] = "MT564"
    with pytest.raises(ValueError, match="EXPECTED_MT567"):
        bind_instruction_status(facts, _instruction(), now="N")


def test_wrong_schemas_fail_closed():
    with pytest.raises(ValueError, match="INVALID_SWIFT_FACTS"):
        bind_instruction_status({"schema": "X"}, _instruction())
    with pytest.raises(ValueError, match="INVALID_INSTRUCTION"):
        bind_instruction_status(_inst_facts(), {"schema": "X"})


# 10-11. determinism + no mutation
def test_deterministic_and_no_mutation():
    facts, ins = _inst_facts(), _instruction()
    f0, i0 = copy.deepcopy(facts), copy.deepcopy(ins)
    a = bind_instruction_status(facts, ins, now="N")
    b = bind_instruction_status(
        _inst_facts(), _instruction(), now="N"
    )
    assert a == b
    assert facts == f0 and ins == i0


requires_jar = pytest.mark.skipif(
    not default_adapter_jar().is_file(),
    reason="adapter jar no construido",
)


# 12. e2e real: FIN fixture -> facts -> bind
@requires_jar
def test_e2e_real_mt567_binds():
    fin = FIXTURE_FIN.read_text(encoding="utf-8")
    facts_doc, code = parse_mt(fin)
    assert code == 0
    assert facts_doc["message_identifier"] == "MT567"
    doc = bind_instruction_status(facts_doc, _instruction(), now="N")
    assert doc["instruction_binding_status"] == BOUND
    assert doc["statuses"][0]["normalized_status"] == "ACCEPTED"
    assert doc["statuses"][0]["reason_code_raw"] == "CONF"
    # provenance apunta a paths reales del mensaje
    paths = doc["statuses"][0]["provenance"]
    assert any("25D" in p and "IPRC" in p for p in paths)
    assert any("24B" in p for p in paths)


# 13. malformed MT567 -> PARSE_ERROR (sin leak en detail)
@requires_jar
def test_e2e_malformed_mt567():
    bad = "{4:\n:16R:GENL\n:20C::PREV//INS-0001\n"
    facts_doc, code = parse_mt(bad)
    assert code == 2
    assert facts_doc["parse_status"] == "PARSE_ERROR"
    detail = str(facts_doc.get("detail"))
    assert "INS-0001" not in detail


@requires_jar
def test_cli_instruction_status(tmp_path, capsys):
    from ca_es.cli import main

    ins_p = tmp_path / "ins.json"
    ins_p.write_text(json.dumps(_instruction()))
    code = main([
        "instruction-status",
        "--fin", str(FIXTURE_FIN),
        "--instruction", str(ins_p),
        "--now", "N",
    ])
    assert code == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["instruction_binding_status"] == "BOUND"
