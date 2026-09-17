"""P6.1 — CA_ES_POSITION_IMPACT_V1.

Unico impacto implementable (auditoria P6.0): CASH_RECEIVABLE para
CASH_DIVIDEND, compuesto del resultado P2.0 ya adjudicado. El modulo
no recalcula entitlements, no reinterpreta estados y nunca muta sus
inputs.
"""

import copy

import pytest

from ca_es.canonical import canonical_json, sha256_hex
from ca_es.position_impact import (
    CASH_RECEIVABLE,
    IMPACT_SCHEMA,
    INDETERMINATE,
    PROJECTED,
    UNSUPPORTED,
    compute_position_impact,
)

NOW = "2026-09-17T00:00:00Z"
SHA = "aa" * 32
ISIN = "ES0105448007"
RECORD = "2026-07-03"
EID = "E1"


def _canon(event_type="CASH_DIVIDEND", eid=EID):
    return {
        "canon_version": "CA_ES_OPERATIONAL_CANON_V1",
        "logical_sha256": SHA,
        "events": [
            {
                "canonical_event_id": eid,
                "event_type": event_type,
                "affected_instrument": {"isin": ISIN},
                "facts": [],
                "conflicts": [],
            }
        ],
    }


def _rules(*rules):
    return {"schema": "CA_ES_IMPACT_RULES_V1", "rules": list(rules)}


def _cash_rule():
    return {
        "rule_id": "CASH_DIVIDEND_GROSS_RECEIVABLE",
        "event_type": "CASH_DIVIDEND",
        "status": "SUPPORTED",
        "impact_type": "CASH_RECEIVABLE",
        "requires": ["CA_ES_ENTITLEMENT_V1"],
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


def _cell(account="A001", isin=ISIN, qty="12500", as_of=RECORD,
          status="ENTITLED", gross_cash=None, reasons=None):
    cell = {
        "account_id": account,
        "isin": isin,
        "position_quantity": qty,
        "position_as_of": as_of,
        "status": status,
        "reasons": list(reasons or []),
        "evidence": {
            "rule": "CASH_DIVIDEND_GROSS_PER_SHARE_X_POSITION_AT_"
                    "RECORD_DATE",
            "assertion_ids": ["a1"],
            "source_document_ids": ["d1"],
            "evidence_locators": ["loc/1"],
        },
    }
    if status == "ENTITLED":
        cell["entitled_quantity"] = qty
        cell["gross_per_share"] = {
            "normalized": "0.24", "currency": "EUR", "scale": 2,
            "assertion_id": "a1",
        }
        cell["gross_cash"] = gross_cash or {
            "normalized": "3000.00", "currency": "EUR", "scale": 2,
        }
        cell["basis"] = {
            "record_date": RECORD,
            "position_eligibility": "POSITION_AT_RECORD_DATE",
        }
    return cell


def _entitlements(*cells, eid=EID, event_type="CASH_DIVIDEND",
                  as_of=None):
    return {
        "entitlement_version": "CA_ES_ENTITLEMENT_V1",
        "canonical_event_id": eid,
        "event_type": event_type,
        "positions_as_of": as_of,
        "entitlements": list(cells),
        "summary": {},
    }


def test_entitled_position_projects_cash_receivable():
    positions = _positions(_pos())
    entitlements = _entitlements(_cell())
    doc = compute_position_impact(
        _canon(), EID, positions, _rules(_cash_rule()),
        entitlements_doc=entitlements, now=NOW)

    assert doc["schema"] == IMPACT_SCHEMA
    assert doc["canonical_event_id"] == EID
    assert doc["event_type"] == "CASH_DIVIDEND"
    assert doc["rule_id"] == "CASH_DIVIDEND_GROSS_RECEIVABLE"
    assert doc["source_canon_logical_sha256"] == SHA
    assert doc["source_positions_logical_sha256"] == sha256_hex(
        positions)
    assert doc["source_entitlement_sha256"] == sha256_hex(
        entitlements)
    assert doc["summary"] == {
        "positions": 1, "projected": 1, "indeterminate": 0,
        "unsupported": 0,
    }

    item = doc["impacts"][0]
    assert item["status"] == PROJECTED
    assert item["impact_type"] == CASH_RECEIVABLE
    assert item["account_id"] == "A001"
    assert item["source_isin"] == ISIN
    assert item["target_isin"] is None
    assert item["input_quantity"] == "12500"
    assert item["quantity_delta"] is None
    assert item["cash_amount"] == {
        "normalized": "3000.00", "currency": "EUR", "scale": 2}
    assert item["currency"] == "EUR"
    assert item["basis_date"] == RECORD
    assert item["rule_id"] == "CASH_DIVIDEND_GROSS_RECEIVABLE"
    assert item["source_canon_logical_sha256"] == SHA
    assert item["evidence"]["assertion_ids"] == ["a1"]
    assert item["evidence"]["source_document_ids"] == ["d1"]


def test_not_entitled_projects_zero_cash():
    positions = _positions(_pos(qty="0"))
    entitlements = _entitlements(
        _cell(qty="0", status="NOT_ENTITLED", reasons=["ZERO_QUANTITY"]))
    doc = compute_position_impact(
        _canon(), EID, positions, _rules(_cash_rule()),
        entitlements_doc=entitlements, now=NOW)

    item = doc["impacts"][0]
    assert item["status"] == PROJECTED
    assert item["cash_amount"] == {
        "normalized": "0", "currency": None, "scale": 0}
    assert item["currency"] is None
    assert "ZERO_QUANTITY" in item["reasons"]


def test_indeterminate_entitlement_propagates_verbatim():
    positions = _positions(_pos(as_of="2026-07-02"))
    entitlements = _entitlements(
        _cell(as_of="2026-07-02", status="INDETERMINATE",
              reasons=["POSITION_SNAPSHOT_BEFORE_RECORD"]))
    doc = compute_position_impact(
        _canon(), EID, positions, _rules(_cash_rule()),
        entitlements_doc=entitlements, now=NOW)

    item = doc["impacts"][0]
    assert item["status"] == INDETERMINATE
    assert item["reasons"] == ["POSITION_SNAPSHOT_BEFORE_RECORD"]
    assert item["cash_amount"] is None


def test_no_rule_for_event_type_is_unsupported():
    positions = _positions(_pos())
    doc = compute_position_impact(
        _canon(event_type="CAPITAL_INCREASE"), EID, positions,
        _rules(_cash_rule()), now=NOW)

    item = doc["impacts"][0]
    assert item["status"] == UNSUPPORTED
    assert item["reasons"] == ["NO_RULE"]
    assert item["rule_id"] is None


def test_unsupported_rule_carries_preregistered_reason():
    split_rule = {
        "rule_id": "SPLIT_V1",
        "event_type": "SPLIT",
        "status": "UNSUPPORTED",
        "reason": "BASIS_DATE_NOT_PROVABLE",
    }
    positions = _positions(_pos())
    doc = compute_position_impact(
        _canon(event_type="SPLIT"), EID, positions,
        _rules(split_rule), now=NOW)

    item = doc["impacts"][0]
    assert item["status"] == UNSUPPORTED
    assert item["reasons"] == ["BASIS_DATE_NOT_PROVABLE"]
    assert item["rule_id"] == "SPLIT_V1"


def test_missing_entitlement_input_is_indeterminate():
    positions = _positions(_pos())
    doc = compute_position_impact(
        _canon(), EID, positions, _rules(_cash_rule()), now=NOW)

    assert doc["reasons"] == ["MISSING_ENTITLEMENT_INPUT"]
    item = doc["impacts"][0]
    assert item["status"] == INDETERMINATE
    assert item["reasons"] == ["MISSING_ENTITLEMENT_INPUT"]
    assert item["source_entitlement_sha256"] is None


def test_entitlement_event_mismatch_fails_closed():
    positions = _positions(_pos())
    entitlements = _entitlements(_cell(), eid="OTHER")
    doc = compute_position_impact(
        _canon(), EID, positions, _rules(_cash_rule()),
        entitlements_doc=entitlements, now=NOW)

    assert doc["reasons"] == ["ENTITLEMENT_EVENT_MISMATCH"]
    item = doc["impacts"][0]
    assert item["status"] == INDETERMINATE
    assert item["reasons"] == ["ENTITLEMENT_EVENT_MISMATCH"]


def test_entitlement_cell_missing():
    positions = _positions(_pos(account="A002"))
    entitlements = _entitlements(_cell(account="A001"))
    doc = compute_position_impact(
        _canon(), EID, positions, _rules(_cash_rule()),
        entitlements_doc=entitlements, now=NOW)

    item = doc["impacts"][0]
    assert item["status"] == INDETERMINATE
    assert item["reasons"] == ["ENTITLEMENT_CELL_MISSING"]


def test_entitlement_cell_ambiguous():
    positions = _positions(_pos())
    entitlements = _entitlements(_cell(), _cell())
    doc = compute_position_impact(
        _canon(), EID, positions, _rules(_cash_rule()),
        entitlements_doc=entitlements, now=NOW)

    item = doc["impacts"][0]
    assert item["status"] == INDETERMINATE
    assert item["reasons"] == ["ENTITLEMENT_CELL_AMBIGUOUS"]


def test_foreign_isin_position_stays_indeterminate():
    positions = _positions(_pos(isin="ES9999999999"))
    entitlements = _entitlements(
        _cell(isin="ES9999999999", status="INDETERMINATE",
              reasons=["NO_POSITION_FOR_INSTRUMENT"]))
    doc = compute_position_impact(
        _canon(), EID, positions, _rules(_cash_rule()),
        entitlements_doc=entitlements, now=NOW)

    item = doc["impacts"][0]
    assert item["status"] == INDETERMINATE
    assert item["reasons"] == ["NO_POSITION_FOR_INSTRUMENT"]


def test_position_as_of_falls_back_to_doc_level():
    positions = _positions(_pos(as_of=None), as_of=RECORD)
    entitlements = _entitlements(_cell(), as_of=RECORD)
    doc = compute_position_impact(
        _canon(), EID, positions, _rules(_cash_rule()),
        entitlements_doc=entitlements, now=NOW)

    item = doc["impacts"][0]
    assert item["status"] == PROJECTED


def test_no_mutation_and_determinism():
    canon = _canon()
    positions = _positions(_pos())
    rules = _rules(_cash_rule())
    entitlements = _entitlements(_cell())
    snapshot = [
        copy.deepcopy(canon), copy.deepcopy(positions),
        copy.deepcopy(rules), copy.deepcopy(entitlements),
    ]
    doc1 = compute_position_impact(
        canon, EID, positions, rules,
        entitlements_doc=entitlements, now=NOW)
    doc2 = compute_position_impact(
        canon, EID, positions, rules,
        entitlements_doc=entitlements, now=NOW)
    assert canonical_json(doc1) == canonical_json(doc2)
    assert canon == snapshot[0]
    assert positions == snapshot[1]
    assert rules == snapshot[2]
    assert entitlements == snapshot[3]


def test_invalid_schemas_fail_closed():
    with pytest.raises(ValueError):
        compute_position_impact(
            {"canon_version": "OTHER"}, EID, _positions(),
            _rules(_cash_rule()), now=NOW)
    with pytest.raises(ValueError):
        compute_position_impact(
            _canon(), EID, {"schema": "OTHER"}, _rules(_cash_rule()),
            now=NOW)
    with pytest.raises(ValueError):
        compute_position_impact(
            _canon(), EID, _positions(), {"schema": "OTHER"}, now=NOW)
    with pytest.raises(ValueError):
        compute_position_impact(
            _canon(), EID, _positions(), _rules(_cash_rule()),
            entitlements_doc={"schema": "OTHER"}, now=NOW)
    with pytest.raises(ValueError):
        compute_position_impact(
            _canon(), "MISSING", _positions(), _rules(_cash_rule()),
            now=NOW)


def test_float_quantity_fails_closed():
    # un float en positions viola el contrato canonico: el hash del
    # artefacto lo rechaza antes de calcular (nunca se normaliza)
    positions = _positions(_pos(qty=12500.0))
    with pytest.raises(ValueError):
        compute_position_impact(
            _canon(), EID, positions, _rules(_cash_rule()),
            entitlements_doc=_entitlements(_cell()), now=NOW)
