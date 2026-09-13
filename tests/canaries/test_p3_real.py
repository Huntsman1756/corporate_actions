from __future__ import annotations


def _p3_event(result: dict) -> dict:
    for event in result["body"]["events"]:
        if event["event_type"] != "CASH_DIVIDEND":
            continue
        facts = [
            f
            for f in result["body"]["facts"]
            if f["event_id"] == event["canonical_event_id"]
        ]
        if any(
            isinstance(f["value"], dict)
            and f["value"].get("__financial__")
            and f["value"]["normalized"] == "0.11840672"
            for f in facts
        ):
            return event
    raise AssertionError("P3 event not found")


def test_p3_real_portfolio_document(repo_root, real_run):
    event = _p3_event(real_run)
    facts = {
        f["field_path"]: f
        for f in real_run["body"]["facts"]
        if f["event_id"] == event["canonical_event_id"]
    }
    amount = facts["amount.gross_per_share"]["value"]
    assert amount["raw_lexeme"] == "0,11840672"
    assert amount["normalized"] == "0.11840672"
    assert amount["scale"] == 8
    assert amount["currency"] == "EUR"


def test_p3_real_temporal_semantics(repo_root, real_run):
    event = _p3_event(real_run)
    facts = {
        f["field_path"]: f
        for f in real_run["body"]["facts"]
        if f["event_id"] == event["canonical_event_id"]
    }
    record = facts["date.record_date"]["value"]
    ex = facts["date.ex_date"]["value"]
    payment = facts["date.payment_date"]["value"]
    assert record < ex  # 2025-07-23 < 2025-07-24
    assert payment == ex
    assert event["temporal"]["violations"] == []


def test_p3_real_euroclear_france_not_csd(repo_root, real_run):
    event = _p3_event(real_run)
    facts = [
        f
        for f in real_run["body"]["facts"]
        if f["event_id"] == event["canonical_event_id"]
    ]
    paths = {f["field_path"] for f in facts}
    assert "infrastructure_role.PAYMENT_CHANNEL" in paths
    channel = next(f for f in facts if f["field_path"] == "infrastructure_role.PAYMENT_CHANNEL")
    assert channel["value"] == "EUROCLEAR_FRANCE"
    assert "infrastructure_role.ISSUER_CSD" not in paths
