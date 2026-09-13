from __future__ import annotations

from ca_es.assertions import Assertion
from ca_es.numeric import FinancialAmount
from ca_es.provenance import build_facts, detect_conflicts


def _assertion(document_id: str, value: str, source_id: str) -> Assertion:
    return Assertion(
        document_id=document_id,
        source_id=source_id,
        field_path="amount.gross_per_share",
        value=FinancialAmount.parse(value, currency="EUR"),
        raw_value=value,
        evidence_locator=f"{source_id} locator",
        raw_pointer="/claims/0",
    )


def test_source_conflict_is_explicit_and_retained():
    facts = build_facts(
        [_assertion("doc-a", "0,10", "CNMV"), _assertion("doc-b", "0,11", "ISSUER_IR")],
        "event-1",
        "revision-1",
    )
    report = detect_conflicts(facts)
    assert len(report.conflicts) == 1
    assert len(report.facts) == 2
    assert all(fact.evidence_mode == "CONFLICTING" for fact in report.facts)


def test_agreement_is_not_a_conflict():
    facts = build_facts(
        [_assertion("doc-a", "0,10", "CNMV"), _assertion("doc-b", "0,10", "ISSUER_IR")],
        "event-1",
        "revision-1",
    )
    report = detect_conflicts(facts)
    assert report.conflicts == ()
    assert all(fact.evidence_mode == "EXPLICIT" for fact in report.facts)
