# -*- coding: utf-8 -*-
"""Tests G2: canon operacional, manifest sellado y control SAN."""
import hashlib
import json
from pathlib import Path

import pytest

from ca_es.export import (
    canon_bytes,
    canon_payload,
    logical_sha256,
    operational_canon,
)
from ca_es.namespaces import candidate_event_id
from ca_es.pipeline import run_pipeline
from ca_es.reference.esma_firds import load_firds_listings

REPO = Path(__file__).resolve().parents[2]
MANIFEST = "g2/manifests/qualification-corpus.json"
PREREG = "docs/gates/g2-preregistered.json"
ADJUDICATIONS = "g0/manifests/adjudications-real.json"
BINDINGS = "g0/corpus/reference/portfolio-instruments.json"
FIRDS = REPO / "g0/corpus/reference/esma-firds-listings-real.json"
CORPUS_ID = "CA_ES_G2_QUALIFICATION_V1"


def _run(adjudications=None, run_id="t"):
    resolver = load_firds_listings(FIRDS) if FIRDS.exists() else None
    return run_pipeline(
        REPO,
        manifest_relpath=MANIFEST,
        adjudications_relpath=adjudications,
        instrument_bindings_relpath=BINDINGS,
        resolver=resolver,
        run_id=run_id,
        executed_at="2026-09-16T00:00:00Z",
    )


def _minimal_body(**overrides):
    body = {
        "documents": [],
        "identity": {"resolutions": [], "ledger": {"relations": []}},
        "facts": [],
        "conflicts": [],
        "events": [],
    }
    body.update(overrides)
    return body


def test_canon_excludes_runtime_metadata():
    canon = operational_canon(_minimal_body(), CORPUS_ID)
    assert "run_id" not in canon
    assert "executed_at" not in canon
    assert "metadata" not in canon
    assert canon["canon_version"] == "CA_ES_OPERATIONAL_CANON_V1"
    assert canon["corpus_id"] == CORPUS_ID


def _fact(field, rev, src, assertion, value="x"):
    return {
        "assertion_id": assertion,
        "event_id": "E1",
        "revision_id": rev,
        "field_path": field,
        "value": value,
        "evidence_locator": "el",
        "raw_pointer": "/rp",
        "asserted_as_of": "2026-01-01",
        "date_kind": "EXPLICIT",
        "fact_origin": "SOURCE_ASSERTION",
        "evidence_mode": "EXPLICIT",
        "source_document_id": src,
        "source_id": "CNMV",
        "is_current": True,
    }


def _event_fixture():
    return {
        "canonical_event_id": "E1",
        "event_type": "CASH_DIVIDEND",
        "event_type_status": "ACTIVE",
        "issuer_name": None,
        "lei": None,
        "isin": "ES0000000000",
        "instrument_binding": None,
        "revisions": [
            {"revision_id": "r1", "canonical_event_id": "E1",
             "generation": 0, "document_ids": ["d"], "candidate_ids": ["c"],
             "supersedes_revision_id": None, "evidence": []},
        ],
        "temporal": {},
        "candidate_ids": ["c"],
        "event_type_evidence_locator": None,
    }


def _body_with_event(facts):
    return _minimal_body(
        documents=[
            {"document_id": "d", "source_id": "CNMV",
             "official_document_id": "O1",
             "content_sha256": "0" * 64, "publication_date": "2026-01-01"},
        ],
        events=[_event_fixture()],
        facts=list(facts),
    )


def test_facts_sorted_by_total_order():
    facts = [
        _fact("b.f", "r1", "D2", "a2"),
        _fact("a.f", "r1", "D2", "a1"),
        _fact("a.f", "r1", "D1", "a0"),
    ]
    canon = operational_canon(_body_with_event(facts), CORPUS_ID)
    order = [
        (f["field_path"], f["revision_id"], f["source_document_id"],
         f["assertion_id"])
        for f in canon["events"][0]["facts"]
    ]
    assert order == sorted(order)
    assert [f["assertion_id"] for f in canon["events"][0]["facts"]] == [
        "a0", "a1", "a2",
    ]


def test_canon_bytes_deterministic():
    body = _body_with_event([_fact("a", "r", "D", "x")])
    canon = operational_canon(body, CORPUS_ID)
    payload = canon_payload(canon)
    b1 = canon_bytes(payload)
    b2 = canon_bytes(
        canon_payload(
            operational_canon(json.loads(json.dumps(body)), CORPUS_ID)
        )
    )
    assert b1 == b2
    assert payload["logical_sha256"] == logical_sha256(canon)
    assert payload["logical_sha256"] == hashlib.sha256(
        canon_bytes(canon)
    ).hexdigest()


@pytest.mark.private_corpus("g2")
def test_manifest_seals_full_sha256():
    manifest = json.loads((REPO / MANIFEST).read_text(encoding="utf-8"))
    for doc in manifest["documents"]:
        sha = doc["content_sha256"]
        assert len(sha) == 64
        raw = (REPO / doc["raw_relpath"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == sha


def test_manifest_matches_preregistration():
    manifest = json.loads((REPO / MANIFEST).read_text(encoding="utf-8"))
    prereg = json.loads((REPO / PREREG).read_text(encoding="utf-8"))
    expected = {
        d["id"]: d["content_sha256"]
        for case in prereg["qualification_corpus"]["cases"]
        for d in case["documents"]
    }
    assert len(manifest["documents"]) == len(expected) == 10
    for doc in manifest["documents"]:
        assert doc["content_sha256"] == expected[doc["official_document_id"]]


@pytest.mark.private_corpus("g2")
def test_san_no_merge_without_adjudication():
    body = _run()["body"]
    san_a = candidate_event_id("CNMV", "CNMV-SAN-DIV-2026")
    san_b = candidate_event_id("ISSUER_IR", "SAN-IR-REMUNERATION")
    events = {
        r["candidate_id"]: r["canonical_event_id"]
        for r in body["identity"]["resolutions"]
    }
    assert events[san_a] != events[san_b]
    assert not any(
        {r["a"], r["b"]} == {san_a, san_b}
        for r in body["identity"]["ledger"]["relations"]
    )


@pytest.mark.private_corpus("g2")
def test_san_manual_merge_with_adjudication():
    body = _run(ADJUDICATIONS)["body"]
    san_a = candidate_event_id("CNMV", "CNMV-SAN-DIV-2026")
    san_b = candidate_event_id("ISSUER_IR", "SAN-IR-REMUNERATION")
    events = {
        r["candidate_id"]: r["canonical_event_id"]
        for r in body["identity"]["resolutions"]
    }
    assert events[san_a] == events[san_b]
    assert any(
        r["decision_basis"] == "MANUAL_ADJUDICATION"
        and {r["a"], r["b"]} == {san_a, san_b}
        for r in body["identity"]["ledger"]["relations"]
    )


@pytest.mark.private_corpus("g2")
def test_portfolio_quarantine_in_corpus():
    body = _run(ADJUDICATIONS)["body"]
    canon = operational_canon(body, CORPUS_ID)
    for event in canon["events"]:
        for fact in event["facts"]:
            if fact["source_id"] == "PORTFOLIO_STOCK_EXCHANGE":
                assert fact["field_path"] != "amount.issue_price_per_share"
