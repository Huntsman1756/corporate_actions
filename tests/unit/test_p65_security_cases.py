"""P6.5 — excepciones P3.5 sobre el recon de valores.

El motor consume CA_ES_SECURITY_RECON_V1 ya adjudicado: no recalcula
impacto ni movimiento. factual_status != workflow_status; case_key
estable por evento+sujeto, nunca por factual_status.
"""

import copy

from ca_es.exceptions import (
    apply_transition,
    build_cases_doc,
    classify_cases,
)

NOW = "2026-09-17T00:00:00Z"
EID = "E-SPLIT"
ISIN = "ES0105857009"


def _recon(*items):
    return {
        "schema": "CA_ES_SECURITY_RECON_V1",
        "generated_at": NOW,
        "canonical_event_id": EID,
        "event_type": "SPLIT",
        "items": list(items),
        "summary": {},
    }


def _item(status, account="A001", isin=ISIN, direction="DELIVERY",
          expected="12500", actual=None, delta=None,
          mids=None, reasons=None):
    return {
        "account_id": account,
        "isin": isin,
        "direction": direction,
        "status": status,
        "expected_quantity": expected,
        "actual_quantity": actual,
        "delta": delta,
        "expected_ref": "impacts[0]",
        "movement_ids": list(mids or []),
        "reasons": list(reasons or []),
        "evidence": {"expected": {"assertion_ids": ["a1"]},
                     "actual": []},
    }


def test_missing_security_movement_creates_case():
    recon = _recon(_item("MISSING_SECURITY_MOVEMENT"))
    cases = classify_cases(recon)
    assert len(cases) == 1
    case = cases[0]
    assert case["factual_status"] == "MISSING_SECURITY_MOVEMENT"
    assert case["priority"] == "HIGH"
    assert case["expected_quantity"] == "12500"
    assert case["direction"] == "DELIVERY"
    assert case["case_key"] == (
        f"{EID}|expected:A001:{ISIN}:DELIVERY")


def test_unexpected_movement_case_keyed_by_movement():
    recon = _recon(_item("UNEXPECTED_SECURITY_MOVEMENT",
                         expected=None, actual="10",
                         mids=["SWIFT-x-SECMOVE0"]))
    case = classify_cases(recon)[0]
    assert case["factual_status"] == "UNEXPECTED_SECURITY_MOVEMENT"
    assert case["priority"] == "MEDIUM"
    assert case["case_key"] == f"{EID}|movement:A001:SWIFT-x-SECMOVE0"


def test_quantity_mismatch_high_priority():
    recon = _recon(_item("QUANTITY_MISMATCH", actual="12000",
                         delta="-500",
                         mids=["SWIFT-x-SECMOVE0"]))
    case = classify_cases(recon)[0]
    assert case["factual_status"] == "QUANTITY_MISMATCH"
    assert case["priority"] == "HIGH"
    assert case["delta"] == "-500"


def test_match_never_creates_case():
    recon = _recon(_item("MATCH", actual="12500", delta="0",
                         mids=["SWIFT-x-SECMOVE0"]))
    assert classify_cases(recon) == []


def test_factual_evolution_keeps_single_case():
    # MISSING -> QUANTITY_MISMATCH -> MATCH es el mismo caso
    doc1 = build_cases_doc(
        _recon(_item("MISSING_SECURITY_MOVEMENT")), now="T1")
    assert len(doc1["cases"]) == 1
    key = doc1["cases"][0]["case_key"]

    doc2 = build_cases_doc(
        _recon(_item("QUANTITY_MISMATCH", actual="12000",
                     delta="-500", mids=["SWIFT-x-SECMOVE0"])),
        previous_cases=doc1["cases"], now="T2")
    assert len(doc2["cases"]) == 1
    case = doc2["cases"][0]
    assert case["case_key"] == key
    assert case["factual_status"] == "QUANTITY_MISMATCH"
    assert case["actual_quantity"] == "12000"
    types = [h["type"] for h in case["history"]]
    assert types == ["CREATED", "FACT_UPDATED"]

    # el MATCH hace desaparecer el item -> NOT_OBSERVED, nunca borrado
    doc3 = build_cases_doc(
        _recon(_item("MATCH", actual="12500", delta="0",
                     mids=["SWIFT-x-SECMOVE0"])),
        previous_cases=doc2["cases"], now="T3")
    case3 = doc3["cases"][0]
    assert case3["case_key"] == key
    assert case3["observed"] is False
    assert "NOT_OBSERVED" in [h["type"] for h in case3["history"]]


def test_resolved_case_reopens_on_reappearance():
    doc1 = build_cases_doc(
        _recon(_item("MISSING_SECURITY_MOVEMENT")), now="T1")
    case = apply_transition(
        doc1["cases"][0], "RESOLVED", "ops", "T2",
        resolution_code="CORRECTED", note="manual fix")
    doc2 = build_cases_doc(
        _recon(_item("MISSING_SECURITY_MOVEMENT")),
        previous_cases=[case], now="T3")
    reopened = doc2["cases"][0]
    assert reopened["workflow_status"] == "OPEN"
    assert reopened["factual_status"] == "MISSING_SECURITY_MOVEMENT"
    assert any(h["type"] == "REOPENED" for h in reopened["history"])


def test_queue_orders_security_cases():
    recon = _recon(
        _item("UNEXPECTED_SECURITY_MOVEMENT", account="A009",
              isin="ES0000000002", direction="RECEIPT",
              expected=None, actual="1",
              mids=["SWIFT-u-SECMOVE0"]),
        _item("QUANTITY_MISMATCH", delta="-999999",
              mids=["SWIFT-x-SECMOVE0"]))
    doc = build_cases_doc(recon, now="T1")
    queue = doc["queue"]
    assert [q["factual_status"] for q in queue] == [
        "QUANTITY_MISMATCH", "UNEXPECTED_SECURITY_MOVEMENT"]


def test_no_mutation():
    recon = _recon(_item("MISSING_SECURITY_MOVEMENT"))
    snap = copy.deepcopy(recon)
    build_cases_doc(recon, now="T1")
    assert recon == snap
