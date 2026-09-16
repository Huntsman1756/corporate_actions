"""P3.5 — exception cases: identidad, lifecycle, audit, queue.

Los recon docs se construyen con reconcile() real sobre entitlements
sinteticos; los casos de lifecycle usan build_cases_doc + merge.
"""

import json

import pytest

from ca_es.exceptions import (
    CASES_SCHEMA,
    apply_transition,
    build_cases_doc,
    classify_cases,
    queue,
)
from ca_es.reconciliation import reconcile

EV = "evt-1"
T0 = "2026-07-15T09:00:00Z"
T1 = "2026-07-15T10:00:00Z"
T2 = "2026-07-16T09:00:00Z"


def _ent_doc(*ents):
    return {"canonical_event_id": EV, "entitlements": list(ents)}


def _ent(account="A001", amount="100.00", currency="EUR",
         status="ENTITLED", reasons=None, isin="ES01"):
    e = {
        "account_id": account,
        "isin": isin,
        "status": status,
        "reasons": reasons or [],
        "evidence": {"gross": {"assertion_ids": ["as-1"]}},
    }
    if amount is not None:
        e["gross_cash"] = {
            "normalized": amount,
            "currency": currency,
            "scale": 2,
        }
    return e


def _mov(mid="M1", account="A001", amount="100.00", currency="EUR",
         basis="GROSS"):
    return {
        "movement_id": mid,
        "account_id": account,
        "event_id": EV,
        "currency": currency,
        "amount": amount,
        "amount_basis": basis,
        "value_date": "2026-07-14",
    }


def _movs(*ms):
    return {"schema": "CA_ES_CASH_MOVEMENTS_V2", "movements": list(ms)}


def _recon(*ents, movements=()):
    return reconcile(_ent_doc(*ents), _movs(*movements))


def _doc(*ents, movements=(), now=T0, previous=None):
    return build_cases_doc(
        _recon(*ents, movements=movements), previous, now=now
    )


# ------------------------------------------------------- classification

def test_match_creates_no_case():
    doc = _doc(_ent(), movements=[_mov()])
    assert doc["cases"] == []
    assert doc["queue"] == []


def test_mismatch_case_carries_exact_delta():
    doc = _doc(_ent(), movements=[_mov(amount="90.00")])
    case = doc["cases"][0]
    assert case["factual_status"] == "AMOUNT_MISMATCH"
    assert case["delta"]["normalized"] == "-10.00"
    assert case["expected_amount"]["normalized"] == "100.00"
    assert case["actual_amount"] == "90.00"
    assert case["amount_basis"] == "GROSS"
    assert case["workflow_status"] == "OPEN"
    assert case["priority"] == "HIGH"
    assert case["evidence"]["entitlement"] is not None
    assert case["history"][0]["type"] == "CREATED"


def test_net_basis_case_preserves_reason_without_delta():
    doc = _doc(_ent(), movements=[_mov(amount="82.50", basis="NET")])
    case = doc["cases"][0]
    assert case["factual_status"] == "INDETERMINATE"
    assert case["reason_codes"] == ["NET_EXPECTED_NOT_AVAILABLE"]
    assert case["actual_amount"] == "82.50"
    assert case["amount_basis"] == "NET"
    assert case["delta"] is None


def test_unknown_basis_never_mismatch():
    doc = _doc(_ent(), movements=[_mov(amount="50.00", basis="UNKNOWN")])
    case = doc["cases"][0]
    assert case["factual_status"] == "INDETERMINATE"
    assert case["reason_codes"] == ["UNKNOWN_AMOUNT_BASIS"]


def test_unexpected_cash_keyed_by_movement_keeps_basis():
    doc = _doc(
        movements=[_mov(mid="MX", account="A9", basis="NET")]
    )
    case = doc["cases"][0]
    assert case["factual_status"] == "UNEXPECTED_CASH"
    assert case["amount_basis"] == "NET"
    assert "MX" in case["case_key"]
    assert case["expected_amount"] is None
    assert case["priority"] == "MEDIUM"


def test_missing_cash_case():
    doc = _doc(_ent())
    case = doc["cases"][0]
    assert case["factual_status"] == "MISSING_CASH"
    assert case["priority"] == "HIGH"
    assert case["expected_amount"]["normalized"] == "100.00"
    assert case["actual_amount"] is None


def test_entitlement_indeterminate_passthrough_case():
    doc = _doc(
        _ent(status="INDETERMINATE", reasons=["MISSING_RECORD_DATE"],
             amount=None)
    )
    case = doc["cases"][0]
    assert case["factual_status"] == "INDETERMINATE"
    assert "ENTITLEMENT_INDETERMINATE" in case["reason_codes"]
    assert "MISSING_RECORD_DATE" in case["reason_codes"]


# ---------------------------------------------------------- lifecycle

def test_rerun_same_result_no_duplicates():
    first = _doc(_ent(), movements=[_mov(amount="90.00")], now=T0)
    again = _doc(
        _ent(), movements=[_mov(amount="90.00")],
        now=T1, previous=first["cases"],
    )
    assert len(again["cases"]) == 1
    case = again["cases"][0]
    assert case["first_seen_at"] == T0
    assert case["last_seen_at"] == T1
    types = [h["type"] for h in case["history"]]
    assert types == ["CREATED"]  # nada nuevo: ni audit noise


def test_disappearance_registered_not_deleted():
    first = _doc(_ent(), movements=[_mov(amount="90.00")], now=T0)
    second = _doc(_ent(), movements=[_mov()], now=T1,
                  previous=first["cases"])
    case = second["cases"][0]
    assert case["observed"] is False
    assert case["workflow_status"] == "OPEN"  # workflow intacto
    assert [h["type"] for h in case["history"]] == [
        "CREATED", "NOT_OBSERVED"
    ]
    assert second["queue"] == []  # fuera de la cola


def test_resolved_reappears_reopens_same_case():
    first = _doc(_ent(), movements=[_mov(amount="90.00")], now=T0)
    case = first["cases"][0]
    apply_transition(
        case, "RESOLVED", actor="ops", at=T1,
        resolution_code="CORRECTED", note="fixed upstream",
    )
    third = _doc(
        _ent(), movements=[_mov(amount="95.00")],
        now=T2, previous=first["cases"],
    )
    case = third["cases"][0]
    assert case["workflow_status"] == "OPEN"
    assert case["resolution_code"] is None
    assert case["resolved_at"] is None
    assert case["actual_amount"] == "95.00"  # snapshot actualizado
    types = [h["type"] for h in case["history"]]
    assert types == ["CREATED", "TRANSITION", "FACT_UPDATED",
                     "REOPENED"]
    reopen = case["history"][-1]
    assert reopen["from_status"] == "RESOLVED"
    assert reopen["to_status"] == "OPEN"


def test_movement_replacement_same_case():
    # mismatch con MOV-A; el proximo run trae MOV-B (mismo importe
    # erroneo): el sujeto es la expectativa, no el movement_id
    first = _doc(_ent(), movements=[_mov(mid="MA", amount="90.00")],
                 now=T0)
    second = _doc(_ent(), movements=[_mov(mid="MB", amount="90.00")],
                  now=T1, previous=first["cases"])
    assert len(second["cases"]) == 1
    assert second["cases"][0]["case_key"] == first["cases"][0]["case_key"]
    assert second["cases"][0]["movement_ids"] == ["MB"]


def test_status_evolution_same_case():
    # UNKNOWN basis -> movimiento corregido a GROSS con importe malo:
    # el caso evoluciona INDETERMINATE -> AMOUNT_MISMATCH con el mismo
    # case_key (factual_status no forma parte de la identidad)
    first = _doc(_ent(), movements=[_mov(amount="90.00",
                                         basis="UNKNOWN")], now=T0)
    second = _doc(_ent(), movements=[_mov(amount="90.00")],
                  now=T1, previous=first["cases"])
    assert len(second["cases"]) == 1
    case = second["cases"][0]
    assert case["case_key"] == first["cases"][0]["case_key"]
    assert case["factual_status"] == "AMOUNT_MISMATCH"
    assert [h["type"] for h in case["history"]] == [
        "CREATED", "FACT_UPDATED"
    ]


def test_regression_missing_to_mismatch_same_case():
    first = _doc(_ent(), now=T0)  # MISSING_CASH
    second = _doc(_ent(), movements=[_mov(amount="90.00")],
                  now=T1, previous=first["cases"])
    assert len(second["cases"]) == 1
    case = second["cases"][0]
    assert case["case_key"] == first["cases"][0]["case_key"]
    assert case["factual_status"] == "AMOUNT_MISMATCH"
    assert [h["type"] for h in case["history"]] == [
        "CREATED", "FACT_UPDATED"
    ]


def test_regression_resolved_missing_reappears_as_mismatch():
    first = _doc(_ent(), now=T0)  # MISSING_CASH
    apply_transition(
        first["cases"][0], "RESOLVED", actor="ops", at=T0,
        resolution_code="CORRECTED",
    )
    second = _doc(_ent(), movements=[_mov(amount="90.00")],
                  now=T1, previous=first["cases"])
    assert len(second["cases"]) == 1
    case = second["cases"][0]
    assert case["case_key"] == first["cases"][0]["case_key"]
    assert case["factual_status"] == "AMOUNT_MISMATCH"
    assert case["workflow_status"] == "OPEN"
    assert [h["type"] for h in case["history"]] == [
        "CREATED", "TRANSITION", "FACT_UPDATED", "REOPENED"
    ]


def test_regression_disappeared_then_reappears_same_case():
    first = _doc(_ent(), now=T0)                       # MISSING_CASH
    second = _doc(_ent(), movements=[_mov()], now=T1,  # MATCH
                  previous=first["cases"])
    case = second["cases"][0]
    assert case["observed"] is False
    third = _doc(_ent(), movements=[_mov(amount="90.00")], now=T2,
                 previous=second["cases"])
    assert len(third["cases"]) == 1
    case = third["cases"][0]
    assert case["case_key"] == first["cases"][0]["case_key"]
    assert case["observed"] is True
    assert case["factual_status"] == "AMOUNT_MISMATCH"
    assert [h["type"] for h in case["history"]] == [
        "CREATED", "NOT_OBSERVED", "FACT_UPDATED", "REOBSERVED"
    ]


# ------------------------------------------------------ audit/workflow

def test_transition_never_touches_factual():
    doc = _doc(_ent(), movements=[_mov(amount="90.00")])
    case = doc["cases"][0]
    apply_transition(case, "RESOLVED", actor="ops", at=T1,
                     resolution_code="ACCEPTED_AS_IS")
    assert case["workflow_status"] == "RESOLVED"
    assert case["factual_status"] == "AMOUNT_MISMATCH"  # intacto
    assert case["resolved_at"] == T1
    tr = case["history"][-1]
    assert tr["actor"] == "ops"
    assert tr["from_status"] == "OPEN"


def test_closed_transition_requires_resolution_code():
    doc = _doc(_ent(), movements=[_mov(amount="90.00")])
    case = doc["cases"][0]
    with pytest.raises(ValueError):
        apply_transition(case, "RESOLVED", actor="ops", at=T1)
    with pytest.raises(ValueError):
        apply_transition(case, "DISMISSED", actor="ops", at=T1,
                         resolution_code="NOPE")
    with pytest.raises(ValueError):
        apply_transition(case, "IN_REVIEW", actor="", at=T1)
    assert case["workflow_status"] == "OPEN"


def test_audit_trail_is_append_only():
    first = _doc(_ent(), movements=[_mov(amount="90.00")], now=T0)
    case = first["cases"][0]
    apply_transition(case, "IN_REVIEW", actor="a", at=T1, note="mirando")
    apply_transition(case, "WAITING_EXTERNAL", actor="a", at=T1)
    hist = case["history"]
    assert [h["type"] for h in hist] == [
        "CREATED", "TRANSITION", "TRANSITION"
    ]
    assert hist[1]["to_status"] == "IN_REVIEW"
    assert hist[2]["from_status"] == "IN_REVIEW"


# ------------------------------------------------------------- queue

def test_queue_deterministic_order_and_filters():
    doc = _doc(
        _ent(account="A-HI", amount="500.00"),
        _ent(account="A-LO", amount="10.00"),
        movements=[
            _mov(mid="M-HI", account="A-HI", amount="1.00"),
            _mov(mid="M-LO", account="A-LO", amount="1.00"),
            _mov(mid="M-UNX", account="A9"),  # UNEXPECTED MEDIUM
        ],
    )
    q = doc["queue"]
    # HIGH (mismatch) antes que MEDIUM (unexpected); dentro de HIGH
    # manda |delta| mayor (499 > 9)
    assert [e["account_id"] for e in q] == ["A-HI", "A-LO", "A9"]
    # resuelto sale de la cola
    case = next(
        c for c in doc["cases"] if c["account_id"] == "A-HI"
    )
    apply_transition(case, "RESOLVED", actor="ops", at=T1,
                     resolution_code="CORRECTED")
    q2 = queue(doc["cases"])
    assert [e["account_id"] for e in q2] == ["A-LO", "A9"]


def test_build_cases_doc_deterministic():
    a = _doc(_ent(), movements=[_mov(amount="90.00")], now=T0)
    b = _doc(_ent(), movements=[_mov(amount="90.00")], now=T0)
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(
        b, sort_keys=True, default=str
    )


def test_summary_counts():
    doc = _doc(
        _ent(account="A1"),
        _ent(account="A2", amount="7.00"),
        movements=[_mov(mid="M2", account="A2", amount="1.00")],
    )
    s = doc["summary"]
    assert s["cases"] == 2
    assert s["observed"] == 2
    assert s["by_factual"]["MISSING_CASH"] == 1
    assert s["by_factual"]["AMOUNT_MISMATCH"] == 1
    assert doc["schema"] == CASES_SCHEMA


def test_duplicate_entitlement_key_single_case():
    # dos entitlements con la misma clave -> dos items INDETERMINATE
    # sobre expected:A001:EUR -> un solo caso
    doc = _doc(
        _ent(account="A001"),
        _ent(account="A001", isin="ES02"),
    )
    assert len(doc["cases"]) == 1
    case = doc["cases"][0]
    assert case["reason_codes"] == ["DUPLICATE_ENTITLEMENT_KEY"]


def test_classify_does_not_mutate_recon():
    recon = _recon(_ent(), movements=[_mov(amount="90.00")])
    before = json.dumps(recon, sort_keys=True, default=str)
    classify_cases(recon)
    assert json.dumps(recon, sort_keys=True, default=str) == before
