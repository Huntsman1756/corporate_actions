"""P16.6 — CA_ES_MARKET_CLAIM_CANCELLATION_V1: intents y outcomes.

La cancelacion es un intent SEPARADO del estado del claim:

- seev.051 -> intent registrado (REQUESTED); NO cancela.
- seev.053 -> outcome: CANCEL_ACCEPTED/CANCEL_COMPLETED cierra;
  CANCEL_REJECTED rechaza el intent; CANCEL_PENDING lo mantiene.

Cada item registra claim_id, intent_ref (MktClmCreId/TxRef de la
051), outcome_ref (MktClmCxlReqId de la 053), outcome y estado
resultante del claim. Sin evidencia explicita de outcome
aceptado, el claim NUNCA queda CANCELLED por este doc.
"""

from __future__ import annotations

CANCELLATION_SCHEMA = "CA_ES_MARKET_CLAIM_CANCELLATION_V1"

REQUESTED = "REQUESTED"
ACCEPTED_OUTCOME = "ACCEPTED"
REJECTED_OUTCOME = "REJECTED"
PENDING_OUTCOME = "PENDING"
NO_OUTCOME = "NO_OUTCOME"

_OUTCOME_BY_STATUS = {
    "CANCEL_ACCEPTED": ACCEPTED_OUTCOME,
    "CANCEL_COMPLETED": ACCEPTED_OUTCOME,
    "CANCEL_REJECTED": REJECTED_OUTCOME,
    "CANCEL_PENDING": PENDING_OUTCOME,
}


def cancellation_doc(claims_doc: dict,
                     cancel_events: list[dict],
                     now: str | None = None) -> dict:
    """Eventos de cancelacion ya aplicados -> doc de intents/
    outcomes por claim.

    cancel_events: eventos CANCELLATION_REQUEST /
    CANCELLATION_STATUS con claim_id ligado + source_ref.
    """
    intents: dict[str, dict] = {}
    for ev in cancel_events or []:
        cid = ev.get("claim_id")
        if not cid:
            continue
        item = intents.setdefault(cid, {
            "claim_id": cid,
            "intents": [],
            "outcomes": [],
            "current_outcome": NO_OUTCOME,
        })
        if ev.get("event_type") == "CANCELLATION_REQUEST":
            item["intents"].append({
                "intent_ref": ev.get("source_ref"),
                "at": ev.get("at"),
                "message_identifier": ev.get(
                    "message_identifier"),
            })
            if item["current_outcome"] == NO_OUTCOME:
                item["current_outcome"] = REQUESTED
        elif ev.get("event_type") == "CANCELLATION_STATUS":
            outcome = _OUTCOME_BY_STATUS.get(
                ev.get("cancel_outcome"), "UNSUPPORTED")
            item["outcomes"].append({
                "outcome_ref": ev.get("source_ref"),
                "at": ev.get("at"),
                "outcome": outcome,
                "message_identifier": ev.get(
                    "message_identifier"),
            })
            item["current_outcome"] = outcome

    items = []
    claims = {c.get("claim_id"): c
              for c in claims_doc.get("claims") or []}
    for cid in sorted(intents):
        item = intents[cid]
        claim = claims.get(cid) or {}
        item["claim_status"] = claim.get("status")
        items.append(item)
    summary = {}
    for i in items:
        o = i["current_outcome"]
        summary[o] = summary.get(o, 0) + 1
    return {
        "schema": CANCELLATION_SCHEMA,
        "generated_at": now,
        "canonical_event_id": claims_doc.get("canonical_event_id"),
        "items": items,
        "summary": summary,
    }
