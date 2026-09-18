"""P7.5 — Operational health (CA_ES_OPERATIONAL_HEALTH_V1).

docs/p7/p75-health.md. Salud del RUNTIME (inputs, frescura,
integridad, restos de crash); nunca reinterpreta el negocio.
Umbrales solo desde config.health.
"""

from __future__ import annotations

from datetime import UTC, datetime

HEALTH_SCHEMA = "CA_ES_OPERATIONAL_HEALTH_V1"

HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
FAILED = "FAILED"

OK = "OK"
INFO = "INFO"

_SEVERITY = {OK: 0, INFO: 0, DEGRADED: 1, FAILED: 2}


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat(
    ).replace("+00:00", "Z")


def _check(name: str, status: str, detail=None) -> dict:
    return {"name": name, "status": status, "detail": detail}


def compute_health(state, conn, config: dict, *,
                   input_docs: dict | None = None,
                   inbox_index: dict | None = None,
                   deadlines_doc: dict | None = None,
                   current_run_id: str | None = None,
                   as_of: str | None = None,
                   now: str | None = None) -> dict:
    """Evalua los checks preregistered. ``input_docs`` son los docs
    de input ya cargados por validate_inputs (o {})."""
    ts = now or _utcnow()
    input_docs = input_docs or {}
    health_cfg = config.get("health") or {}
    inputs_cfg = config.get("inputs") or {}
    checks = []

    # --- last successful run -----------------------------------
    last = state.latest_successful_run(conn)
    if last is None:
        checks.append(_check("last_successful_run", DEGRADED,
                             "NO_SUCCESSFUL_RUN"))
    else:
        checks.append(_check("last_successful_run", OK, {
            "run_id": last["run_id"],
            "as_of": last["as_of"],
            "completed_at": last["completed_at"],
        }))

    # --- required inputs ----------------------------------------
    missing = [n for n, spec in inputs_cfg.items()
               if spec.get("required") and n not in input_docs]
    checks.append(_check(
        "required_inputs", FAILED if missing else OK,
        {"missing": sorted(missing)} if missing else None))

    # --- positions ----------------------------------------------
    positions = input_docs.get("positions")
    if "positions" not in inputs_cfg:
        checks.append(_check("positions_available", INFO,
                             "NOT_CONFIGURED"))
    elif positions is None:
        checks.append(_check("positions_available", DEGRADED,
                             "MISSING"))
    else:
        checks.append(_check("positions_available", OK))
        max_age = health_cfg.get("positions_max_age_days")
        pos_asof = positions.get("as_of")
        if max_age is None:
            checks.append(_check("positions_freshness", INFO,
                                 "NO_THRESHOLD_CONFIGURED"))
        elif pos_asof is None:
            checks.append(_check("positions_freshness", DEGRADED,
                                 "POSITIONS_AS_OF_UNKNOWN"))
        else:
            try:
                run_day = datetime.fromisoformat(
                    as_of or "1970-01-01")
                pos_day = datetime.fromisoformat(str(pos_asof))
                age = (run_day - pos_day).days
                status = DEGRADED if age > max_age else OK
                checks.append(_check(
                    "positions_freshness", status,
                    {"as_of": pos_asof, "age_days": age,
                     "max_age_days": max_age}))
            except ValueError:
                checks.append(_check(
                    "positions_freshness", DEGRADED,
                    "POSITIONS_AS_OF_INVALID"))

    # --- inbox ---------------------------------------------------
    failures = 0
    if inbox_index is not None:
        failures = sum(
            1 for m in inbox_index.get("messages") or []
            if m.get("processing_status") == "FAILED")
    checks.append(_check(
        "inbox_failures", DEGRADED if failures else OK,
        {"failed": failures} if failures else None))

    # --- stale running steps ------------------------------------
    stale = []
    for r in conn.execute(
            "SELECT s.run_id, s.step_id FROM run_steps s"
            " JOIN runs r ON r.run_id = s.run_id"
            " WHERE s.status='RUNNING'").fetchall():
        if r["run_id"] != current_run_id:
            stale.append({"run_id": r["run_id"],
                          "step_id": r["step_id"]})
    checks.append(_check(
        "stale_running_steps", DEGRADED if stale else OK,
        {"steps": stale} if stale else None))

    # --- artifact integrity --------------------------------------
    integrity_failures = []
    if last is not None:
        for s in state.get_steps(conn, last["run_id"]):
            sha = s.get("output_sha256")
            if not sha:
                continue
            try:
                state.get_artifact(sha)
            except Exception as exc:
                integrity_failures.append({
                    "step_id": s["step_id"],
                    "sha256": sha[:16],
                    "error": str(exc)[:80],
                })
    checks.append(_check(
        "artifact_integrity",
        FAILED if integrity_failures else OK,
        {"failures": integrity_failures}
        if integrity_failures else None))

    # --- fuentes (P9.7): disponibilidad, nunca verdad de negocio ---
    sources_cfg = config.get("sources") or {}
    if not sources_cfg.get("enabled"):
        checks.append(_check("source_refresh", INFO,
                             "NOT_CONFIGURED"))
    else:
        row = conn.execute(
            "SELECT refresh_id, status, completed_at"
            " FROM source_refreshes"
            " ORDER BY started_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
        if row is None:
            checks.append(_check(
                "source_refresh", DEGRADED, "NO_REFRESH_YET"))
        else:
            sev = {"SUCCESS": OK, "UNCHANGED": OK,
                   "PARTIAL": DEGRADED}.get(row["status"], FAILED)
            checks.append(_check("source_refresh", sev, {
                "refresh_id": row["refresh_id"],
                "status": row["status"],
                "completed_at": row["completed_at"],
            }))
            arow = conn.execute(
                "SELECT sha256 FROM artifacts"
                " WHERE schema='CA_ES_SOURCE_REFRESH_V1'"
                " ORDER BY created_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
            refresh_doc = None
            if arow is not None:
                try:
                    refresh_doc = state.get_artifact(arow["sha256"])
                except Exception:
                    refresh_doc = None
            if refresh_doc:
                required_bad = [
                    f"{sr['source_id']}/{sr['surface_id']}"
                    for sr in
                    refresh_doc.get("source_results") or []
                    if sr.get("required")
                    and sr.get("status") in ("FAILED", "PARTIAL")]
                checks.append(_check(
                    "source_required",
                    FAILED if required_bad else OK,
                    {"degraded": required_bad}
                    if required_bad else None))
            else:
                checks.append(_check(
                    "source_required", INFO, "NO_REFRESH_DOC"))
        # parse failures pendientes sobre el latest observado
        pf = conn.execute(
            "SELECT COUNT(*) c FROM source_parse_results pr"
            " JOIN source_documents d"
            " ON pr.source_id=d.source_id"
            " AND pr.source_document_id=d.source_document_id"
            " AND pr.content_sha256=d.latest_content_sha256"
            " WHERE pr.parse_status='PARSE_FAILED'").fetchone()["c"]
        checks.append(_check(
            "source_parse_failures",
            DEGRADED if pf else OK,
            {"count": pf} if pf else None))
        cp_age = health_cfg.get("source_checkpoint_max_age_days")
        if cp_age is None:
            checks.append(_check(
                "source_checkpoints", INFO, "NO_THRESHOLD"))
        else:
            oldest = conn.execute(
                "SELECT MIN(updated_at) m"
                " FROM source_checkpoints").fetchone()["m"]
            if oldest is None:
                checks.append(_check(
                    "source_checkpoints", DEGRADED,
                    "NO_CHECKPOINTS"))
            else:
                try:
                    run_day = datetime.fromisoformat(
                        as_of or ts[:10])
                    cp_day = datetime.fromisoformat(oldest[:10])
                    age = (run_day - cp_day).days
                    checks.append(_check(
                        "source_checkpoints",
                        DEGRADED if age > cp_age else OK,
                        {"oldest": oldest, "age_days": age,
                         "max_age_days": cp_age}))
                except ValueError:
                    checks.append(_check(
                        "source_checkpoints", INFO,
                        "UNPARSEABLE"))

    # --- informational -------------------------------------------
    indeterminate = 0
    if deadlines_doc is not None:
        indeterminate = sum(
            1 for d in deadlines_doc.get("deadlines") or []
            if d.get("derivation_status") == "INDETERMINATE")
    checks.append(_check("indeterminate_deadlines", INFO,
                         {"count": indeterminate}))

    pending = conn.execute(
        "SELECT COUNT(*) c FROM outbox"
        " WHERE delivery_state='PENDING_DELIVERY'"
    ).fetchone()["c"]
    checks.append(_check("pending_alerts", INFO,
                         {"count": pending}))

    worst = max((_SEVERITY[c["status"]] for c in checks),
                default=0)
    overall = {0: HEALTHY, 1: DEGRADED, 2: FAILED}[worst]
    return {
        "schema": HEALTH_SCHEMA,
        "generated_at": ts,
        "status": overall,
        "checks": checks,
    }
