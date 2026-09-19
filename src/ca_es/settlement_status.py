"""P17.3 — CA_ES_SETTLEMENT_STATUS_V1: vista auditable del ciclo
de cada transaccion del ledger.

No deriva nada nuevo: consolida lo ya aplicado por
build_ledger en una vista por tx con history ordenada y
deltas de estado. MATCHED != SETTLED; partial != full.
"""

from __future__ import annotations

STATUS_SCHEMA = "CA_ES_SETTLEMENT_STATUS_V1"


def status_doc(ledger_doc: dict, now: str | None = None) -> dict:
    items = []
    for tx in sorted(
            ledger_doc.get("transactions") or [],
            key=lambda t: t.get("transaction_id") or ""):
        items.append({
            "transaction_id": tx.get("transaction_id"),
            "account_id": tx.get("account_id"),
            "isin": tx.get("isin"),
            "direction": tx.get("direction"),
            "status": tx.get("status"),
            "matching_status": tx.get("matching_status"),
            "processing_status": tx.get("processing_status"),
            "settlement_status_observed": tx.get(
                "settlement_status_observed"),
            "instructed_quantity": tx.get("instructed_quantity"),
            "settled_quantity": tx.get("settled_quantity"),
            "remaining_quantity": tx.get("remaining_quantity"),
            "partial": bool(tx.get("partial")),
            "quantity_semantics": tx.get("quantity_semantics"),
            "trade_date": tx.get("trade_date"),
            "intended_settlement_date": tx.get(
                "intended_settlement_date"),
            "actual_settlement_date": tx.get(
                "actual_settlement_date"),
            "has_instruction": bool(tx.get("has_instruction")),
            "has_status_advice": bool(tx.get("has_status_advice")),
            "has_confirmation": bool(tx.get("has_confirmation")),
            "conflicts": list(tx.get("conflicts") or []),
            "history": list(tx.get("history") or []),
        })
    summary = {}
    for i in items:
        summary[i["status"]] = summary.get(i["status"], 0) + 1
    return {
        "schema": STATUS_SCHEMA,
        "generated_at": now,
        "items": items,
        "orphan_observations": list(
            ledger_doc.get("orphan_observations") or []),
        "summary": {"by_status": summary,
                    "transactions": len(items)},
    }
