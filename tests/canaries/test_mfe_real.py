from __future__ import annotations


def _mfe_event(result: dict) -> dict:
    for event in result["body"]["events"]:
        if event["event_type"] != "CASH_DIVIDEND" or len(event["revisions"]) != 2:
            continue
        facts = [
            f
            for f in result["body"]["facts"]
            if f["event_id"] == event["canonical_event_id"]
        ]
        if any(
            isinstance(f["value"], dict)
            and f["value"].get("__financial__")
            and f["value"]["normalized"] == "0.22"
            for f in facts
        ):
            return event
    raise AssertionError("MFE event not found")


def test_mfe_real_explicit_revision(repo_root, real_run):
    event = _mfe_event(real_run)
    assert len(event["revisions"]) == 2
    gen0 = next(r for r in event["revisions"] if r["generation"] == 0)
    gen1 = next(r for r in event["revisions"] if r["generation"] == 1)
    assert gen1["supersedes_revision_id"] == gen0["revision_id"]
    assert gen1["evidence"]
    assert event["candidate_ids"] == sorted(event["candidate_ids"])
    assert len(event["candidate_ids"]) == 2


def test_mfe_real_partial_modification_changes_dates_only(repo_root, real_run):
    event = _mfe_event(real_run)
    facts = [
        f
        for f in real_run["body"]["facts"]
        if f["event_id"] == event["canonical_event_id"]
    ]
    by_rev: dict[str, dict] = {}
    for fact in facts:
        by_rev.setdefault(fact["revision_id"], {})[fact["field_path"]] = fact

    gen0 = next(r for r in event["revisions"] if r["generation"] == 0)["revision_id"]
    gen1 = next(r for r in event["revisions"] if r["generation"] == 1)["revision_id"]

    # Modificacion PARCIAL: el importe (0,22) solo consta en la revision
    # original; la revision posterior cambia solo las fechas. No se
    # reescribe ni se borra la revision anterior.
    assert by_rev[gen0]["amount.gross_per_share"]["value"]["normalized"] == "0.22"
    assert "amount.gross_per_share" not in by_rev[gen1]
    assert by_rev[gen0]["date.payment_date"]["value"] == "2026-07-29"
    assert by_rev[gen1]["date.payment_date"]["value"] == "2026-07-22"
    assert by_rev[gen0]["date.ex_date"]["value"] == "2026-07-27"
    assert by_rev[gen1]["date.ex_date"]["value"] == "2026-07-20"
    # La revision anterior se conserva (no se borra).
    assert by_rev[gen0]["date.record_date"]["value"] == "2026-07-28"
    assert by_rev[gen1]["date.record_date"]["value"] == "2026-07-21"
