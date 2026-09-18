"""P7.2 — Operational DAG + resume.

docs/p7/p72-dag.md. El engine ejecuta un DAG explicito de pasos que
componen funciones de dominio P1–P6 ya cerradas. P7 no recalcula
semantica: selecciona inputs, ejecuta, persiste checkpoints,
reutiliza pasos puros y ensambla salidas.

Cache key = canonical_json({step_id, step_version, inputs ordenados
(semantic sha256), config relevante (semantic sha256), output
schema/version, as_of}). SKIPPED_UNCHANGED solo para pasos puros
con artefacto re-verificado y schema/version vigente.
"""

from __future__ import annotations

import json
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .ops_config import validate_ops_config
from .ops_state import (
    OPS_STATE_SCHEMA_VERSION,
    OpsState,
    SchemaMismatch,
)
from .semantic_hash import (
    byte_sha256,
    canonical_json,
    semantic_sha256,
)

RUN_SCHEMA = "CA_ES_OPERATIONAL_RUN_V1"
INPUTS_SCHEMA = "CA_ES_OPS_INPUTS_V1"
INDEX_SCHEMA = "CA_ES_OPS_INDEX_V1"
OUTBOX_SCHEMA = "CA_ES_ALERT_OUTBOX_V1"

RUNNING = "RUNNING"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
PARTIAL = "PARTIAL"
SKIPPED_UNCHANGED = "SKIPPED_UNCHANGED"
BLOCKED = "BLOCKED"
PENDING = "PENDING"


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat(
    ).replace("+00:00", "Z")


# ------------------------------------------------------------------
# Step definition
# ------------------------------------------------------------------

ExecuteFn = Callable[["RunContext"], dict | None]


@dataclass
class OperationalStep:
    step_id: str
    version: str
    dependencies: tuple[str, ...] = ()
    pure: bool = True
    mandatory: bool = True
    expected_output_schema: str | None = None
    expected_output_version: str | None = None
    config_section: str | None = None
    uses_inputs: tuple[str, ...] = ()
    uses_as_of: bool = False
    dynamic_inputs: Callable[["RunContext"], list] | None = None
    fn: ExecuteFn = field(default=lambda ctx: None)


class RunContext:
    """Contexto mutable del run: inputs, outputs, state."""

    def __init__(self, config: dict, state: OpsState, conn,
                 as_of: str, run_id: str, now_fn):
        self.config = config
        self.state = state
        self.conn = conn
        self.as_of = as_of
        self.run_id = run_id
        self.now = now_fn
        self.input_docs: dict[str, dict] = {}
        self.input_refs: dict[str, dict] = {}
        self.outputs: dict[str, dict] = {}   # step_id -> artifact ref
        self.docs: dict[str, dict] = {}      # step_id -> doc
        self.lineage_events: list[dict] = []

    def input_doc(self, name: str) -> dict | None:
        return self.input_docs.get(name)

    def lineage(self, event: dict) -> None:
        self.lineage_events.append(event)


# ------------------------------------------------------------------
# Step implementations (dominio P1-P6)
# ------------------------------------------------------------------

def _step_validate_inputs(ctx: RunContext) -> dict:
    inputs = (ctx.config.get("inputs") or {})
    entries = {}
    missing = []
    for name, spec in inputs.items():
        paths = list(spec.get("paths") or ([] if not spec.get("path")
                                          else [spec["path"]]))
        refs, docs = [], []
        for p in paths:
            raw = Path(p).read_bytes()
            doc = json.loads(raw.decode("utf-8"))
            ref = ctx.state.store_artifact(
                ctx.conn, doc, doc.get("schema")
                or doc.get("canon_version")
                or doc.get("schema_version") or "UNKNOWN",
                doc.get("schema_version") or "V1",
                run_id=ctx.run_id)
            ref["byte_sha256"] = byte_sha256(raw)
            refs.append(ref)
            docs.append(doc)
        if refs:
            entries[name] = refs[0] if len(refs) == 1 else refs
            ctx.input_docs[name] = docs[0] if len(docs) == 1 else docs
            ctx.input_refs[name] = entries[name]
        elif spec.get("required"):
            missing.append(name)
    if missing:
        raise ValueError(
            "MISSING_REQUIRED_INPUT:" + ",".join(sorted(set(missing))))
    return {
        "schema": INPUTS_SCHEMA,
        "generated_at": ctx.now(),
        "inputs": entries,
    }


def _step_process_inbox(ctx: RunContext) -> dict | None:
    inbox_cfg = ctx.config.get("inbox") or {}
    inbox_dir = Path(inbox_cfg["path"]) if inbox_cfg.get("path") \
        else ctx.state.root / "inbox"
    if not (inbox_dir / "incoming").is_dir() and \
            not inbox_dir.is_dir():
        return None
    from .ops_inbox import process_inbox

    return process_inbox(
        ctx.state, ctx.conn, inbox_dir,
        run_id=ctx.run_id, now=ctx.now())


def _step_deadlines(ctx: RunContext) -> dict:
    from .deadlines import compute_deadlines

    return compute_deadlines(
        ctx.input_doc("canon"), ctx.input_doc("deadline_rules"),
        ctx.input_doc("calendars"), now=ctx.now())


def _step_action_queue(ctx: RunContext) -> dict:
    from .action_queue import build_action_queue

    aq = ctx.config.get("action_queue") or {}
    return build_action_queue(
        ctx.docs["compute_deadlines"], ctx.as_of,
        aq["window_days"], aq["due_soon_days"], now=ctx.now())


def _step_brief(ctx: RunContext) -> dict:
    from .surface import Surface

    surface = Surface(ctx.input_doc("canon"),
                      ctx.input_doc("source_policy"))
    return surface.brief_v2(
        ctx.as_of, ctx.docs["build_action_queue"])


def _step_entitlements(ctx: RunContext) -> dict | None:
    positions = ctx.input_doc("positions")
    if positions is None:
        return None
    from .entitlement_engine import compute_entitlements
    from .surface import Surface

    surface = Surface(ctx.input_doc("canon"),
                      ctx.input_doc("source_policy"))
    items = {}
    for event in ctx.input_doc("canon").get("events", []):
        eid = event.get("canonical_event_id")
        doc = compute_entitlements(surface, eid, positions)
        if doc is None:
            continue
        ref = ctx.state.store_artifact(
            ctx.conn, doc, "CA_ES_ENTITLEMENT_V1", "V1",
            run_id=ctx.run_id)
        ctx.docs[f"entitlement:{eid}"] = doc
        items[eid] = ref
    return {
        "schema": INDEX_SCHEMA,
        "generated_at": ctx.now(),
        "kind": "CA_ES_ENTITLEMENT_V1",
        "items": items,
    }


def _step_cash_recon(ctx: RunContext) -> dict | None:
    movements = ctx.input_doc("cash_movements")
    ent_index = ctx.docs.get("entitlements")
    if movements is None or ent_index is None:
        return None
    from .reconciliation import reconcile

    events_cfg = (ctx.config.get("reconciliation") or {}).get(
        "events", "all")
    items = {}
    for eid in sorted(ent_index.get("items") or {}):
        if events_cfg != "all" and eid not in events_cfg:
            continue
        ent_doc = ctx.state.get_artifact(
            ent_index["items"][eid]["sha256"])
        doc = reconcile(ent_doc, movements)
        ref = ctx.state.store_artifact(
            ctx.conn, doc, "CA_ES_RECON_RESULT_V1", "V1",
            run_id=ctx.run_id)
        items[eid] = ref
    return {
        "schema": INDEX_SCHEMA,
        "generated_at": ctx.now(),
        "kind": "CA_ES_RECON_RESULT_V1",
        "items": items,
    }


def _step_exception_cases(ctx: RunContext) -> dict | None:
    recon_index = ctx.docs.get("cash_reconciliation")
    if recon_index is None:
        return None
    from .exceptions import build_cases_doc

    prev_cases = _previous_cases(ctx)
    items = {}
    for eid in sorted(recon_index.get("items") or {}):
        recon = ctx.state.get_artifact(
            recon_index["items"][eid]["sha256"])
        doc = build_cases_doc(recon, prev_cases.get(eid),
                              now=ctx.now())
        ref = ctx.state.store_artifact(
            ctx.conn, doc, "CA_ES_EXCEPTION_CASES_V1", "V1",
            run_id=ctx.run_id)
        items[eid] = ref
    return {
        "schema": INDEX_SCHEMA,
        "generated_at": ctx.now(),
        "kind": "CA_ES_EXCEPTION_CASES_V1",
        "items": items,
    }


def _previous_cases(ctx: RunContext) -> dict[str, list]:
    """Casos previos por evento desde el ultimo run exitoso."""
    out: dict[str, list] = {}
    run = ctx.state.latest_successful_run(ctx.conn)
    if not run:
        return out
    steps = ctx.state.get_steps(ctx.conn, run["run_id"])
    for s in steps:
        if s["step_id"] != "exception_cases" or not s["output_sha256"]:
            continue
        try:
            index = ctx.state.get_artifact(s["output_sha256"])
        except Exception:
            continue
        for eid, ref in (index.get("items") or {}).items():
            try:
                doc = ctx.state.get_artifact(ref["sha256"])
            except Exception:
                continue
            out[eid] = doc.get("cases") or []
    return out


def _step_alert_outbox(ctx: RunContext) -> dict:
    """Deriva candidatos desde los outputs ya producidos y los
    aplica al outbox. Solo las categorias cuya fuente produjo
    output este run se consideran evaluadas (clear)."""
    from .ops_alerts import (
        DEADLINE_CATEGORIES,
        apply_alerts,
        derive_deadline_alerts,
        derive_exception_alerts,
        derive_inbox_alerts,
    )

    candidates = []
    evaluated = set()
    queue_doc = ctx.docs.get("build_action_queue")
    if queue_doc is not None:
        candidates += derive_deadline_alerts(
            queue_doc, ctx.outputs.get("build_action_queue"))
        evaluated.update(DEADLINE_CATEGORIES.values())
    cases_index = ctx.docs.get("exception_cases")
    if cases_index is not None:
        for eid, ref in sorted(
                (cases_index.get("items") or {}).items()):
            cases_doc = ctx.state.get_artifact(ref["sha256"])
            candidates += derive_exception_alerts(cases_doc, ref)
        evaluated.add("EXCEPTION_CASE")
    inbox_doc = ctx.docs.get("process_inbox")
    if inbox_doc is not None:
        candidates += derive_inbox_alerts(
            inbox_doc, ctx.outputs.get("process_inbox"))
        evaluated.add("PROCESSING_FAILURE")

    stats = apply_alerts(
        ctx.conn, candidates, ctx.run_id, evaluated,
        now=ctx.now())
    return {
        "schema": OUTBOX_SCHEMA,
        "generated_at": ctx.now(),
        "candidates": len(candidates),
        "stats": stats,
    }


def _step_health_report(ctx: RunContext) -> dict:
    """CA_ES_OPERATIONAL_HEALTH_V1 del run: runtime, nunca
    negocio."""
    from .ops_health import compute_health

    return compute_health(
        ctx.state, ctx.conn, ctx.config,
        input_docs=ctx.input_docs,
        inbox_index=ctx.docs.get("process_inbox"),
        deadlines_doc=ctx.docs.get("compute_deadlines"),
        current_run_id=ctx.run_id,
        as_of=ctx.as_of,
        now=ctx.now())


def _dyn_prev_cases(ctx: RunContext) -> list:
    """Semantic hash del estado de casos previos (input efectivo
    del step exception_cases; un estado previo distinto invalida
    la cache)."""
    prev = _previous_cases(ctx)
    if not prev:
        return ["prev_cases:<none>"]
    return [
        f"prev_cases:{eid}:{semantic_sha256(cases)}"
        for eid, cases in sorted(prev.items())
    ]


# ------------------------------------------------------------------
# DAG
# ------------------------------------------------------------------

def default_dag() -> list[OperationalStep]:
    return [
        # pure=False: siempre re-registra inputs; es barato y pobla
        # ctx.input_docs/input_refs para los pasos downstream.
        OperationalStep(
            "validate_inputs", "1",
            pure=False,
            expected_output_schema=INPUTS_SCHEMA,
            expected_output_version="V1",
            fn=_step_validate_inputs),
        # pure=False: la ingestion tiene side effects (mueve
        # ficheros, registra observaciones); es idempotente por
        # input_sha256.
        OperationalStep(
            "process_inbox", "1",
            dependencies=("validate_inputs",),
            pure=False, mandatory=False,
            expected_output_schema="CA_ES_OPS_INBOX_V1",
            expected_output_version="V1",
            fn=_step_process_inbox),
        OperationalStep(
            "compute_deadlines", "1",
            dependencies=("validate_inputs",),
            expected_output_schema="CA_ES_OPERATIONAL_DEADLINE_V1",
            expected_output_version="V1",
            uses_inputs=("canon", "deadline_rules", "calendars"),
            fn=_step_deadlines),
        OperationalStep(
            "build_action_queue", "1",
            dependencies=("compute_deadlines",),
            expected_output_schema="CA_ES_ACTION_QUEUE_V1",
            expected_output_version="V1",
            config_section="action_queue",
            uses_as_of=True,
            fn=_step_action_queue),
        OperationalStep(
            "morning_brief_v2", "1",
            dependencies=("build_action_queue",),
            expected_output_schema="CA_ES_MORNING_BRIEF_V2",
            expected_output_version="V2",
            uses_inputs=("canon", "source_policy"),
            uses_as_of=True,
            fn=_step_brief),
        OperationalStep(
            "entitlements", "1",
            dependencies=("validate_inputs",),
            mandatory=False,
            expected_output_schema=INDEX_SCHEMA,
            expected_output_version="V1",
            uses_inputs=("canon", "positions", "source_policy"),
            fn=_step_entitlements),
        OperationalStep(
            "cash_reconciliation", "1",
            dependencies=("entitlements",),
            mandatory=False,
            expected_output_schema=INDEX_SCHEMA,
            expected_output_version="V1",
            config_section="reconciliation",
            uses_inputs=("cash_movements",),
            fn=_step_cash_recon),
        OperationalStep(
            "exception_cases", "1",
            dependencies=("cash_reconciliation",),
            mandatory=False,
            expected_output_schema=INDEX_SCHEMA,
            expected_output_version="V1",
            dynamic_inputs=_dyn_prev_cases,
            fn=_step_exception_cases),
        # impuro: upsert al outbox con dedup por alert_key; lee
        # oportunistamente los outputs opcionales del ctx.
        OperationalStep(
            "alert_outbox", "1",
            dependencies=("morning_brief_v2",),
            pure=False,
            expected_output_schema=OUTBOX_SCHEMA,
            expected_output_version="V1",
            fn=_step_alert_outbox),
        # impuro: lee estado mutable del store; siempre fresco.
        OperationalStep(
            "health_report", "1",
            dependencies=("alert_outbox",),
            pure=False,
            expected_output_schema="CA_ES_OPERATIONAL_HEALTH_V1",
            expected_output_version="V1",
            fn=_step_health_report),
    ]


# ------------------------------------------------------------------
# Engine
# ------------------------------------------------------------------

def _input_sem_hashes(ctx: RunContext, step: OperationalStep) -> list:
    """Semantic hashes de los inputs efectivos del step.

    Solo los inputs declarados en ``uses_inputs`` + los outputs de
    las dependencias; nunca todos los inputs del config.

    ``validate_inputs`` es dependencia de ORDEN (registra los
    artefactos de input), no de datos: su output agrega todos los
    inputs del config y contaminaria la cache key de cada step con
    inputs que no consume. La dependencia de datos real via
    ``uses_inputs``.
    """
    hashes = [
        ctx.outputs[d]["semantic_sha256"]
        for d in step.dependencies
        if d in ctx.outputs and d != "validate_inputs"
    ]
    for name in step.uses_inputs:
        ref = ctx.input_refs.get(name)
        if isinstance(ref, dict):
            hashes.append(f"input:{name}:{ref['semantic_sha256']}")
        elif isinstance(ref, list):
            for r in ref:
                hashes.append(
                    f"input:{name}:{r['semantic_sha256']}")
        else:
            hashes.append(f"input:{name}:<absent>")
    if step.dynamic_inputs is not None:
        hashes.extend(step.dynamic_inputs(ctx))
    return sorted(set(hashes))


def _step_config_hash(ctx: RunContext, step: OperationalStep) -> str:
    """Semantic hash del subconjunto de config relevante al step."""
    subset = {}
    if step.config_section:
        subset[step.config_section] = ctx.config.get(step.config_section)
    for name in step.uses_inputs:
        subset[f"inputs.{name}"] = (
            (ctx.config.get("inputs") or {}).get(name))
    return semantic_sha256(subset)


def _cache_key(ctx: RunContext, step: OperationalStep,
               input_hashes: list, config_hash: str) -> str:
    key = {
        "step_id": step.step_id,
        "step_version": step.version,
        "inputs": input_hashes,
        "config": config_hash,
        "output_schema": step.expected_output_schema,
        "output_version": step.expected_output_version,
    }
    if step.uses_as_of:
        key["as_of"] = ctx.as_of
    return canonical_json(key)


def _verify_cached(ctx: RunContext, step: OperationalStep,
                   cached: dict) -> dict | None:
    """Re-verifica el artefacto cacheado; devuelve el ref o None."""
    if cached.get("expected_output_schema") != \
            step.expected_output_schema or \
            cached.get("expected_output_version") != \
            step.expected_output_version:
        return None
    sha = cached.get("output_sha256")
    if not sha:
        return None
    try:
        doc = ctx.state.get_artifact(sha)
    except Exception:
        return None
    return {
        "sha256": sha,
        "semantic_sha256": cached.get("output_semantic_sha256"),
        "ref": cached.get("output_ref"),
        "doc": doc,
        "source_run_id": cached.get("run_id"),
    }


def run_ops(config: dict, state: OpsState,
            as_of: str | None = None,
            resume_run_id: str | None = None,
            now_fn: Callable[[], str] | None = None,
            dag: list[OperationalStep] | None = None) -> dict:
    """Ejecuta (o reanuda) un run operativo. Devuelve el manifest."""
    now = now_fn or _utcnow
    validate_ops_config(config)
    dag = dag or default_dag()

    run_id = resume_run_id or uuid.uuid4().hex[:16]
    conn = state.acquire_run_lock(run_id)
    try:
        row = conn.execute(
            "SELECT value FROM state_meta"
            " WHERE key='schema_version'").fetchone()
        if row is None or row["value"] != OPS_STATE_SCHEMA_VERSION:
            raise SchemaMismatch(
                "ops.db schema_version="
                f"{row['value'] if row else None!r}, esperada "
                f"{OPS_STATE_SCHEMA_VERSION!r}")
        ctx = RunContext(config, state, conn, as_of, run_id, now)

        if resume_run_id:
            run = state.get_run(conn, run_id)
            if run is None:
                raise ValueError(f"RUN_NOT_FOUND:{run_id}")
            if run["run_status"] == "SUCCEEDED":
                raise ValueError(f"RUN_IMMUTABLE:{run_id}")
            if as_of is None:
                as_of = run["as_of"]
                ctx.as_of = as_of
        else:
            if not as_of:
                raise ValueError("AS_OF_REQUIRED")
            prev = state.latest_successful_run(conn)
            state.insert_run(conn, {
                "run_id": run_id,
                "as_of": as_of,
                "started_at": now(),
                "run_status": RUNNING,
                "config_sha256": semantic_sha256(config),
                "config_semantic_sha256": semantic_sha256(config),
                "previous_successful_run_id": (
                    prev["run_id"] if prev else None),
                "manifest": {},
            })
            state.checkpoint()

        # steps huerfanos de una ejecucion previa -> se rehacen
        step_records = {s["step_id"]: s
                        for s in state.get_steps(conn, run_id)}
        mandatory_failed = False
        optional_failed = False
        blocked_steps = []

        for step in dag:
            rec = {
                "step_id": step.step_id,
                "step_version": step.version,
                "status": PENDING,
            }

            # dependencias
            dep_block = False
            for dep in step.dependencies:
                dep_rec = step_records.get(dep)
                dep_status = (
                    ctx_step_status(dep_rec)
                    if dep_rec else None)
                if dep_status in (FAILED, BLOCKED):
                    dep_block = True
            if dep_block:
                rec.update(status=BLOCKED,
                           error_code="DEPENDENCY_FAILED")
                state.upsert_step(conn, run_id, rec)
                state.checkpoint()
                step_records[step.step_id] = {**rec,
                                              "status": BLOCKED}
                blocked_steps.append(step.step_id)
                if step.mandatory:
                    mandatory_failed = True
                else:
                    optional_failed = True
                continue

            # inputs semanticos
            input_hashes = _input_sem_hashes(ctx, step)
            config_hash = _step_config_hash(ctx, step)
            cache_key = _cache_key(
                ctx, step, input_hashes, config_hash)

            rec.update({
                "input_semantic_hashes": [cache_key],
                "config_semantic_hash": config_hash,
                "expected_output_schema":
                    step.expected_output_schema,
                "expected_output_version":
                    step.expected_output_version,
            })

            # cache hit? (la columna persiste json.dumps(list))
            if step.pure:
                cached = state.find_cached_step(
                    conn, step.step_id, step.version,
                    json.dumps([cache_key]),
                    current_run_id=run_id)
                if cached:
                    verified = _verify_cached(ctx, step, cached)
                    if verified:
                        rec.update({
                            "status": SKIPPED_UNCHANGED,
                            "output_ref": verified["ref"],
                            "output_sha256": verified["sha256"],
                            "output_semantic_sha256":
                                verified["semantic_sha256"],
                            "cache_source_run_id":
                                verified["source_run_id"],
                            "started_at": now(),
                            "completed_at": now(),
                        })
                        state.upsert_step(conn, run_id, rec)
                        state.checkpoint()
                        step_records[step.step_id] = {
                            **rec, "status": SKIPPED_UNCHANGED}
                        ctx.outputs[step.step_id] = verified
                        ctx.docs[step.step_id] = verified["doc"]
                        continue

            # ejecutar
            rec["status"] = RUNNING
            rec["started_at"] = now()
            state.upsert_step(conn, run_id, rec)
            state.checkpoint()
            try:
                doc = step.fn(ctx)
            except Exception as exc:
                rec.update({
                    "status": FAILED,
                    "completed_at": now(),
                    "error_code": exc.__class__.__name__,
                    "error_detail": str(exc)[:500],
                })
                state.upsert_step(conn, run_id, rec)
                state.checkpoint()
                step_records[step.step_id] = {
                    **rec, "status": FAILED}
                if step.mandatory:
                    mandatory_failed = True
                else:
                    optional_failed = True
                continue

            if doc is None:
                rec.update(status=BLOCKED, completed_at=now(),
                           error_code="MISSING_INPUTS")
                state.upsert_step(conn, run_id, rec)
                state.checkpoint()
                step_records[step.step_id] = {
                    **rec, "status": BLOCKED}
                blocked_steps.append(step.step_id)
                if step.mandatory:
                    mandatory_failed = True
                else:
                    optional_failed = True
                continue

            if step.expected_output_schema:
                got = (doc.get("schema") or doc.get("brief_version")
                       or doc.get("schema_version"))
                if got != step.expected_output_schema:
                    rec.update({
                        "status": FAILED,
                        "completed_at": now(),
                        "error_code": "OUTPUT_SCHEMA_MISMATCH",
                        "error_detail": f"{got!r} != "
                                        f"{step.expected_output_schema!r}",
                    })
                    state.upsert_step(conn, run_id, rec)
                    state.checkpoint()
                    step_records[step.step_id] = {
                        **rec, "status": FAILED}
                    if step.mandatory:
                        mandatory_failed = True
                    else:
                        optional_failed = True
                    continue

            ref = state.store_artifact(
                conn, doc,
                step.expected_output_schema or "UNKNOWN",
                step.expected_output_version or "V1",
                run_id=run_id)
            rec.update({
                "status": SUCCEEDED,
                "completed_at": now(),
                "output_ref": ref["ref"],
                "output_sha256": ref["sha256"],
                "output_semantic_sha256": ref["semantic_sha256"],
            })
            state.upsert_step(conn, run_id, rec)
            state.checkpoint()
            step_records[step.step_id] = {
                **rec, "status": SUCCEEDED}
            ctx.outputs[step.step_id] = ref
            ctx.docs[step.step_id] = doc

        final = FAILED if mandatory_failed else (
            PARTIAL if optional_failed else SUCCEEDED)
        if final == FAILED:
            # alerta operativa del propio fallo (el step
            # alert_outbox puede no haber llegado a ejecutarse)
            from .ops_alerts import apply_alerts, run_failed_candidate
            failed_steps = [
                s["step_id"] for s in step_records.values()
                if s.get("status") == FAILED]
            apply_alerts(
                conn,
                [run_failed_candidate(run_id, failed_steps)],
                run_id, {"RUN_FAILED"}, now=now())
        manifest = {
            "schema": RUN_SCHEMA,
            "run_id": run_id,
            "as_of": as_of,
            "started_at": now(),
            "completed_at": now(),
            "run_status": final,
            "config_semantic_sha256": semantic_sha256(config),
            "steps": [
                {
                    "step_id": s["step_id"],
                    "status": s["status"],
                    "step_version": s.get("step_version"),
                    "output_sha256": s.get("output_sha256"),
                    "output_semantic_sha256":
                        s.get("output_semantic_sha256"),
                    "cache_source_run_id":
                        s.get("cache_source_run_id"),
                }
                for s in step_records.values()
            ],
            "outputs": {
                sid: ref.get("ref")
                for sid, ref in ctx.outputs.items()
            },
            "lineage_events": ctx.lineage_events,
        }
        state.update_run(
            conn, run_id, completed_at=now(),
            run_status=final, manifest_json=manifest,
            error_summary=(json.dumps(blocked_steps)
                           if blocked_steps else None))
        state.checkpoint()
        return manifest
    finally:
        state.release_run_lock()


def ctx_step_status(rec: dict | None) -> str | None:
    return rec.get("status") if rec else None


def traceback_str() -> str:  # pragma: no cover - diagnostico
    return traceback.format_exc()
