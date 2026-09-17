from __future__ import annotations

import pytest

from ca_es.pipeline import run_pipeline

REAL_MANIFEST = "g0/manifests/real-corpus.json"

pytestmark = pytest.mark.private_corpus("g0")


def _capital_increase(result: dict) -> tuple[dict, dict]:
    event = next(
        e for e in result["body"]["events"] if e["event_type"] == "CAPITAL_INCREASE"
    )
    facts = {
        f["field_path"]: f
        for f in result["body"]["facts"]
        if f["event_id"] == event["canonical_event_id"]
    }
    return event, facts


def test_almirall_real_cnmv_amounts_exact(repo_root):
    result = run_pipeline(repo_root, manifest_relpath=REAL_MANIFEST)
    event, facts = _capital_increase(result)
    gross = facts["amount.gross_proceeds"]["value"]
    assert gross["raw_lexeme"] == "199.999.992,6"
    assert gross["normalized"] == "199999992.6"
    assert gross["scale"] == 1
    assert facts["shares.new_shares"]["value"] == 24390243
    assert facts["shares.subscribed_by_reference_holder"]["value"] == 15559000
    # No se inventan ratios ni fechas ex/record/payment.
    assert "ratio.terms" not in facts
    for invented in ("date.ex_date", "date.record_date", "date.payment_date"):
        assert invented not in facts


def test_almirall_real_explicit_cross_reference_clusters(repo_root):
    result = run_pipeline(repo_root, manifest_relpath=REAL_MANIFEST)
    event, _ = _capital_increase(result)
    # Dos documentos CNMV (1884, 1885) enlazados por referencia oficial exacta.
    assert len(event["candidate_ids"]) == 2
    assert len(event["revisions"]) == 1  # cross-reference, no revision
    ledger = result["body"]["identity"]["ledger"]["relations"]
    assert any(
        r["relation"] == "SAME_CORPORATE_ACTION"
        and r["decision_basis"] == "DETERMINISTIC"
        and r["evidence"]
        for r in ledger
    )


def test_almirall_real_explicit_date_conflict(repo_root):
    result = run_pipeline(repo_root, manifest_relpath=REAL_MANIFEST)
    event, _ = _capital_increase(result)
    conflicts = [
        c
        for c in result["body"]["conflicts"]
        if c["event_id"] == event["canonical_event_id"]
    ]
    assert conflicts
    assert conflicts[0]["field_path"] == "date.announcement_date"
    assert len(conflicts[0]["values"]) == 2


def test_real_pipeline_is_deterministic(repo_root):
    first = run_pipeline(repo_root, manifest_relpath=REAL_MANIFEST, run_id="a")
    second = run_pipeline(
        repo_root,
        manifest_relpath=REAL_MANIFEST,
        run_id="b",
        executed_at="2026-06-06T00:00:00Z",
    )
    assert first["result_sha"] == second["result_sha"]
