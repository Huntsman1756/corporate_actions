"""P15.2 — CA_ES_TAX_RECOVERY_ASSESSMENT_V1.

Tax entitlement (P14) + evidencia ACTUAL + perfil + recovery rules
    -> assessment por (cuenta, regla).

Regla esencial: NUNCA se concluye importe recuperable porque
`actual tax > P14 expected tax`. La diferencia esperado-vs-actual
puede ser mismatch, perfil incorrecto, relief no aplicado o
reclaim real. `recoverable_amount` solo existe cuando una regla
recovery, un perfil y la evidencia necesaria lo demuestran:

    recoverable = withheld_evidenced - entitled(rule)  sobre gross

Metodos (mismo lifecycle, no pipelines separados):
- RELIEF_AT_SOURCE: claim_kind=RATE_RELIEF; elegible solo si el
  perfil demuestra la tasa reducida y el pago aun no consta
  evidenciado (la evidencia ACTUAL cierra la via relief: el
  exceso pasa a las vias refund, evaluadas por sus propias reglas).
- QUICK_REFUND / STANDARD_RECLAIM: claim_kind=CASH_REFUND;
  elegible solo si actual > entitled y el deadline effective-dated
  no ha expirado.

WITHHOLDING_MISMATCH (P14) != RECOVERY_ELIGIBLE: el assessment
usa la regla recovery como unica base de entitlement fiscal.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .tax_profile import PROFILE_SCHEMA, profile_for_account
from .tax_recovery_rules import (
    RULES_SCHEMA, recovery_rule_candidates, rule_deadline,
    validate_recovery_ruleset)
from .tax_rules import conditions_satisfied

ASSESSMENT_SCHEMA = "CA_ES_TAX_RECOVERY_ASSESSMENT_V1"

ELIGIBLE = "ELIGIBLE"
NOT_APPLICABLE = "NOT_APPLICABLE"
INDETERMINATE = "INDETERMINATE"
EXPIRED = "EXPIRED"

CASH_REFUND = "CASH_REFUND"
RATE_RELIEF = "RATE_RELIEF"

_CLAIM_KIND = {
    "RELIEF_AT_SOURCE": RATE_RELIEF,
    "QUICK_REFUND": CASH_REFUND,
    "STANDARD_RECLAIM": CASH_REFUND,
}


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


def _money(value, currency):
    if value is None:
        return None
    return {"normalized": _fmt(value), "currency": currency}


def _rate_fraction(raw, unit) -> Decimal | None:
    value = _dec(raw)
    if value is None:
        return None
    return value / Decimal(100) if (unit or
                                    "PERCENTAGE") == "PERCENTAGE" \
        else value


def _actual_withholding(evidence_docs):
    """Withholding evidenciado (ACTUAL): rates y amounts por
    ocurrencia; nunca derivado de gross - net."""
    rates, amounts = [], []
    refs = []
    for doc in evidence_docs or []:
        if doc.get("evidence_role") != "ACTUAL":
            continue
        for scope in doc.get("scopes") or []:
            for item in scope.get("items") or []:
                if item.get("tax_type") != "WITHHOLDING_PRIMARY":
                    continue
                if item.get("kind") == "rate":
                    fr = _rate_fraction(item.get("rate"),
                                        item.get("rate_unit"))
                    if fr is not None:
                        rates.append((fr, item))
                elif item.get("kind") == "amount":
                    am = _dec(item.get("amount"))
                    if am is not None:
                        amounts.append(
                            (am, item.get("currency"), item))
        for p in doc.get("provenance") or []:
            refs.append(p)
        if doc.get("input_sha256"):
            refs.append(doc["input_sha256"])
    return rates, amounts, refs


def claim_reference(event_id, account_id, rule_id, method):
    """Clave determinista del claim (join key, no event id)."""
    return "|".join([
        event_id or "-", account_id or "-", rule_id or "-",
        method or "-"])


def recovery_assessment(tax_entitlement_doc: dict,
                        actual_evidence_docs: list[dict] | None,
                        profile_doc: dict | None,
                        ruleset_doc: dict | None, *,
                        jurisdiction: str,
                        income_type: str,
                        assessment_date: str | None,
                        payment_date: str | None = None,
                        now: str | None = None) -> dict:
    """-> CA_ES_TAX_RECOVERY_ASSESSMENT_V1."""
    event_id = tax_entitlement_doc.get("canonical_event_id")
    base = {
        "schema": ASSESSMENT_SCHEMA,
        "generated_at": now,
        "canonical_event_id": event_id,
        "jurisdiction": jurisdiction,
        "income_type": income_type,
        "assessment_date": assessment_date,
        "payment_date": payment_date,
        "items": [],
        "status": "OK",
        "reasons": [],
    }

    if ruleset_doc is None:
        base["status"] = INDETERMINATE
        base["reasons"].append("NO_RECOVERY_RULESET")
        return base
    errors = validate_recovery_ruleset(ruleset_doc)
    if errors:
        base["status"] = "INVALID"
        base["reasons"].extend(
            f"INVALID_RULESET:{e}" for e in errors)
        return base

    active_rules, rule_reasons = recovery_rule_candidates(
        ruleset_doc, jurisdiction, income_type,
        assessment_date or "")

    rates, amounts, ev_refs = _actual_withholding(
        actual_evidence_docs)
    actual_rates = {r for r, _ in rates}
    actual_amounts = {(a, c) for a, c, _ in amounts}
    actual_rate = next(iter(actual_rates)) \
        if len(actual_rates) == 1 else None
    multi_actual = len(actual_rates) > 1 or len(actual_amounts) > 1

    items = tax_entitlement_doc.get("items") or []
    single_account = len(items) == 1

    for ent_item in items:
        account = ent_item.get("account_id")
        gross = _dec((ent_item.get("gross_entitlement") or {})
                     .get("normalized"))
        currency = (ent_item.get("gross_entitlement") or {}).get(
            "currency")

        def _item(rule, status, reasons, **extra):
            it = {
                "account_id": account,
                "rule_id": (rule or {}).get("rule_id"),
                "recovery_method": (rule or {}).get(
                    "recovery_method"),
                "claim_kind": _CLAIM_KIND.get(
                    (rule or {}).get("recovery_method")),
                "claim_reference": claim_reference(
                    event_id, account, (rule or {}).get("rule_id"),
                    (rule or {}).get("recovery_method")),
                "status": status,
                "reason_codes": list(reasons),
                "gross_amount": _money(gross, currency),
                "withheld_amount": None,
                "withheld_rate_fraction": _fmt(actual_rate),
                "entitled_rate_fraction": _fmt(_rate_fraction(
                    (rule or {}).get("entitled_rate"),
                    (rule or {}).get("rate_unit"))),
                "recoverable_amount": None,
                "deadline_date": rule_deadline(
                    rule or {}, payment_date) if rule else None,
                "evidence_refs": list(ev_refs),
            }
            it.update(extra)
            base["items"].append(it)
            return it

        if not active_rules:
            _item(None, INDETERMINATE,
                  rule_reasons or ["NO_APPLICABLE_RULE"])
            continue

        # resolucion de perfil: una sola vez por cuenta
        profile = None
        profile_reasons = []
        if profile_doc is None:
            profile_reasons = ["NO_TAX_PROFILE"]
        elif profile_doc.get("schema") != PROFILE_SCHEMA:
            profile_reasons = ["INVALID_TAX_PROFILE"]
        else:
            profile, profile_reasons = profile_for_account(
                profile_doc, account, assessment_date or "")

        for rule in active_rules:
            method = rule.get("recovery_method")
            entitled = _rate_fraction(rule.get("entitled_rate"),
                                      rule.get("rate_unit"))
            deadline = rule_deadline(rule, payment_date)

            if profile is None:
                _item(rule, INDETERMINATE, profile_reasons)
                continue
            ok, missing = conditions_satisfied(rule, profile)
            if missing:
                _item(rule, INDETERMINATE,
                      [f"PROFILE_FIELD_MISSING:{m}"
                       for m in missing])
                continue
            if not ok:
                _item(rule, NOT_APPLICABLE,
                      ["PROFILE_CONDITIONS_NOT_MET"])
                continue

            if method == "RELIEF_AT_SOURCE":
                # la evidencia ACTUAL cierra la via relief: el
                # exceso, si existe, pertenece a las vias refund
                if rates or amounts:
                    _item(rule, NOT_APPLICABLE,
                          ["PAYMENT_ALREADY_EVIDENCED"])
                    continue
                if deadline is not None and assessment_date and \
                        assessment_date > deadline:
                    _item(rule, EXPIRED,
                          ["RECOVERY_DEADLINE_PASSED"])
                    continue
                if deadline is None:
                    _item(rule, INDETERMINATE,
                          ["RECOVERY_DEADLINE_UNKNOWN"])
                    continue
                expected_rate = None
                for comp in ent_item.get("tax_components") or []:
                    if comp.get("component_type") == \
                            "WITHHOLDING_PRIMARY":
                        expected_rate = _dec(
                            comp.get("rate_fraction"))
                if gross is None or expected_rate is None:
                    _item(rule, INDETERMINATE,
                          ["EXPECTED_RATE_NOT_AVAILABLE"])
                    continue
                if entitled is None or entitled >= expected_rate:
                    _item(rule, NOT_APPLICABLE,
                          ["NO_RECOVERABLE_BASIS"])
                    continue
                avoided = gross * (expected_rate - entitled)
                _item(rule, ELIGIBLE, [],
                      withheld_rate_fraction=_fmt(expected_rate),
                      prospective_amount=_money(avoided, currency))
                continue

            # QUICK_REFUND / STANDARD_RECLAIM: CASH_REFUND.
            # deadline statutory: expirado -> EXPIRED, nunca eligible
            if deadline is not None and assessment_date and \
                    assessment_date > deadline:
                _item(rule, EXPIRED, ["RECOVERY_DEADLINE_PASSED"])
                continue
            if deadline is None:
                _item(rule, INDETERMINATE,
                      ["RECOVERY_DEADLINE_UNKNOWN"])
                continue
            if multi_actual:
                _item(rule, INDETERMINATE,
                      ["CONFLICTING_ACTUAL_WITHHOLDING"])
                continue
            if not rates and not amounts:
                _item(rule, INDETERMINATE,
                      ["NO_ACTUAL_WITHHOLDING_EVIDENCE"])
                continue
            if gross is None or currency is None:
                _item(rule, INDETERMINATE,
                      ["INVALID_GROSS_ENTITLEMENT"])
                continue
            if entitled is None:
                _item(rule, INDETERMINATE,
                      ["ENTITLED_RATE_NOT_AVAILABLE"])
                continue

            recoverable = None
            withheld_money = None
            if actual_rate is not None:
                # base explicita: rate evidenciado vs rate entitled
                if actual_rate <= entitled:
                    _item(rule, NOT_APPLICABLE,
                          ["NO_RECOVERABLE_AMOUNT"])
                    continue
                withheld_money = _money(gross * actual_rate,
                                        currency)
                recoverable = gross * (actual_rate - entitled)
            else:
                actual_amt, amt_ccy = next(iter(actual_amounts))
                if amt_ccy is not None and amt_ccy != currency:
                    _item(rule, INDETERMINATE, ["FX_REQUIRED"])
                    continue
                if not single_account:
                    _item(rule, INDETERMINATE,
                          ["ACTUAL_RATE_MISSING"])
                    continue
                entitled_amt = gross * entitled
                withheld_money = _money(actual_amt, currency)
                if actual_amt <= entitled_amt:
                    _item(rule, NOT_APPLICABLE,
                          ["NO_RECOVERABLE_AMOUNT"])
                    continue
                recoverable = actual_amt - entitled_amt

            _item(rule, ELIGIBLE, [],
                  withheld_amount=withheld_money,
                  recoverable_amount=_money(recoverable, currency))

    summary = {}
    for it in base["items"]:
        summary[it["status"]] = summary.get(it["status"], 0) + 1
    base["summary"] = summary
    return base
