from __future__ import annotations

from ca_es.vocab import InfrastructureRole


def test_p3_temporal_semantics(events_by_type, run_result, facts_for):
    event = events_by_type["CASH_DIVIDEND"]
    event = next(e for e in event if e["issuer_name"] == "P3 Spain SOCIMI")
    dates = event["temporal"]["dates"]
    assert dates["RECORD_DATE"] < dates["EX_DATE"]
    assert dates["PAYMENT_DATE"] == dates["EX_DATE"]
    assert event["temporal"]["violations"] == []


def test_p3_high_precision_amount(events_by_type, run_result, facts_for):
    event = next(
        e
        for e in events_by_type["CASH_DIVIDEND"]
        if e["issuer_name"] == "P3 Spain SOCIMI"
    )
    amount = next(
        fact
        for fact in facts_for(run_result, event)
        if fact["field_path"] == "amount.gross_per_share"
    )
    value = amount["value"]
    assert value["raw_lexeme"] == "0,11840672"
    assert value["normalized"] == "0.11840672"
    assert value["scale"] == 8
    assert value["currency"] == "EUR"


def test_p3_payment_channel_not_upcast_to_csd(events_by_type, run_result, facts_for):
    event = next(
        e
        for e in events_by_type["CASH_DIVIDEND"]
        if e["issuer_name"] == "P3 Spain SOCIMI"
    )
    facts = facts_for(run_result, event)
    channel = [
        fact["value"]
        for fact in facts
        if fact["field_path"]
        == f"infrastructure_role.{InfrastructureRole.PAYMENT_CHANNEL.value}"
    ]
    assert channel == ["EUROCLEAR_FRANCE"]
    assert not any(
        fact["field_path"]
        == f"infrastructure_role.{InfrastructureRole.ISSUER_CSD.value}"
        for fact in facts
    )
