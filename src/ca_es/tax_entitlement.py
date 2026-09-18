"""P14.8-P14.12 — expected withholding -> expected net -> expected cash.

CA_ES_ENTITLEMENT_V1 + CA_ES_TAX_EVIDENCE_V1
    + CA_ES_TAX_PROFILE_V1 + CA_ES_TAX_RULES_V1
        -> CA_ES_TAX_ENTITLEMENT_V1
        -> CA_ES_EXPECTED_CASH_V1

Reglas duras:

- Decimal exclusivo; nunca float;
- el gross viene del entitlement existente (no se recalcula);
- retencion = basis x rate solo cuando rate y basis son explicitos
  (regla configurada o rate declarada en fuente);
- rounding solo segun rule.rounding; sin default global;
- nunca se infiere tax = gross - net;
- segunda capa (WITL/ScndLvlTax) sin regla que pruebe su basis ->
  UNSUPPORTED_MULTI_LEVEL_TAX, no se calcula;
- rate declarada en fuente distinta de la regla configurada ->
  CONFLICTING; no hay ganador arbitrario;
- divisa distinta entre basis e impuesto -> FX_REQUIRED;
- perfil/regla insuficiente -> INDETERMINATE, nunca se fabrica net.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import (Decimal, InvalidOperation, ROUND_DOWN,
                     ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP,
                     localcontext)

from .tax_profile import PROFILE_SCHEMA, profile_for_account
from .tax_rules import (RULES_SCHEMA, conditions_satisfied,
                        rule_candidates, validate_ruleset)

ENTITLEMENT_SCHEMA = "CA_ES_TAX_ENTITLEMENT_V1"
EXPECTED_CASH_SCHEMA = "CA_ES_EXPECTED_CASH_V1"

CALCULATED = "CALCULATED"
INDETERMINATE = "INDETERMINATE"
UNSUPPORTED = "UNSUPPORTED"
CONFLICTING = "CONFLICTING"
PENDING_ELECTION = "PENDING_ELECTION"

_ROUNDING = {
    "HALF_UP": ROUND_HALF_UP,
    "HALF_EVEN": ROUND_HALF_EVEN,
    "DOWN": ROUND_DOWN,
    "UP": ROUND_UP,
}


def _dec(raw):
    if isinstance(raw, float):
        return None
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
    return {"normalized": _fmt(value), "currency": currency}


def _sha(doc):
    payload = json.dumps(doc, sort_keys=True, default=str,
                         separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _rate_fraction(rate_raw, rate_unit) -> Decimal | None:
    """Rate declarada/configurada -> fraccion Decimal (0.19)."""
    rate = _dec(rate_raw)
    if rate is None:
        return None
    unit = (rate_unit or "PERCENTAGE").upper()
    if unit == "PERCENTAGE":
        return rate / Decimal(100)
    if unit == "FRACTION":
        return rate
    return None


def _tax_items(evidence_docs, tax_types, *, option_scope=None,
               kind=None):
    """Items de evidencia de los tipos dados, restringidos al scope
    de opcion elegida si se indica."""
    items = []
    for doc in evidence_docs or []:
        for scope in doc.get("scopes") or []:
            if option_scope is not None:
                if scope.get("option_number") != option_scope.get(
                        "option_number") and option_scope.get(
                        "option_number") is not None:
                    continue
                if scope.get("option_type") != option_scope.get(
                        "option_type") and option_scope.get(
                        "option_type") is not None:
                    continue
            for item in scope.get("items") or []:
                if item.get("tax_type") in tax_types:
                    if kind and item.get("kind") != kind:
                        continue
                    it = dict(item)
                    it["_source_sha256"] = doc.get("input_sha256")
                    it["_source_message"] = doc.get(
                        "source_message_identifier")
                    items.append(it)
    return items


def _distinct_rates(items):
    """Fracciones distintas de los items rate."""
    out = set()
    for it in items:
        frac = _rate_fraction(it.get("rate_lexeme") or it.get("rate"),
                              it.get("rate_unit"))
        if frac is not None:
            out.add(frac)
    return out


def tax_entitlement(entitlement_doc: dict,
                    tax_evidence_docs: list[dict] | None,
                    profile_doc: dict | None,
                    ruleset_doc: dict | None, *,
                    jurisdiction: str,
                    income_type: str,
                    calculation_date: str | None,
                    option_scope: dict | None = None,
                    requires_election: bool = False,
                    now: str | None = None) -> dict:
    """Entitlement + evidencia + perfil + reglas -> tax entitlement.

    calculation_date = fecha fiscal de la retencion (payment date);
    nunca la fecha actual del run salvo que el caller la pase.
    """
    canonical_event_id = entitlement_doc.get("canonical_event_id")
    ruleset_sha = _sha(ruleset_doc) if ruleset_doc else None
    profile_sha = _sha(profile_doc) if profile_doc else None
    base = {
        "schema": ENTITLEMENT_SCHEMA,
        "generated_at": now,
        "canonical_event_id": canonical_event_id,
        "jurisdiction": jurisdiction,
        "income_type": income_type,
        "calculation_date": calculation_date,
        "ruleset_sha256": ruleset_sha,
        "profile_sha256": profile_sha,
        "items": [],
        "status": "OK",
        "reasons": [],
    }

    if ruleset_doc is None:
        base["status"] = INDETERMINATE
        base["reasons"].append("NO_TAX_RULESET")
    else:
        errors = validate_ruleset(ruleset_doc)
        if errors:
            base["status"] = "INVALID"
            base["reasons"].extend(
                f"INVALID_RULESET:{e}" for e in errors)
            return base

    if requires_election and option_scope is None:
        for ent in entitlement_doc.get("entitlements") or []:
            base["items"].append({
                "account_id": ent.get("account_id"),
                "gross_entitlement": ent.get("gross_cash"),
                "tax_components": [],
                "total_withholding": None,
                "expected_net_cash": None,
                "status": PENDING_ELECTION,
                "reason_codes": ["PENDING_ELECTION"],
                "trace": None,
            })
        base["status"] = INDETERMINATE
        return base

    active_rules = []
    rule_reasons = []
    if ruleset_doc is not None:
        active_rules, rule_reasons = rule_candidates(
            ruleset_doc, jurisdiction, income_type,
            calculation_date or "")

    for ent in entitlement_doc.get("entitlements") or []:
        item = {
            "account_id": ent.get("account_id"),
            "gross_entitlement": ent.get("gross_cash"),
            "tax_components": [],
            "total_withholding": None,
            "expected_net_cash": None,
            "status": INDETERMINATE,
            "reason_codes": [],
            "conflicts": [],
            "trace": None,
        }
        base["items"].append(item)
        reasons = item["reason_codes"]

        if ent.get("status") != "ENTITLED":
            reasons.extend([f"ENTITLEMENT_{ent.get('status')}",
                            *ent.get("reasons", [])])
            continue

        gross_raw = (ent.get("gross_cash") or {}).get("normalized")
        gross = _dec(gross_raw)
        currency = (ent.get("gross_cash") or {}).get("currency")
        if gross is None or currency is None:
            reasons.append("INVALID_GROSS_ENTITLEMENT")
            continue

        if ruleset_doc is None:
            reasons.append("NO_TAX_RULESET")
            continue
        if calculation_date is None:
            reasons.append("MISSING_CALCULATION_DATE")
            continue
        if not active_rules:
            reasons.extend(rule_reasons or ["NO_APPLICABLE_RULE"])
            continue

        if profile_doc is None:
            reasons.append("NO_TAX_PROFILE")
            continue
        if profile_doc.get("schema") != PROFILE_SCHEMA:
            reasons.append("INVALID_TAX_PROFILE")
            continue
        profile, p_reasons = profile_for_account(
            profile_doc, ent.get("account_id"), calculation_date)
        if profile is None:
            reasons.extend(p_reasons)
            continue

        # seleccion de regla: exactamente una satisfecha por perfil
        satisfied, incomplete = [], []
        for rule in active_rules:
            ok, missing = conditions_satisfied(rule, profile)
            if ok:
                satisfied.append(rule)
            elif missing:
                incomplete.append((rule, missing))
        if not satisfied:
            if incomplete:
                reasons.extend(
                    f"PROFILE_FIELD_MISSING:{m}"
                    for _, ms in incomplete for m in ms)
            else:
                reasons.append("RULE_NOT_APPLICABLE")
            continue
        if len(satisfied) > 1:
            reasons.append("AMBIGUOUS_RULE")
            item["status"] = CONFLICTING
            continue
        rule = satisfied[0]
        item["rule_id"] = rule["rule_id"]

        # evidencia scoped a la opcion elegida (o toda si no aplica)
        declared_rates = _tax_items(
            tax_evidence_docs, {"WITHHOLDING_PRIMARY"},
            option_scope=option_scope, kind="rate")
        declared_amounts = _tax_items(
            tax_evidence_docs, {"WITHHOLDING_PRIMARY"},
            option_scope=option_scope, kind="amount")
        second_level = _tax_items(
            tax_evidence_docs, {"WITHHOLDING_SECOND_LEVEL"},
            option_scope=option_scope)
        if second_level:
            item["status"] = UNSUPPORTED
            reasons.append("UNSUPPORTED_MULTI_LEVEL_TAX")
            item["tax_components"].extend(
                _evidence_components(second_level))
            continue

        # resolution de la rate
        rate_source = rule.get("rate_source")
        rate_frac = None
        declared_fracs = _distinct_rates(declared_rates)
        if rate_source == "EXEMPT":
            rate_frac = Decimal(0)
        elif rate_source == "SOURCE_DECLARED_RATE":
            if len(declared_fracs) > 1:
                reasons.append("MULTIPLE_TAX_RATES")
                item["status"] = CONFLICTING
                item["conflicts"].append({
                    "kind": "MULTIPLE_DECLARED_RATES",
                    "rates": sorted(_fmt(v) for v in declared_fracs),
                })
                continue
            if not declared_fracs:
                reasons.append("SOURCE_RATE_MISSING")
                continue
            rate_frac = next(iter(declared_fracs))
        else:  # CONFIGURED_*
            configured = _rate_fraction(rule.get("rate"),
                                        rule.get("rate_unit"))
            if configured is None:
                reasons.append("INVALID_RULE_RATE")
                continue
            if declared_fracs and (
                    len(declared_fracs) > 1
                    or next(iter(declared_fracs)) != configured):
                item["status"] = CONFLICTING
                reasons.append("SOURCE_RULE_RATE_CONFLICT")
                item["conflicts"].append({
                    "kind": "SOURCE_VS_RULE_RATE",
                    "rule_id": rule["rule_id"],
                    "configured_rate": _fmt(configured),
                    "declared_rates": sorted(
                        _fmt(v) for v in declared_fracs),
                })
                continue
            rate_frac = configured

        # basis
        if rule.get("calculation_basis") == "EXPLICIT_BASIS":
            basis_type = rule.get("basis_tax_type", "TAXABLE_BASIS")
            basis_items = _tax_items(
                tax_evidence_docs, {basis_type},
                option_scope=option_scope, kind="amount")
            amounts = {it.get("amount") for it in basis_items
                       if it.get("amount")}
            if len(amounts) != 1:
                reasons.append("TAX_BASIS_NOT_ESTABLISHED")
                continue
            basis = _dec(next(iter(amounts)))
            basis_ccy = basis_items[0].get("currency")
            if basis_ccy and basis_ccy != currency:
                reasons.append("FX_REQUIRED")
                continue
        else:
            basis = gross
        if basis is None:
            reasons.append("TAX_BASIS_NOT_ESTABLISHED")
            continue

        # aritmetica: exacta + rounding explicito
        with localcontext() as ctx:
            ctx.prec = 40
            raw_tax = basis * rate_frac
        rnd = rule.get("rounding") or {}
        mode = rnd.get("mode", "NONE")
        if mode == "NONE":
            withholding = raw_tax
        else:
            scale = int(rnd.get("scale", 2))
            if rnd.get("currency") and rnd["currency"] != currency:
                reasons.append("ROUNDING_CURRENCY_MISMATCH")
                continue
            withholding = raw_tax.quantize(
                Decimal(1).scaleb(-scale),
                rounding=_ROUNDING[mode])
        component = {
            "component_type": "WITHHOLDING_PRIMARY",
            "basis": _money(basis, currency),
            "rate_fraction": _fmt(rate_frac),
            "rate_source": rate_source,
            "amount": _fmt(withholding),
            "currency": currency,
            "rule_id": rule["rule_id"],
            "evidence_refs": [
                it.get("_source_sha256") for it in
                (*declared_rates, *declared_amounts)
                if it.get("_source_sha256")],
        }
        net = gross - withholding
        item["tax_components"].append(component)
        item["total_withholding"] = _money(withholding, currency)
        item["expected_net_cash"] = _money(net, currency)
        item["status"] = CALCULATED
        item["trace"] = {
            "gross": _fmt(gross),
            "currency": currency,
            "rule_id": rule["rule_id"],
            "rate_source": rate_source,
            "rate_fraction": _fmt(rate_frac),
            "basis": _fmt(basis),
            "raw_tax": _fmt(raw_tax),
            "rounding": {
                "mode": mode,
                "scale": rnd.get("scale"),
                "currency": rnd.get("currency"),
            },
            "withholding": _fmt(withholding),
            "net": _fmt(net),
            "calculation_date": calculation_date,
            "profile_fields_used": sorted(
                (rule.get("conditions") or {}).keys()),
        }
    return base


def _evidence_components(items):
    """Componentes declarados en evidencia (no calculados)."""
    out = []
    for it in items:
        out.append({
            "component_type": it.get("tax_type"),
            "basis": None,
            "rate_fraction": _fmt(_rate_fraction(
                it.get("rate_lexeme"), it.get("rate_unit"))),
            "rate_source": "SOURCE_DECLARED_RATE",
            "amount": it.get("amount"),
            "currency": it.get("currency"),
            "rule_id": None,
            "evidence_refs": [it.get("_source_sha256")],
        })
    return out


def expected_cash(tax_entitlement_doc: dict) -> dict:
    """CA_ES_TAX_ENTITLEMENT_V1 -> CA_ES_EXPECTED_CASH_V1.

    Lado esperado de la reconciliacion NET; el movimiento V2 sigue
    siendo el lado actual."""
    items = []
    for it in tax_entitlement_doc.get("items") or []:
        gross = it.get("gross_entitlement")
        wh = it.get("total_withholding")
        net = it.get("expected_net_cash")
        calculated = it.get("status") == CALCULATED
        items.append({
            "account_id": it.get("account_id"),
            "gross_expected": gross,
            "tax_expected": wh,
            "other_deductions_expected": None,
            "net_expected": net if calculated else None,
            "currency": (gross or {}).get("currency"),
            "gross_basis_status": "KNOWN" if gross else "UNKNOWN",
            "tax_status": it.get("status"),
            "net_status": "AVAILABLE" if calculated else
            "NOT_AVAILABLE",
            "reason_codes": list(it.get("reason_codes") or []),
            "evidence_refs": [
                tax_entitlement_doc.get("ruleset_sha256"),
                tax_entitlement_doc.get("profile_sha256"),
            ],
        })
    return {
        "schema": EXPECTED_CASH_SCHEMA,
        "generated_at": tax_entitlement_doc.get("generated_at"),
        "canonical_event_id": tax_entitlement_doc.get(
            "canonical_event_id"),
        "tax_entitlement_sha256": _sha(tax_entitlement_doc),
        "items": items,
    }
