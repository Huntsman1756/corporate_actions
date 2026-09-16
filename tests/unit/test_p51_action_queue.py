"""P5.1 — CA_ES_ACTION_QUEUE_V1 + CA_ES_MORNING_BRIEF_V2.

La cola consume deadlines (P5.0), nunca date.* del canon por
proximidad. Umbrales explicitos; INDETERMINATE aparte; SOURCE y
DERIVED coexisten. Brief V1 intacto.
"""

import json
from pathlib import Path

import pytest

from ca_es.action_queue import (
    DUE_SOON,
    DUE_TODAY,
    OVERDUE,
    QUEUE_SCHEMA,
    UPCOMING,
    build_action_queue,
)
from ca_es.deadlines import compute_deadlines
from ca_es.desk import build_desk_model, detail_lines
from ca_es.surface import load_surface

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "g3" / "input" / "canon.json"
POLICY = ROOT / "docs" / "sources" / "source-policy.json"

NOW = "2026-09-16T00:00:00Z"
AS_OF = "2026-07-06"  # lunes


def _dl(eid, dtype, date_, status="DERIVED", rule="R1", cal="TARGET2"):
    return {
        "deadline_key": f"{eid}|{dtype}|{rule or 'SOURCE'}",
        "canonical_event_id": eid,
        "deadline_type": dtype,
        "deadline_date": date_,
        "derivation_status": status,
        "source_date": "2026-07-10",
        "rule_id": rule,
        "calendar_id": cal,
        "business_days_offset": -1 if rule else None,
        "reasons": [] if status != "INDETERMINATE" else ["UNKNOWN_CALENDAR"],
        "assertion_ids": ["a1"],
        "evidence": [{"field_path": "date.payment_date",
                      "value": "2026-07-10", "assertion_ids": ["a1"]}],
    }


def _queue(*deadlines, as_of=AS_OF, window=7, soon=2):
    return build_action_queue(
        {"schema": "CA_ES_OPERATIONAL_DEADLINE_V1",
         "deadlines": list(deadlines)},
        as_of, window_days=window, due_soon_days=soon, now=NOW)


def test_overdue_always_visible():
    q = _queue(_dl("E1", "T", "2026-07-01"))
    assert q["schema"] == QUEUE_SCHEMA
    assert q["items"][0]["action_status"] == OVERDUE
    assert q["items"][0]["days_until"] == -5


def test_overdue_far_past_still_visible():
    q = _queue(_dl("E1", "T", "2020-01-01"))
    assert q["items"][0]["action_status"] == OVERDUE


def test_due_today():
    q = _queue(_dl("E1", "T", AS_OF))
    i = q["items"][0]
    assert i["action_status"] == DUE_TODAY and i["days_until"] == 0


def test_due_soon_threshold():
    q = _queue(_dl("E1", "T", "2026-07-08"))  # +2d, soon=2
    assert q["items"][0]["action_status"] == DUE_SOON
    q = _queue(_dl("E1", "T", "2026-07-09"))  # +3d > soon
    assert q["items"][0]["action_status"] == UPCOMING


def test_upcoming_within_window_only():
    q = _queue(_dl("E1", "T", "2026-07-13"))  # +7d = window
    assert q["items"][0]["action_status"] == UPCOMING
    q = _queue(_dl("E1", "T", "2026-07-14"))  # +8d fuera
    assert q["items"] == []


def test_indeterminate_preserved_apart():
    q = _queue(_dl("E1", "T", None, status="INDETERMINATE"))
    assert q["items"] == []
    assert len(q["indeterminate"]) == 1
    assert q["indeterminate"][0]["reasons"] == ["UNKNOWN_CALENDAR"]


def test_source_and_derived_same_type_coexist():
    q = _queue(
        _dl("E1", "T", "2026-07-08", status="SOURCE", rule=None,
            cal=None),
        _dl("E1", "T", "2026-07-09", status="DERIVED"),
    )
    types = {(i["derivation_status"], i["deadline_type"])
             for i in q["items"]}
    assert types == {("SOURCE", "T"), ("DERIVED", "T")}


def test_deterministic_order():
    ds = [
        _dl("E2", "B", "2026-07-09"),
        _dl("E1", "A", "2026-07-01"),   # overdue
        _dl("E1", "A", AS_OF),         # today
        _dl("E3", "C", "2026-07-07"),  # soon
    ]
    q = _queue(*ds)
    order = [(i["action_status"], i["deadline_date"],
              i["canonical_event_id"]) for i in q["items"]]
    assert order == [
        (OVERDUE, "2026-07-01", "E1"),
        (DUE_TODAY, AS_OF, "E1"),
        (DUE_SOON, "2026-07-07", "E3"),
        (UPCOMING, "2026-07-09", "E2"),
    ]
    again = _queue(*ds)
    assert json.dumps(q, sort_keys=True) == json.dumps(
        again, sort_keys=True)


def test_item_fields_complete():
    q = _queue(_dl("E1", "T", "2026-07-08"))
    i = q["items"][0]
    for key in ("deadline_key", "canonical_event_id", "deadline_type",
                "deadline_date", "derivation_status", "days_until",
                "action_status", "rule_id", "calendar_id",
                "assertion_ids", "evidence"):
        assert key in i


@pytest.fixture
def surface():
    return load_surface(CANON, POLICY)


def _rules_cals():
    rules = {"rules": [{"rule_id": "R1",
                        "deadline_type": "RESPONSE_DEADLINE",
                        "source_field": "date.payment_date",
                        "business_days_offset": -1,
                        "calendar_id": "TARGET2"}]}
    cals = {"calendars": [{"calendar_id": "TARGET2",
                           "business_week": [0, 1, 2, 3, 4],
                           "holidays": []}]}
    return rules, cals


def test_v1_brief_intact(surface):
    brief = surface.brief("2026-07-06", window_days=7)
    assert brief["brief_version"] == "CA_ES_MORNING_BRIEF_V1"
    # V1: cualquier date.* vigente en ventana cuenta como accionable
    assert all(i["field_path"].startswith("date.")
               for i in brief["action_required"])
    assert "indeterminate_deadlines" not in brief


def test_v2_action_required_is_queue_not_proximity(surface):
    canon = json.loads(CANON.read_text(encoding="utf-8"))
    rules, cals = _rules_cals()
    deadlines = compute_deadlines(canon, rules, cals, now=NOW)
    queue = build_action_queue(
        deadlines, "2026-07-06", window_days=7, due_soon_days=2,
        now=NOW)

    v1 = surface.brief("2026-07-06", window_days=7)
    v2 = surface.brief_v2("2026-07-06", queue)

    assert v2["brief_version"] == "CA_ES_MORNING_BRIEF_V2"
    # V2 action_required == queue items (deadlines), no date.*
    assert len(v2["action_required"]) == len(queue["items"])
    assert all("action_status" in i for i in v2["action_required"])
    assert all("deadline_type" in i for i in v2["action_required"])
    # V1 lista mas cosas por mera proximidad de date.*
    assert len(v1["action_required"]) >= len(v2["action_required"])
    # secciones V1 reutilizadas intactas
    assert v2["conflicts"] == v1["conflicts"]
    assert v2["recent_changes"] == v1["recent_changes"]
    assert v2["unsupported"] == v1["unsupported"]
    # enriquecimiento desk
    assert all("issuer_name" in i for i in v2["action_required"])
    assert "indeterminate_deadlines" in v2


def test_desk_consumes_v2_without_recomputing(surface):
    canon = json.loads(CANON.read_text(encoding="utf-8"))
    rules, cals = _rules_cals()
    deadlines = compute_deadlines(canon, rules, cals, now=NOW)
    queue = build_action_queue(
        deadlines, "2026-07-06", window_days=7, due_soon_days=2,
        now=NOW)
    v2 = surface.brief_v2("2026-07-06", queue)

    model = build_desk_model(v2)
    keys = [s["key"] for s in model["sections"]]
    assert "action_required" in keys
    assert "indeterminate_deadlines" in keys
    action = model["sections"][0]
    assert len(action["items"]) == len(queue["items"])
    lines = detail_lines("action_required",
                         action["items"][0]["item"])
    assert any("Deadline" in l for l in lines)
    # item del desk referencia exactamente el item del brief
    assert action["items"][0]["item"] is v2["action_required"][0]
