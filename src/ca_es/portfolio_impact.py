"""P6 — Portfolio impact summary (read-only).

    CA_ES_POSITION_IMPACT_V1 -> aggregate_portfolio_impact()
        -> CA_ES_PORTFOLIO_IMPACT_V1

Agregacion solo donde es semanticamente aditiva:

- cash: suma de cash_amount por currency (nunca cross-currency);
- valores: suma de quantity_delta por (account_id, isin).

Solo items PROJECTED aportan; el resto se cuenta por status. Sin FX,
sin valoracion, sin precios de mercado, sin score.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .canonical import sha256_hex
from .position_impact import IMPACT_SCHEMA, PROJECTED

PORTFOLIO_SCHEMA = "CA_ES_PORTFOLIO_IMPACT_V1"


def _decimal(raw) -> Decimal | None:
    if raw is None or isinstance(raw, float):
        return None
    if isinstance(raw, dict):
        raw = raw.get("normalized")
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def aggregate_portfolio_impact(impact_doc: dict,
                               now: str | None = None) -> dict:
    """impact doc -> CA_ES_PORTFOLIO_IMPACT_V1. read-only."""
    if impact_doc.get("schema") != IMPACT_SCHEMA:
        raise ValueError(
            f"impact schema debe ser {IMPACT_SCHEMA}, "
            f"recibido {impact_doc.get('schema')!r}"
        )

    cash: dict[str, Decimal] = {}
    securities: dict[tuple, Decimal] = {}
    excluded: dict[str, int] = {}
    reasons: list[str] = []

    for item in impact_doc.get("impacts", []):
        status = item.get("status")
        if status != PROJECTED:
            excluded[status] = excluded.get(status, 0) + 1
            continue
        amount = _decimal(item.get("cash_amount"))
        if amount is not None:
            currency = (item.get("cash_amount") or {}).get("currency")
            if currency:
                cash[currency] = cash.get(currency, Decimal(0)) + amount
            else:
                reasons.append("CASH_WITHOUT_CURRENCY")
        delta = _decimal(item.get("quantity_delta"))
        if delta is not None:
            key = (
                item.get("account_id"),
                item.get("target_isin") or item.get("source_isin"),
            )
            securities[key] = securities.get(key, Decimal(0)) + delta

    cash_lines = [
        {
            "currency": currency,
            "expected_amount": format(cash[currency], "f"),
        }
        for currency in sorted(cash)
    ]
    security_lines = [
        {
            "account_id": account,
            "isin": isin,
            "expected_quantity_delta": format(
                securities[(account, isin)], "f"),
        }
        for account, isin in sorted(
            securities, key=lambda k: (str(k[0]), str(k[1])))
    ]

    return {
        "schema": PORTFOLIO_SCHEMA,
        "generated_at": now,
        "canonical_event_id": impact_doc.get("canonical_event_id"),
        "event_type": impact_doc.get("event_type"),
        "source_impact_sha256": sha256_hex(impact_doc),
        "reasons": sorted(set(reasons)),
        "cash_by_currency": cash_lines,
        "securities_by_account_isin": security_lines,
        "excluded_items": dict(sorted(excluded.items())),
        "summary": {
            "cash_lines": len(cash_lines),
            "security_lines": len(security_lines),
        },
    }
