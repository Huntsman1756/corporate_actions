"""P15.7 — CA_ES_TAX_RECOVERY_RECON_V1: refund cash reconciliation.

Claims CASH_REFUND vs movimientos observados (P13/P4):

- ligadura SOLO por referencia explicita: claim_id, instruction_id
  y referencias documentales TARE registradas en el doc set. Un
  movimiento con el mismo importe y fecha sin referencia NO liga
  (R11: NO_MATCH, nunca bind por amount+date).
- refund parcial: suma de abonos ligados; PARTIALLY_PAID no
  liquida el claim — OUTSTANDING persiste hasta PAID/EXPIRED.
- OVERPAID si la suma supera el claim -> caso.
- REJECTED/EXPIRED se propagan como items -> casos P3.5.
- FX: moneda divergente en abono ligado -> FX_REQUIRED
  (fail-closed, no suma).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .custody_bind import REFERENCE_FIELDS
from .tax_recovery_docs import DOCSET_SCHEMA

RECON_SCHEMA = "CA_ES_TAX_RECOVERY_RECON_V1"

PAID = "PAID"
PARTIALLY_PAID = "PARTIALLY_PAID"
OVERPAID = "OVERPAID"
NO_REFUND_OBSERVED = "NO_REFUND_OBSERVED"
NOT_SUBMITTED = "NOT_SUBMITTED"
NOT_APPLICABLE = "NOT_APPLICABLE"
REJECTED = "REJECTED"
EXPIRED = "EXPIRED"
INDETERMINATE = "INDETERMINATE"

_PRE_SUBMISSION = {"ASSESSED", "PENDING_DOCUMENTATION",
                   "READY_TO_SUBMIT"}


def _dec(raw):
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def _fmt(value):
    return format(value, "f") if value is not None else None


def _claim_refs(claim: dict, instruction: dict | None,
                doc_set: dict | None) -> set[str]:
    """Referencias explicitas que ligan un abono al claim."""
    refs = set()
    if claim.get("claim_id"):
        refs.add(claim["claim_id"])
    if instruction and instruction.get("instruction_id"):
        refs.add(instruction["instruction_id"])
    for item in (doc_set or {}).get("items") or []:
        if item.get("doc_type") == "RECLAIM_DOCUMENTATION_REFERENCE" \
                and item.get("reference"):
            refs.add(item["reference"])
    for r in claim.get("binding_references") or []:
        refs.add(r)
    return refs


def _movement_refs(movement: dict) -> list[str]:
    refs = []
    if movement.get("source_reference"):
        refs.append(str(movement["source_reference"]))
    for field in REFERENCE_FIELDS:
        if movement.get(field):
            refs.append(str(movement[field]))
    return refs


def _observation_refs(entry: dict) -> list[str]:
    refs = []
    for field in REFERENCE_FIELDS:
        if entry.get(field):
            refs.append(str(entry[field]))
    structured = (entry.get("structured_details") or {}).get(
        "refs") or {}
    for value in structured.values():
        if value:
            refs.append(str(value))
    return refs


def recovery_recon(cases_doc: dict,
                   instructions_doc: dict | None = None,
                   doc_sets_doc: dict | None = None,
                   movements_docs: list[dict] | None = None,
                   observation_docs: list[dict] | None = None,
                   now: str | None = None) -> dict:
    """-> CA_ES_TAX_RECOVERY_RECON_V1."""
    instructions = {i.get("claim_id"): i for i in
                    (instructions_doc or {}).get(
                        "instructions") or []}
    sets = (doc_sets_doc or {}).get("sets") or {} \
        if (doc_sets_doc or {}).get("schema") == DOCSET_SCHEMA \
        else {}

    movements = []
    for doc in movements_docs or []:
        movements.extend(doc.get("movements") or [])
    entries = []
    for doc in observation_docs or []:
        entries.extend(doc.get("entries") or [])

    items = []
    for claim in cases_doc.get("claims") or []:
        cid = claim.get("claim_id")
        status = claim.get("status")
        amount = _dec((claim.get("claim_amount") or {}).get(
            "normalized"))
        currency = (claim.get("claim_amount") or {}).get(
            "currency")

        item = {
            "claim_id": cid,
            "canonical_event_id": claim.get("canonical_event_id"),
            "account_id": claim.get("account_id"),
            "recovery_method": claim.get("recovery_method"),
            "claim_status": status,
            "expected_amount": _fmt(amount),
            "refunded_amount": None,
            "outstanding_amount": None,
            "currency": currency,
            "status": None,
            "reason_codes": [],
            "bound_movement_ids": [],
            "bound_references": [],
        }

        if claim.get("claim_kind") == "RATE_RELIEF":
            item["status"] = NOT_APPLICABLE
            item["reason_codes"] = ["RATE_RELIEF_NO_REFUND_LEG"]
            items.append(item)
            continue
        if status in _PRE_SUBMISSION:
            item["status"] = NOT_SUBMITTED
            item["reason_codes"] = ["CLAIM_NOT_YET_SUBMITTED"]
            items.append(item)
            continue
        if status == REJECTED:
            item["status"] = REJECTED
            item["reason_codes"] = ["CLAIM_REJECTED"]
            items.append(item)
            continue
        if status == EXPIRED:
            item["status"] = EXPIRED
            item["reason_codes"] = ["RECOVERY_DEADLINE_PASSED"]
            items.append(item)
            continue

        refs = _claim_refs(claim, instructions.get(cid),
                           sets.get(cid))
        bound = []
        for m in movements:
            hit = refs & set(_movement_refs(m))
            if hit:
                bound.append((m, sorted(hit)[0]))
        for e in entries:
            hit = refs & set(_observation_refs(e))
            if hit:
                bound.append(({
                    "movement_id": e.get("entry_id"),
                    "amount": e.get("amount"),
                    "currency": e.get("currency"),
                    "direction": e.get("debit_credit"),
                    "value_date": e.get("value_date"),
                }, sorted(hit)[0]))

        if not bound:
            item["status"] = NO_REFUND_OBSERVED
            item["reason_codes"] = ["NO_EXPLICIT_REFERENCE_MATCH"]
            item["refunded_amount"] = "0"
            item["outstanding_amount"] = _fmt(amount)
            items.append(item)
            continue

        total = Decimal(0)
        fx = False
        for m, ref in bound:
            if m.get("currency") is not None and currency is not None \
                    and m.get("currency") != currency:
                fx = True
                continue
            amt = _dec(m.get("amount"))
            if amt is None:
                continue
            # abonos de refund se esperan CREDIT; un DEBIT ligado se
            # registra pero no compensa el claim
            if m.get("direction") not in (None, "CRDT", "CREDIT"):
                continue
            total += amt
            item["bound_movement_ids"].append(m.get("movement_id"))
            item["bound_references"].append(ref)

        if fx:
            item["status"] = INDETERMINATE
            item["reason_codes"] = ["FX_REQUIRED"]
            item["refunded_amount"] = _fmt(total)
            items.append(item)
            continue

        item["refunded_amount"] = _fmt(total)
        if amount is None:
            item["status"] = INDETERMINATE
            item["reason_codes"] = ["CLAIM_AMOUNT_NOT_AVAILABLE"]
        elif total > amount:
            item["status"] = OVERPAID
            item["reason_codes"] = ["REFUND_EXCEEDS_CLAIM"]
            item["outstanding_amount"] = "0"
        elif total == amount:
            item["status"] = PAID
            item["outstanding_amount"] = "0"
        else:
            item["status"] = PARTIALLY_PAID
            item["reason_codes"] = ["REFUND_PARTIAL"]
            item["outstanding_amount"] = _fmt(amount - total)
        items.append(item)

    summary = {}
    for i in items:
        summary[i["status"]] = summary.get(i["status"], 0) + 1
    return {
        "schema": RECON_SCHEMA,
        "generated_at": now,
        "canonical_event_id": cases_doc.get("canonical_event_id"),
        "case_scope": "tax-recovery",
        "items": items,
        "summary": summary,
    }
