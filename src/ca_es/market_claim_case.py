"""P16.3 — CA_ES_MARKET_CLAIM_V1: claim entity + lifecycle.

Un claim nace SOLO de un assessment PROVEN. Separacion
obligatoria:

    claim EXPECTED (regla probada)
        != NOTIFIED (seev.050 ligada)
        != ACCEPTED (seev.052)
        != SETTLED (movimiento observado)

La cancelacion es un intent separado del estado del claim:
seev.051 -> CANCELLATION_REQUESTED; CANCELLED solo con
evidencia explicita (seev.053 aceptada o seev.052 Canc).

PARTIALLY_SETTLED es estructural: la primera liquidacion
parcial no cierra el claim.
"""

from __future__ import annotations

import copy

CLAIMS_SCHEMA = "CA_ES_MARKET_CLAIM_V1"

EXPECTED = "EXPECTED"
NOTIFIED = "NOTIFIED"
PENDING = "PENDING"
MATCHING = "MATCHING"
ACCEPTED = "ACCEPTED"
REJECTED = "REJECTED"
CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
CANCELLED = "CANCELLED"
PARTIALLY_SETTLED = "PARTIALLY_SETTLED"
SETTLED = "SETTLED"

TERMINAL = {REJECTED, CANCELLED, SETTLED}

EDGES = {
    EXPECTED: {NOTIFIED, CANCELLED},
    NOTIFIED: {PENDING, MATCHING, ACCEPTED, REJECTED,
               CANCELLATION_REQUESTED, CANCELLED,
               PARTIALLY_SETTLED, SETTLED},
    PENDING: {MATCHING, ACCEPTED, REJECTED,
              CANCELLATION_REQUESTED, CANCELLED,
              PARTIALLY_SETTLED, SETTLED},
    MATCHING: {PENDING, ACCEPTED, REJECTED,
               CANCELLATION_REQUESTED, CANCELLED,
               PARTIALLY_SETTLED, SETTLED},
    ACCEPTED: {CANCELLATION_REQUESTED, CANCELLED,
               PARTIALLY_SETTLED, SETTLED},
    CANCELLATION_REQUESTED: {CANCELLED, NOTIFIED, PENDING,
                             MATCHING, ACCEPTED},
    PARTIALLY_SETTLED: {PARTIALLY_SETTLED, SETTLED},
}


def _audit(claim, event_type, at, actor, **extra):
    claim.setdefault("history", []).append(
        {"type": event_type, "at": at, "actor": actor, **extra})


def open_claims(assessment_doc: dict, *, actor: str = "system",
                now: str | None = None) -> dict:
    """Assessment PROVEN -> claims EXPECTED."""
    claims = []
    for item in assessment_doc.get("items") or []:
        if item.get("status") != "PROVEN":
            continue
        claim = {
            "claim_id": item.get("claim_id"),
            "canonical_event_id": assessment_doc.get(
                "canonical_event_id"),
            "event_type": assessment_doc.get("event_type"),
            "transaction_id": item.get("transaction_id"),
            "settlement_instruction_id": item.get(
                "settlement_instruction_id"),
            "account_id": item.get("account_id"),
            "isin": item.get("isin"),
            "quantity": item.get("quantity"),
            "tx_direction": item.get("tx_direction"),
            "rule_id": item.get("rule_id"),
            "claim_type": item.get("claim_type"),
            "proceeds_direction": item.get("proceeds_direction"),
            "expected_amount": item.get("expected_amount"),
            "expected_quantity": item.get("expected_quantity"),
            "currency": item.get("currency"),
            "target_isin": item.get("target_isin"),
            "deadline_date": item.get("deadline_date"),
            "status": EXPECTED,
            "settled_amount": None,
            "settled_quantity": None,
            "notification_refs": [],
            "binding_references": _binding_refs(item),
            "evidence_refs": list(item.get("evidence_refs") or []),
            "history": [],
        }
        _audit(claim, "CLAIM_OPENED", now, actor,
               from_status=None, to_status=EXPECTED)
        claims.append(claim)
    claims.sort(key=lambda c: c["claim_id"])
    return {
        "schema": CLAIMS_SCHEMA,
        "generated_at": now,
        "canonical_event_id": assessment_doc.get(
            "canonical_event_id"),
        "claims": claims,
        "summary": _summary(claims),
    }


def _binding_refs(item: dict) -> list[str]:
    refs = [item.get("claim_id"),
            item.get("transaction_id"),
            item.get("settlement_instruction_id")]
    return [r for r in refs if r]


def _summary(claims):
    out = {}
    for c in claims:
        out[c["status"]] = out.get(c["status"], 0) + 1
    return out


def find_claim(claims_doc: dict, claim_id: str) -> dict | None:
    for c in claims_doc.get("claims") or []:
        if c.get("claim_id") == claim_id:
            return c
    return None


def transition(claim: dict, to_status: str, *, at: str | None,
               actor: str, reason: str | None = None,
               event_ref: str | None = None) -> dict:
    """Transicion validada; ValueError si el salto no esta en
    EDGES."""
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
    """Claims previos por claim_id + nuevos. Un claim existente NO
    se reabre: el lifecycle persiste; el assessment solo refresca
    campos factuales."""
    prev = {c["claim_id"]: c
            for c in (previous_doc or {}).get("claims") or []}
    merged = []
    seen = set()
    for claim in new_doc.get("claims") or []:
        cid = claim["claim_id"]
        seen.add(cid)
        if cid in prev:
            kept = copy.deepcopy(prev[cid])
            for f in ("expected_amount", "expected_quantity",
                      "deadline_date", "binding_references",
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
