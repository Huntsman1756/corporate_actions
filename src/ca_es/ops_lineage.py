"""P7.7 — OpenLineage export (opcional, stdlib-only).

docs/p7/p77-openlineage.md. JSONL determinista: un RunEvent por
linea; datasets content-addressed (artifact:<sha256>); nunca
contenido de negocio en la exportacion.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_URL = ("https://openlineage.io/spec/1-0-5/OpenLineage.json"
              "#/definitions/RunEvent")
PRODUCER = "https://github.com/romeotech/ca-es"
NS = "ca-es"
DS_NS = "ca-es-artifacts"


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat(
    ).replace("+00:00", "Z")


def _dataset(sha: str, kind: str) -> dict:
    return {
        "namespace": DS_NS,
        "name": f"artifact:{sha}",
        "facets": {
            "caEs": {
                "_producer": PRODUCER,
                "_schemaURL": SCHEMA_URL,
                "kind": kind,
            },
        },
    }


def _facet(extra: dict) -> dict:
    return {
        "caEs": {
            "_producer": PRODUCER,
            "_schemaURL": SCHEMA_URL,
            **extra,
        },
    }


def _event(event_type: str, event_time: str, run_id: str,
           job_name: str, inputs=None, outputs=None,
           run_facets=None, job_facets=None) -> dict:
    ev = {
        "eventType": event_type,
        "eventTime": event_time,
        "run": {
            "runId": run_id,
            "facets": run_facets or {},
        },
        "job": {
            "namespace": NS,
            "name": job_name,
            "facets": job_facets or {},
        },
        "inputs": inputs or [],
        "outputs": outputs or [],
        "producer": PRODUCER,
        "schemaURL": SCHEMA_URL,
    }
    return ev


def build_lineage_events(state, conn, run_id: str) -> list[dict]:
    """Reconstruye los eventos del run desde el state store.

    Determinista: orden por DAG/rowid; contenido solo ids, hashes
    y metadata de ejecucion.
    """
    run = state.get_run(conn, run_id)
    if run is None:
        raise ValueError(f"RUN_NOT_FOUND:{run_id}")
    steps = state.get_steps(conn, run_id)
    events = [
        _event("START", run["started_at"], run_id, "ops-run",
               run_facets=_facet({
                   "as_of": run["as_of"],
                   "config_semantic_sha256":
                       run["config_semantic_sha256"],
                   "previous_successful_run_id":
                       run["previous_successful_run_id"],
               })),
    ]
    for s in steps:
        inputs = []
        try:
            hashes = json.loads(
                s.get("input_semantic_hashes_json") or "[]")
        except json.JSONDecodeError:
            hashes = []
        for h in hashes:
            inputs.append({"namespace": DS_NS,
                           "name": f"cachekey:{h[:32]}"})
        outputs = []
        if s.get("output_sha256"):
            outputs.append(_dataset(
                s["output_sha256"], "step_output"))
        status = s["status"]
        event_type = "COMPLETE" if status in (
            "SUCCEEDED", "SKIPPED_UNCHANGED") else "FAIL"
        events.append(_event(
            event_type,
            s.get("completed_at") or s.get("started_at")
            or run["started_at"],
            f"{run_id}:{s['step_id']}",
            f"ops-run.{s['step_id']}",
            inputs=inputs, outputs=outputs,
            run_facets=_facet({
                "status": status,
                "cache_source_run_id":
                    s.get("cache_source_run_id"),
            }),
            job_facets=_facet({
                "step_version": s.get("step_version"),
                "expected_output_schema":
                    s.get("expected_output_schema"),
                "expected_output_version":
                    s.get("expected_output_version"),
                "output_semantic_sha256":
                    s.get("output_semantic_sha256"),
                "config_semantic_hash":
                    s.get("config_semantic_hash"),
            })))
    final_type = "COMPLETE" if run["run_status"] in (
        "SUCCEEDED", "PARTIAL") else "FAIL"
    events.append(_event(
        final_type, run["completed_at"] or run["started_at"],
        run_id, "ops-run",
        run_facets=_facet({"run_status": run["run_status"]})))
    return events


def export_lineage(state, conn, run_id: str,
                   out_path: Path) -> dict:
    """Escribe <out_path> (JSONL) y devuelve resumen."""
    events = build_lineage_events(state, conn, run_id)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(
        json.dumps(e, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True) + "\n"
        for e in events)
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(out_path)
    return {
        "path": str(out_path),
        "events": len(events),
        "run_id": run_id,
    }
