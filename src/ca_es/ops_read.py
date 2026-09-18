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
