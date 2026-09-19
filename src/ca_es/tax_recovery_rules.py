"""P15.1 — CA_ES_TAX_RECOVERY_RULES_V1: ruleset recovery declarativo.

Mismas invariantes que CA_ES_TAX_RULES_V1 (P14): datos, no codigo;
sin eval(); effective-dating estricto; solapes -> error estatico.

Una regla recovery declara:
- recovery_method: RELIEF_AT_SOURCE | QUICK_REFUND | STANDARD_RECLAIM
- entitled_rate (+rate_unit): tasa a la que el perfil tiene derecho
  segun esta regla. El importe recuperable NUNCA se deriva de
  `actual > P14 expected`: se calcula como
  (withheld_evidenced - entitled) sobre la base explicita.
- conditions: predicados sobre el perfil (mismo vocabulario P14).
- deadline: {basis: PAYMENT_DATE, months: N} — plazo statutory
  effective-dated; no existe plazo generico por defecto.
- required_documents: doc types exigidos para READY_TO_SUBMIT.
- submission: {channel: MANUAL | PROVIDER_PROFILE} — PROVIDER_PROFILE
  exige un CA_ES_TAX_RECOVERY_PROVIDER_V1 valido en la instruccion.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from .tax_rules import CONDITION_FIELDS

RULES_SCHEMA = "CA_ES_TAX_RECOVERY_RULES_V1"

RECOVERY_METHODS = {
    "RELIEF_AT_SOURCE",
    "QUICK_REFUND",
    "STANDARD_RECLAIM",
}

DOC_TYPES = {
    "RESIDENCE_CERTIFICATE",
    "BENEFICIAL_OWNER_DECLARATION",
    "BENEFICIAL_OWNER_REFERENCE",      # BORE
    "TAX_RECLAIM_FORM",
    "RECLAIM_DOCUMENTATION_REFERENCE",  # TARE
    "VOUCHER",
    "POWER_OF_ATTORNEY",
    "OTHER",
}

SUBMISSION_CHANNELS = {"MANUAL", "PROVIDER_PROFILE"}

DEADLINE_BASES = {"PAYMENT_DATE"}

RULE_REQUIRED = {
    "rule_id", "jurisdiction", "income_type", "valid_from",
    "recovery_method", "entitled_rate", "rate_unit", "deadline",
}


def _iso_date(value):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _dec(raw):
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def validate_recovery_ruleset(doc: dict) -> list[str]:
    """Errores estaticos; [] = ruleset valido."""
    errors = []
    if doc.get("schema") != RULES_SCHEMA:
        return [f"schema debe ser {RULES_SCHEMA}"]
    rules = doc.get("rules")
    if not isinstance(rules, list) or not rules:
        return ["rules debe ser una lista no vacia"]
    seen_ids = set()
    for i, r in enumerate(rules):
        tag = f"rules[{i}]"
        if not isinstance(r, dict):
            errors.append(f"{tag} no es objeto")
            continue
        missing = RULE_REQUIRED - set(r)
        if missing:
            errors.append(f"{tag} faltan {sorted(missing)}")
            continue
        rid = r["rule_id"]
        if rid in seen_ids:
            errors.append(f"{tag} rule_id duplicado: {rid}")
        seen_ids.add(rid)
        vf, vt = _iso_date(r.get("valid_from")), _iso_date(
            r.get("valid_to"))
        if vf is None:
            errors.append(f"{tag} valid_from no ISO")
        if r.get("valid_to") is not None and vt is None:
            errors.append(f"{tag} valid_to no ISO")
        if vf and vt and vf > vt:
            errors.append(f"{tag} valid_from > valid_to")
        if r.get("recovery_method") not in RECOVERY_METHODS:
            errors.append(f"{tag} recovery_method desconocido")
        if _dec(r.get("entitled_rate")) is None:
            errors.append(f"{tag} entitled_rate ausente/no decimal")
        if r.get("rate_unit") not in ("PERCENTAGE", "FRACTION"):
            errors.append(f"{tag} rate_unit debe ser "
                          f"PERCENTAGE|FRACTION")
        conds = r.get("conditions") or {}
        if not isinstance(conds, dict):
            errors.append(f"{tag} conditions no es objeto")
            conds = {}
        unknown = set(conds) - CONDITION_FIELDS
        if unknown:
            errors.append(f"{tag} conditions desconocidas: "
                          f"{sorted(unknown)}")
        for field, values in conds.items():
            if not isinstance(values, list) or not values:
                errors.append(f"{tag} conditions.{field} debe ser "
                              f"lista no vacia")
        dl = r.get("deadline")
        if not isinstance(dl, dict):
            errors.append(f"{tag} deadline no es objeto")
        else:
            if dl.get("basis") not in DEADLINE_BASES:
                errors.append(f"{tag} deadline.basis desconocido")
            months = dl.get("months")
            if not isinstance(months, int) or months < 0:
                errors.append(f"{tag} deadline.months invalido")
        docs = r.get("required_documents") or []
        if not isinstance(docs, list):
            errors.append(f"{tag} required_documents no es lista")
        else:
            bad_docs = set(docs) - DOC_TYPES
            if bad_docs:
                errors.append(f"{tag} doc types desconocidos: "
                              f"{sorted(bad_docs)}")
        sub = r.get("submission") or {}
        if sub and sub.get("channel") not in SUBMISSION_CHANNELS:
            errors.append(f"{tag} submission.channel desconocido")

    # solapes: mismo (jurisdiction, income_type, recovery_method)
    # con ventanas que se tocan -> conditions disjuntas obligatorias
    for i, a in enumerate(rules):
        for j, b in enumerate(rules):
            if j <= i:
                continue
            key_a = (a.get("jurisdiction"), a.get("income_type"),
                     a.get("recovery_method"))
            key_b = (b.get("jurisdiction"), b.get("income_type"),
                     b.get("recovery_method"))
            if key_a != key_b:
                continue
            avf, avt = _iso_date(a.get("valid_from")), _iso_date(
                a.get("valid_to")) or date.max
            bvf, bvt = _iso_date(b.get("valid_from")), _iso_date(
                b.get("valid_to")) or date.max
            if avf is None or bvf is None or avf > bvt or bvf > avt:
                continue
            ca, cb = a.get("conditions") or {}, b.get(
                "conditions") or {}
            disjoint = any(
                set(ca.get(k) or []) & set(cb.get(k) or []) == set()
                and ca.get(k) and cb.get(k)
                for k in CONDITION_FIELDS)
            if not disjoint:
                errors.append(
                    f"rules[{i}] y rules[{j}] solapan en ventana "
                    f"sin conditions disjuntas "
                    f"({a.get('rule_id')} vs {b.get('rule_id')})")
    return errors


def recovery_rule_candidates(ruleset: dict, jurisdiction: str,
                             income_type: str, as_of: str,
                             method: str | None = None) -> tuple[
                                 list, list]:
    """Reglas recovery vigentes para (jurisdiction, income_type,
    fecha[, method]). Devuelve (reglas, reasons)."""
    day = _iso_date(as_of)
    if day is None:
        return [], ["INVALID_ASSESSMENT_DATE"]
    active = []
    expired = 0
    for r in ruleset.get("rules") or []:
        if r.get("jurisdiction") != jurisdiction:
            continue
        if r.get("income_type") != income_type:
            continue
        if method is not None and r.get("recovery_method") != method:
            continue
        vf = _iso_date(r.get("valid_from"))
        vt = _iso_date(r.get("valid_to")) or date.max
        if vf and vf <= day <= vt:
            active.append(r)
        else:
            expired += 1
    if not active and expired:
        return [], ["RULE_NOT_EFFECTIVE"]
    if not active:
        return [], ["NO_APPLICABLE_RULE"]
    return active, []


def rule_deadline(rule: dict, payment_date: str) -> str | None:
    """Fecha limite explicita = payment_date + deadline.months.

    Devuelve ISO date o None si la base no esta probada.
    """
    dl = rule.get("deadline") or {}
    if dl.get("basis") != "PAYMENT_DATE":
        return None
    base = _iso_date(payment_date)
    months = dl.get("months")
    if base is None or not isinstance(months, int):
        return None
    month = base.month - 1 + months
    year = base.year + month // 12
    month = month % 12 + 1
    # ultimo dia del mes si el dia no existe (p.ej. 31 -> 30/28)
    days = [31, 29 if year % 4 == 0 and (
        year % 100 != 0 or year % 400 == 0) else 28,
        31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day = min(base.day, days[month - 1])
    return date(year, month, day).isoformat()
