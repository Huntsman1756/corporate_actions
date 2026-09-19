"""P17.5 — CA_ES_SETTLEMENT_RECON_V1: consistencia factual del
ledger de settlement por transaccion.

Compara cantidad instruida vs cumulative settled + conflictos
detectados en el merge. Nunca fabrica movimientos parciales:
PARTIALLY_SETTLED es un estado factual, no dos transacciones.

Statuses:
- MATCH: settled == instructed (con instruccion presente).
- PARTIALLY_SETTLED: 0 < settled < instructed (factual).
- OVER_SETTLED: settled > instructed -> caso P3.5.
- NO_INSTRUCTION_BASIS: confirmacion/status sin instruccion.
- NO_SETTLEMENT_OBSERVED: instruccion sin confirmacion.
- QUANTITY_CONFLICT: evidencia conflictiva de cantidad.
- CANCELLED / FAILED / MATCHED / PENDING / INSTRUCTED:
  passthrough del ciclo (informativos).
- INSUFFICIENT_IDENTITY: observaciones huerfanas agregadas.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

RECON_SCHEMA = "CA_ES_SETTLEMENT_RECON_V1"

MATCH = "MATCH"
PARTIALLY_SETTLED = "PARTIALLY_SETTLED"
OVER_SETTLED = "OVER_SETTLED"
NO_INSTRUCTION_BASIS = "NO_INSTRUCTION_BASIS"
NO_SETTLEMENT_OBSERVED = "NO_SETTLEMENT_OBSERVED"
QUANTITY_CONFLICT = "QUANTITY_CONFLICT"
INSUFFICIENT_IDENTITY = "INSUFFICIENT_IDENTITY"


def _dec(raw):
    if raw is None:
        return None
    try:
        v = Decimal(str(raw).replace(",", "."))
    except InvalidOperation:
        return None
    return v if v.is_finite() else None


def settlement_recon(ledger_doc: dict,
                     now: str | None = None) -> dict:
    items = []
    for tx in sorted(
            ledger_doc.get("transactions") or [],
            key=lambda t: t.get("transaction_id") or ""):
        item = {
            "transaction_id": tx.get("transaction_id"),
            "account_id": tx.get("account_id"),
            "isin": tx.get("isin"),
            "tx_status": tx.get("status"),
            "instructed_quantity": tx.get("instructed_quantity"),
            "settled_quantity": tx.get("settled_quantity"),
            "outstanding_quantity": None,
            "status": None,
            "reason_codes": [],
            "conflicts": list(tx.get("conflicts") or []),
            "provenance": [{
                "source": "settlement-feed",
                "ref": tx.get("transaction_id")}],
        }
        conflicts = tx.get("conflicts") or []
        qty_conf = [c for c in conflicts
                    if c.get("field") in (
                        "instructed_quantity",)]
        instructed = _dec(tx.get("instructed_quantity"))
        settled = _dec(tx.get("settled_quantity")) or Decimal(0)
        tx_status = tx.get("status")

        if qty_conf:
            item["status"] = QUANTITY_CONFLICT
            item["reason_codes"] = ["INSTRUCTED_QUANTITY_CONFLICT"]
        elif tx_status in ("CANCELLED", "FAILED"):
            item["status"] = tx_status
        elif not tx.get("has_instruction"):
            item["status"] = NO_INSTRUCTION_BASIS
            item["reason_codes"] = ["OBSERVED_WITHOUT_INSTRUCTION"]
        elif instructed is None:
            item["status"] = NO_INSTRUCTION_BASIS
            item["reason_codes"] = [
                "INSTRUCTED_QUANTITY_NOT_OBSERVED"]
        elif not tx.get("has_confirmation") and settled == 0:
            item["status"] = NO_SETTLEMENT_OBSERVED
            item["outstanding_quantity"] = tx.get(
                "instructed_quantity")
            if tx_status == "MATCHED":
                item["reason_codes"] = ["MATCHED_NOT_SETTLED"]
        elif settled == instructed:
            item["status"] = MATCH
            item["outstanding_quantity"] = "0"
        elif settled > instructed:
            item["status"] = OVER_SETTLED
            item["outstanding_quantity"] = format(
                instructed - settled, "f")
            item["reason_codes"] = ["SETTLED_EXCEEDS_INSTRUCTED"]
        else:
            item["status"] = PARTIALLY_SETTLED
            item["outstanding_quantity"] = format(
                instructed - settled, "f")
        items.append(item)

    for orphan in ledger_doc.get("orphan_observations") or []:
        items.append({
            "transaction_id": None,
            "account_id": None, "isin": None,
            "tx_status": None,
            "instructed_quantity": None,
            "settled_quantity": None,
            "outstanding_quantity": None,
            "status": INSUFFICIENT_IDENTITY,
            "reason_codes": [orphan.get("reason")
                             or "NO_USABLE_REFERENCE"],
            "conflicts": [],
            "message_identifier": orphan.get("message_identifier"),
            "source_ref": orphan.get("source_ref"),
            "provenance": [{
                "source": "settlement-feed",
                "ref": orphan.get("source_ref")}],
        })

    summary = {}
    for i in items:
        summary[i["status"]] = summary.get(i["status"], 0) + 1
    return {
        "schema": RECON_SCHEMA,
        "generated_at": now,
        "items": items,
        "summary": {"by_status": summary, "items": len(items)},
    }
