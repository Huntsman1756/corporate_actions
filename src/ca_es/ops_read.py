"""P7.8 — lectura read-only del state store: ops-status,
ops-latest, ops-export-run. Nunca recalcula negocio."""

from __future__ import annotations

import json
import shutil
from pathlib import Path


def _steps_of(state, conn, run_id: str) -> list[dict]:
    return state.get_steps(conn, run_id)


def _artifact_or_none(state, sha: str | None) -> dict | None:
    if not sha:
        return None
    try:
        return state.get_artifact(sha)
    except Exception:
        return None


def latest_artifacts(state, conn, run_id: str) -> dict:
    """step_id -> metadata de artefacto del run."""
    out = {}
    for s in _steps_of(state, conn, run_id):
        out[s["step_id"]] = {
            "status": s["status"],
            "sha256": s.get("output_sha256"),
            "semantic_sha256": s.get("output_semantic_sha256"),
            "schema": s.get("expected_output_schema"),
            "schema_version": s.get("expected_output_version"),
            "ref": s.get("output_ref"),
            "cache_source_run_id": s.get("cache_source_run_id"),
            "error_code": s.get("error_code"),
        }
    return out


def ops_latest_doc(state, conn) -> dict:
    run = state.latest_successful_run(conn)
    if run is None:
        return {"schema": "CA_ES_OPS_LATEST_V1",
                "status": "NO_SUCCESSFUL_RUN",
                "run": None, "artifacts": {}}
    return {
        "schema": "CA_ES_OPS_LATEST_V1",
        "run": {
            "run_id": run["run_id"],
            "as_of": run["as_of"],
            "completed_at": run["completed_at"],
            "run_status": run["run_status"],
            "config_semantic_sha256":
                run["config_semantic_sha256"],
            "previous_successful_run_id":
                run["previous_successful_run_id"],
        },
        "artifacts": latest_artifacts(state, conn, run["run_id"]),
    }


def _step_doc(state, conn, run_id: str, step_id: str):
    for s in _steps_of(state, conn, run_id):
        if s["step_id"] == step_id:
            return _artifact_or_none(state, s.get("output_sha256"))
    return None


def ops_status_doc(state, conn) -> dict:
    """Resumen operativo: runs, steps, health, alerts, inbox."""
    active = conn.execute(
        "SELECT * FROM runs WHERE run_status='RUNNING'"
        " ORDER BY started_at DESC LIMIT 1").fetchone()
    latest = state.latest_run(conn)
    last_ok = state.latest_successful_run(conn)
    last_failed = conn.execute(
        "SELECT * FROM runs WHERE run_status='FAILED'"
        " ORDER BY started_at DESC, rowid DESC LIMIT 1"
    ).fetchone()

    steps = []
    if latest is not None:
        steps = [
            {"step_id": s["step_id"], "status": s["status"],
             "error_code": s.get("error_code")}
            for s in _steps_of(state, conn, latest["run_id"])]

    health = None
    action_counts = {"OVERDUE": 0, "DUE_TODAY": 0, "DUE_SOON": 0}
    open_exceptions = 0
    if last_ok is not None:
        health_doc = _step_doc(
            state, conn, last_ok["run_id"], "health_report")
        if health_doc:
            health = health_doc.get("status")
        queue = _step_doc(
            state, conn, last_ok["run_id"], "build_action_queue")
        for item in (queue or {}).get("items") or []:
            st = item.get("action_status")
            if st in action_counts:
                action_counts[st] += 1
        cases_index = _step_doc(
            state, conn, last_ok["run_id"], "exception_cases")
        for ref in (cases_index or {}).get("items", {}).values():
            doc = _artifact_or_none(state, ref.get("sha256"))
            for c in (doc or {}).get("cases") or []:
                if c.get("workflow_status") == "OPEN":
                    open_exceptions += 1

    pending_alerts = conn.execute(
        "SELECT COUNT(*) c FROM outbox"
        " WHERE delivery_state='PENDING_DELIVERY'"
    ).fetchone()["c"]
    inbox_failures = conn.execute(
        "SELECT COUNT(*) c FROM inbox_messages"
        " WHERE processing_status='FAILED'").fetchone()["c"]

    # P10.11 — resumen del ledger de entrega (aditivo; las tablas
    # existen siempre tras la migracion a schema v3).
    delivery: dict | None = None
    has_ledger = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table'"
        " AND name='deliveries'").fetchone()
    if has_ledger:
        counts = {r["status"]: r["c"] for r in conn.execute(
            "SELECT status, COUNT(*) c FROM deliveries"
            " GROUP BY status").fetchall()}
        if counts.get("FAILED_PERMANENT") or counts.get(
                "UNKNOWN_OUTCOME"):
            d_status = "FAILED"
        elif counts.get("FAILED_RETRYABLE") or counts.get("PENDING"):
            d_status = "DEGRADED"
        else:
            d_status = "HEALTHY"
        delivery = {
            "status": d_status,
            "pending": counts.get("PENDING", 0),
            "delivered": counts.get("DELIVERED", 0),
            "failed_retryable": counts.get("FAILED_RETRYABLE", 0),
            "failed_permanent": counts.get("FAILED_PERMANENT", 0),
            "unknown_outcome": counts.get("UNKNOWN_OUTCOME", 0),
            "abandoned": counts.get("ABANDONED", 0),
        }

    # P11 — resumen del send ledger (aditivo; tablas tras schema v4).
    send: dict | None = None
    has_sends = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table'"
        " AND name='sends'").fetchone()
    if has_sends:
        scounts = {r["status"]: r["c"] for r in conn.execute(
            "SELECT status, COUNT(*) c FROM sends"
            " GROUP BY status").fetchall()}
        quarantined = conn.execute(
            "SELECT COUNT(*) c FROM send_receipts"
            " WHERE status='QUARANTINED'").fetchone()["c"]
        if scounts.get("SPOOL_FAILED_PERMANENT") or scounts.get(
                "UNKNOWN_OUTCOME") or quarantined:
            s_status = "FAILED"
        elif scounts.get("SPOOL_FAILED_RETRYABLE") or scounts.get(
                "PREPARED") or scounts.get("SPOOLED"):
            s_status = "DEGRADED"
        else:
            s_status = "HEALTHY"
        send = {
            "status": s_status,
            "prepared": scounts.get("PREPARED", 0),
            "spooled": scounts.get("SPOOLED", 0),
            "gateway_accepted": scounts.get("GATEWAY_ACCEPTED", 0),
            "gateway_rejected": scounts.get("GATEWAY_REJECTED", 0),
            "failed_retryable": scounts.get(
                "SPOOL_FAILED_RETRYABLE", 0),
            "failed_permanent": scounts.get(
                "SPOOL_FAILED_PERMANENT", 0),
            "unknown_outcome": scounts.get("UNKNOWN_OUTCOME", 0),
            "abandoned": scounts.get("ABANDONED", 0),
            "quarantined_receipts": quarantined,
        }

    return {
        "schema": "CA_ES_OPS_STATUS_V1",
        "active_run": (
            {"run_id": active["run_id"], "as_of": active["as_of"],
             "started_at": active["started_at"]}
            if active else None),
        "latest_run": (
            {"run_id": latest["run_id"],
             "run_status": latest["run_status"],
             "as_of": latest["as_of"]}
            if latest else None),
        "latest_successful_run": (
            {"run_id": last_ok["run_id"], "as_of": last_ok["as_of"],
             "completed_at": last_ok["completed_at"]}
            if last_ok else None),
        "latest_failed_run": (
            {"run_id": last_failed["run_id"],
             "as_of": last_failed["as_of"],
             "error_summary": last_failed["error_summary"]}
            if last_failed else None),
        "steps": steps,
        "health": health or "NO_HEALTH",
        "pending_alerts": pending_alerts,
        "open_exceptions": open_exceptions,
        "action_counts": action_counts,
        "inbox_failures": inbox_failures,
        "delivery": delivery,
        "send": send,
    }


def ops_source_status_doc(state, conn) -> dict:
    """P9.8 — estado read-only por fuente/superficie.

    Documentos acumulados, divergencia latest-vs-chosen, parse
    failures sobre latest, checkpoints y ultimo refresh. Nunca
    recalcula negocio.
    """
    latest_refresh = state.latest_source_refresh(conn)
    # surface_id no es columna de source_documents: se deriva de las
    # observaciones (identidad del doc estable por fuente).
    surf = {}
    for r in conn.execute(
            "SELECT DISTINCT source_id, source_document_id,"
            " surface_id FROM source_observations").fetchall():
        surf[(r["source_id"], r["source_document_id"])] = \
            r["surface_id"]
    sources: dict[tuple, dict] = {}
    for row in state.list_source_documents(conn):
        key = (row["source_id"],
               surf.get((row["source_id"],
                         row["source_document_id"])) or "?")
        entry = sources.setdefault(key, {
            "source_id": row["source_id"],
            "surface_id": key[1],
            "documents": 0,
            "with_chosen": 0,
            "divergent_latest": 0,
        })
        entry["documents"] += 1
        if row.get("chosen_content_sha256"):
            entry["with_chosen"] += 1
        if (row.get("latest_content_sha256")
                and row["latest_content_sha256"]
                != row.get("chosen_content_sha256")):
            entry["divergent_latest"] += 1
    pf_rows = conn.execute(
        "SELECT d.source_id, d.source_document_id, COUNT(*) c"
        " FROM source_parse_results pr"
        " JOIN source_documents d"
        " ON pr.source_id=d.source_id"
        " AND pr.source_document_id=d.source_document_id"
        " AND pr.content_sha256=d.latest_content_sha256"
        " WHERE pr.parse_status='PARSE_FAILED'"
        " GROUP BY d.source_id, d.source_document_id").fetchall()
    for row in pf_rows:
        key = (row["source_id"],
               surf.get((row["source_id"],
                         row["source_document_id"])) or "?")
        if key in sources:
            sources[key]["parse_failures"] = (
                sources[key].get("parse_failures", 0) + row["c"])
    for cp in conn.execute(
            "SELECT * FROM source_checkpoints").fetchall():
        key = (cp["source_id"], cp["surface_id"])
        if key in sources:
            sources[key]["checkpoint"] = {
                "updated_at": cp["updated_at"],
                "cursor": json.loads(cp["cursor_json"] or "{}"),
            }
    return {
        "schema": "CA_ES_SOURCE_STATUS_V1",
        "latest_refresh": (
            {"refresh_id": latest_refresh["refresh_id"],
             "status": latest_refresh["status"],
             "completed_at": latest_refresh["completed_at"]}
            if latest_refresh else None),
        "sources": [sources[k] for k in sorted(sources)],
    }


def export_run(state, conn, run_id: str, output: Path,
               include_inputs: bool = False) -> dict:
    """Exporta manifest + steps + artefactos derivados del run.

    Sin blobs raw de inbox ni inputs confidenciales por defecto.
    """
    from .ops_lineage import export_lineage

    run = state.get_run(conn, run_id)
    if run is None:
        raise ValueError(f"RUN_NOT_FOUND:{run_id}")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "artifacts").mkdir(exist_ok=True)

    manifest = json.loads(run["manifest_json"] or "{}")
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True,
                   ensure_ascii=True) + "\n", encoding="utf-8")
    steps = _steps_of(state, conn, run_id)
    (output / "steps.json").write_text(
        json.dumps(steps, indent=2, sort_keys=True,
                   ensure_ascii=True, default=str) + "\n",
        encoding="utf-8")

    copied = []
    for s in steps:
        if s["step_id"] == "validate_inputs" and \
                not include_inputs:
            continue
        sha = s.get("output_sha256")
        if not sha:
            continue
        src = state.artifacts_dir / f"{sha[:2]}/{sha}.json"
        if not src.is_file():
            continue
        dst = output / "artifacts" / f"{s['step_id']}-{sha[:12]}.json"
        shutil.copyfile(src, dst)
        copied.append({"step_id": s["step_id"], "sha256": sha,
                       "file": dst.name})
        # index docs: copiar tambien los artefactos referenciados
        try:
            idx = state.get_artifact(sha)
        except Exception:
            continue
        sub_items = idx.get("items") or {}
        if isinstance(sub_items, dict):
            refs = sub_items.values()
        elif isinstance(sub_items, list):
            refs = sub_items
        else:
            refs = []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            sub_sha = ref.get("sha256")
            if not sub_sha:
                continue
            sub_src = (state.artifacts_dir
                       / f"{sub_sha[:2]}/{sub_sha}.json")
            if not sub_src.is_file():
                continue
            sub_dst = (output / "artifacts"
                       / f"{s['step_id']}-{sub_sha[:12]}.json")
            shutil.copyfile(sub_src, sub_dst)
            copied.append({"step_id": s["step_id"],
                           "sha256": sub_sha,
                           "file": sub_dst.name})

    lineage = export_lineage(
        state, conn, run_id, output / "lineage.jsonl")
    return {
        "schema": "CA_ES_OPS_EXPORT_V1",
        "run_id": run_id,
        "output": str(output),
        "artifacts": copied,
        "lineage": lineage,
        "include_inputs": include_inputs,
    }
