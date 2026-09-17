"""P5.3 — CA_ES_ELECTION_ELIGIBILITY_V1.

Eligibility demostrable por posicion y opcion bajo regla explicita;
ausencia de evidencia nunca se convierte en semantica; binding
opportunity/canon fail-closed; nunca se suman posiciones duplicadas.
"""

import copy
import json

import pytest

from ca_es.canonical import canonical_json, sha256_hex
from ca_es.election_eligibility import (
    ELIGIBILITY_SCHEMA,
    ELIGIBLE,
    INDETERMINATE,
    NOT_ELIGIBLE,
    UNSUPPORTED,
    compute_election_eligibility,
)

NOW = "2026-09-17T00:00:00Z"
SHA = "aa" * 32
ISIN = "ES0105448007"
RECORD = "2026-07-03"


def _fact(path, value, rev="r1", aid="a1"):
    return {
        "field_path": path,
        "value": value,
        "revision_id": rev,
        "assertion_id": aid,
    }


def _event(eid="E1", isin=ISIN, record=RECORD, extra_isins=(),
           record_values=None, event_type="CASH_DIVIDEND"):
    facts = []
    if isin:
        facts.append(_fact("instrument.isin", isin))
    for extra in extra_isins:
        facts.append(_fact("instrument.isin", extra, aid="a9"))
    if record_values:
        for i, value in enumerate(record_values):
            facts.append(
                _fact("date.record_date", value, aid=f"ar{i}")
            )
    elif record is not None:
        facts.append(_fact("date.record_date", record, aid="ar0"))
    return {
        "canonical_event_id": eid,
        "event_type": event_type,
        "affected_instrument": {"isin": isin},
        "facts": facts,
        "conflicts": [],
    }


def _canon(*events, sha=SHA):
    return {
        "canon_version": "CA_ES_OPERATIONAL_CANON_V1",
        "logical_sha256": sha,
        "events": list(events),
    }


def _option(ident="001", code="CASH", kind="CASH", eid="E1"):
    return {
        "option_key": f"{eid}|option:{ident}",
        "option_identifier": ident,
        "option_code_raw": code,
        "option_kind": kind,
        "default_status": "DEFAULT",
        "source_response_deadline": RECORD,
        "terms": [],
        "provenance": [
            {
                "source_tag": "22F",
                "source_qualifier": "CAON",
                "sequence": "USEQ/CAOPTN",
                "occurrence": 0,
                "evidence_locator": "block4.tag[0]",
                "raw": ident,
            }
        ],
    }


def _opportunity(options, status="PROJECTED", canon_sha=SHA, eid="E1"):
    return {
        "schema": "CA_ES_ELECTION_OPPORTUNITY_V1",
        "generated_at": NOW,
        "source_canon_logical_sha256": canon_sha,
        "source_message_identifier": "MT564",
        "input_sha256": "bb" * 32,
        "canonical_event_id": eid,
        "options": options,
        "source_response_deadline": RECORD,
        "operational_deadlines": [],
        "deadline_binding_status": "NOT_APPLICABLE",
        "reasons": [],
        "projection_status": status,
    }


def _pos(account="A001", isin=ISIN, qty="12500", as_of=RECORD):
    position = {"account_id": account, "isin": isin, "quantity": qty}
    if as_of is not None:
        position["as_of"] = as_of
    return position


def _positions(*positions, as_of=None):
    doc = {"schema": "CA_ES_POSITIONS_V1", "positions": list(positions)}
    if as_of is not None:
        doc["as_of"] = as_of
    return doc


def _rule(rule_id="R1", basis_field="date.record_date",
          position_basis="POSITION_AT_DATE_FIELD",
          quantity_rule="FULL_POSITION", **filters):
    rule = {
        "rule_id": rule_id,
        "basis_field": basis_field,
        "position_basis": position_basis,
        "quantity_rule": quantity_rule,
    }
    rule.update({k: v for k, v in filters.items() if v is not None})
    return rule


def _rules(*rules):
    return {
        "schema": "CA_ES_ELECTION_ELIGIBILITY_RULES_V1",
        "rules": list(rules),
    }


def _compute(positions, options=None, rules=None, event=None,
             opportunity=None, canon=None, now=NOW):
    return compute_election_eligibility(
        opportunity or _opportunity(
            options if options is not None else [_option()]),
        canon or _canon(event if event is not None else _event()),
        positions,
        rules if rules is not None else _rules(_rule()),
        now=now,
    )


def test_one_position_two_options_eligible():
    doc = _compute(
        _positions(_pos()),
        options=[_option("001", "CASH", "CASH"),
                 _option("002", "SECU", "SECURITIES")],
    )
    assert doc["schema"] == ELIGIBILITY_SCHEMA
    assert doc["canonical_event_id"] == "E1"
    assert doc["source_canon_logical_sha256"] == SHA
    assert len(doc["eligibilities"]) == 2
    for cell in doc["eligibilities"]:
        assert cell["eligibility_status"] == ELIGIBLE
        assert cell["eligible_quantity"] == "12500"
        assert cell["basis_date"] == RECORD
        assert cell["rule_id"] == "R1"
        assert cell["position_basis"] == "POSITION_AT_DATE_FIELD"
    keys = [c["eligibility_key"] for c in doc["eligibilities"]]
    assert keys == ["E1|A001|E1|option:001", "E1|A001|E1|option:002"]


def test_zero_quantity_not_eligible():
    doc = _compute(_positions(_pos(qty="0")))
    cell = doc["eligibilities"][0]
    assert cell["eligibility_status"] == NOT_ELIGIBLE
    assert cell["reasons"] == ["ZERO_QUANTITY"]
    assert cell["eligible_quantity"] is None


def test_snapshot_before_basis_indeterminate():
    doc = _compute(_positions(_pos(as_of="2026-07-02")))
    cell = doc["eligibilities"][0]
    assert cell["eligibility_status"] == INDETERMINATE
    assert cell["reasons"] == ["POSITION_SNAPSHOT_BEFORE_BASIS"]


def test_snapshot_after_basis_indeterminate():
    doc = _compute(_positions(_pos(as_of="2026-07-04")))
    cell = doc["eligibilities"][0]
    assert cell["eligibility_status"] == INDETERMINATE
    assert cell["reasons"] == ["POSITION_SNAPSHOT_AFTER_BASIS"]


def test_doc_level_as_of_fallback():
    doc = _compute(
        _positions(_pos(as_of=None), as_of=RECORD))
    assert doc["eligibilities"][0]["eligibility_status"] == ELIGIBLE
    assert doc["eligibilities"][0]["position_as_of"] == RECORD


def test_missing_conflicting_invalid_basis_date():
    missing = _compute(
        _positions(_pos()), event=_event(record=None))
    assert missing["eligibilities"][0]["reasons"] == [
        "MISSING_BASIS_DATE"]

    conflicting = _compute(
        _positions(_pos()),
        event=_event(record=None,
                     record_values=[RECORD, "2026-07-04"]))
    cell = conflicting["eligibilities"][0]
    assert cell["reasons"] == ["CONFLICTING_BASIS_DATE"]
    assert cell["evidence"]["assertion_ids"] == ["ar0", "ar1"]

    invalid = _compute(
        _positions(_pos()), event=_event(record="no-es-fecha"))
    cell = invalid["eligibilities"][0]
    assert cell["reasons"] == ["INVALID_BASIS_DATE"]
    assert cell["basis_date"] == "no-es-fecha"


def test_invalid_and_negative_quantity():
    invalid = _compute(_positions(_pos(qty="abc")))
    cell = invalid["eligibilities"][0]
    assert cell["eligibility_status"] == INDETERMINATE
    assert cell["reasons"] == ["INVALID_QUANTITY"]
    assert cell["position_quantity"] is None

    negative = _compute(_positions(_pos(qty="-5")))
    cell = negative["eligibilities"][0]
    assert cell["eligibility_status"] == INDETERMINATE
    assert cell["reasons"] == ["NEGATIVE_QUANTITY_UNSUPPORTED"]


def test_opportunity_canon_mismatch_fail_closed():
    with pytest.raises(ValueError, match="OPPORTUNITY_CANON_MISMATCH"):
        _compute(
            _positions(_pos()),
            opportunity=_opportunity([_option()], canon_sha="ff" * 32),
        )


def test_no_applicable_rule():
    doc = _compute(_positions(_pos()), rules=_rules())
    cell = doc["eligibilities"][0]
    assert cell["eligibility_status"] == INDETERMINATE
    assert cell["reasons"] == ["NO_APPLICABLE_RULE"]

    filtered = _compute(
        _positions(_pos()),
        rules=_rules(_rule(event_types=["TENDER_OFFER"])))
    assert filtered["eligibilities"][0]["reasons"] == [
        "NO_APPLICABLE_RULE"]


def test_two_applicable_rules_ambiguous():
    doc = _compute(
        _positions(_pos()),
        rules=_rules(_rule(rule_id="R2"), _rule(rule_id="R1")))
    cell = doc["eligibilities"][0]
    assert cell["eligibility_status"] == INDETERMINATE
    assert cell["reasons"] == ["AMBIGUOUS_ELIGIBILITY_RULE"]
    assert cell["evidence"]["candidate_rule_ids"] == ["R1", "R2"]


def test_unsupported_rule_semantics():
    doc = _compute(
        _positions(_pos()),
        rules=_rules(_rule(position_basis="POSITION_AT_PAYMENT_DATE")))
    cell = doc["eligibilities"][0]
    assert cell["eligibility_status"] == UNSUPPORTED
    assert cell["reasons"] == ["UNSUPPORTED_ELIGIBILITY_RULE"]
    assert cell["rule_id"] == "R1"


def test_unsupported_option_kind():
    doc = _compute(
        _positions(_pos()),
        options=[_option(code="MPUT", kind="UNSUPPORTED")])
    cell = doc["eligibilities"][0]
    assert cell["eligibility_status"] == UNSUPPORTED
    assert cell["option_code_raw"] == "MPUT"


def test_duplicate_position_key_never_sums():
    doc = _compute(
        _positions(_pos(), _pos()))
    assert len(doc["eligibilities"]) == 2
    for cell in doc["eligibilities"]:
        assert cell["eligibility_status"] == INDETERMINATE
        assert cell["reasons"] == ["DUPLICATE_POSITION_KEY"]
        assert cell["position_quantity"] == "12500"
        assert cell["eligible_quantity"] is None


def test_missing_and_ambiguous_instrument_identity():
    missing = _compute(
        _positions(_pos()), event=_event(isin=None))
    assert missing["eligibilities"][0]["reasons"] == [
        "MISSING_INSTRUMENT_IDENTITY"]

    ambiguous = _compute(
        _positions(_pos()),
        event=_event(extra_isins=("ES1111111111",)))
    assert ambiguous["eligibilities"][0]["reasons"] == [
        "AMBIGUOUS_INSTRUMENT_IDENTITY"]

    mismatch = _compute(
        _positions(_pos(isin="ES9999999999")))
    assert mismatch["eligibilities"][0]["reasons"] == [
        "NO_POSITION_FOR_INSTRUMENT"]


def test_evidence_links_rule_assertion_option_position():
    doc = _compute(_positions(_pos()))
    cell = doc["eligibilities"][0]
    evidence = cell["evidence"]
    assert evidence["rule_id"] == "R1"
    assert evidence["assertion_ids"] == ["ar0"]
    assert evidence["option_key"] == "E1|option:001"
    assert evidence["option_provenance"]
    assert evidence["position_index"] == 0
    assert doc["source_positions_logical_sha256"] == sha256_hex(
        _positions(_pos()))
    assert doc["source_message_input_sha256"] == "bb" * 32


def test_inputs_not_mutated():
    opportunity = _opportunity([_option()])
    canon = _canon(_event())
    positions = _positions(_pos())
    rules = _rules(_rule())
    snapshot = [copy.deepcopy(d)
                for d in (opportunity, canon, positions, rules)]
    compute_election_eligibility(
        opportunity, canon, positions, rules, now=NOW)
    assert [opportunity, canon, positions, rules] == snapshot


def test_deterministic_fixed_now():
    a = _compute(_positions(_pos()),
                 options=[_option("001"), _option("002")])
    b = _compute(_positions(_pos()),
                 options=[_option("001"), _option("002")])
    assert canonical_json(a) == canonical_json(b)
    assert a["generated_at"] == NOW


def test_opportunity_not_projected_never_eligible():
    doc = _compute(
        _positions(_pos()),
        opportunity=_opportunity([_option()], status="INDETERMINATE"))
    cell = doc["eligibilities"][0]
    assert cell["eligibility_status"] == INDETERMINATE
    assert cell["reasons"] == ["OPPORTUNITY_NOT_PROJECTED"]


def test_no_options_no_cells():
    doc = _compute(_positions(_pos()), options=[])
    assert doc["eligibilities"] == []


def test_cli_smoke(tmp_path):
    from ca_es.cli import main

    for name, doc in (
        ("opportunity", _opportunity([_option()])),
        ("canon", _canon(_event())),
        ("positions", _positions(_pos())),
        ("rules", _rules(_rule())),
    ):
        (tmp_path / f"{name}.json").write_text(
            json.dumps(doc), encoding="utf-8")
    assert main([
        "election-eligibility",
        "--opportunity", str(tmp_path / "opportunity.json"),
        "--canon", str(tmp_path / "canon.json"),
        "--positions", str(tmp_path / "positions.json"),
        "--rules", str(tmp_path / "rules.json"),
        "--now", NOW,
    ]) == 0
