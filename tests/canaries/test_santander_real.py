from __future__ import annotations


def _san_event(result: dict) -> dict:
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
            and f["value"]["normalized"] == "0.1250"
            for f in facts
        ):
            return event
    raise AssertionError("Santander event not found")


def test_santander_dual_source_reconciliation(repo_root, real_run):
    event = _san_event(real_run)
    # CNMV + IR enlazados por adjudicacion humana registrada.
    assert len(event["candidate_ids"]) == 2
    assert len(event["revisions"]) == 1  # no es revision
    assert event["conflict_count"] == 0  # acuerdo, no conflicto


def test_santander_same_amount_from_both_sources(repo_root, real_run):
    event = _san_event(real_run)
    amounts = [
        f
        for f in real_run["body"]["facts"]
        if f["event_id"] == event["canonical_event_id"]
        and f["field_path"] == "amount.gross_per_share"
    ]
    assert len(amounts) == 2
    assert {a["source_id"] for a in amounts} == {"CNMV", "ISSUER_IR"}
    # Ambos normalizan a 0,1250 EUR (centimos -> EUR, escala
    # preservada, etiquetado derivado).
    assert {a["value"]["normalized"] for a in amounts} == {"0.1250"}
    assert all(a["evidence_mode"] == "DERIVED_BY_DEFINITION" for a in amounts)


def test_santander_cnmv_supplements_dates(repo_root, real_run):
    event = _san_event(real_run)
    facts = {
        f["field_path"]: f
        for f in real_run["body"]["facts"]
        if f["event_id"] == event["canonical_event_id"]
    }
    assert facts["date.payment_date"]["value"] == "2026-05-05"
    assert facts["date.ex_date"]["value"] == "2026-04-30"
    assert facts["date.record_date"]["value"] == "2026-05-04"
    # Ex/record sin anio en la fuente: derivadas y etiquetadas.
    assert facts["date.payment_date"]["evidence_mode"] == "EXPLICIT"
    assert facts["date.ex_date"]["evidence_mode"] == "DERIVED_BY_DEFINITION"
    assert facts["date.record_date"]["evidence_mode"] == "DERIVED_BY_DEFINITION"


def test_santander_manual_adjudication_is_recorded(repo_root, real_run):
    relations = real_run["body"]["identity"]["ledger"]["relations"]
    manual = [r for r in relations if r["decision_basis"] == "MANUAL_ADJUDICATION"]
    assert len(manual) == 1
    assert manual[0]["relation"] == "SAME_CORPORATE_ACTION"
    assert manual[0]["reviewer"] and manual[0]["reviewed_at"]
