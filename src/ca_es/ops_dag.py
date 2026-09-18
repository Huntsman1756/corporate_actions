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
LINEAGE_SCHEMA = "CA_ES_OPS_LINEAGE_V1"

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
                 as_of: str, run_id: str, now_fn,
                 source_fetchers: dict | None = None):
        self.config = config
        self.state = state
        self.conn = conn
        self.as_of = as_of
        self.run_id = run_id
        self.now = now_fn
        # fetchers inyectables P9 (tests/offline); None = urllib real
        self.source_fetchers = source_fetchers
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


def _step_source_refresh(ctx: RunContext) -> dict | None:
    """P9: discovery+fetch+persistencia de fuentes publicas.

    Impuro (red + estado mutable). Nunca devuelve None por una caida
    de fuente: los fallos quedan aislados por fuente dentro del doc.
    Solo devuelve None si falta la source_policy (sin ella no se
    puede clasificar adquisicion — fail closed)."""
    sources_cfg = ctx.config.get("sources")
    if sources_cfg is None:
        sources_cfg = {"enabled": False}
    if not sources_cfg.get("enabled"):
        return {
            "schema": "CA_ES_SOURCE_REFRESH_V1",
            "refresh_id": None,
            "status": "UNCHANGED",
            "enabled": False,
            "reasons": ["SOURCES_DISABLED"],
            "source_results": [],
            "summary": {},
        }
    policy = ctx.input_doc("source_policy")
    if policy is None:
        return None  # sin policy autoritativa no hay adquisicion
    from .ops_sources import run_source_refresh

    return run_source_refresh(
        ctx.state, ctx.conn, sources_cfg,
        fetchers=ctx.source_fetchers, now=ctx.now(), policy=policy)


def _step_canon_refresh(ctx: RunContext) -> dict | None:
    """P9.5: rebuild del canon sobre la evidencia acumulada.

    Impuro pero con early-return: si el evidence set
    (doc, chosen_sha) no cambio devuelve el MISMO artefacto, y los
    pasos puros downstream saltan como SKIPPED_UNCHANGED.

    No depende de ``source_refresh``: una caida de fuente no impide
    reconstruir sobre evidencia durable. Si hay canon acumulado lo
    inyecta como input ``canon`` efectivo de los pasos downstream;
    un canon acumulado vacio nunca pisa al canon de config."""
    inputs = ctx.config.get("inputs") or {}
    spec = inputs.get("source_policy") or {}
    policy_path = spec.get("path") or (
        (spec.get("paths") or [None])[0])
    if not policy_path:
        return None
    from .ops_canon import (
        _META_CANON_SHA, get_state_meta, run_canon_refresh)

    refresh_doc = ctx.docs.get("source_refresh") or {}
    doc = run_canon_refresh(
        ctx.state, ctx.conn,
        policy_path=Path(policy_path),
        source_refresh_id=refresh_doc.get("refresh_id"),
        now=ctx.now())
    canon_sha = get_state_meta(ctx.conn, _META_CANON_SHA)
    if canon_sha:
        canon = ctx.state.get_artifact(canon_sha)
        # Solo se inyecta un canon acumulado con contenido de negocio:
        # vacio nunca pisa al canon de config ni "rescue" un run que
        # debe fallar por canon ausente (P7 semantic intacta).
        if canon.get("events"):
            ctx.input_docs["canon"] = canon
            ctx.input_refs["canon"] = {
                "sha256": canon_sha,
                "semantic_sha256": semantic_sha256(canon),
                "ref": f"{canon_sha[:2]}/{canon_sha}.json",
            }
    return doc


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

    expected_cash = ctx.docs.get("_expected_cash") or {}
    events_cfg = (ctx.config.get("reconciliation") or {}).get(
        "events", "all")
    items = {}
    for eid in sorted(ent_index.get("items") or {}):
        if events_cfg != "all" and eid not in events_cfg:
            continue
        ent_doc = ctx.state.get_artifact(
            ent_index["items"][eid]["sha256"])
        doc = reconcile(ent_doc, movements,
                        expected_cash_doc=expected_cash.get(eid))
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


_INCOME_TYPE_BY_EVENT = {
    "CASH_DIVIDEND": "DIVIDEND",
    "INTEREST_PAYMENT": "INTEREST",
    "CAPITAL_REPAYMENT": "CAPITAL_REPAYMENT",
}


def _inbox_facts_all(ctx: RunContext) -> list[dict]:
    """Facts docs MT+MX de mensajes PROCESSED (dedup por sha)."""
    rows = ctx.conn.execute(
        "SELECT artifact_refs_json FROM inbox_messages"
        " WHERE processing_status='PROCESSED'"
    ).fetchall()
    seen: set[str] = set()
    out = []
    for row in rows:
        for ref in json.loads(row["artifact_refs_json"] or "[]"):
            sha = ref.get("sha256")
            if not sha or sha in seen:
                continue
            try:
                doc = ctx.state.get_artifact(sha)
            except Exception:
                continue
            if doc.get("schema_version") in (
                    "CA_ES_SWIFT_MT_FACTS_V1",
                    "CA_ES_SWIFT_MX_FACTS_V1"):
                seen.add(sha)
                out.append(doc)
    return out


def _step_tax_events(ctx: RunContext) -> dict | None:
    """P14.18: tax evidence -> tax entitlement -> expected_cash ->
    tax recon -> cases. Impuro (lee inbox), opcional.

    Solo invalida la rama fiscal: cambios en tax_profile/tax_rules
    entran via uses_inputs/config_section del step; el cache
    semantico mantiene intactas discovery/positions/parsing."""
    canon = ctx.input_doc("canon")
    ent_index = ctx.docs.get("entitlements")
    if canon is None or ent_index is None:
        return None

    from .exceptions import build_cases_doc
    from .surface import Surface
    from .swift_ca import bind_event, project_ca_message
    from .tax_entitlement import expected_cash, tax_entitlement
    from .tax_evidence import tax_evidence
    from .tax_recon import tax_recon

    try:
        from .mx_ca import project_mx_message
    except ImportError:
        project_mx_message = None

    tax_cfg = ctx.config.get("tax") or {}
    jurisdiction = tax_cfg.get("jurisdiction")
    profile_doc = ctx.input_doc("tax_profile")
    rules_doc = ctx.input_doc("tax_rules")
    if profile_doc is None and rules_doc is None:
        # rama fiscal no configurada: indice minimo estable para no
        # invalidar el cache semantico de cash_reconciliation
        return {
            "schema": INDEX_SCHEMA,
            "generated_at": ctx.now(),
            "kind": "CA_ES_TAX_EVENT_V1",
            "items": {},
        }
    surface = Surface(canon, ctx.input_doc("source_policy"))
    facts_docs = _inbox_facts_all(ctx)
    now = ctx.now()

    # pasada 1: evidencia fiscal por mensaje, ligada a evento canon.
    # Notificaciones (MT564/seev.031) ligan via binder canonico;
    # confirmaciones (MT566/seev.036) ligan por referencia de evento
    # compartida con una notificacion ya ligada (CORP/CorpActnEvtId).
    evidence_by_event: dict[str, dict[str, list]] = {}
    pending: list[tuple[dict, dict, str | None]] = []
    ref_to_eid: dict[str, str] = {}
    for facts_doc in facts_docs:
        mid = facts_doc.get("message_identifier")
        is_mt = isinstance(mid, str) and mid.startswith("MT")
        is_mx = isinstance(mid, str) and mid.startswith("seev.")
        if not (is_mt or is_mx):
            continue
        eid = None
        if mid == "MT564":
            msg = project_ca_message(facts_doc, now=now)
            if msg.get("status") == "OK":
                eid = (bind_event(msg, canon, now=now) or {}).get(
                    "canonical_event_id")
        elif is_mx and mid.startswith("seev.031.") and (
                project_mx_message is not None):
            try:
                msg = project_mx_message(facts_doc, now=now)
                eid = (bind_event(msg, canon, now=now) or {}).get(
                    "canonical_event_id")
            except Exception:
                eid = None
        ev = tax_evidence(facts_doc, canonical_event_id=eid, now=now)
        pending.append((facts_doc, ev, eid))
        if eid:
            for ref_item in ev.get("event_references") or []:
                ref_to_eid.setdefault(
                    ref_item.get("reference"), eid)

    for facts_doc, ev, eid in pending:
        if eid is None:
            for ref_item in ev.get("event_references") or []:
                eid = ref_to_eid.get(ref_item.get("reference"))
                if eid:
                    ev["canonical_event_id"] = eid
                    break
        ref = ctx.state.store_artifact(
            ctx.conn, ev, "CA_ES_TAX_EVIDENCE_V1", "V1",
            run_id=ctx.run_id)
        if eid:
            role = "actual" if ev.get("evidence_role") == "ACTUAL" \
                else "expected"
            slot = evidence_by_event.setdefault(
                eid, {"expected": [], "actual": [],
                      "expected_docs": [], "actual_docs": []})
            slot[role].append(ref)
            slot[f"{role}_docs"].append(ev)

    # pasada 2: entitlement + profile + rules -> tax entitlement
    items: dict = {}
    expected_cash_docs: dict = ctx.docs.setdefault(
        "_expected_cash", {})
    prev_cases = _previous_cases(ctx)
    for eid in sorted(ent_index.get("items") or {}):
        ent_doc = ctx.state.get_artifact(
            ent_index["items"][eid]["sha256"])
        event = surface._find(eid)
        state = surface._current_state(event) if event else {}
        payment_date = (state.get("payment_date") or {}).get("value") \
            if isinstance(state.get("payment_date"), dict) else \
            state.get("payment_date")
        income_type = _INCOME_TYPE_BY_EVENT.get(
            (event or {}).get("event_type"), "DIVIDEND")
        slot = evidence_by_event.get(
            eid, {"expected_docs": [], "actual_docs": []})
        tax_doc = tax_entitlement(
            ent_doc, slot["expected_docs"], profile_doc, rules_doc,
            jurisdiction=jurisdiction or "ES",
            income_type=income_type,
            calculation_date=payment_date,
            now=now)
        entry = {
            "tax_evidence": slot.get("expected", []),
            "tax_evidence_actual": slot.get("actual", []),
            "tax_entitlement": ctx.state.store_artifact(
                ctx.conn, tax_doc, "CA_ES_TAX_ENTITLEMENT_V1", "V1",
                run_id=ctx.run_id),
        }
        exp_doc = expected_cash(tax_doc)
        entry["expected_cash"] = ctx.state.store_artifact(
            ctx.conn, exp_doc, "CA_ES_EXPECTED_CASH_V1", "V1",
            run_id=ctx.run_id)
        expected_cash_docs[eid] = exp_doc
        recon = tax_recon(tax_doc, slot["actual_docs"], now=now)
        entry["tax_recon"] = ctx.state.store_artifact(
            ctx.conn, recon, "CA_ES_TAX_RECON_V1", "V1",
            run_id=ctx.run_id)
        cases = build_cases_doc(
            recon, previous_cases=prev_cases.get(eid), now=now)
        entry["tax_cases"] = ctx.state.store_artifact(
            ctx.conn, cases, "CA_ES_EXCEPTION_CASES_V1", "V1",
            run_id=ctx.run_id)
        items[eid] = entry

    return {
        "schema": INDEX_SCHEMA,
        "generated_at": now,
        "kind": "CA_ES_TAX_EVENT_V1",
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


_SEC_MECHANISMS = {
    None, "REVERSE_SPLIT", "RIGHTS_DISTRIBUTION", "RIGHTS_EXERCISE",
    "STOCK_DIVIDEND", "SCRIP_DIVIDEND", "BONUS_ISSUE",
}


def _inbox_facts(ctx: RunContext) -> list[dict]:
    """Facts docs de mensajes PROCESSED del inbox (dedup por sha)."""
    rows = ctx.conn.execute(
        "SELECT artifact_refs_json FROM inbox_messages"
        " WHERE processing_status='PROCESSED'"
    ).fetchall()
    seen: set[str] = set()
    out = []
    for row in rows:
        for ref in json.loads(row["artifact_refs_json"] or "[]"):
            sha = ref.get("sha256")
            if not sha or sha in seen:
                continue
            try:
                doc = ctx.state.get_artifact(sha)
            except Exception:
                continue
            if doc.get("schema_version") == \
                    "CA_ES_SWIFT_MT_FACTS_V1":
                seen.add(sha)
                out.append(doc)
    return out


def _step_securities_events(ctx: RunContext) -> dict | None:
    """P8: inbox MT564/MT566 -> terms -> entitlement -> impact
    -> security recon -> cases. Impuro (lee inbox), opcional."""
    canon = ctx.input_doc("canon")
    positions = ctx.input_doc("positions")
    if canon is None or positions is None:
        return None
    facts_docs = _inbox_facts(ctx)

    from .event_terms import build_event_terms
    from .exceptions import build_cases_doc
    from .securities_entitlement import (
        compute_securities_entitlements)
    from .security_impact import compute_security_impact
    from .security_recon import reconcile_security_movements
    from .swift_ca import bind_event, project_ca_message
    from .swift_securities import security_movement_candidate

    elections = ctx.input_doc("elections") or {}
    prev_cases = _previous_security_cases(ctx)
    items: dict = {}
    candidates: dict[str, list] = {}
    now = ctx.now()

    # pasada 1: MT566 -> candidates (el recon los consume despues,
    # independientemente del orden de llegada al inbox)
    for facts_doc in facts_docs:
        if facts_doc.get("message_identifier") != "MT566":
            continue
        cand = security_movement_candidate(
            facts_doc, canon, now=now)
        ref = ctx.state.store_artifact(
            ctx.conn, cand,
            "CA_ES_SWIFT_SECURITY_MOVEMENT_CANDIDATE_V1", "V1",
            run_id=ctx.run_id)
        eid = cand.get("canonical_event_id")
        if cand.get("binding_status") == "BOUND" and eid:
            candidates.setdefault(eid, []).append(cand)
        items.setdefault("_candidates", {})[
            facts_doc["input_sha256"]] = ref

    # pasada 2: MT564 -> terms -> entitlement -> impact -> recon
    for facts_doc in facts_docs:
        if facts_doc.get("message_identifier") != "MT564":
            continue
        msg = project_ca_message(facts_doc, now=now)
        if msg.get("status") != "OK" or msg.get("mechanism") \
                not in _SEC_MECHANISMS or msg.get("event_type") \
                not in ("SPLIT", "RIGHTS_ISSUE", "STOCK_DIVIDEND",
                        "SCRIP_DIVIDEND", "CAPITAL_INCREASE"):
            continue
        binding = bind_event(msg, canon, now=now)
        terms = build_event_terms(msg, binding, now=now)
        key = (binding.get("canonical_event_id")
               or f"unbound:{facts_doc.get('input_sha256')}")
        elected = elections.get(
            binding.get("canonical_event_id") or "") or {}
        ent = compute_securities_entitlements(
            terms, positions, election=elected, now=now)
        impact = compute_security_impact(ent, positions, now=now)

        entry = {}
        for name, doc, schema in (
            ("terms", terms, "CA_ES_EVENT_TERMS_V1"),
            ("entitlement", ent,
             "CA_ES_SECURITIES_ENTITLEMENT_V1"),
            ("impact", impact, "CA_ES_POSITION_IMPACT_V1"),
        ):
            entry[name] = ctx.state.store_artifact(
                ctx.conn, doc, schema, "V1", run_id=ctx.run_id)

        eid = impact.get("canonical_event_id")
        recon = reconcile_security_movements(
            impact, candidates.get(eid, []) if eid else [], now=now)
        entry["recon"] = ctx.state.store_artifact(
            ctx.conn, recon, "CA_ES_SECURITY_RECON_V1", "V1",
            run_id=ctx.run_id)
        cases = build_cases_doc(
            recon, previous_cases=prev_cases.get(key), now=now)
        entry["cases"] = ctx.state.store_artifact(
            ctx.conn, cases, "CA_ES_EXCEPTION_CASES_V1", "V1",
            run_id=ctx.run_id)
        items[key] = entry

    return {
        "schema": INDEX_SCHEMA,
        "generated_at": now,
        "kind": "CA_ES_SECURITIES_EVENT_V1",
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


def _previous_security_cases(ctx: RunContext) -> dict[str, list]:
    """Casos previos por evento de valores desde el ultimo run
    exitoso (index `securities_events`, excluye `_candidates`)."""
    out: dict[str, list] = {}
    run = ctx.state.latest_successful_run(ctx.conn)
    if not run:
        return out
    steps = ctx.state.get_steps(ctx.conn, run["run_id"])
    for s in steps:
        if s["step_id"] != "securities_events" \
                or not s["output_sha256"]:
            continue
        try:
            index = ctx.state.get_artifact(s["output_sha256"])
        except Exception:
            continue
        for key, entry in (index.get("items") or {}).items():
            if key == "_candidates" or not isinstance(entry, dict):
                continue
            ref = entry.get("cases")
            if not isinstance(ref, dict):
                continue
            try:
                doc = ctx.state.get_artifact(ref["sha256"])
            except Exception:
                continue
            out[key] = doc.get("cases") or []
    return out


def _step_alert_outbox(ctx: RunContext) -> dict:
    """Deriva candidatos desde los outputs ya producidos y los
    aplica al outbox. Solo las categorias cuya fuente produjo
    output este run se consideran evaluadas (clear)."""
    from .ops_alerts import (
        DEADLINE_CATEGORIES,
        SOURCE_CATEGORIES,
        apply_alerts,
        derive_deadline_alerts,
        derive_exception_alerts,
        derive_inbox_alerts,
        derive_source_alerts,
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
    sec_index = ctx.docs.get("securities_events")
    if sec_index is not None:
        for key, entry in sorted(
                (sec_index.get("items") or {}).items()):
            if key == "_candidates" or not isinstance(entry, dict):
                continue
            ref = entry.get("cases")
            if not isinstance(ref, dict):
                continue
            cases_doc = ctx.state.get_artifact(ref["sha256"])
            candidates += derive_exception_alerts(cases_doc, ref)
        evaluated.add("EXCEPTION_CASE")
    inbox_doc = ctx.docs.get("process_inbox")
    if inbox_doc is not None:
        candidates += derive_inbox_alerts(
            inbox_doc, ctx.outputs.get("process_inbox"))
        evaluated.add("PROCESSING_FAILURE")
    # P9.7: fuentes — solo si el run produjo docs de source/canon
    # refresh; en caso contrario las categorias no se evaluan y no
    # se limpian alertas abiertas por un run sin sources.
    refresh_doc = ctx.docs.get("source_refresh")
    canon_doc = ctx.docs.get("canon_refresh")
    sources_cfg = ctx.config.get("sources") or {}
    if (sources_cfg.get("enabled")
            and (refresh_doc is not None or canon_doc is not None)):
        candidates += derive_source_alerts(
            refresh_doc, ctx.outputs.get("source_refresh"),
            canon_doc, ctx.outputs.get("canon_refresh"),
            sources_cfg=sources_cfg, conn=ctx.conn,
            now=ctx.now())
        evaluated.update(SOURCE_CATEGORIES)

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


def _step_lineage_export(ctx: RunContext) -> dict:
    """OpenLineage JSONL (opcional). Fallo con required=false no
    invalida el run de negocio."""
    from .ops_lineage import export_lineage

    cfg = ctx.config.get("lineage") or {}
    if not cfg.get("enabled"):
        return {"schema": LINEAGE_SCHEMA,
                "generated_at": ctx.now(),
                "enabled": False, "events": 0}
    out = Path(cfg["path"]) if cfg.get("path") else \
        ctx.state.root / "lineage" / f"{ctx.run_id}.jsonl"
    try:
        res = export_lineage(ctx.state, ctx.conn, ctx.run_id, out)
    except Exception as exc:
        if cfg.get("required"):
            raise
        return {"schema": LINEAGE_SCHEMA,
                "generated_at": ctx.now(),
                "enabled": True,
                "error": f"{exc.__class__.__name__}:{exc}"[:200]}
    return {"schema": LINEAGE_SCHEMA,
            "generated_at": ctx.now(),
            "enabled": True, **res}


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
        # P9.3: impuro (red + estado mutable), opcional; los fallos
        # de fuente quedan aislados dentro del doc, nunca bloquean
        # el run. Sin dependency edge hacia canon_refresh: una caida
        # de fuente no impide reconstruir sobre evidencia durable.
        OperationalStep(
            "source_refresh", "1",
            dependencies=("validate_inputs",),
            pure=False, mandatory=False,
            expected_output_schema="CA_ES_SOURCE_REFRESH_V1",
            expected_output_version="V1",
            uses_inputs=("source_policy",),
            fn=_step_source_refresh),
        # P9.5/P9.6: impuro pero early-return sobre evidence-set
        # inalterado (mismo artefacto -> mismo semantic hash ->
        # downstream SKIPPED_UNCHANGED). Sin edge hacia
        # source_refresh ni hacia consumidores de canon: un fallo de
        # adquisicion o de rebuild degrada a canon de config en vez
        # de bloquear el run. El orden lo da la posicion en la lista.
        OperationalStep(
            "canon_refresh", "1",
            dependencies=("validate_inputs",),
            pure=False, mandatory=False,
            expected_output_schema="CA_ES_CANON_REFRESH_V1",
            expected_output_version="V1",
            uses_inputs=("source_policy",),
            fn=_step_canon_refresh),
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
        # P14.18: rama fiscal entre entitlements y cash_recon.
        # uses_inputs de tax_profile/tax_rules + config_section
        # 'tax' -> un cambio fiscal invalida SOLO este step (y
        # downstream via outputs), nunca discovery/positions.
        OperationalStep(
            "tax_events", "1",
            dependencies=("entitlements", "process_inbox"),
            pure=False, mandatory=False,
            expected_output_schema=INDEX_SCHEMA,
            expected_output_version="V1",
            config_section="tax",
            uses_inputs=("canon", "source_policy",
                         "tax_profile", "tax_rules"),
            fn=_step_tax_events),
        OperationalStep(
            "cash_reconciliation", "1",
            dependencies=("entitlements", "tax_events"),
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
        # P8: impuro (lee inbox_messages mutable), opcional;
        # cadena terms->entitlement->impact->recon->cases por
        # evento de valores procedente del inbox MT564/MT566.
        OperationalStep(
            "securities_events", "1",
            dependencies=("process_inbox",),
            pure=False, mandatory=False,
            expected_output_schema=INDEX_SCHEMA,
            expected_output_version="V1",
            uses_inputs=("canon", "positions", "source_policy",
                       "elections"),
            fn=_step_securities_events),
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
        # opcional: export OpenLineage; fallo con required=false
        # no invalida el run.
        OperationalStep(
            "lineage_export", "1",
            dependencies=("health_report",),
            pure=False, mandatory=False,
            expected_output_schema=LINEAGE_SCHEMA,
            expected_output_version="V1",
            fn=_step_lineage_export),
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
            dag: list[OperationalStep] | None = None,
            source_fetchers: dict | None = None) -> dict:
    """Ejecuta (o reanuda) un run operativo. Devuelve el manifest.

    ``source_fetchers``: mapa adapter_name -> fetch(url, referer)
    inyectable para P9 (tests/offline). ``None`` = fetchers urllib
    reales construidos por adapter."""
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
        ctx = RunContext(config, state, conn, as_of, run_id, now,
                         source_fetchers)

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
