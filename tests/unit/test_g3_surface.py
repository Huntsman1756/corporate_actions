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


@pytest.mark.parametrize("artifact", ["canon", "policy"])
@pytest.mark.parametrize("invalid_json", [
    '{"events": [], "sources": {}, "metadata": {"value": 1, "value": 2}}',
    '{"events": [], "sources": {}, "metadata": {"value": 0.5}}',
    '{"events": [], "sources": {}, "metadata": {"value": NaN}}',
    '{"events": [], "sources": {}, "metadata": {"value": Infinity}}',
    '{"events": [], "sources": {}, "metadata": {"value": -Infinity}}',
    '[]',
    'null',
])
def test_load_surface_rejects_invalid_artifact_json(
    tmp_path, artifact, invalid_json
):
    canon_path = tmp_path / "canon.json"
    policy_path = tmp_path / "policy.json"
    canon_path.write_text('{"events": []}', encoding="utf-8")
    policy_path.write_text('{"sources": {}}', encoding="utf-8")
    target = canon_path if artifact == "canon" else policy_path
    target.write_text(invalid_json, encoding="utf-8")
    with pytest.raises(ValueError):
        load_surface(canon_path, policy_path)


def test_load_surface_accepts_canonical_json_types(tmp_path):
    canon = {"events": [], "metadata": {
        "amount": "0.50", "count": 1, "enabled": True, "absent": None}}
    policy = {"sources": {}}
    canon_path = tmp_path / "canon.json"
    policy_path = tmp_path / "policy.json"
    canon_path.write_text(json.dumps(canon), encoding="utf-8")
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    loaded = load_surface(canon_path, policy_path)
    assert loaded.canon == canon
    assert loaded.policy == policy


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


# --------------------------------------------------------------------- P1

def test_brief_structure(surface):
    brief = surface.brief("2026-07-15")
    assert brief["brief_version"] == "CA_ES_MORNING_BRIEF_V1"
    assert brief["summary"]["events"] == 7
    assert brief["summary"]["unsupported_items"] == 1
    assert brief["summary"]["conflicting_events"] == 2
    assert brief["summary"]["revised_events"] == 1


def test_brief_action_required_window(surface):
    brief = surface.brief("2026-07-15")
    items = {(i["field_path"], i["date"]) for i in brief["action_required"]}
    assert ("date.ex_date", "2026-07-20") in items
    assert ("date.payment_date", "2026-07-22") in items
    # fuera de ventana no aparece
    narrow = surface.brief("2026-07-15", window_days=3)
    assert not narrow["action_required"]
    # antes de la ventana: as_of posterior a las fechas -> nada
    late = surface.brief("2026-08-01")
    assert not late["action_required"]


def test_brief_items_carry_evidence(surface):
    brief = surface.brief("2026-07-15")
    for section in ("action_required", "recent_changes", "conflicts"):
        for item in brief[section]:
            assert item["canonical_event_id"]
    for item in brief["action_required"]:
        assert item["assertion_id"] and item["evidence_locator"]


def test_brief_recent_changes_diff(surface):
    brief = surface.brief("2026-07-15")
    mfe = next(
        i for i in brief["recent_changes"] if i["canonical_event_id"] == MFE
    )
    assert mfe["latest_generation"] == 1
    assert mfe["changes"]["date.ex_date"]["previous_values"] == ["2026-07-27"]
    assert mfe["changes"]["date.ex_date"]["values"] == ["2026-07-20"]
    assert "amount.gross_per_share" in mfe["carried_forward"]


def test_brief_unsupported_and_conflicts_honest(surface):
    brief = surface.brief("2026-07-15")
    poex_unsup = [
        i for i in brief["unsupported"] if i["canonical_event_id"] == POEX
    ]
    assert poex_unsup[0]["field_path"] == "amount.issue_price_per_share"
    assert poex_unsup[0]["status"] == "UNSUPPORTED"
    almirall_conflict = [
        i for i in brief["conflicts"] if i["canonical_event_id"] == ALMIRALL
    ]
    assert set(almirall_conflict[0]["values"]) == {
        '"2023-06-12"', '"2023-06-13"',
    }


def test_brief_deterministic(surface):
    a = surface.brief("2026-07-15")
    b = load_surface(CANON, POLICY).brief("2026-07-15")
    from ca_es.canonical import canonical_json
    assert canonical_json(a) == canonical_json(b)


def test_brief_render_deterministic(surface):
    from ca_es.surface import render_brief
    a = render_brief(surface.brief("2026-07-15"))
    b = render_brief(load_surface(CANON, POLICY).brief("2026-07-15"))
    assert a == b
    assert "ACTION REQUIRED" in a and "UNSUPPORTED" in a


# ------------------------------------------------------------------- P1.1

def _surface_of(canon_dict):
    return Surface(
        canon_dict, json.loads(POLICY.read_text(encoding="utf-8"))
    )


def _canon_copy():
    return json.loads(CANON.read_text(encoding="utf-8"))



def test_delta_identical_snapshots_empty(surface):
    previous = _surface_of(_canon_copy())
    assert surface.delta(previous) == []
    brief = surface.brief("2026-07-15", previous=previous)
    assert brief["new_since_previous"] == []
    assert brief["summary"]["new_since_previous"] == 0


def test_delta_new_event_no_cascade(surface):
    previous_canon = _canon_copy()
    previous_canon["events"] = [
        e for e in previous_canon["events"]
        if e["canonical_event_id"] != "03888619-246f-58da-850b-1f715ad1008e"
    ]
    delta = surface.delta(_surface_of(previous_canon))
    assert [i["kind"] for i in delta] == ["NEW_EVENT"]
    assert delta[0]["canonical_event_id"].startswith("03888619")


def test_delta_changed_assertion_before_after(surface):
    previous_canon = _canon_copy()
    mfe = next(
        e for e in previous_canon["events"] if e["canonical_event_id"] == MFE
    )
    target = next(
        f for f in mfe["facts"]
        if f["field_path"] == "date.ex_date" and f["value"] == "2026-07-20"
    )
    target["value"] = "2026-07-19"
    delta = surface.delta(_surface_of(previous_canon))
    assert [i["kind"] for i in delta] == ["CHANGED_ASSERTION"]
    item = delta[0]
    assert item["field_path"] == "date.ex_date"
    assert item["previous_value"] == "2026-07-19"
    assert item["value"] == "2026-07-20"
    assert item["assertion_id"] and item["previous_assertion_id"]
    assert item["evidence_locator"] and item["previous_evidence_locator"]


def test_delta_provenance_only_change_silent(surface):
    previous_canon = _canon_copy()
    for event in previous_canon["events"]:
        for fact in event["facts"]:
            fact["evidence_locator"] = "LOCATOR-DIFFERENT"
            fact["raw_pointer"] = "/different/pointer"
            fact["assertion_id"] = "00000000-0000-0000-0000-000000000000"
    assert surface.delta(_surface_of(previous_canon)) == []


def test_delta_conflict_new_and_resolved(surface):
    previous_canon = _canon_copy()
    almirall = next(
        e for e in previous_canon["events"]
        if e["canonical_event_id"] == ALMIRALL
    )
    almirall["conflicts"] = []
    delta = surface.delta(_surface_of(previous_canon))
    assert any(
        i["kind"] == "NEW_CONFLICT"
        and i["field_path"] == "date.announcement_date"
        and set(i["values"]) == {'"2023-06-12"', '"2023-06-13"'}
        for i in delta
    )
    reverse = _surface_of(previous_canon).delta(surface)
    assert any(
        i["kind"] == "RESOLVED_CONFLICT"
        and i["field_path"] == "date.announcement_date"
        for i in reverse
    )


def test_delta_removed_event_no_cascade(surface):
    # Almirall tiene conflicto: al desaparecer el evento, su conflicto
    # no debe emitir RESOLVED_CONFLICT (cascada cubierta por REMOVED_EVENT)
    current_canon = _canon_copy()
    current_canon["events"] = [
        e for e in current_canon["events"]
        if e["canonical_event_id"] != ALMIRALL
    ]
    delta = _surface_of(current_canon).delta(surface)
    assert [i["kind"] for i in delta] == ["REMOVED_EVENT"]
    assert delta[0]["canonical_event_id"] == ALMIRALL


def test_delta_removed_assertion(surface):
    current_canon = _canon_copy()
    mfe = next(
        e for e in current_canon["events"] if e["canonical_event_id"] == MFE
    )
    removed = next(
        f for f in mfe["facts"]
        if f["field_path"] == "date.ex_date" and f["value"] == "2026-07-20"
    )
    mfe["facts"] = [f for f in mfe["facts"] if f is not removed]
    delta = _surface_of(current_canon).delta(surface)
    assert [i["kind"] for i in delta] == ["REMOVED_ASSERTION"]
    item = delta[0]
    assert item["field_path"] == "date.ex_date"
    assert item["previous_value"] == "2026-07-20"
    assert item["previous_assertion_id"] == removed["assertion_id"]
    assert item["previous_evidence_locator"]


def test_delta_supported_now(surface):
    # SUPPORTED_NOW = el evento sigue existiendo pero la capacidad
    # deja de estar unsupported (aparece una afirmacion para el field)
    current_canon = _canon_copy()
    poex = next(
        e for e in current_canon["events"]
        if e["canonical_event_id"] == POEX
    )
    new_fact = dict(poex["facts"][0])
    new_fact["field_path"] = "amount.issue_price_per_share"
    new_fact["value"] = {
        "__financial__": True, "normalized": "1.58",
        "currency": "EUR", "raw_lexeme": "1,58", "scale": 2,
    }
    poex["facts"].append(new_fact)
    delta = _surface_of(current_canon).delta(surface)
    assert any(
        i["kind"] == "SUPPORTED_NOW"
        and i["field_path"] == "amount.issue_price_per_share"
        for i in delta
    )


def test_delta_no_snapshot_mutation(surface):
    before_cur = _canon_copy()
    before_prev = _canon_copy()
    prev_canon = _canon_copy()
    prev_canon["events"][0]["facts"][0]["value"] = "MUTATED"
    _surface_of(json.loads(CANON.read_text(encoding="utf-8"))).delta(
        _surface_of(prev_canon)
    )
    assert _canon_copy() == before_cur
    assert prev_canon[  # previous tampoco mutado
        "events"
    ][0]["facts"][0]["value"] == "MUTATED"


def test_delta_deterministic_and_render(surface):
    previous = _surface_of(_canon_copy())
    from ca_es.canonical import canonical_json
    a = canonical_json(surface.brief("2026-07-15", previous=previous))
    b = canonical_json(
        load_surface(CANON, POLICY).brief("2026-07-15", previous=previous)
    )
    assert a == b
    from ca_es.surface import render_brief
    text = render_brief(
        surface.brief("2026-07-15", previous=previous)
    )
    assert "NEW SINCE PREVIOUS" in text
