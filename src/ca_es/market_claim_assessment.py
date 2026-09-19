"""P16.3 — CA_ES_MARKET_CLAIM_ASSESSMENT_V1: expected claim.

Regla central:

    trade before ex-date + settlement after record date
        != automaticamente market claim

El assessment exige:

1. basis item con facts_proven (P16.1),
2. relaciones temporales que satisfacen la eligibility de la regla,
3. regla de mercado explicita vigente (P16.0):
   NO_APPLICABLE_RULE -> MARKET_PRACTICE_REQUIRED,
4. proceeds rate explicita (del entitlement P8 via caller):
   ausente -> INDETERMINATE / PROCEEDS_BASIS_REQUIRED.

Statuses: PROVEN | INDETERMINATE | MARKET_PRACTICE_REQUIRED |
NOT_APPLICABLE. Solo PROVEN genera una expected claim con
claim_id determinista; el resto son evaluaciones, no claims.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .market_claim_basis import (AFTER_EX_DATE, AFTER_RECORD_DATE,
                                 BEFORE_EX_DATE, BEFORE_RECORD_DATE,
                                 BUY, ON_OR_AFTER_RECORD_DATE,
                                 ON_OR_BEFORE_EX_DATE, SELL, UNKNOWN)
from .market_claim_rules import (claim_deadline,
                                 claim_rule_candidates)
from .semantic_hash import semantic_sha256

ASSESSMENT_SCHEMA = "CA_ES_MARKET_CLAIM_ASSESSMENT_V1"

PROVEN = "PROVEN"
INDETERMINATE = "INDETERMINATE"
MARKET_PRACTICE_REQUIRED = "MARKET_PRACTICE_REQUIRED"
NOT_APPLICABLE = "NOT_APPLICABLE"

_TRADE_OK = {
    "BEFORE_EX_DATE": {BEFORE_EX_DATE},
    "ON_OR_BEFORE_EX_DATE": {BEFORE_EX_DATE, ON_OR_BEFORE_EX_DATE},
}
_SETTLE_OK = {
    "AFTER_RECORD_DATE": {AFTER_RECORD_DATE},
    "ON_OR_AFTER_RECORD_DATE": {AFTER_RECORD_DATE,
                                ON_OR_AFTER_RECORD_DATE},
}


def _dec(raw):
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def _fmt(value):
    return format(value, "f") if value is not None else None


def _claim_id(event_id, transaction_id, rule_id):
    return "MC-" + semantic_sha256({
        "canonical_event_id": event_id,
        "transaction_id": transaction_id,
        "rule_id": rule_id,
    })[:16]


def _eligibility(rule: dict, item: dict) -> list[str]:
    """Reasons si la transaccion no satisface la ventana."""
    reasons = []
    elig = rule.get("eligibility") or {}
    tr = item.get("trade_date_relation")
    sr = item.get("settlement_date_relation")
    if tr == UNKNOWN:
        reasons.append("TRADE_DATE_RELATION_UNKNOWN")
    elif tr not in _TRADE_OK.get(
            elig.get("trade_date_relation") or "", set()):
        reasons.append(f"TRADE_RELATION_NOT_MET:{tr}")
    if sr == UNKNOWN:
        reasons.append("SETTLEMENT_DATE_RELATION_UNKNOWN")
    elif sr not in _SETTLE_OK.get(
            elig.get("settlement_date_relation") or "", set()):
        reasons.append(f"SETTLEMENT_RELATION_NOT_MET:{sr}")
    allowed = set(elig.get("settlement_status") or [])
    if item.get("settlement_status") not in allowed:
        reasons.append(
            f"SETTLEMENT_STATUS_NOT_ELIGIBLE:"
            f"{item.get('settlement_status')}")
    return reasons


def _rule_direction(rule: dict, tx_direction: str) -> str | None:
    """Quien queda compensado y hacia donde va el proceeds.

    BUY + BUYER_COMPENSATED: el comprador adquirio cum-dividend
    pero liquidara post-record -> el vendedor le debe el proceeds:
    RECEIPT para el lado del comprador.
    SELL + SELLER_COMPENSATED (RVMC): simetrico.
    """
    d = rule.get("claim_direction")
    if d == "BUYER_COMPENSATED" and tx_direction == BUY:
        return "RECEIPT"
    if d == "SELLER_COMPENSATED" and tx_direction == SELL:
        return "DELIVERY"
    return None


def claim_assessment(basis_doc: dict, ruleset_doc: dict | None,
                     *, jurisdiction: str, assessment_date: str,
                     proceeds_rate: str | None = None,
                     proceeds_currency: str | None = None,
                     proceeds_quantity_ratio: str | None = None,
                     proceeds_target_isin: str | None = None,
                     now: str | None = None) -> dict:
    """basis + rules + proceeds explicito -> ASSESSMENT doc."""
    event_id = basis_doc.get("canonical_event_id")
    event_type = basis_doc.get("event_type")
    items = []
    for bi in basis_doc.get("items") or []:
        item = {
            "transaction_id": bi.get("transaction_id"),
            "settlement_instruction_id": bi.get(
                "settlement_instruction_id"),
            "account_id": bi.get("account_id"),
            "isin": bi.get("isin"),
            "quantity": bi.get("quantity"),
            "tx_direction": bi.get("direction"),
            "claim_id": None,
            "rule_id": None,
            "claim_type": None,
            "proceeds_direction": None,
            "expected_amount": None,
            "expected_quantity": None,
            "currency": proceeds_currency,
            "target_isin": proceeds_target_isin,
            "deadline_date": None,
            "status": None,
            "reason_codes": [],
            "evidence_refs": list(bi.get("provenance") or []),
        }
        if not bi.get("facts_proven"):
            item["status"] = INDETERMINATE
            item["reason_codes"] = ["TRANSACTION_FACTS_NOT_PROVEN"] \
                + list(bi.get("reason_codes") or [])
            items.append(item)
            continue

        # direccion candidata por el tipo de transaccion
        direction = ("BUYER_COMPENSATED"
                     if bi.get("direction") == BUY
                     else "SELLER_COMPENSATED"
                     if bi.get("direction") == SELL else None)
        if direction is None:
            item["status"] = INDETERMINATE
            item["reason_codes"] = ["TRANSACTION_DIRECTION_UNKNOWN"]
            items.append(item)
            continue

        if ruleset_doc is None:
            item["status"] = MARKET_PRACTICE_REQUIRED
            item["reason_codes"] = ["NO_CLAIM_RULESET"]
            items.append(item)
            continue

        rules, reasons = claim_rule_candidates(
            ruleset_doc, jurisdiction, event_type,
            assessment_date, direction=direction)
        if not rules:
            item["status"] = MARKET_PRACTICE_REQUIRED
            item["reason_codes"] = reasons or ["NO_APPLICABLE_RULE"]
            items.append(item)
            continue
        if len(rules) > 1:
            item["status"] = INDETERMINATE
            item["reason_codes"] = ["AMBIGUOUS_CLAIM_RULES"]
            items.append(item)
            continue

        rule = rules[0]
        item["rule_id"] = rule.get("rule_id")
        item["claim_type"] = rule.get("claim_type")
        fails = _eligibility(rule, bi)
        if fails:
            item["status"] = NOT_APPLICABLE
            item["reason_codes"] = fails
            items.append(item)
            continue

        proceeds_direction = _rule_direction(
            rule, bi.get("direction"))
        if proceeds_direction is None:
            item["status"] = INDETERMINATE
            item["reason_codes"] = [
                "CLAIM_DIRECTION_NOT_RESOLVABLE"]
            items.append(item)
            continue
        item["proceeds_direction"] = proceeds_direction

        proceeds = rule.get("proceeds") or {}
        qty = _dec(bi.get("quantity"))
        if qty is None:
            item["status"] = INDETERMINATE
            item["reason_codes"] = ["QUANTITY_NOT_DECIMAL"]
            items.append(item)
            continue

        if proceeds.get("kind") == "CASH":
            rate = _dec(proceeds_rate)
            if rate is None:
                item["status"] = INDETERMINATE
                item["reason_codes"] = ["PROCEEDS_BASIS_REQUIRED"]
                items.append(item)
                continue
            item["expected_amount"] = _fmt(qty * rate)
        elif proceeds.get("kind") == "SECURITIES":
            ratio = _dec(proceeds_quantity_ratio)
            if ratio is None or proceeds_target_isin is None:
                item["status"] = INDETERMINATE
                item["reason_codes"] = ["PROCEEDS_BASIS_REQUIRED"]
                items.append(item)
                continue
            item["expected_quantity"] = _fmt(qty * ratio)
        else:
            item["status"] = INDETERMINATE
            item["reason_codes"] = ["PROCEEDS_KIND_UNKNOWN"]
            items.append(item)
            continue

        basis_date = basis_doc.get("record_date") if (
            (rule.get("deadline") or {}).get("basis")
            == "RECORD_DATE") else basis_doc.get("payment_date")
        item["deadline_date"] = claim_deadline(rule, basis_date)
        item["claim_id"] = _claim_id(
            event_id, bi.get("transaction_id"), rule.get("rule_id"))
        item["status"] = PROVEN
        items.append(item)

    items.sort(key=lambda i: (i.get("claim_id")
                              or i.get("transaction_id") or ""))
    summary = {}
    for i in items:
        summary[i["status"]] = summary.get(i["status"], 0) + 1
    return {
        "schema": ASSESSMENT_SCHEMA,
        "generated_at": now,
        "canonical_event_id": event_id,
        "event_type": event_type,
        "jurisdiction": jurisdiction,
        "assessment_date": assessment_date,
        "items": items,
        "summary": summary,
    }
