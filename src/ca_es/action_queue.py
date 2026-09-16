"""P5.1 — Action Queue.

docs/p5/p50-scope.md + P5.1:

    CA_ES_OPERATIONAL_DEADLINE_V1 + as_of + thresholds explicitos
        -> CA_ES_ACTION_QUEUE_V1

Reglas duras:

- solo SOURCE/DERIVED con deadline_date producen queue item;
  INDETERMINATE se conserva en `indeterminate`, nunca se inventa fecha
- days_until = deadline_date - as_of en dias naturales (no se vuelve
  a contar business days)
- OVERDUE siempre visible aunque este fuera de la ventana futura;
  UPCOMING solo hasta window_days
- SOURCE y DERIVED del mismo tipo coexisten, sin ganador
- umbrales explicitos (window_days, due_soon_days): ningun default
  financiero/custodio oculto
- ACTION_REQUIRED del brief V1 (todo date.* proximo) queda intacto en
  V1; V2 consume esta cola
"""

from __future__ import annotations

from datetime import date

from .swift_ca import _now

QUEUE_SCHEMA = "CA_ES_ACTION_QUEUE_V1"
BRIEF_V2_SCHEMA = "CA_ES_MORNING_BRIEF_V2"

OVERDUE = "OVERDUE"
DUE_TODAY = "DUE_TODAY"
DUE_SOON = "DUE_SOON"
UPCOMING = "UPCOMING"

_STATUS_ORDER = {OVERDUE: 0, DUE_TODAY: 1, DUE_SOON: 2, UPCOMING: 3}


def _parse_iso(value):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def build_action_queue(deadlines_doc: dict, as_of: str,
                       window_days: int, due_soon_days: int,
                       now: str | None = None) -> dict:
    """deadlines + as_of -> CA_ES_ACTION_QUEUE_V1.

    window_days y due_soon_days son obligatorios y explicitos.
    read-only: no muta deadlines_doc.
    """
    start = date.fromisoformat(as_of)

    items = []
    indeterminate = []
    for d in deadlines_doc.get("deadlines", []):
        if d.get("derivation_status") == "INDETERMINATE":
            indeterminate.append(d)
            continue
        day = _parse_iso(d.get("deadline_date"))
        if day is None:
            indeterminate.append(d)
            continue
        days = (day - start).days
        if days < 0:
            status = OVERDUE
        elif days == 0:
            status = DUE_TODAY
        elif days <= due_soon_days:
            status = DUE_SOON
        elif days <= window_days:
            status = UPCOMING
        else:
            continue
        items.append({
            "deadline_key": d["deadline_key"],
            "canonical_event_id": d["canonical_event_id"],
            "deadline_type": d["deadline_type"],
            "deadline_date": d["deadline_date"],
            "derivation_status": d["derivation_status"],
            "source_date": d.get("source_date"),
            "rule_id": d.get("rule_id"),
            "calendar_id": d.get("calendar_id"),
            "business_days_offset": d.get("business_days_offset"),
            "days_until": days,
            "action_status": status,
            "assertion_ids": d.get("assertion_ids") or [],
            "evidence": d.get("evidence") or [],
        })

    items.sort(key=lambda i: (
        _STATUS_ORDER[i["action_status"]],
        i["deadline_date"],
        i["canonical_event_id"],
        i["deadline_key"],
    ))
    indeterminate.sort(key=lambda d: d.get("deadline_key") or "")

    return {
        "schema": QUEUE_SCHEMA,
        "generated_at": now or _now(),
        "as_of": as_of,
        "window_days": window_days,
        "due_soon_days": due_soon_days,
        "items": items,
        "indeterminate": indeterminate,
    }
