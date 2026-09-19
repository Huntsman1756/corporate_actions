"""P15.3 — CA_ES_TAX_RECOVERY_CASE_V1: claims con lifecycle.

Un claim nace SOLO de un assessment ELIGIBLE. Las salidas
NOT_APPLICABLE / INDETERMINATE del assessment no son claims: son
resultados de evaluacion y quedan en el assessment doc.

Separacion semantica obligatoria:

    WITHHOLDING_MISMATCH != RECOVERY_ELIGIBLE
    RECOVERY_ELIGIBLE    != READY_TO_SUBMIT
    SUBMITTED            != ACCEPTED
    ACCEPTED             != REFUND_PAID

Transiciones validadas por EDGES; cada salto queda en history[]
(at/actor/reason/event_ref). Terminales: REJECTED, PAID, APPLIED,
EXPIRED. PARTIALLY_PAID es estructural: el primer abono NO
liquida el claim.
"""

from __future__ import annotations

import copy

CASES_SCHEMA = "CA_ES_TAX_RECOVERY_CASE_V1"

ASSESSED = "ASSESSED"
PENDING_DOCUMENTATION = "PENDING_DOCUMENTATION"
READY_TO_SUBMIT = "READY_TO_SUBMIT"
SUBMITTED = "SUBMITTED"
ACKNOWLEDGED = "ACKNOWLEDGED"
ACCEPTED = "ACCEPTED"
REJECTED = "REJECTED"
PARTIALLY_PAID = "PARTIALLY_PAID"
PAID = "PAID"
APPLIED = "APPLIED"          # relief at source aplicado (terminal)
EXPIRED = "EXPIRED"

TERMINAL = {REJECTED, PAID, APPLIED, EXPIRED}

EDGES = {
    ASSESSED: {PENDING_DOCUMENTATION, READY_TO_SUBMIT, EXPIRED},
    PENDING_DOCUMENTATION: {READY_TO_SUBMIT, EXPIRED},
    READY_TO_SUBMIT: {SUBMITTED, EXPIRED},
    SUBMITTED: {ACKNOWLEDGED, REJECTED, EXPIRED},
    ACKNOWLEDGED: {ACCEPTED, REJECTED, PARTIALLY_PAID, PAID,
                   APPLIED, EXPIRED},
    ACCEPTED: {PARTIALLY_PAID, PAID, APPLIED, EXPIRED},
    PARTIALLY_PAID: {PARTIALLY_PAID, PAID, EXPIRED},
}


def _audit(claim, event_type, at, actor, **extra):
    claim.setdefault("history", []).append(
        {"type": event_type, "at": at, "actor": actor, **extra})


def open_claims(assessment_doc: dict, *,
                doc_complete: dict[str, bool] | None = None,
                actor: str = "system",
                now: str | None = None) -> dict:
    """Assessment ELIGIBLE -> claims.

    doc_complete: {claim_reference: bool} — si se conoce el estado
    del document set, el claim abre directamente en
    READY_TO_SUBMIT (complete) o PENDING_DOCUMENTATION (incomplete).
    Sin doc set: ASSESSED.
    """
    doc_complete = doc_complete or {}
    claims = []
    for item in assessment_doc.get("items") or []:
        if item.get("status") != "ELIGIBLE":
            continue
        ref = item.get("claim_reference")
        claim = {
            "claim_id": ref,
            "canonical_event_id": assessment_doc.get(
                "canonical_event_id"),
            "account_id": item.get("account_id"),
            "rule_id": item.get("rule_id"),
            "recovery_method": item.get("recovery_method"),
            "claim_kind": item.get("claim_kind"),
            "claim_amount": item.get("recoverable_amount"),
            "entitled_rate_fraction": item.get(
                "entitled_rate_fraction"),
            "withheld_amount": item.get("withheld_amount"),
            "withheld_rate_fraction": item.get(
                "withheld_rate_fraction"),
            "deadline_date": item.get("deadline_date"),
            "status": ASSESSED,
            "refunded_amount": None,
            "evidence_refs": list(item.get("evidence_refs") or []),
            "history": [],
        }
        _audit(claim, "CLAIM_OPENED", now, actor,
               from_status=None, to_status=ASSESSED)
        if ref in doc_complete:
            target = READY_TO_SUBMIT if doc_complete[ref] \
                else PENDING_DOCUMENTATION
            claim["status"] = target
            _audit(claim, "DOC_SET_EVALUATED", now, actor,
                   from_status=ASSESSED, to_status=target)
        claims.append(claim)
    claims.sort(key=lambda c: c["claim_id"])
    return {
        "schema": CASES_SCHEMA,
        "generated_at": now,
        "canonical_event_id": assessment_doc.get(
            "canonical_event_id"),
        "claims": claims,
        "summary": _summary(claims),
    }


def _summary(claims):
    out = {}
    for c in claims:
        out[c["status"]] = out.get(c["status"], 0) + 1
    return out


def find_claim(cases_doc: dict, claim_id: str) -> dict | None:
    for c in cases_doc.get("claims") or []:
        if c.get("claim_id") == claim_id:
            return c
    return None


def transition(claim: dict, to_status: str, *, at: str | None,
               actor: str, reason: str | None = None,
               event_ref: str | None = None) -> dict:
    """Aplica una transicion validada. Devuelve el claim mutado;
    ValueError si el salto no esta en EDGES."""
    current = claim.get("status")
    if current in TERMINAL:
        raise ValueError(f"CLAIM_TERMINAL:{current}")
    allowed = EDGES.get(current) or set()
    if to_status not in allowed:
        raise ValueError(
            f"INVALID_TRANSITION:{current}->{to_status}")
    claim["status"] = to_status
    _audit(claim, "STATUS_TRANSITION", at, actor,
           from_status=current, to_status=to_status,
           reason=reason, event_ref=event_ref)
    return claim


def merge_claims(previous_doc: dict | None, new_doc: dict,
                 now: str | None = None) -> dict:
    """Persistencia determinista: claims previos por claim_id +
    nuevos. Los nuevos con claim_id existente NO se reabren: el
    claim es una entidad viva; el assessment es re-evaluable."""
    prev = {c["claim_id"]: c
            for c in (previous_doc or {}).get("claims") or []}
    merged = []
    seen = set()
    for claim in new_doc.get("claims") or []:
        cid = claim["claim_id"]
        seen.add(cid)
        if cid in prev:
            kept = copy.deepcopy(prev[cid])
            # actualiza campos factuales del assessment, preserva
            # status/history del lifecycle
            for f in ("claim_amount", "withheld_amount",
                      "withheld_rate_fraction",
                      "entitled_rate_fraction", "deadline_date",
                      "evidence_refs"):
                kept[f] = claim.get(f)
            merged.append(kept)
        else:
            merged.append(claim)
    for cid, claim in prev.items():
        if cid not in seen:
            merged.append(copy.deepcopy(claim))
    merged.sort(key=lambda c: c["claim_id"])
    new_doc = dict(new_doc)
    new_doc["claims"] = merged
    new_doc["summary"] = _summary(merged)
    return new_doc
