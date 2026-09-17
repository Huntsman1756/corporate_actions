from __future__ import annotations

import pytest

from ca_es.pipeline import run_pipeline

REAL_MANIFEST = "g0/manifests/real-corpus.json"

pytestmark = pytest.mark.private_corpus("g0")


def _facts(result: dict, event: dict) -> dict:
    return {
        f["field_path"]: f
        for f in result["body"]["facts"]
        if f["event_id"] == event["canonical_event_id"]
    }


def _parlem_event(result: dict) -> dict:
    return next(
        e
        for e in result["body"]["events"]
        if e["event_type"] == "RIGHTS_ISSUE"
        and (e.get("issuer_name") or "").startswith("PARLEM")
    )


def test_parlem_real_borme_document(repo_root):
    result = run_pipeline(repo_root, manifest_relpath=REAL_MANIFEST)
    verification = result["body"]["verification"]
    assert verification and all(v["sha256_match"] for v in verification)
    event = _parlem_event(result)
    assert event["event_type"] == "RIGHTS_ISSUE"
    assert event["issuer_name"].startswith("PARLEM TELECOM")
    facts = _facts(result, event)

    price = facts["amount.issue_price_per_share"]["value"]
    assert price["raw_lexeme"] == "0,80"
    assert price["normalized"] == "0.80"
    assert price["scale"] == 2
    assert price["currency"] == "EUR"

    assert facts["amount.nominal_per_share"]["value"]["raw_lexeme"] == "0,01"
    assert (
        facts["amount.nominal_issue_max"]["value"]["raw_lexeme"] == "99.375,00"
    )
    assert (
        facts["amount.issue_premium_total_max"]["value"]["raw_lexeme"]
        == "7.850.625,00"
    )

    # Ratio tal como se publica: 20 nuevas por 39 antiguas (enteros exactos).
    assert facts["ratio.terms"]["value"] == {"new_shares": 20, "old_shares": 39}

    basis = facts["entitlement_basis"]
    assert basis["value"]["eligible_shares"] == 19378125
    assert basis["value"]["components"] == {
        "registered_shares": 19865753,
        "treasury_shares": 209745,
        "waived_rights_basis_shares": 277883,
    }
    assert basis["asserted_as_of"] == "2026-08-31"
    assert basis["value"]["status"] == "SUBJECT_TO_ADJUSTMENT"

    assert facts["infrastructure_role.ISSUER_CSD"]["value"] == "IBERCLEAR"
    assert facts["infrastructure_role.TRADING_VENUE"]["value"] == "BME Growth"


def test_parlem_real_dates_not_invented(repo_root):
    result = run_pipeline(repo_root, manifest_relpath=REAL_MANIFEST)
    event = _parlem_event(result)
    facts = _facts(result, event)
    # El anuncio expresa el periodo de forma relativa: no hay fechas ex/record/payment.
    for invented in ("date.ex_date", "date.record_date", "date.payment_date"):
        assert invented not in facts
    assert facts["date.announcement_date"]["value"] == "2026-09-08"


def test_parlem_real_provenance_points_to_document_fragment(repo_root):
    result = run_pipeline(repo_root, manifest_relpath=REAL_MANIFEST)
    event = _parlem_event(result)
    facts = _facts(result, event)
    locator = facts["amount.issue_price_per_share"]["evidence_locator"]
    assert "BORME-C-2026-4914" in locator
    assert "0,80" in locator
    # El raw_pointer resuelve a un fragmento exacto dentro del texto extraido.
    assert facts["amount.issue_price_per_share"]["raw_pointer"].startswith("/anchors/")
