"""P5.0 — CA_ES_OPERATIONAL_DEADLINE_V1.

Regla + calendario explicitos; sin calendar_id valido -> INDETERMINATE,
nunca Mon-Fri por defecto. Canon read-only.
"""

import copy
import json

from ca_es.deadlines import (
    DEADLINE_SCHEMA,
    DERIVED,
    INDETERMINATE,
    SOURCE,
    compute_deadlines,
)

NOW = "2026-09-16T00:00:00Z"


def _fact(path, value, rev="r1", aid="a1"):
    return {"field_path": path, "value": value,
            "revision_id": rev, "assertion_id": aid}


def _event(eid="E1", facts=None, etype="CASH_DIVIDEND"):
    return {"canonical_event_id": eid, "event_type": etype,
            "facts": facts or [], "conflicts": []}


def _canon(*events):
    return {"canon_version": "CA_ES_OPERATIONAL_CANON_V1",
            "events": list(events)}


def _rule(rid="R1", source="date.payment_date", offset=-1,
          cal="TARGET2", etypes=None):
    r = {"rule_id": rid, "deadline_type": "RESPONSE_DEADLINE",
         "source_field": source, "business_days_offset": offset,
         "calendar_id": cal}
    if etypes is not None:
        r["event_types"] = etypes
    return r


RULES = {"schema": "CA_ES_DEADLINE_RULES_V1", "rules": [_rule()]}
CALS = {"schema": "CA_ES_CALENDARS_V1",
        "calendars": [{"calendar_id": "TARGET2",
                       "business_week": [0, 1, 2, 3, 4],
                       "holidays": ["2026-07-09"]}]}


def _one(doc, dtype="RESPONSE_DEADLINE"):
    return [d for d in doc["deadlines"] if d["deadline_type"] == dtype]


def test_source_deadline_from_canon_fact():
    ev = _event(facts=[_fact("deadline.market_cutoff", "2026-07-09")])
    doc = compute_deadlines(_canon(ev), {"rules": []}, {"calendars": []},
                            now=NOW)
    assert doc["schema"] == DEADLINE_SCHEMA
    d = _one(doc, "market_cutoff")[0]
    assert d["derivation_status"] == SOURCE
    assert d["deadline_date"] == "2026-07-09"
    assert d["rule_id"] is None and d["calendar_id"] is None
    assert d["assertion_ids"] == ["a1"]
    assert d["evidence"][0]["field_path"] == "deadline.market_cutoff"


def test_derived_business_day_offset_skips_holiday():
    # 2026-07-10 es viernes; -1 habil salta el festivo 2026-07-09 -> 07-08
    ev = _event(facts=[_fact("date.payment_date", "2026-07-10")])
    doc = compute_deadlines(_canon(ev), RULES, CALS, now=NOW)
    d = _one(doc)[0]
    assert d["derivation_status"] == DERIVED
    assert d["source_date"] == "2026-07-10"
    assert d["deadline_date"] == "2026-07-08"
    assert d["rule_id"] == "R1" and d["calendar_id"] == "TARGET2"


def test_derived_offset_skips_weekend():
    # lunes 2026-07-13, -1 habil -> viernes 2026-07-10
    ev = _event(facts=[_fact("date.payment_date", "2026-07-13")])
    doc = compute_deadlines(_canon(ev), RULES, CALS, now=NOW)
    assert _one(doc)[0]["deadline_date"] == "2026-07-10"


def test_offset_zero_returns_source_date():
    rules = {"rules": [_rule(offset=0)]}
    ev = _event(facts=[_fact("date.payment_date", "2026-07-10")])
    doc = compute_deadlines(_canon(ev), rules, CALS, now=NOW)
    d = _one(doc)[0]
    assert d["derivation_status"] == DERIVED
    assert d["deadline_date"] == "2026-07-10"


def test_unknown_calendar_indeterminate_never_default():
    rules = {"rules": [_rule(cal="NO_EXISTE")]}
    ev = _event(facts=[_fact("date.payment_date", "2026-07-10")])
    doc = compute_deadlines(_canon(ev), rules, CALS, now=NOW)
    d = _one(doc)[0]
    assert d["derivation_status"] == INDETERMINATE
    assert d["reasons"] == ["UNKNOWN_CALENDAR"]
    assert d["deadline_date"] is None


def test_missing_source_date():
    doc = compute_deadlines(_canon(_event()), RULES, CALS, now=NOW)
    d = _one(doc)[0]
    assert d["derivation_status"] == INDETERMINATE
    assert d["reasons"] == ["MISSING_SOURCE_DATE"]


def test_conflicting_source_date():
    ev = _event(facts=[
        _fact("date.payment_date", "2026-07-10", aid="a1"),
        _fact("date.payment_date", "2026-07-11", aid="a2"),
    ])
    doc = compute_deadlines(_canon(ev), RULES, CALS, now=NOW)
    d = _one(doc)[0]
    assert d["derivation_status"] == INDETERMINATE
    assert d["reasons"] == ["CONFLICTING_SOURCE_DATE"]
    assert sorted(d["assertion_ids"]) == ["a1", "a2"]


def test_invalid_source_date():
    ev = _event(facts=[_fact("date.payment_date", "no-es-fecha")])
    doc = compute_deadlines(_canon(ev), RULES, CALS, now=NOW)
    assert _one(doc)[0]["reasons"] == ["INVALID_SOURCE_DATE"]


def test_no_rule_no_deadline():
    ev = _event(facts=[_fact("date.payment_date", "2026-07-10")])
    doc = compute_deadlines(_canon(ev), {"rules": []}, CALS, now=NOW)
    assert doc["deadlines"] == []


def test_event_type_filter():
    rules = {"rules": [_rule(etypes=["RIGHTS_ISSUE"])]}
    ev = _event(facts=[_fact("date.payment_date", "2026-07-10")],
                etype="CASH_DIVIDEND")
    doc = compute_deadlines(_canon(ev), rules, CALS, now=NOW)
    assert doc["deadlines"] == []


def test_event_id_filter():
    ev1 = _event("E1", [_fact("date.payment_date", "2026-07-10")])
    ev2 = _event("E2", [_fact("date.payment_date", "2026-07-10")])
    doc = compute_deadlines(_canon(ev1, ev2), RULES, CALS,
                            event_id="E2", now=NOW)
    assert [d["canonical_event_id"] for d in doc["deadlines"]] == ["E2"]


def test_source_and_derived_coexist_no_winner():
    ev = _event(facts=[
        _fact("deadline.RESPONSE_DEADLINE", "2026-07-06"),
        _fact("date.payment_date", "2026-07-10"),
    ])
    doc = compute_deadlines(_canon(ev), RULES, CALS, now=NOW)
    ds = _one(doc)
    assert len(ds) == 2
    statuses = sorted(d["derivation_status"] for d in ds)
    assert statuses == [DERIVED, SOURCE]


def test_deterministic_and_canon_untouched():
    canon = _canon(_event(facts=[
        _fact("date.payment_date", "2026-07-10")]))
    before = copy.deepcopy(canon)
    a = compute_deadlines(canon, RULES, CALS, now=NOW)
    b = compute_deadlines(canon, RULES, CALS, now=NOW)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert canon == before
