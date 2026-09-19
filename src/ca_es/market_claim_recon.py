"""P16.4 — CA_ES_MARKET_CLAIM_RECON_V1: settlement del claim.

La liquidacion de una market claim viaja como movimiento
cash/security ordinario (MT566/camt/P13). La ligadura es SOLO
por referencia explicita: claim_id, referencias TxRef de la
seev.050, settlement_instruction_id, transaction_id. Un
movimiento con el mismo importe sin referencia NO liga —
nunca bind por amount+date.

- suma ligada == esperado -> MATCH (claim -> SETTLED)
- suma ligada != esperado -> AMOUNT_MISMATCH con
  settled/outstanding explicitos (parcial estructural: el claim
  queda abierto en PARTIALLY_SETTLED; una liquidacion posterior
  puede completar -> MATCH). Overpaid -> reason
  SETTLEMENT_EXCEEDS_EXPECTED.
- moneda divergente en movimiento ligado -> INDETERMINATE /
  FX_REQUIRED.
- claims EXPECTED (sin seev.050) -> NOT_NOTIFIED.
- REJECTED/CANCELLED/SETTLED se propagan.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .custody_bind import REFERENCE_FIELDS
from .market_claim_case import (ACCEPTED, CANCELLED, EXPECTED,
                                MATCHING, NOTIFIED,
                                PARTIALLY_SETTLED, PENDING,
                                REJECTED, SETTLED)

RECON_SCHEMA = "CA_ES_MARKET_CLAIM_RECON_V1"

MATCH = "MATCH"
AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
NO_SETTLEMENT_OBSERVED = "NO_SETTLEMENT_OBSERVED"
NOT_NOTIFIED = "NOT_NOTIFIED"
INDETERMINATE = "INDETERMINATE"

_SETTLEABLE = {NOTIFIED, PENDING, MATCHING, ACCEPTED,
               PARTIALLY_SETTLED}


def _dec(raw):
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def _fmt(value):
    return format(value, "f") if value is not None else None


def _claim_refs(claim: dict) -> set[str]:
    refs = set()
    for r in (claim.get("binding_references") or []):
        if r:
            refs.add(str(r))
    for r in (claim.get("notification_refs") or []):
        if r:
            refs.add(str(r))
    if claim.get("claim_id"):
        refs.add(claim["claim_id"])
    if claim.get("transaction_id"):
        refs.add(claim["transaction_id"])
    if claim.get("settlement_instruction_id"):
        refs.add(claim["settlement_instruction_id"])
    return refs


def _movement_refs(movement: dict) -> list[str]:
    refs = []
    if movement.get("source_reference"):
        refs.append(str(movement["source_reference"]))
    for field in REFERENCE_FIELDS:
        if movement.get(field):
            refs.append(str(movement[field]))
    return refs


def claim_recon(claims_doc: dict,
                movements_docs: list[dict] | None = None,
                now: str | None = None) -> dict:
    """claims + cash/security movements -> RECON doc."""
    movements = []
    for doc in movements_docs or []:
        movements.extend(doc.get("movements") or [])

    items = []
    for claim in claims_doc.get("claims") or []:
        cid = claim.get("claim_id")
        status = claim.get("status")
        item = {
            "claim_id": cid,
            "canonical_event_id": claim.get("canonical_event_id"),
            "account_id": claim.get("account_id"),
            "claim_status": status,
            "claim_type": claim.get("claim_type"),
            "expected_amount": claim.get("expected_amount"),
            "expected_quantity": claim.get("expected_quantity"),
            "currency": claim.get("currency"),
            "settled_amount": None,
            "settled_quantity": None,
            "outstanding_amount": None,
            "outstanding_quantity": None,
            "status": None,
            "reason_codes": [],
            "bound_movement_ids": [],
            "bound_references": [],
        }

        if status == EXPECTED:
            item["status"] = NOT_NOTIFIED
            item["reason_codes"] = ["CLAIM_NOT_YET_NOTIFIED"]
            items.append(item)
            continue
        if status in (REJECTED, CANCELLED, SETTLED):
            item["status"] = status
            items.append(item)
            continue
        if status not in _SETTLEABLE:
            item["status"] = INDETERMINATE
            item["reason_codes"] = [f"CLAIM_STATUS:{status}"]
            items.append(item)
            continue

        refs = _claim_refs(claim)
        bound = []
        for m in movements:
            hit = refs & set(_movement_refs(m))
            if hit:
                bound.append((m, sorted(hit)[0]))

        if not bound:
            item["status"] = NO_SETTLEMENT_OBSERVED
            item["reason_codes"] = ["NO_EXPLICIT_REFERENCE_MATCH"]
            item["settled_amount"] = "0"
            item["outstanding_amount"] = claim.get(
                "expected_amount")
            item["outstanding_quantity"] = claim.get(
                "expected_quantity")
            items.append(item)
            continue

        total_amt = Decimal(0)
        total_qty = Decimal(0)
        fx = False
        for m, ref in bound:
            if m.get("currency") is not None and item.get(
                    "currency") is not None and \
                    m.get("currency") != item["currency"]:
                fx = True
                continue
            amt = _dec(m.get("amount"))
            if amt is not None:
                total_amt += amt
                item["bound_movement_ids"].append(
                    m.get("movement_id"))
                item["bound_references"].append(ref)
                continue
            qty = _dec(m.get("quantity") or m.get("unit"))
            if qty is not None:
                total_qty += qty
                item["bound_movement_ids"].append(
                    m.get("movement_id"))
                item["bound_references"].append(ref)

        if fx:
            item["status"] = INDETERMINATE
            item["reason_codes"] = ["FX_REQUIRED"]
            items.append(item)
            continue

        item["settled_amount"] = _fmt(total_amt)
        item["settled_quantity"] = _fmt(total_qty)

        expected_amt = _dec(claim.get("expected_amount"))
        expected_qty = _dec(claim.get("expected_quantity"))
        if expected_amt is not None:
            if total_amt == expected_amt:
                item["status"] = MATCH
                item["outstanding_amount"] = "0"
            else:
                item["status"] = AMOUNT_MISMATCH
                item["outstanding_amount"] = _fmt(
                    expected_amt - total_amt)
                item["reason_codes"] = [
                    "SETTLEMENT_EXCEEDS_EXPECTED"
                    if total_amt > expected_amt
                    else "SETTLEMENT_BELOW_EXPECTED"]
        elif expected_qty is not None:
            if total_qty == expected_qty:
                item["status"] = MATCH
                item["outstanding_quantity"] = "0"
            else:
                item["status"] = QUANTITY_MISMATCH
                item["outstanding_quantity"] = _fmt(
                    expected_qty - total_qty)
                item["reason_codes"] = [
                    "SETTLEMENT_EXCEEDS_EXPECTED"
                    if total_qty > expected_qty
                    else "SETTLEMENT_BELOW_EXPECTED"]
        else:
            item["status"] = INDETERMINATE
            item["reason_codes"] = ["EXPECTED_BASIS_NOT_AVAILABLE"]
        items.append(item)

    summary = {}
    for i in items:
        summary[i["status"]] = summary.get(i["status"], 0) + 1
    return {
        "schema": RECON_SCHEMA,
        "generated_at": now,
        "canonical_event_id": claims_doc.get("canonical_event_id"),
        "case_scope": "market-claim",
        "items": items,
        "summary": summary,
    }
