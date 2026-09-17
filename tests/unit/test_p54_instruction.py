"""P5.4 — CA_ES_ELECTION_INSTRUCTION_V1.

Instruction intent interno sobre celda ELIGIBLE demostrada; requested
== eligible unicamente (parcial no modelado); binding fail-closed
eligibility<->opportunity; instruction_id nunca sintetizado.
"""

import copy
import json

import pytest

from ca_es.canonical import canonical_json
from ca_es.election_eligibility import INDETERMINATE, UNSUPPORTED
from ca_es.election_instruction import (
    INSTRUCTION_SCHEMA,
    READY,
    build_instruction,
)

NOW = "2026-09-17T00:00:00Z"
SHA = "aa" * 32
ISHA = "bb" * 32
ISIN = "ES0105448007"
OPTION_KEY = "E1|option:001"


def _cell(account="A001", option_key=OPTION_KEY, status="ELIGIBLE",
          eligible="12500", kind="CASH", isin=ISIN):
    return {
        "eligibility_key": f"E1|{account}|{option_key}",
        "account_id": account,
        "isin": isin,
        "option_key": option_key,
        "option_identifier": "001",
        "option_code_raw": "CASH",
        "option_kind": kind,
        "rule_id": "R1",
        "position_basis": "POSITION_AT_DATE_FIELD",
        "basis_field": "date.record_date",
        "basis_date": "2026-07-03",
        "position_quantity": "12500",
        "position_as_of": "2026-07-03",
        "eligible_quantity": eligible,
        "eligibility_status": status,
        "reasons": [] if status == "ELIGIBLE" else ["ZERO_QUANTITY"],
        "evidence": {
            "rule_id": "R1",
            "assertion_ids": ["ar0"],
            "option_key": option_key,
            "option_provenance": [
                {"source_tag": "22F", "source_qualifier": "CAON",
                 "sequence": "USEQ/CAOPTN", "occurrence": 0,
                 "evidence_locator": "block4.tag[0]", "raw": "001"}
            ],
            "position_index": 0,
        },
    }


def _eligibility(*cells, canon_sha=SHA, input_sha=ISHA, eid="E1"):
    return {
        "schema": "CA_ES_ELECTION_ELIGIBILITY_V1",
        "generated_at": NOW,
        "source_canon_logical_sha256": canon_sha,
        "source_positions_logical_sha256": "cc" * 32,
        "source_message_input_sha256": input_sha,
        "canonical_event_id": eid,
        "eligibilities": list(cells),
    }


def _opportunity(option_keys=(OPTION_KEY,), canon_sha=SHA,
                 input_sha=ISHA, eid="E1"):
    return {
        "schema": "CA_ES_ELECTION_OPPORTUNITY_V1",
        "generated_at": NOW,
        "source_canon_logical_sha256": canon_sha,
        "source_message_identifier": "MT564",
        "input_sha256": input_sha,
        "canonical_event_id": eid,
        "options": [
            {
                "option_key": key,
                "option_identifier": key.rsplit(":", 1)[-1],
                "option_code_raw": "CASH",
                "option_kind": "CASH",
                "default_status": "DEFAULT",
                "source_response_deadline": "2026-07-03",
                "terms": [],
                "provenance": [],
            }
            for key in option_keys
        ],
        "source_response_deadline": "2026-07-03",
        "operational_deadlines": [],
        "deadline_binding_status": "NOT_APPLICABLE",
        "reasons": [],
        "projection_status": "PROJECTED",
    }


def _request(**over):
    request = {
        "instruction_id": "INS-0001",
        "account_id": "A001",
        "option_key": OPTION_KEY,
        "requested_quantity": "12500",
        "actor": "ops.user",
        "instructed_at": "2026-07-01T09:30:00Z",
    }
    request.update(over)
    return request


def _build(cells=None, opportunity=None, request=None, now=NOW):
    return build_instruction(
        _eligibility(*(cells if cells is not None else [_cell()])),
        opportunity if opportunity is not None else _opportunity(),
        request if request is not None else _request(),
        now=now,
    )


def test_valid_full_position_ready():
    doc = _build()
    assert doc["schema"] == INSTRUCTION_SCHEMA
    assert doc["instruction_status"] == READY
    assert doc["instruction_id"] == "INS-0001"
    assert doc["canonical_event_id"] == "E1"
    assert doc["account_id"] == "A001"
    assert doc["isin"] == ISIN
    assert doc["option_key"] == OPTION_KEY
    assert doc["option_identifier"] == "001"
    assert doc["requested_quantity"] == "12500"
    assert doc["eligible_quantity"] == "12500"
    assert doc["actor"] == "ops.user"
    assert doc["instructed_at"] == "2026-07-01T09:30:00Z"
    assert doc["eligibility_key"] == "E1|A001|E1|option:001"
    assert doc["eligibility_rule_id"] == "R1"
    assert doc["source_canon_logical_sha256"] == SHA
    assert doc["source_positions_logical_sha256"] == "cc" * 32
    assert doc["source_message_input_sha256"] == ISHA
    assert doc["evidence"]["assertion_ids"] == ["ar0"]
    assert doc["evidence"]["option_provenance"]
    assert doc["evidence"]["position_index"] == 0


def test_unknown_account_cell_not_found():
    doc = _build(request=_request(account_id="ZZZ"))
    assert doc["instruction_status"] == INDETERMINATE
    assert doc["reasons"] == ["ELIGIBILITY_CELL_NOT_FOUND"]


def test_unknown_option_cell_not_found():
    doc = _build(request=_request(option_key="E1|option:999"))
    assert doc["instruction_status"] == INDETERMINATE
    assert doc["reasons"] == ["ELIGIBILITY_CELL_NOT_FOUND"]


def test_non_eligible_cell():
    doc = _build(cells=[_cell(status="NOT_ELIGIBLE", eligible="0")])
    assert doc["instruction_status"] == INDETERMINATE
    assert doc["reasons"] == ["CELL_NOT_ELIGIBLE"]


def test_zero_negative_invalid_requested():
    for raw, reason in (
        ("0", "NON_POSITIVE_REQUESTED_QUANTITY"),
        ("-5", "NON_POSITIVE_REQUESTED_QUANTITY"),
        ("abc", "INVALID_REQUESTED_QUANTITY"),
    ):
        doc = _build(request=_request(requested_quantity=raw))
        assert doc["instruction_status"] == INDETERMINATE
        assert doc["reasons"] == [reason]


def test_request_exceeds_eligible():
    doc = _build(request=_request(requested_quantity="12501"))
    assert doc["instruction_status"] == INDETERMINATE
    assert doc["reasons"] == ["REQUEST_EXCEEDS_ELIGIBLE_QUANTITY"]


def test_partial_unsupported():
    doc = _build(request=_request(requested_quantity="12499"))
    assert doc["instruction_status"] == UNSUPPORTED
    assert doc["reasons"] == ["PARTIAL_ELECTION_TERMS_NOT_MODELED"]


def test_artifact_mismatch_fail_closed():
    for opportunity in (
        _opportunity(canon_sha="ff" * 32),
        _opportunity(input_sha="ee" * 32),
        _opportunity(eid="E2"),
    ):
        with pytest.raises(
            ValueError, match="ELIGIBILITY_OPPORTUNITY_MISMATCH"
        ):
            _build(opportunity=opportunity)


def test_ambiguous_cell_resolution():
    doc = _build(cells=[_cell(), _cell()])
    assert doc["instruction_status"] == INDETERMINATE
    assert doc["reasons"] == ["AMBIGUOUS_ELIGIBILITY_CELL"]


def test_unsupported_option_kind():
    doc = _build(cells=[_cell(kind="UNSUPPORTED")])
    assert doc["instruction_status"] == UNSUPPORTED
    assert doc["reasons"] == ["UNSUPPORTED_OPTION_KIND"]


def test_option_not_in_opportunity():
    doc = _build(opportunity=_opportunity(option_keys=()))
    assert doc["instruction_status"] == INDETERMINATE
    assert doc["reasons"] == ["OPTION_NOT_IN_OPPORTUNITY"]


def test_missing_request_fields_fail_closed():
    for field in (
        "instruction_id", "account_id", "option_key",
        "requested_quantity", "actor", "instructed_at",
    ):
        request = _request()
        del request[field]
        with pytest.raises(
            ValueError, match="INVALID_INSTRUCTION_REQUEST"
        ):
            _build(request=request)


def test_instruction_id_never_synthesized():
    doc = _build()
    assert doc["instruction_id"] == "INS-0001"


def test_inputs_not_mutated():
    eligibility = _eligibility(_cell())
    opportunity = _opportunity()
    request = _request()
    snapshot = copy.deepcopy((eligibility, opportunity, request))
    build_instruction(eligibility, opportunity, request, now=NOW)
    assert (eligibility, opportunity, request) == snapshot


def test_deterministic_fixed_now():
    a = _build()
    b = _build()
    assert canonical_json(a) == canonical_json(b)
    assert a["generated_at"] == NOW


def test_cli_smoke(tmp_path):
    from ca_es.cli import main

    for name, doc in (
        ("eligibility", _eligibility(_cell())),
        ("opportunity", _opportunity()),
        ("request", _request()),
    ):
        (tmp_path / f"{name}.json").write_text(
            json.dumps(doc), encoding="utf-8")
    assert main([
        "election-instruction",
        "--eligibility", str(tmp_path / "eligibility.json"),
        "--opportunity", str(tmp_path / "opportunity.json"),
        "--request", str(tmp_path / "request.json"),
        "--now", NOW,
    ]) == 0
