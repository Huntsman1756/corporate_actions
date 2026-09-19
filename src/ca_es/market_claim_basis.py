"""P16.1 — CA_ES_MARKET_CLAIM_BASIS_V1: base factual de la claim.

Una market claim nace de una transaccion de valores alrededor de un
evento CA. Este doc prueba SOLO los hechos:

- transaccion observada (declared input con provenance),
- relaciones temporales sobre fechas EXPLICITAS (nunca inferidas):
  trade_date vs ex_date, settlement_date vs record_date,
- settlement_status declarado.

NO decide elegibilidad: eso es assessment + regla de mercado
(P16.3). Una relacion UNKNOWN (fecha ausente o no ISO) queda
explicita — fail-closed, no estima.

La ausencia de una transaccion en un feed posterior NO borra la
evidencia previa (M13): el basis doc es una observacion
append-only; quien lo regenera aporta las transacciones vigentes.
"""

from __future__ import annotations

from datetime import date

BASIS_SCHEMA = "CA_ES_MARKET_CLAIM_BASIS_V1"
TRANSACTIONS_SCHEMA = "CA_ES_SECURITIES_TRANSACTIONS_V1"

BUY = "BUY"
SELL = "SELL"
DIRECTIONS = {BUY, SELL}

SETTLEMENT_STATUSES = {"PENDING", "SETTLED", "SETTLED_LATE",
                       "FAILED", "CANCELLED"}

BEFORE_EX_DATE = "BEFORE_EX_DATE"
ON_OR_BEFORE_EX_DATE = "ON_OR_BEFORE_EX_DATE"
ON_OR_AFTER_EX_DATE = "ON_OR_AFTER_EX_DATE"
AFTER_EX_DATE = "AFTER_EX_DATE"
AFTER_RECORD_DATE = "AFTER_RECORD_DATE"
ON_OR_AFTER_RECORD_DATE = "ON_OR_AFTER_RECORD_DATE"
ON_OR_BEFORE_RECORD_DATE = "ON_OR_BEFORE_RECORD_DATE"
BEFORE_RECORD_DATE = "BEFORE_RECORD_DATE"
UNKNOWN = "UNKNOWN"

TX_REQUIRED = {
    "transaction_id", "account_id", "isin", "quantity",
    "direction", "settlement_status",
}


def _iso_date(value):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _trade_relation(trade_date, ex_date):
    """trade vs ex: solo con ambas fechas explicitas."""
    td, ed = _iso_date(trade_date), _iso_date(ex_date)
    if td is None or ed is None:
        return UNKNOWN
    if td < ed:
        return BEFORE_EX_DATE
    if td == ed:
        return ON_OR_BEFORE_EX_DATE
    return AFTER_EX_DATE


def _settlement_relation(settlement_date, record_date):
    sd, rd = _iso_date(settlement_date), _iso_date(record_date)
    if sd is None or rd is None:
        return UNKNOWN
    if sd > rd:
        return AFTER_RECORD_DATE
    if sd == rd:
        return ON_OR_AFTER_RECORD_DATE
    return BEFORE_RECORD_DATE


def _tx_facts(tx: dict, i: int) -> tuple[dict, list]:
    """Campos factuales + reasons estaticas de la transaccion."""
    reasons = []
    if not isinstance(tx, dict):
        return {}, [f"transactions[{i}] no es objeto"]
    missing = TX_REQUIRED - set(tx)
    if missing:
        reasons.append(f"MISSING_FIELDS:{sorted(missing)}")
    if tx.get("direction") not in DIRECTIONS:
        reasons.append("INVALID_DIRECTION")
    if tx.get("settlement_status") not in SETTLEMENT_STATUSES:
        reasons.append("INVALID_SETTLEMENT_STATUS")
    return tx, reasons


def claim_basis(transactions_doc: dict, *, canonical_event_id: str,
                event_type: str | None = None,
                ex_date: str | None = None,
                record_date: str | None = None,
                payment_date: str | None = None,
                now: str | None = None) -> dict:
    """transactions + fechas explicitas del evento -> BASIS doc."""
    if transactions_doc.get("schema") != TRANSACTIONS_SCHEMA:
        raise ValueError(
            f"transactions schema debe ser {TRANSACTIONS_SCHEMA}")
    items = []
    for i, tx in enumerate(
            transactions_doc.get("transactions") or []):
        tx, reasons = _tx_facts(tx, i)
        item = {
            "transaction_id": tx.get("transaction_id"),
            "settlement_instruction_id": tx.get(
                "settlement_instruction_id"),
            "account_id": tx.get("account_id"),
            "isin": tx.get("isin"),
            "quantity": tx.get("quantity"),
            "direction": tx.get("direction"),
            "counterparty_ref": tx.get("counterparty_ref"),
            "trade_date": tx.get("trade_date"),
            "settlement_date": tx.get("settlement_date"),
            "settlement_status": tx.get("settlement_status"),
            "trade_date_relation": _trade_relation(
                tx.get("trade_date"), ex_date),
            "settlement_date_relation": _settlement_relation(
                tx.get("settlement_date"), record_date),
            "facts_proven": not reasons,
            "reason_codes": reasons,
            "provenance": tx.get("provenance") or [],
        }
        items.append(item)
    items.sort(key=lambda it: (it.get("transaction_id") or ""))
    return {
        "schema": BASIS_SCHEMA,
        "generated_at": now,
        "canonical_event_id": canonical_event_id,
        "event_type": event_type,
        "ex_date": ex_date,
        "record_date": record_date,
        "payment_date": payment_date,
        "dates_status": {
            "ex_date": "EXPLICIT" if _iso_date(ex_date) else UNKNOWN,
            "record_date": "EXPLICIT" if _iso_date(
                record_date) else UNKNOWN,
            "payment_date": "EXPLICIT" if _iso_date(
                payment_date) else UNKNOWN,
        },
        "items": items,
    }
