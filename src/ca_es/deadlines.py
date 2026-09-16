"""P5.0 — Operational deadlines.

docs/p5/p50-scope.md:

    canonical event/date + regla explicita + calendario explicito
        -> CA_ES_OPERATIONAL_DEADLINE_V1

Reglas duras:

- official_date != operational_deadline; el canon nunca se muta
- derivar solo con regla preregistrada (CA_ES_DEADLINE_RULES_V1)
- calendar_id obligatorio para offsets business-day; calendario
  desconocido -> INDETERMINATE/UNKNOWN_CALENDAR, nunca Mon-Fri
  por defecto
- la cuenta business-day usa exclusivamente business_week + holidays
  declarados en CA_ES_CALENDARS_V1; sin heurísticas
- SOURCE: fact canonico deadline.<type>; DERIVED: regla+calendario;
  nunca se elige entre ambos
"""

from __future__ import annotations

from datetime import date, timedelta

from .swift_ca import _current_dates, _now

DEADLINE_SCHEMA = "CA_ES_OPERATIONAL_DEADLINE_V1"
RULES_SCHEMA = "CA_ES_DEADLINE_RULES_V1"
CALENDARS_SCHEMA = "CA_ES_CALENDARS_V1"

SOURCE = "SOURCE"
DERIVED = "DERIVED"
INDETERMINATE = "INDETERMINATE"

DEADLINE_FIELD_PREFIX = "deadline."


def _parse_iso(value):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _shift_business_days(source: date, offset: int,
                         business_week: set, holidays: set) -> date:
    """offset>0 avanza N dias habiles; offset<0 retrocede; offset==0
    devuelve la fecha fuente sin ajuste."""
    if offset == 0:
        return source
    step = 1 if offset > 0 else -1
    remaining = abs(offset)
    d = source
    while remaining:
        d += timedelta(days=step)
        if d.weekday() in business_week and d.isoformat() not in holidays:
            remaining -= 1
    return d


def _evidence(path, cur):
    return [{
        "field_path": path,
        "value": cur.get("value"),
        "assertion_ids": cur.get("assertion_ids") or [],
    }]


def _source_deadlines(event_id, current):
    """Facts canonicos deadline.<type> -> deadlines SOURCE."""
    out = []
    for path in sorted(current):
        if not path.startswith(DEADLINE_FIELD_PREFIX):
            continue
        cur = current[path]
        dtype = path[len(DEADLINE_FIELD_PREFIX):]
        base = {
            "deadline_key": f"{event_id}|{dtype}|SOURCE",
            "canonical_event_id": event_id,
            "deadline_type": dtype,
            "rule_id": None,
            "calendar_id": None,
            "business_days_offset": None,
            "assertion_ids": cur.get("assertion_ids") or [],
            "evidence": _evidence(path, cur),
        }
        if cur["status"] != "CURRENT":
            out.append({**base, "deadline_date": None,
                        "source_date": None,
                        "derivation_status": INDETERMINATE,
                        "reasons": ["CONFLICTING_SOURCE_DATE"]})
            continue
        d = _parse_iso(cur["value"])
        if d is None:
            out.append({**base, "deadline_date": None,
                        "source_date": cur["value"],
                        "derivation_status": INDETERMINATE,
                        "reasons": ["INVALID_SOURCE_DATE"]})
            continue
        out.append({**base, "deadline_date": d.isoformat(),
                    "source_date": d.isoformat(),
                    "derivation_status": SOURCE, "reasons": []})
    return out


def _derived_deadline(event_id, event_type, rule, current, calendars):
    dtype = rule["deadline_type"]
    source_field = rule["source_field"]
    offset = int(rule["business_days_offset"])
    cal_id = rule["calendar_id"]

    base = {
        "deadline_key": f"{event_id}|{dtype}|{rule['rule_id']}",
        "canonical_event_id": event_id,
        "deadline_type": dtype,
        "rule_id": rule["rule_id"],
        "calendar_id": cal_id,
        "business_days_offset": offset,
    }

    cur = current.get(source_field)
    if cur is None:
        return {**base, "deadline_date": None, "source_date": None,
                "derivation_status": INDETERMINATE,
                "reasons": ["MISSING_SOURCE_DATE"],
                "assertion_ids": [], "evidence": []}
    base["assertion_ids"] = cur.get("assertion_ids") or []
    base["evidence"] = _evidence(source_field, cur)

    if cur["status"] != "CURRENT":
        return {**base, "deadline_date": None, "source_date": None,
                "derivation_status": INDETERMINATE,
                "reasons": ["CONFLICTING_SOURCE_DATE"]}
    src = _parse_iso(cur["value"])
    if src is None:
        return {**base, "deadline_date": None,
                "source_date": cur["value"],
                "derivation_status": INDETERMINATE,
                "reasons": ["INVALID_SOURCE_DATE"]}

    cal = calendars.get(cal_id)
    if cal is None:
        return {**base, "deadline_date": None,
                "source_date": src.isoformat(),
                "derivation_status": INDETERMINATE,
                "reasons": ["UNKNOWN_CALENDAR"]}

    result = _shift_business_days(
        src, offset,
        set(cal.get("business_week") or []),
        set(cal.get("holidays") or []))
    return {**base, "deadline_date": result.isoformat(),
            "source_date": src.isoformat(),
            "derivation_status": DERIVED, "reasons": []}


def compute_deadlines(canon_doc: dict, rules_doc: dict,
                      calendars_doc: dict, event_id: str | None = None,
                      now: str | None = None) -> dict:
    """canon + reglas + calendarios -> CA_ES_OPERATIONAL_DEADLINE_V1.

    read-only: no muta canon, reglas ni calendarios.
    """
    calendars = {
        c["calendar_id"]: c
        for c in (calendars_doc or {}).get("calendars", [])
    }
    rules = (rules_doc or {}).get("rules", [])

    deadlines = []
    for event in sorted(canon_doc.get("events", []),
                        key=lambda e: e.get("canonical_event_id") or ""):
        eid = event.get("canonical_event_id")
        if event_id is not None and eid != event_id:
            continue
        etype = event.get("event_type")
        current = _current_dates(event)
        deadlines.extend(_source_deadlines(eid, current))
        for rule in sorted(rules, key=lambda r: r.get("rule_id") or ""):
            allowed = rule.get("event_types")
            if allowed is not None and etype not in allowed:
                continue
            deadlines.append(
                _derived_deadline(eid, etype, rule, current, calendars))

    deadlines.sort(key=lambda d: d["deadline_key"])
    return {
        "schema": DEADLINE_SCHEMA,
        "generated_at": now or _now(),
        "deadlines": deadlines,
    }
