"""P3.5 — exception cases / operational workflow.

Consume un resultado de reconciliation (CA_ES_CASH_RECON_V1) y lo
proyecta a casos operativos (CA_ES_EXCEPTION_CASES_V1) SIN
reinterpretar los hechos: este modulo nunca recalcula dinero ni decide
si un importe "deberia" ser bruto/neto. Recibe estados ya adjudicados.

Frontera (docs/p3/p35-scope.md):

    recon result -> classify_cases() -> merge_cases() -> queue()

Invariantes duras:

- MATCH nunca crea caso.
- case_key es estable y NO depende ni del workflow ni del
  factual_status: se deriva de (canonical_event_id, sujeto). Una
  excepcion que evoluciona (MISSING_CASH -> AMOUNT_MISMATCH) es el
  mismo caso con FACT_UPDATED, no dos casos. Reejecutar el motor con
  el mismo resultado no duplica casos.
- factual_status y workflow_status son taxonomias separadas.
  RESOLVED/DISMISSED nunca modifican factual_status ni reason_codes.
- Una excepcion RESOLVED/DISMISSED que reaparece al reprocesar se
  REABRE (workflow -> OPEN), conservando su historia.
- Una excepcion que desaparece del resultado queda registrada
  (observed=false + evento NOT_OBSERVED), nunca borrada.
- reason_codes se conservan exactos (NET_EXPECTED_NOT_AVAILABLE,
  UNKNOWN_AMOUNT_BASIS...); delta solo existe cuando el item lo
  trae (comparacion semanticamente valida).
- La prioridad deriva solo de hechos observables (tipo de excepcion,
  magnitud comparable, antiguedad). Sin heuristicas financieras.
- El audit trail por caso es append-only: actor, timestamp,
  estado anterior/nuevo y nota en cada transicion.

Fuera de alcance: SLA, notificaciones, dashboards, asignacion
automatica, TUI.
"""

from __future__ import annotations

import copy
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .canonical import load_strict_json_object

CASES_SCHEMA = "CA_ES_EXCEPTION_CASES_V1"

WORKFLOW_OPEN = "OPEN"
WORKFLOW_IN_REVIEW = "IN_REVIEW"
WORKFLOW_WAITING_EXTERNAL = "WAITING_EXTERNAL"
WORKFLOW_RESOLVED = "RESOLVED"
WORKFLOW_DISMISSED = "DISMISSED"

WORKFLOW_STATUSES = {
    WORKFLOW_OPEN,
    WORKFLOW_IN_REVIEW,
    WORKFLOW_WAITING_EXTERNAL,
    WORKFLOW_RESOLVED,
    WORKFLOW_DISMISSED,
}
# estados que mantienen el caso en la cola operativa
ACTIVE_WORKFLOW = {
    WORKFLOW_OPEN,
    WORKFLOW_IN_REVIEW,
    WORKFLOW_WAITING_EXTERNAL,
}
CLOSED_WORKFLOW = {WORKFLOW_RESOLVED, WORKFLOW_DISMISSED}

RESOLUTION_CODES = {
    "CORRECTED",
    "ACCEPTED_AS_IS",
    "FALSE_POSITIVE",
    "DUPLICATE",
    "OTHER",
}

# prioridad: solo del tipo de excepcion (hecho observable)
PRIORITY = {
    "AMOUNT_MISMATCH": "HIGH",
    "MISSING_CASH": "HIGH",
    "UNEXPECTED_CASH": "MEDIUM",
    "INDETERMINATE": "LOW",
}
PRIORITY_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

SYSTEM_ACTOR = "system"

# campos del snapshot factual que merge_cases actualiza al re-observar
_FACTUAL_FIELDS = (
    "factual_status",
    "reason_codes",
    "entitlement_status",
    "amount_basis",
    "expected_amount",
    "actual_amount",
    "delta",
    "currency",
    "value_date",
    "movement_ids",
    "linked_movement_ids",
    "evidence",
    "priority",
)


def load_cases(path: Path) -> dict:
    doc = load_strict_json_object(path)
    if doc.get("schema") != CASES_SCHEMA:
        raise ValueError(
            f"cases schema debe ser {CASES_SCHEMA}, "
            f"recibido {doc.get('schema')!r}"
        )
    cases = doc.get("cases")
    if not isinstance(cases, list) or any(
        not isinstance(case, dict) for case in cases
    ):
        raise ValueError("cases debe ser una lista de objetos")
    return doc


def _money_norm(value) -> Decimal | None:
    """normaliza un importe (str o money object) a Decimal."""
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("normalized")
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _case_key(item: dict, canonical_event_id: str) -> str:
    """Clave estable: evento + sujeto. NUNCA incluye factual_status.

    El sujeto es el movimiento concreto para UNEXPECTED_CASH (el caso
    va sobre ESE cash); para el resto es la expectativa
    (account+currency), de modo que sustituir un movement_id por otro
    o evolucionar MISSING_CASH -> AMOUNT_MISMATCH no fragmenta la
    historia del caso.
    """
    account = item.get("account_id") or "-"
    if item.get("status") == "UNEXPECTED_CASH":
        mids = item.get("movement_ids") or ["-"]
        subject = f"movement:{account}:{mids[0]}"
    else:
        currency = item.get("currency")
        if currency is None:
            expected = item.get("expected_gross_cash") or {}
            currency = expected.get("currency")
        subject = f"expected:{account}:{currency or item.get('isin') or '-'}"
    return "|".join([canonical_event_id or "-", subject])


def classify_cases(recon_doc: dict) -> list[dict]:
    """recon result -> snapshots factuales observados (sin workflow).

    Funcion pura: no muta recon_doc. MATCH no produce caso.
    """
    event_id = recon_doc.get("canonical_event_id")
    observed = []
    for item in recon_doc.get("items", []):
        status = item.get("status")
        if status == "MATCH":
            continue
        if status not in PRIORITY:
            # estado desconocido: no se silencia, pero tampoco se
            # reinterpreta -> LOW y reason explicito
            priority = "LOW"
        else:
            priority = PRIORITY[status]
        expected = item.get("expected_gross_cash")
        observed.append(
            {
                "case_key": _case_key(item, event_id),
                "canonical_event_id": event_id,
                "account_id": item.get("account_id"),
                "isin": item.get("isin"),
                "factual_status": status,
                "reason_codes": list(item.get("reasons") or []),
                "entitlement_status": item.get("entitlement_status"),
                "amount_basis": item.get("amount_basis"),
                "expected_amount": expected,
                "actual_amount": item.get("actual_amount"),
                "delta": item.get("delta"),
                "currency": (
                    item.get("currency")
                    or (expected or {}).get("currency")
                ),
                "value_date": item.get("value_date"),
                "movement_ids": list(item.get("movement_ids") or []),
                "linked_movement_ids": list(
                    item.get("linked_movement_ids") or []
                ),
                "evidence": item.get("evidence"),
                "priority": priority,
            }
        )
    # misma clave dos veces en una ejecucion (p.ej. dos items
    # DUPLICATE_ENTITLEMENT_KEY sobre expected:A:EUR): un solo caso
    seen = set()
    deduped = []
    for c in sorted(observed, key=lambda c: c["case_key"]):
        if c["case_key"] in seen:
            continue
        seen.add(c["case_key"])
        deduped.append(c)
    return deduped


def _snapshot_changed(case: dict, obs: dict) -> bool:
    return any(case.get(f) != obs.get(f) for f in _FACTUAL_FIELDS)


def _audit(case: dict, event_type: str, at: str, actor: str,
           **extra) -> None:
    case.setdefault("history", []).append(
        {
            "type": event_type,
            "at": at,
            "actor": actor,
            **extra,
        }
    )


def merge_cases(previous_cases: list[dict] | None,
                observed: list[dict], now: str) -> list[dict]:
    """Fusiona casos previos con lo observado en esta ejecucion.

    - caso nuevo           -> CREATED, workflow OPEN
    - caso re-observado    -> last_seen_at + FACT_UPDATED si el
                              snapshot factual cambio
    - caso RESOLVED/DISMISSED que reaparece -> workflow OPEN + REOPENED
    - caso no observado    -> observed=false + NOT_OBSERVED
                              (nunca se borra, workflow intacto)
    """
    previous_cases = previous_cases or []
    event_ids = {c.get("canonical_event_id")
                 for c in previous_cases + observed}
    if len(event_ids) > 1:
        raise ValueError("CASES_EVENT_MISMATCH")
    prev = {}
    for case in previous_cases:
        key = case["case_key"]
        if key in prev:
            raise ValueError(f"DUPLICATE_PREVIOUS_CASE_KEY: {key}")
        prev[key] = copy.deepcopy(case)
    merged = []
    for obs in observed:
        key = obs["case_key"]
        case = prev.pop(key, None)
        if case is None:
            case = {
                **obs,
                "workflow_status": WORKFLOW_OPEN,
                "observed": True,
                "first_seen_at": now,
                "last_seen_at": now,
                "assigned_to": None,
                "resolution_code": None,
                "resolution_note": None,
                "resolved_at": None,
                "history": [],
            }
            _audit(case, "CREATED", now, SYSTEM_ACTOR)
            merged.append(case)
            continue

        was_observed = case.get("observed", False)
        if _snapshot_changed(case, obs):
            for f in _FACTUAL_FIELDS:
                if f in obs:
                    case[f] = obs[f]
            _audit(case, "FACT_UPDATED", now, SYSTEM_ACTOR)
        if not was_observed:
            _audit(case, "REOBSERVED", now, SYSTEM_ACTOR)
        if case["workflow_status"] in CLOSED_WORKFLOW:
            _audit(
                case,
                "REOPENED",
                now,
                SYSTEM_ACTOR,
                from_status=case["workflow_status"],
                to_status=WORKFLOW_OPEN,
            )
            case["workflow_status"] = WORKFLOW_OPEN
            case["resolution_code"] = None
            case["resolution_note"] = None
            case["resolved_at"] = None
        case["observed"] = True
        case["last_seen_at"] = now
        merged.append(case)

    # desapariciones: solo los que quedaron en prev (no observados
    # en esta ejecucion); registradas, nunca borradas
    for case in prev.values():
        if case.get("observed", False):
            case["observed"] = False
            _audit(case, "NOT_OBSERVED", now, SYSTEM_ACTOR)
        merged.append(case)

    return sorted(merged, key=lambda c: c["case_key"])


def apply_transition(case: dict, to_status: str, actor: str, at: str,
                     note: str = "", resolution_code: str | None = None,
                     assigned_to: str | None = None) -> dict:
    """Transicion humana de workflow. Nunca toca factual_status."""
    if to_status not in WORKFLOW_STATUSES:
        raise ValueError(f"workflow_status invalido: {to_status!r}")
    if to_status in CLOSED_WORKFLOW and not resolution_code:
        raise ValueError(
            f"{to_status} requiere resolution_code "
            f"({sorted(RESOLUTION_CODES)})"
        )
    if resolution_code and resolution_code not in RESOLUTION_CODES:
        raise ValueError(f"resolution_code invalido: {resolution_code!r}")
    if not actor:
        raise ValueError("actor requerido para una transicion humana")

    from_status = case["workflow_status"]
    _audit(
        case,
        "TRANSITION",
        at,
        actor,
        from_status=from_status,
        to_status=to_status,
        note=note,
        resolution_code=resolution_code,
    )
    case["workflow_status"] = to_status
    if to_status in CLOSED_WORKFLOW:
        case["resolution_code"] = resolution_code
        case["resolution_note"] = note
        case["resolved_at"] = at
    else:
        case["resolution_code"] = None
        case["resolution_note"] = None
        case["resolved_at"] = None
    if assigned_to is not None:
        case["assigned_to"] = assigned_to
    return case


def _queue_magnitude(case: dict) -> Decimal:
    """Magnitud comparable para ordenar: delta si existe, si no el
    importe observado, si no el esperado. Cero si nada es parseable."""
    for value in (case.get("delta"), case.get("actual_amount"),
                  case.get("expected_amount")):
        norm = _money_norm(value)
        if norm is not None:
            return abs(norm)
    return Decimal(0)


def queue(cases: list[dict]) -> list[dict]:
    """Proyeccion determinista de la cola operativa.

    Entran casos observados en la ultima ejecucion y con workflow
    activo. Orden: prioridad, magnitud desc, antiguedad, case_key.
    """
    active = [
        c
        for c in cases
        if c.get("observed") and c["workflow_status"] in ACTIVE_WORKFLOW
    ]
    active.sort(
        key=lambda c: (
            PRIORITY_RANK.get(c.get("priority"), 9),
            -_queue_magnitude(c),
            c.get("first_seen_at") or "",
            c["case_key"],
        )
    )
    return [
        {
            "case_key": c["case_key"],
            "priority": c.get("priority"),
            "factual_status": c["factual_status"],
            "reason_codes": c.get("reason_codes") or [],
            "workflow_status": c["workflow_status"],
            "account_id": c.get("account_id"),
        }
        for c in active
    ]


def build_cases_doc(recon_doc: dict,
                    previous_cases: list[dict] | None = None,
                    now: str = "") -> dict:
    """recon result + casos previos -> CA_ES_EXCEPTION_CASES_V1."""
    event_id = recon_doc.get("canonical_event_id")
    if any(c.get("canonical_event_id") != event_id
           for c in (previous_cases or [])):
        raise ValueError("CASES_EVENT_MISMATCH")
    observed = classify_cases(recon_doc)
    cases = merge_cases(previous_cases, observed, now)
    by_workflow: dict[str, int] = {}
    by_factual: dict[str, int] = {}
    for c in cases:
        by_workflow[c["workflow_status"]] = (
            by_workflow.get(c["workflow_status"], 0) + 1
        )
        by_factual[c["factual_status"]] = (
            by_factual.get(c["factual_status"], 0) + 1
        )
    return {
        "schema": CASES_SCHEMA,
        "generated_at": now,
        "canonical_event_id": recon_doc.get("canonical_event_id"),
        "cases": cases,
        "queue": queue(cases),
        "summary": {
            "cases": len(cases),
            "observed": sum(1 for c in cases if c.get("observed")),
            "by_workflow": by_workflow,
            "by_factual": by_factual,
        },
    }
