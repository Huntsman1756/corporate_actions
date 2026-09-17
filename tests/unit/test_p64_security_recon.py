"""P6.4 — CA_ES_SECURITY_RECON_V1.

Matching exacto por (account, isin, direction); expected derivado del
doc de impacto adjudicado; authoritative solo si la adjudicacion esta
completa; provenance bilateral.
"""

import copy

import pytest

from ca_es.canonical import canonical_json, sha256_hex
from ca_es.security_recon import (
    INDETERMINATE,
    MATCH,
    MISSING_SECURITY_MOVEMENT,
    QUANTITY_MISMATCH,
    UNEXPECTED_SECURITY_MOVEMENT,
    reconcile_security_movements,
)

NOW = "2026-09-17T00:00:00Z"
SHA = "aa" * 32
ISIN = "ES0105857009"
NEW_ISIN = "ES0105857033"
EID = "E-SPLIT"


def _impact_item(account="A001", source=ISIN, target=None,
                 status="PROJECTED", impact_type="SECURITY_DELIVERY",
                 delta="-12500"):
    return {
        "canonical_event_id": EID,
        "account_id": account,
        "source_isin": source,
        "target_isin": target,
        "impact_type": impact_type,
        "status": status,
        "input_quantity": "12500",
        "output_quantity": None,
        "quantity_delta": delta,
        "cash_amount": None,
        "currency": None,
        "rule_id": "R1",
        "basis_date": "2026-06-09",
        "reasons": [],
        "source_canon_logical_sha256": SHA,
        "source_positions_logical_sha256": None,
        "evidence": {"assertion_ids": ["a1"],
                     "source_document_ids": ["d1"],
                     "evidence_locators": ["loc/1"]},
    }


def _impact(*items, event_type="SPLIT"):
    return {
        "schema": "CA_ES_POSITION_IMPACT_V1",
        "generated_at": NOW,
        "canonical_event_id": EID,
        "event_type": event_type,
        "positions_as_of": "2026-06-08",
        "rule_id": "R1",
        "reasons": [],
        "source_canon_logical_sha256": SHA,
        "source_positions_logical_sha256": "bb" * 32,
        "source_entitlement_sha256": None,
        "impacts": list(items),
        "summary": {},
    }


def _movement(account="A001", isin=ISIN, direction="DELIVERY",
              qty="12500", mid="SWIFT-deadbeef-SECMOVE0"):
    return {
        "movement_id": mid,
        "account_id": account,
        "isin": isin,
        "direction": direction,
        "quantity": qty,
        "quantity_type": "UNIT",
        "posting_date": "2026-06-09",
        "status": "PROJECTABLE",
        "reasons": [],
        "provenance": [{"source_tag": "36B", "source_qualifier": "PSTA",
                        "sequence": "CACONF/SECMOVE", "occurrence": 0,
                        "evidence_locator": "block4.tag[18]",
                        "raw": qty}],
    }


def _candidate(*movements, eid=EID, bound=True):
    return {
        "schema": "CA_ES_SWIFT_SECURITY_MOVEMENT_CANDIDATE_V1",
        "generated_at": NOW,
        "message_identifier": "MT566",
        "input_sha256": SHA,
        "canonical_event_id": eid,
        "binding_status": "BOUND" if bound else "NO_MATCH",
        "event_type": "SPLIT",
        "caev": "SPLF",
        "status": "PROJECTABLE",
        "reasons": [],
        "movements": list(movements),
    }


def test_exact_match():
    impact = _impact(_impact_item())
    cand = _candidate(_movement())
    doc = reconcile_security_movements(impact, [cand], now=NOW)

    assert doc["schema"] == "CA_ES_SECURITY_RECON_V1"
    assert doc["expected_set_authoritative"] is True
    assert doc["source_impact_sha256"] == sha256_hex(impact)
    assert doc["source_candidate_sha256s"] == [sha256_hex(cand)]
    item = doc["items"][0]
    assert item["status"] == MATCH
    assert item["expected_quantity"] == "12500"
    assert item["actual_quantity"] == "12500"
    assert item["delta"] == "0"
    assert item["expected_ref"] == "impacts[0]"
    assert item["movement_ids"] == ["SWIFT-deadbeef-SECMOVE0"]
    assert item["evidence"]["expected"]["assertion_ids"] == ["a1"]
    assert item["evidence"]["actual"][0][0]["source_tag"] == "36B"


def test_quantity_mismatch():
    impact = _impact(_impact_item())
    cand = _candidate(_movement(qty="12000"))
    doc = reconcile_security_movements(impact, [cand], now=NOW)
    item = doc["items"][0]
    assert item["status"] == QUANTITY_MISMATCH
    assert item["delta"] == "-500"


def test_missing_security_movement():
    impact = _impact(_impact_item())
    doc = reconcile_security_movements(impact, [], now=NOW)
    item = doc["items"][0]
    assert item["status"] == MISSING_SECURITY_MOVEMENT
    assert item["expected_quantity"] == "12500"
    assert item["movement_ids"] == []


def test_unexpected_movement_when_authoritative():
    impact = _impact(_impact_item())
    cand = _candidate(_movement(),
                      _movement(isin=NEW_ISIN, direction="RECEIPT",
                                qty="125000",
                                mid="SWIFT-deadbeef-SECMOVE1"))
    doc = reconcile_security_movements(impact, [cand], now=NOW)
    by_isin = {i["isin"]: i for i in doc["items"]}
    assert by_isin[ISIN]["status"] == MATCH
    assert by_isin[NEW_ISIN]["status"] == UNEXPECTED_SECURITY_MOVEMENT


def test_unexpected_becomes_indeterminate_when_not_authoritative():
    impact = _impact(
        _impact_item(status="UNSUPPORTED", delta=None))
    cand = _candidate(_movement())
    doc = reconcile_security_movements(impact, [cand], now=NOW)
    item = doc["items"][0]
    assert doc["expected_set_authoritative"] is False
    assert item["status"] == INDETERMINATE
    assert item["reasons"] == ["EXPECTED_SET_INCOMPLETE"]


def test_multiple_actuals_same_key():
    impact = _impact(_impact_item())
    cand = _candidate(
        _movement(), _movement(mid="SWIFT-deadbeef-SECMOVE1"))
    doc = reconcile_security_movements(impact, [cand], now=NOW)
    item = doc["items"][0]
    assert item["status"] == INDETERMINATE
    assert item["reasons"] == ["MULTIPLE_SECURITY_MOVEMENTS"]
    assert len(item["movement_ids"]) == 2


def test_multiple_expected_same_key():
    impact = _impact(_impact_item(), _impact_item(delta="-5000"))
    doc = reconcile_security_movements(impact, [], now=NOW)
    item = doc["items"][0]
    assert item["status"] == INDETERMINATE
    assert item["reasons"] == ["MULTIPLE_EXPECTED"]


def test_cash_dividend_with_secmove_is_unexpected():
    # CASH_DIVIDEND adjudicado completo -> expected de valores vacio
    cash_item = _impact_item(impact_type="CASH_RECEIVABLE", delta=None)
    impact = _impact(cash_item, event_type="CASH_DIVIDEND")
    cand = _candidate(_movement(direction="RECEIPT", qty="10"))
    doc = reconcile_security_movements(impact, [cand], now=NOW)
    item = doc["items"][0]
    assert item["status"] == UNEXPECTED_SECURITY_MOVEMENT


def test_candidate_not_bound_fails_closed():
    impact = _impact(_impact_item())
    cand = _candidate(_movement(), bound=False)
    with pytest.raises(ValueError, match="CANDIDATE_NOT_BOUND"):
        reconcile_security_movements(impact, [cand], now=NOW)


def test_candidate_event_mismatch_fails_closed():
    impact = _impact(_impact_item())
    cand = _candidate(_movement(), eid="OTHER")
    with pytest.raises(ValueError, match="EVENT_MISMATCH"):
        reconcile_security_movements(impact, [cand], now=NOW)


def test_determinism_and_no_mutation():
    impact = _impact(_impact_item())
    cand = _candidate(_movement())
    snap = [copy.deepcopy(impact), copy.deepcopy(cand)]
    a = reconcile_security_movements(impact, [cand], now=NOW)
    b = reconcile_security_movements(impact, [cand], now=NOW)
    assert canonical_json(a) == canonical_json(b)
    assert impact == snap[0] and cand == snap[1]


def test_invalid_schema_fails_closed():
    impact = _impact(_impact_item())
    with pytest.raises(ValueError):
        reconcile_security_movements({"schema": "X"}, [], now=NOW)
    with pytest.raises(ValueError):
        reconcile_security_movements(
            impact, [{"schema": "X"}], now=NOW)
