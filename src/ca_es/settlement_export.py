"""P17.4 — ledger -> CA_ES_SECURITIES_TRANSACTIONS_V1 (output
compatible P16 market_claim_basis).

Mapeo de estado del ciclo al settlement_status V1:

- SETTLED con actual > intended -> SETTLED_LATE; else SETTLED.
- PARTIALLY_SETTLED -> PENDING (+ partially_settled_quantity).
- MATCHED/PENDING/INSTRUCTED -> PENDING.
- CANCELLED -> CANCELLED; REJECTED -> FAILED.

direction RECE -> BUY, DELI -> SELL (economia del movimiento de
titulos, no del cash leg).
"""

from __future__ import annotations

EXPORT_SCHEMA = "CA_ES_SECURITIES_TRANSACTIONS_V1"

_DIR = {"RECE": "BUY", "DELI": "SELL"}


def _export_status(tx: dict) -> str:
    st = tx.get("status")
    if st == "SETTLED":
        intended = tx.get("intended_settlement_date")
        actual = tx.get("actual_settlement_date")
        if intended and actual and actual > intended:
            return "SETTLED_LATE"
        return "SETTLED"
    if st in ("CANCELLED",):
        return "CANCELLED"
    if st in ("FAILED",):
        return "FAILED"
    return "PENDING"


def export_transactions(ledger_doc: dict) -> dict:
    """Ledger -> CA_ES_SECURITIES_TRANSACTIONS_V1."""
    out = []
    for tx in sorted(
            ledger_doc.get("transactions") or [],
            key=lambda t: t.get("transaction_id") or ""):
        refs = tx.get("references") or {}
        actual = tx.get("actual_settlement_date")
        intended = tx.get("intended_settlement_date")
        out.append({
            "transaction_id": tx.get("transaction_id"),
            "settlement_instruction_id": refs.get(
                "acct_svcr_tx_id") or tx.get("primary_ref"),
            "account_id": tx.get("account_id"),
            "isin": tx.get("isin"),
            "quantity": tx.get("instructed_quantity"),
            "direction": _DIR.get(tx.get("direction") or "",
                                  tx.get("direction")),
            "trade_date": tx.get("trade_date"),
            "settlement_date": actual or intended,
            "settlement_status": _export_status(tx),
            "intended_settlement_date": intended,
            "actual_settlement_date": actual,
            "partially_settled_quantity": (
                tx.get("settled_quantity")
                if tx.get("partial") else None),
            "matching_status": tx.get("matching_status"),
            "payment_type": tx.get("payment_type"),
            "references": refs,
            "conflicts": list(tx.get("conflicts") or []),
            "provenance": [{
                "source": "settlement-feed",
                "ref": tx.get("transaction_id"),
                "observations": list(tx.get("observations") or [])}],
        })
    return {"schema": EXPORT_SCHEMA, "transactions": out}
