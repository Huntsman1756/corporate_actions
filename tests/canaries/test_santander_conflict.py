from __future__ import annotations


def test_santander_conflict_is_explicit(events_by_type, run_result, facts_for):
    event = next(
        e
        for e in events_by_type["CASH_DIVIDEND"]
        if e["issuer_name"] == "Banco Santander"
    )
    assert event["conflict_count"] == 1
    conflicts = [
        c
        for c in run_result["body"]["conflicts"]
        if c["event_id"] == event["canonical_event_id"]
    ]
    assert len(conflicts) == 1
    assert conflicts[0]["field_path"] == "amount.gross_per_share"
    assert len(conflicts[0]["values"]) == 2


def test_both_sources_retained_no_silent_override(events_by_type, run_result, facts_for):
    event = next(
        e
        for e in events_by_type["CASH_DIVIDEND"]
        if e["issuer_name"] == "Banco Santander"
    )
    amounts = [
        fact
        for fact in facts_for(run_result, event)
        if fact["field_path"] == "amount.gross_per_share"
    ]
    assert len(amounts) == 2
    assert {fact["value"]["normalized"] for fact in amounts} == {"0.10", "0.11"}
    assert all(fact["evidence_mode"] == "CONFLICTING" for fact in amounts)
    assert {fact["source_id"] for fact in amounts} == {"CNMV", "ISSUER_IR"}
