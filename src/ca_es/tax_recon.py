"""P14.13 — tax reconciliation.

CA_ES_TAX_ENTITLEMENT_V1 (expected, CALCULATED)
    vs CA_ES_TAX_EVIDENCE_V1 evidence_role=ACTUAL (MT566/seev.036)
        -> CA_ES_TAX_RECON_V1

Solo compara componentes explicitamente declarados. Nunca deriva
el impuesto actual como gross - net: la diferencia puede contener
fees/cargos/segundo nivel. Si el mensaje actual declara
gross/net/tax explicitos, la consistencia aritmetica se verifica
sin fabricar identidad de componente.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

RECON_SCHEMA = "CA_ES_TAX_RECON_V1"

MATCH = "MATCH"
WITHHOLDING_AMOUNT_MISMATCH = "WITHHOLDING_AMOUNT_MISMATCH"
WITHHOLDING_RATE_MISMATCH = "WITHHOLDING_RATE_MISMATCH"
MISSING_TAX_COMPONENT = "MISSING_TAX_COMPONENT"
UNEXPECTED_TAX_COMPONENT = "UNEXPECTED_TAX_COMPONENT"
INDETERMINATE = "INDETERMINATE"


def _dec(raw):
    text = str(raw).strip()
    sign = None
    if text[:1] in ("N", "D"):
        sign, text = text[0], text[1:]
    text = text.replace(",", ".")
    if text.endswith("."):
        text = text[:-1]
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite():
        return None
    return -value if sign == "N" else value


def _fmt(value):
    return format(value, "f") if value is not None else None


def _actual_items(evidence_docs):
    """Componentes fiscales declarados en mensajes ACTUAL."""
    out = []
    for doc in evidence_docs or []:
        if doc.get("evidence_role") != "ACTUAL":
            continue
        for scope in doc.get("scopes") or []:
            for item in scope.get("items") or []:
                it = dict(item)
                it["_source_sha256"] = doc.get("input_sha256")
                it["_source_message"] = doc.get(
                    "source_message_identifier")
                out.append(it)
    return out


def tax_recon(tax_entitlement_doc: dict,
              actual_evidence_docs: list[dict] | None,
              now: str | None = None) -> dict:
    """Expected vs actual explicito -> CA_ES_TAX_RECON_V1."""
    items = []
    actual = _actual_items(actual_evidence_docs)
    used = set()

    for ent_item in tax_entitlement_doc.get("items") or []:
        account = ent_item.get("account_id")
        status = ent_item.get("status")
        if status != "CALCULATED":
            items.append({
                "account_id": account,
                "component_type": "WITHHOLDING_PRIMARY",
                "status": INDETERMINATE,
                "reason": f"EXPECTED_TAX_{status}",
                "expected_amount": None,
                "actual_amount": None,
            })
            continue
        for comp in ent_item.get("tax_components") or []:
            ctype = comp.get("component_type")
            expected_amount = _dec(comp.get("amount"))
            expected_rate = _dec(comp.get("rate_fraction"))
            currency = comp.get("currency")

            amounts = [
                a for a in actual
                if a.get("tax_type") == ctype
                and a.get("kind") == "amount"
                and (a.get("currency") in (None, currency))]
            rates = [
                a for a in actual
                if a.get("tax_type") == ctype
                and a.get("kind") == "rate"]

            if not amounts and not rates:
                items.append({
                    "account_id": account,
                    "component_type": ctype,
                    "status": MISSING_TAX_COMPONENT,
                    "reason": "NO_ACTUAL_TAX_COMPONENT",
                    "expected_amount": _fmt(expected_amount),
                    "actual_amount": None,
                })
                continue

            item_status = MATCH
            reason = None
            actual_amount = None
            if amounts:
                distinct = {_dec(a.get("amount")) for a in amounts}
                used.update(id(a) for a in amounts)
                if len(distinct) > 1:
                    item_status = INDETERMINATE
                    reason = "CONFLICTING_ACTUAL_AMOUNTS"
                else:
                    actual_amount = next(iter(distinct))
                    if actual_amount != expected_amount:
                        item_status = WITHHOLDING_AMOUNT_MISMATCH
            if item_status == MATCH and rates:
                used.update(id(a) for a in rates)
                fracs = set()
                for a in rates:
                    f = _dec(a.get("rate_lexeme") or a.get("rate"))
                    if f is not None:
                        unit = (a.get("rate_unit")
                                or "PERCENTAGE").upper()
                        fracs.add(
                            f / Decimal(100) if unit == "PERCENTAGE"
                            else f)
                if len(fracs) > 1:
                    item_status = INDETERMINATE
                    reason = "CONFLICTING_ACTUAL_RATES"
                elif fracs and expected_rate is not None:
                    if next(iter(fracs)) != expected_rate:
                        item_status = WITHHOLDING_RATE_MISMATCH
            items.append({
                "account_id": account,
                "component_type": ctype,
                "status": item_status,
                "reason": reason,
                "expected_amount": _fmt(expected_amount),
                "actual_amount": _fmt(actual_amount),
                "expected_rate_fraction": _fmt(expected_rate),
                "currency": currency,
                "evidence_refs": [
                    a.get("_source_sha256") for a in
                    (*amounts, *rates) if a.get("_source_sha256")],
            })

    for a in actual:
        if id(a) in used or a.get("tax_type") in (
                "GROSS_AMOUNT", "NET_AMOUNT"):
            continue
        items.append({
            "account_id": None,
            "component_type": a.get("tax_type"),
            "status": UNEXPECTED_TAX_COMPONENT,
            "reason": "ACTUAL_COMPONENT_WITHOUT_EXPECTED",
            "expected_amount": None,
            "actual_amount": a.get("amount"),
            "currency": a.get("currency"),
            "evidence_refs": [a.get("_source_sha256")],
        })

    summary = {"items": len(items)}
    for status in (MATCH, WITHHOLDING_AMOUNT_MISMATCH,
                   WITHHOLDING_RATE_MISMATCH, MISSING_TAX_COMPONENT,
                   UNEXPECTED_TAX_COMPONENT, INDETERMINATE):
        summary[status] = sum(
            1 for i in items if i["status"] == status)

    return {
        "schema": RECON_SCHEMA,
        "generated_at": now,
        "canonical_event_id": tax_entitlement_doc.get(
            "canonical_event_id"),
        "case_scope": "tax",
        "items": items,
        "summary": summary,
    }
