# -*- coding: utf-8 -*-
"""Tests G3: superficie operacional sobre el canon sellado."""
import hashlib
import json
from pathlib import Path

import pytest

from ca_es.surface import EVENT_SCOPE, Surface, load_surface

REPO = Path(__file__).resolve().parents[2]
CANON = REPO / "g3/input/canon.json"
POLICY = REPO / "docs/sources/source-policy.json"

MFE = "59303c3c-8be7-578f-bc59-8e5e43a1fdf3"
ALMIRALL = "035e32ca-ba61-5105-8756-e0234e5335fc"
BMEG_DIV = "6881d24a-ef46-5053-80ce-1743a1792f8b"
BMEG_CAP = "3c9270d8-76b3-5953-942c-b1f42c1cc56a"
SAN = "6443e2be-b70d-50c7-88d1-4a62f43789e9"
POEX = "e885fff1-0a3b-57d7-a2fa-f51a6e613f10"


@pytest.fixture(scope="module")
def surface() -> Surface:
    return load_surface(CANON, POLICY)


def test_input_seals():
    raw = CANON.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "c0f7dcd5d330ea69168ef90edcb207b561c237a07c5de216c140ef2147a06f0c"
    )
    payload = json.loads(raw)
    sha = payload.pop("logical_sha256")
    from ca_es.export import canon_bytes
    assert hashlib.sha256(canon_bytes(payload)).hexdigest() == sha


def test_search_isin_exact(surface):
    found = surface.search(isin="ES0105448007")
    assert [e["canonical_event_id"] for e in found] == [BMEG_DIV]
    assert not surface.search(isin="ES0105448006")


def test_search_type_and_issuer(surface):
    divs = surface.search(event_type="CASH_DIVIDEND")
    assert len(divs) == 3
    ids = [e["canonical_event_id"] for e in divs]
    assert ids == sorted(ids)
    advero = surface.search(issuer="advero")
    assert [e["canonical_event_id"] for e in advero] == [BMEG_DIV]


def test_current_state_mfe(surface):
    state = surface._current_state(surface._events[MFE])
    gross = state["amount.gross_per_share"]
    assert gross["status"] == "CURRENT"
    assert gross["values"][0]["value"]["normalized"] == "0.22"
    assert gross["origin_generation"] == 0
    for field, expected in [
        ("date.ex_date", "2026-07-20"),
        ("date.record_date", "2026-07-21"),
        ("date.payment_date", "2026-07-22"),
    ]:
        assert state[field]["values"][0]["value"] == expected
        assert state[field]["origin_generation"] == 1


def test_current_state_conflict_no_winner(surface):
    state = surface._current_state(surface._events[ALMIRALL])
    ann = state["date.announcement_date"]
    assert ann["status"] == "CONFLICTING"
    assert {v["value"] for v in ann["values"]} == {"2023-06-12", "2023-06-13"}


def test_event_scope_facts_always_current(surface):
    event = surface._events[BMEG_CAP]
    scope = [f for f in event["facts"] if f["revision_id"] == EVENT_SCOPE]
    assert scope
    state = surface._current_state(event)
    for fact in scope:
        assert state[fact["field_path"]]["status"] == "CURRENT"
        assert state[fact["field_path"]]["origin_revision_id"] == EVENT_SCOPE


def test_timeline_mfe(surface):
    timeline = surface.timeline(MFE)
    revs = timeline["revisions"]
    assert [r["generation"] for r in revs] == [0, 1]
    assert revs[1]["supersedes_revision_id"] == revs[0]["revision_id"]
    gen1 = revs[1]["changes"]
    assert gen1["date.ex_date"]["kind"] == "CHANGED"
    assert gen1["date.ex_date"]["previous_values"] == ["2026-07-27"]
    assert gen1["date.ex_date"]["values"] == ["2026-07-20"]
    assert "amount.gross_per_share" in revs[1]["carried_forward"]


def test_unsupported_capability_honesty(surface):
    shown = surface.show(POEX)
    unsupported = shown["unsupported_capabilities"]
    assert len(unsupported) == 1
    assert unsupported[0]["field_path"] == "amount.issue_price_per_share"
    assert unsupported[0]["status"] == "UNSUPPORTED"
    # el field no aparece como CURRENT ni ausente a secas
    assert "amount.issue_price_per_share" not in shown["current_state"]


def test_evidence_chain(surface):
    event = surface._events[MFE]
    fact = event["facts"][0]
    ev = surface.evidence(fact["assertion_id"])
    assert ev["field_path"] == fact["field_path"]
    assert ev["evidence_locator"]
    assert ev["raw_pointer"]
    assert ev["source_document"]["official_document_id"].startswith("CNMV-OIR")


def test_export_fidelity(surface):
    for event in surface.canon["events"]:
        exported = surface.export_event(event["canonical_event_id"])
        assert exported == event


def test_deterministic_presentation(surface):
    from ca_es.canonical import canonical_json
    a = canonical_json(surface.show(MFE))
    b = canonical_json(load_surface(CANON, POLICY).show(MFE))
    assert a == b


def test_not_found(surface):
    assert surface.show("nonexistent") is None
    assert surface.evidence("nonexistent") is None
