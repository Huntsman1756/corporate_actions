"""P15.6 — CA_ES_TAX_RECOVERY_STATUS_V1: eventos sobre claims.

Cada evento es un hecho explicito con provenance (receipt del
provider, rechazo, registro manual de envio, vencimiento). El
motor aplica transiciones validadas por EDGES; un evento cuyo
salto no es valido queda registrado como REJECTED_EVENT con
reason — nunca se aplica en silencio.

Eventos soportados:
- SUBMISSION_RECORDED: envio registrado (manual o provider) ->
  SUBMITTED
- RECEIPT: acuse de recibo del provider -> ACKNOWLEDGED
- ACCEPTANCE: claim aceptado -> ACCEPTED
- REJECTION: rechazo explicito -> REJECTED (+ caso P3.5 via recon)
- APPLIED: relief at source aplicado -> APPLIED (terminal)
- EXPIRY_CHECK: evaluacion de deadline -> EXPIRED si vencido
- QUERY: consulta del provider -> registrado, sin cambio de estado
"""

from __future__ import annotations

from .tax_recovery_case import (
    ACKNOWLEDGED, ACCEPTED, APPLIED, EDGES, EXPIRED, REJECTED,
    SUBMITTED, TERMINAL, _audit)

STATUS_SCHEMA = "CA_ES_TAX_RECOVERY_STATUS_V1"

EVENT_TYPES = {
    "SUBMISSION_RECORDED", "RECEIPT", "ACCEPTANCE", "REJECTION",
    "APPLIED", "EXPIRY_CHECK", "QUERY",
}

_EVENT_TARGET = {
    "SUBMISSION_RECORDED": SUBMITTED,
    "RECEIPT": ACKNOWLEDGED,
    "ACCEPTANCE": ACCEPTED,
    "REJECTION": REJECTED,
    "APPLIED": APPLIED,
}


def apply_status_events(cases_doc: dict,
                        events: list[dict] | None, *,
                        actor: str = "system",
                        now: str | None = None) -> dict:
    """Aplica eventos ordenados por `at` a los claims del doc.

    Devuelve CA_ES_TAX_RECOVERY_STATUS_V1 con outcomes por evento:
    APPLIED (transicion hecha), REJECTED_EVENT (salto invalido),
    UNKNOWN_CLAIM, INVALID_EVENT.
    """
    claims = {c["claim_id"]: c
              for c in cases_doc.get("claims") or []}
    outcomes = []

    ordered = sorted(events or [],
                     key=lambda e: (e.get("at") or "",))
    for ev in ordered:
        out = {
            "event": ev,
            "outcome": None,
            "reason": None,
            "from_status": None,
            "to_status": None,
        }
        outcomes.append(out)
        etype = ev.get("event_type")
        if etype not in EVENT_TYPES:
            out["outcome"] = "INVALID_EVENT"
            out["reason"] = "UNKNOWN_EVENT_TYPE"
            continue
        claim = claims.get(ev.get("claim_id"))
        if claim is None:
            out["outcome"] = "UNKNOWN_CLAIM"
            out["reason"] = "CLAIM_ID_NOT_FOUND"
            continue
        current = claim.get("status")
        out["from_status"] = current

        if etype == "QUERY":
            _audit(claim, "PROVIDER_QUERY", ev.get("at"), actor,
                   source_ref=ev.get("source_ref"),
                   reason=ev.get("reason_code"))
            out["outcome"] = "APPLIED"
            out["to_status"] = current
            continue

        if etype == "EXPIRY_CHECK":
            deadline = claim.get("deadline_date")
            at = ev.get("at") or now
            if current in TERMINAL:
                out["outcome"] = "APPLIED"
                out["to_status"] = current
                continue
            if deadline and at and at[:10] > deadline:
                if EXPIRED in (EDGES.get(current) or set()):
                    claim["status"] = EXPIRED
                    _audit(claim, "STATUS_TRANSITION", at, actor,
                           from_status=current, to_status=EXPIRED,
                           reason="RECOVERY_DEADLINE_PASSED",
                           event_ref=ev.get("source_ref"))
                    out["outcome"] = "APPLIED"
                    out["to_status"] = EXPIRED
                else:
                    out["outcome"] = "REJECTED_EVENT"
                    out["reason"] = (
                        f"INVALID_TRANSITION:{current}->EXPIRED")
            else:
                _audit(claim, "EXPIRY_CHECKED", at, actor,
                       deadline=deadline, result="NOT_EXPIRED")
                out["outcome"] = "APPLIED"
                out["to_status"] = current
            continue

        target = _EVENT_TARGET[etype]
        if current in TERMINAL:
            out["outcome"] = "REJECTED_EVENT"
            out["reason"] = f"CLAIM_TERMINAL:{current}"
            continue
        if target not in (EDGES.get(current) or set()):
            out["outcome"] = "REJECTED_EVENT"
            out["reason"] = (
                f"INVALID_TRANSITION:{current}->{target}")
            continue
        claim["status"] = target
        _audit(claim, "STATUS_TRANSITION", ev.get("at"), actor,
               from_status=current, to_status=target,
               reason=ev.get("reason_code"),
               event_ref=ev.get("source_ref"))
        out["outcome"] = "APPLIED"
        out["to_status"] = target

    summary = {}
    for o in outcomes:
        summary[o["outcome"]] = summary.get(o["outcome"], 0) + 1
    doc = {
        "schema": STATUS_SCHEMA,
        "generated_at": now,
        "canonical_event_id": cases_doc.get("canonical_event_id"),
        "outcomes": outcomes,
        "summary": summary,
    }
    # refrescar summary del cases doc tras las transiciones
    counts = {}
    for c in cases_doc.get("claims") or []:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    cases_doc["summary"] = counts
    return doc
