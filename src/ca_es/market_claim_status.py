"""P16.5 — CA_ES_MARKET_CLAIM_STATUS_V1: eventos sobre claims.

Eventos explicitos (cada uno con claim_id ya ligado por
referencia via bind_claim — el caller proyecta y liga):

- NOTIFICATION (seev.050): EXPECTED -> NOTIFIED. Registra
  notification_refs + binding_references. Si el importe/cantidad
  observado difiere del esperado -> CONFLICTING_NOTIFICATION en
  history; el claim NUNCA se sobrescribe (M12).
- STATUS (seev.052): Pdg/AccptdForFrthrPrcg/MtchgSts/Rjctd/Canc
  -> PENDING/ACCEPTED/MATCHING/REJECTED/CANCELLED.
- CANCELLATION_REQUEST (seev.051): -> CANCELLATION_REQUESTED;
  guarda pre_cancellation_status (intent != outcome).
- CANCELLATION_STATUS (seev.053): CANCEL_ACCEPTED/CANCEL_COMPLETED
  -> CANCELLED; CANCEL_REJECTED -> restaura
  pre_cancellation_status; CANCEL_PENDING -> se mantiene.
- SETTLEMENT_OBSERVED (recon): -> PARTIALLY_SETTLED / SETTLED.

Idempotencia: mismo source_ref ya registrado ->
DUPLICATE_IGNORED (M11). Transiciones invalidas ->
REJECTED_EVENT, nunca aplicadas en silencio.
"""

from __future__ import annotations

from .market_claim_case import (ACCEPTED, CANCELLATION_REQUESTED,
                                CANCELLED, CLAIMS_SCHEMA, EXPECTED,
                                MATCHING, NOTIFIED,
                                PARTIALLY_SETTLED, PENDING,
                                SETTLED, find_claim, transition)

STATUS_SCHEMA = "CA_ES_MARKET_CLAIM_STATUS_V1"

APPLIED = "APPLIED"
REJECTED_EVENT = "REJECTED_EVENT"
DUPLICATE_IGNORED = "DUPLICATE_IGNORED"
CONFLICTING_NOTIFICATION = "CONFLICTING_NOTIFICATION"

_EVENT_TYPES = {
    "NOTIFICATION", "STATUS", "CANCELLATION_REQUEST",
    "CANCELLATION_STATUS", "SETTLEMENT_OBSERVED",
}

_STATUS_TARGETS = {"ACCEPTED", "PENDING", "MATCHING", "REJECTED",
                   "CANCELLED"}


def _audit(claim, event_type, at, actor, **extra):
    claim.setdefault("history", []).append(
        {"type": event_type, "at": at, "actor": actor, **extra})


def _seen(claim, source_ref):
    if not source_ref:
        return False
    for ref in (claim.get("notification_refs") or []):
        if ref == source_ref:
            return True
    for h in claim.get("history") or []:
        if h.get("source_ref") == source_ref:
            return True
    return False


def _register_refs(claim, projection):
    for ref in sorted(
            {r for r in _proj_refs(projection) if r}):
        refs = claim.setdefault("binding_references", [])
        if ref not in refs:
            refs.append(ref)


def _proj_refs(projection):
    r = (projection or {}).get("references") or {}
    out = list(r.values())
    if (projection or {}).get("related_settlement_instruction_id"):
        out.append(projection["related_settlement_instruction_id"])
    return out


def _notification(claim, event, at, actor):
    """seev.050 ligada -> NOTIFIED + chequeo de conflicto."""
    projection = event.get("projection") or {}
    conflicts = []
    observed_amt = event.get("observed_amount")
    if observed_amt is not None and claim.get(
            "expected_amount") is not None and \
            str(observed_amt) != str(claim["expected_amount"]):
        conflicts.append("AMOUNT_DIFFERS")
    observed_qty = event.get("observed_quantity")
    if observed_qty is not None and claim.get(
            "expected_quantity") is not None and \
            str(observed_qty) != str(claim["expected_quantity"]):
        conflicts.append("QUANTITY_DIFFERS")

    claim.setdefault("notification_refs", []).append(
        event.get("source_ref"))
    _register_refs(claim, projection)
    outcome = APPLIED
    if claim.get("status") == EXPECTED:
        transition(claim, NOTIFIED, at=at, actor=actor,
                   reason="SEEV050_BOUND",
                   event_ref=event.get("source_ref"))
    if conflicts:
        _audit(claim, "CONFLICTING_NOTIFICATION", at, actor,
               conflicts=conflicts,
               observed_amount=observed_amt,
               observed_quantity=observed_qty,
               source_ref=event.get("source_ref"))
        outcome = CONFLICTING_NOTIFICATION
    return outcome


def _cancel_status(claim, event, at, actor):
    outcome = event.get("cancel_outcome")
    if outcome in ("CANCEL_ACCEPTED", "CANCEL_COMPLETED"):
        transition(claim, CANCELLED, at=at, actor=actor,
                   reason=f"SEEV053_{outcome}",
                   event_ref=event.get("source_ref"))
        return APPLIED
    if outcome == "CANCEL_REJECTED":
        prior = claim.get("pre_cancellation_status")
        if prior is None:
            _audit(claim, "CANCEL_REJECTED_NO_PRIOR", at, actor,
                   source_ref=event.get("source_ref"))
            return REJECTED_EVENT
        transition(claim, prior, at=at, actor=actor,
                   reason="SEEV053_CANCEL_REJECTED",
                   event_ref=event.get("source_ref"))
        claim.pop("pre_cancellation_status", None)
        return APPLIED
    if outcome == "CANCEL_PENDING":
        _audit(claim, "CANCEL_PENDING_OBSERVED", at, actor,
               source_ref=event.get("source_ref"))
        return APPLIED
    return REJECTED_EVENT


def apply_claim_events(claims_doc: dict, events: list[dict],
                       actor: str = "system",
                       now: str | None = None) -> dict:
    """Aplica eventos ordenados; muta claims in-place y devuelve
    el doc de status con outcomes por evento."""
    outcomes = []
    for i, ev in enumerate(events or []):
        etype = ev.get("event_type")
        at = ev.get("at") or now
        out = {"index": i, "event_type": etype,
               "claim_id": ev.get("claim_id"),
               "source_ref": ev.get("source_ref"),
               "outcome": None, "reason": None}
        if etype not in _EVENT_TYPES:
            out["outcome"] = REJECTED_EVENT
            out["reason"] = "UNKNOWN_EVENT_TYPE"
            outcomes.append(out)
            continue
        claim = find_claim(claims_doc, ev.get("claim_id") or "")
        if claim is None:
            out["outcome"] = REJECTED_EVENT
            out["reason"] = "CLAIM_NOT_FOUND"
            outcomes.append(out)
            continue
        if _seen(claim, ev.get("source_ref")):
            out["outcome"] = DUPLICATE_IGNORED
            outcomes.append(out)
            continue
        try:
            if etype == "NOTIFICATION":
                out["outcome"] = _notification(claim, ev, at, actor)
            elif etype == "STATUS":
                target = ev.get("internal_status")
                if target not in _STATUS_TARGETS:
                    out["outcome"] = REJECTED_EVENT
                    out["reason"] = f"UNSUPPORTED_STATUS:{target}"
                else:
                    transition(
                        claim, target, at=at, actor=actor,
                        reason=ev.get("status_choice"),
                        event_ref=ev.get("source_ref"))
                    out["outcome"] = APPLIED
            elif etype == "CANCELLATION_REQUEST":
                claim["pre_cancellation_status"] = claim.get(
                    "status")
                transition(
                    claim, CANCELLATION_REQUESTED, at=at,
                    actor=actor, reason="SEEV051_BOUND",
                    event_ref=ev.get("source_ref"))
                out["outcome"] = APPLIED
            elif etype == "CANCELLATION_STATUS":
                out["outcome"] = _cancel_status(claim, ev, at,
                                                actor)
            elif etype == "SETTLEMENT_OBSERVED":
                target = (SETTLED if ev.get("fully_settled")
                          else PARTIALLY_SETTLED)
                transition(claim, target, at=at, actor=actor,
                           reason="RECON_SETTLEMENT",
                           event_ref=ev.get("source_ref"))
                out["outcome"] = APPLIED
        except ValueError as e:
            out["outcome"] = REJECTED_EVENT
            out["reason"] = str(e)
        outcomes.append(out)

    summary = {}
    for o in outcomes:
        summary[o["outcome"]] = summary.get(o["outcome"], 0) + 1
    return {
        "schema": STATUS_SCHEMA,
        "generated_at": now,
        "canonical_event_id": claims_doc.get("canonical_event_id"),
        "outcomes": outcomes,
        "summary": summary,
    }
