"""P5.0 — CA_ES_OPERATIONAL_DEADLINE_V1.

Regla + calendario explicitos; sin calendar_id valido -> INDETERMINATE,
nunca Mon-Fri por defecto. Canon read-only.
"""

import copy
import json

import pytest

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


@pytest.mark.parametrize("offset", [0.5, -1.5, 1.0, True, False, "-1", None])
def test_invalid_offset_rejected_without_mutation(offset):
    canon = _canon(_event(facts=[
        _fact("date.payment_date", "2026-07-10")]))
    rules = {"rules": [_rule(offset=offset)]}
    before = copy.deepcopy((canon, rules, CALS))
    with pytest.raises(ValueError, match="INVALID_BUSINESS_DAYS_OFFSET"):
        compute_deadlines(canon, rules, CALS, now=NOW)
    assert (canon, rules, CALS) == before


def test_missing_offset_rejected_even_without_events():
    rule = _rule()
    del rule["business_days_offset"]
    with pytest.raises(ValueError, match="INVALID_BUSINESS_DAYS_OFFSET"):
        compute_deadlines(_canon(), {"rules": [rule]}, CALS, now=NOW)


def test_positive_offset_uses_declared_calendar():
    canon = _canon(_event(facts=[
        _fact("date.payment_date", "2026-07-08")]))
    doc = compute_deadlines(canon, {"rules": [_rule(offset=2)]}, CALS,
                            now=NOW)
    d = _one(doc)[0]
    assert d["derivation_status"] == DERIVED
    assert d["business_days_offset"] == 2
    assert d["deadline_date"] == "2026-07-13"


@pytest.mark.parametrize("offset", [0.5, True, False, "-1", None])
@pytest.mark.parametrize("event_id", [None, "OTHER"])
def test_invalid_offset_rejected_before_event_filters(offset, event_id):
    rules = {"rules": [_rule(offset=offset, etypes=["RIGHTS_ISSUE"])]}
    with pytest.raises(ValueError, match="INVALID_BUSINESS_DAYS_OFFSET"):
        compute_deadlines(_canon(_event()), rules, CALS,
                          event_id=event_id, now=NOW)


@pytest.mark.parametrize("week", [
    None, [], [7], [-1], [True], [False], [1.0], ["0"], [0, 7], "01234",
])
@pytest.mark.parametrize("with_event", [False, True])
def test_invalid_business_week_rejected_before_derivation(week, with_event):
    calendars = copy.deepcopy(CALS)
    calendars["calendars"][0]["business_week"] = week
    canon = _canon(_event()) if with_event else _canon()
    before = copy.deepcopy((canon, calendars))
    with pytest.raises(ValueError, match="INVALID_BUSINESS_WEEK"):
        compute_deadlines(canon, RULES, calendars, now=NOW)
    assert (canon, calendars) == before


@pytest.mark.parametrize("field, reason", [
    ("business_week", "INVALID_BUSINESS_WEEK"),
    ("holidays", "INVALID_HOLIDAYS"),
    ("calendar_id", "INVALID_CALENDAR_ID"),
])
def test_missing_calendar_fields_rejected(field, reason):
    calendars = copy.deepcopy(CALS)
    del calendars["calendars"][0][field]
    with pytest.raises(ValueError, match=reason):
        compute_deadlines(_canon(), RULES, calendars, now=NOW)


@pytest.mark.parametrize("cal_id", [None, "", "   ", 1, True, []])
@pytest.mark.parametrize("in_rule", [False, True])
def test_invalid_calendar_id_rejected(cal_id, in_rule):
    rules, calendars = copy.deepcopy((RULES, CALS))
    entry = rules["rules"][0] if in_rule else calendars["calendars"][0]
    entry["calendar_id"] = cal_id
    with pytest.raises(ValueError, match="INVALID_CALENDAR_ID"):
        compute_deadlines(_canon(), rules, calendars, now=NOW)


@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_calendar_ids_rejected_without_mutation(reverse):
    calendars = copy.deepcopy(CALS)
    duplicate = copy.deepcopy(calendars["calendars"][0])
    duplicate["holidays"] = []
    calendars["calendars"].append(duplicate)
    if reverse:
        calendars["calendars"].reverse()
    before = copy.deepcopy(calendars)
    with pytest.raises(ValueError, match="DUPLICATE_CALENDAR_ID"):
        compute_deadlines(_canon(), RULES, calendars, now=NOW)
    assert calendars == before


@pytest.mark.parametrize("holiday", [
    None, True, 20260709, "", "2026-02-29", "2026-13-01", "20260709",
    "2026-W28-4", "2026-07-09T00:00:00", [], {},
])
def test_invalid_holiday_date_rejected(holiday):
    calendars = copy.deepcopy(CALS)
    calendars["calendars"][0]["holidays"] = [holiday]
    with pytest.raises(ValueError, match="INVALID_HOLIDAY_DATE"):
        compute_deadlines(_canon(), RULES, calendars, now=NOW)


@pytest.mark.parametrize("holidays", [None, "2026-07-09", {}])
def test_invalid_holidays_collection_rejected(holidays):
    calendars = copy.deepcopy(CALS)
    calendars["calendars"][0]["holidays"] = holidays
    with pytest.raises(ValueError, match="INVALID_HOLIDAYS"):
        compute_deadlines(_canon(), RULES, calendars, now=NOW)


@pytest.mark.parametrize("source, offset, week, holidays", [
    ("0001-01-01", -1, [0, 1, 2, 3, 4], []),
    ("9999-12-31", 1, [0, 1, 2, 3, 4], []),
    ("9999-12-30", 1, [0], []),
    ("0001-01-02", -1, [0], ["0001-01-01"]),
    ("2026-07-10", 10 ** 100, [0, 1, 2, 3, 4], []),
    ("2026-07-10", -(10 ** 100), [0, 1, 2, 3, 4], []),
])
def test_date_overflow_is_controlled_value_error(source, offset, week,
                                                 holidays):
    canon = _canon(_event(facts=[_fact("date.payment_date", source)]))
    rules = {"rules": [_rule(offset=offset)]}
    calendars = {"calendars": [{"calendar_id": "TARGET2",
                                "business_week": week,
                                "holidays": holidays}]}
    before = copy.deepcopy((canon, rules, calendars))
    with pytest.raises(ValueError, match="DEADLINE_DATE_OVERFLOW"):
        compute_deadlines(canon, rules, calendars, now=NOW)
    assert (canon, rules, calendars) == before


@pytest.mark.parametrize("source", ["0001-01-01", "9999-12-31"])
def test_zero_offset_valid_at_date_boundaries(source):
    canon = _canon(_event(facts=[_fact("date.payment_date", source)]))
    doc = compute_deadlines(canon, {"rules": [_rule(offset=0)]}, CALS,
                            now=NOW)
    assert _one(doc)[0]["deadline_date"] == source


def test_nonstandard_business_week_and_leap_day_holiday():
    calendars = {"calendars": [{"calendar_id": "CUSTOM",
                                "business_week": [3, 6],
                                "holidays": ["2024-02-29"]}]}
    canon = _canon(_event(facts=[
        _fact("date.payment_date", "2024-02-28")]))
    doc = compute_deadlines(canon, {"rules": [_rule(offset=1, cal="CUSTOM")]},
                            calendars, now=NOW)
    assert _one(doc)[0]["deadline_date"] == "2024-03-03"


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
