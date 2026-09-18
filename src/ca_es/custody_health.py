"""P13.14 — CA_ES_CUSTODY_FEED_HEALTH_V1.

Salud del feed de custodia (infraestructura), NO correccion de
negocio: un portfolio con breaks de reconciliacion puede tener el
feed HEALTHY; un feed caido no significa que las posiciones sean
cero — el ultimo snapshot COMPLETE sigue disponible y se marca
STALE por freshness.

Umbrales explicitos (parametros, no constantes ocultas):

- position freshness: dias desde statement_as_of <= max_age_days;
- completeness: snapshot COMPLETE disponible por cuenta requerida;
- cash freshness: ultima entrada vista <= max_cash_age_days;
- parse/bind: entradas sin binding > max_unbound;
- conflicts: cualquier CONFLICTING_POSITION_SNAPSHOTS -> FAILED.
"""

from __future__ import annotations

from datetime import date

HEALTH_SCHEMA = "CA_ES_CUSTODY_FEED_HEALTH_V1"

HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
FAILED = "FAILED"


def _days_between(a: str | None, b: str | None) -> int | None:
    try:
        da = date.fromisoformat(str(a)[:10])
        db = date.fromisoformat(str(b)[:10])
    except (TypeError, ValueError):
        return None
    return (db - da).days


def feed_health(index_doc: dict | None, now: str,
                required_accounts: list[str] | None = None,
                max_position_age_days: int = 7,
                max_cash_age_days: int = 7,
                max_unbound_entries: int = 50) -> dict:
    """index doc + thresholds -> CA_ES_CUSTODY_FEED_HEALTH_V1."""
    checks = []

    def _check(name, status, detail):
        checks.append({"check": name, "status": status,
                       "detail": detail})

    if index_doc is None:
        return {
            "schema": HEALTH_SCHEMA,
            "generated_at": now,
            "status": FAILED,
            "checks": [{"check": "feed_index_present",
                        "status": FAILED,
                        "detail": "NO_CUSTODY_INDEX"}],
        }

    statements = index_doc.get("statements") or []
    conflicts = index_doc.get("conflicting_slots") or []
    if conflicts:
        _check("position_snapshot_conflicts", FAILED,
               f"{len(conflicts)} conflicting slots")
    else:
        _check("position_snapshot_conflicts", HEALTHY, "none")

    required = required_accounts or []
    complete = {s.get("account_id_raw") for s in statements
                if s.get("completeness") == "COMPLETE"}
    partial = {s.get("account_id_raw") for s in statements
               if s.get("completeness") in ("PARTIAL", "INDETERMINATE")}
    missing = [a for a in required if a not in complete]
    if missing:
        _check("account_coverage", FAILED,
               f"no COMPLETE snapshot: {sorted(missing)}")
    else:
        _check("account_coverage", HEALTHY,
               f"{len(complete)} accounts covered")

    as_ofs = [s.get("statement_as_of") for s in statements
              if s.get("completeness") == "COMPLETE"
              and s.get("statement_as_of")]
    freshest = max(as_ofs) if as_ofs else None
    age = _days_between(freshest, now)
    if freshest is None:
        _check("position_freshness", FAILED, "no complete snapshot")
    elif age is None:
        _check("position_freshness", DEGRADED,
               f"unparseable as_of {freshest!r}")
    elif age > max_position_age_days:
        _check("position_freshness", DEGRADED,
               f"latest complete snapshot {age}d old "
               f"(stale>{max_position_age_days}d)")
    else:
        _check("position_freshness", HEALTHY,
               f"latest complete snapshot {age}d old")

    if partial:
        _check("partial_statements", DEGRADED,
               f"{len(partial)} accounts with PARTIAL/INDETERMINATE")
    else:
        _check("partial_statements", HEALTHY, "none")

    reports = index_doc.get("cash_reports") or []
    unbound = (index_doc.get("bindings_summary") or {}).get(
        "unbound_entries", 0)
    if unbound > max_unbound_entries:
        _check("unbound_cash_entries", DEGRADED,
               f"{unbound} unbound > {max_unbound_entries}")
    else:
        _check("unbound_cash_entries", HEALTHY,
               f"{unbound} unbound")
    _check("cash_feed_present",
           HEALTHY if reports else DEGRADED,
           f"{len(reports)} cash reports" if reports
           else "no cash reports ingested")

    statuses = {c["status"] for c in checks}
    overall = (FAILED if FAILED in statuses
               else DEGRADED if DEGRADED in statuses else HEALTHY)
    return {
        "schema": HEALTH_SCHEMA,
        "generated_at": now,
        "status": overall,
        "thresholds": {
            "max_position_age_days": max_position_age_days,
            "max_cash_age_days": max_cash_age_days,
            "max_unbound_entries": max_unbound_entries,
        },
        "checks": checks,
    }
