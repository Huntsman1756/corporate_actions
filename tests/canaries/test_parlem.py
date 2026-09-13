from __future__ import annotations

from ca_es.vocab import InfrastructureRole


def test_parlem_entitlement_basis_is_temporal(events_by_type, run_result, facts_for):
    event = events_by_type["RIGHTS_ISSUE"][0]
    assert event["issuer_name"] == "Parlem"
    basis = [
        fact
        for fact in facts_for(run_result, event)
        if fact["field_path"] == "entitlement_basis"
    ]
    assert len(basis) == 1
    assert basis[0]["asserted_as_of"] == "2026-08-31"
    value = basis[0]["value"]
    assert value["eligible_shares"] == 19378125
    assert value["status"] == "SUBJECT_TO_ADJUSTMENT"
    assert value["components"]["treasury_shares"] == "209745"
    assert value["components"]["waived_rights_basis_shares"] == "277883"


def test_parlem_iberclear_registration_role(events_by_type, run_result, facts_for):
    event = events_by_type["RIGHTS_ISSUE"][0]
    facts = facts_for(run_result, event)
    csd = [
        fact
        for fact in facts
        if fact["field_path"] == f"infrastructure_role.{InfrastructureRole.ISSUER_CSD.value}"
    ]
    assert len(csd) == 1
    assert csd[0]["value"] == "IBERCLEAR"
    assert csd[0]["evidence_mode"] == "EXPLICIT"


def test_parlem_trading_venue(events_by_type, run_result, facts_for):
    event = events_by_type["RIGHTS_ISSUE"][0]
    venues = [
        fact["value"]
        for fact in facts_for(run_result, event)
        if fact["field_path"]
        == f"infrastructure_role.{InfrastructureRole.TRADING_VENUE.value}"
    ]
    assert venues == ["BME_GROWTH"]


def test_parlem_no_payment_channel_upcasting(events_by_type, run_result, facts_for):
    event = events_by_type["RIGHTS_ISSUE"][0]
    paths = {fact["field_path"] for fact in facts_for(run_result, event)}
    assert f"infrastructure_role.{InfrastructureRole.PAYMENT_CHANNEL.value}" not in paths
