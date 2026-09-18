"""P14.6/P14.7 — CA_ES_TAX_RULES_V1: ruleset versionado y declarativo.

Las reglas son DATOS, no codigo. El evaluador es un interprete
declarativo minimo (opcion A de P14.7): predicados explicitos,
rate declarada o referenciada, basis explicita, rounding explicito.

- sin eval(), sin codigo en config;
- validacion estatica completa del ruleset;
- effective-dating estricto: una regla aplica en
  [valid_from, valid_to] inclusive; fuera -> NO_APPLICABLE_RULE;
- solapes dentro de (jurisdiction, income_type) con predicados no
  disjuntos -> error de validacion, nunca resolucion implicita;
- rate_source:
    CONFIGURED_STATUTORY_RATE -> rate/rate_unit obligatorios;
    CONFIGURED_TREATY_RATE    -> idem + conditions.treaty_profile;
    SOURCE_DECLARED_RATE      -> rate tomada del mensaje;
    EXEMPT                    -> retencion 0 explicita.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

RULES_SCHEMA = "CA_ES_TAX_RULES_V1"

RATE_SOURCES = {
    "CONFIGURED_STATUTORY_RATE",
    "CONFIGURED_TREATY_RATE",
    "SOURCE_DECLARED_RATE",
    "EXEMPT",
}

BASES = {"GROSS_ENTITLEMENT", "EXPLICIT_BASIS"}

ROUNDING_MODES = {"HALF_UP", "HALF_EVEN", "DOWN", "UP", "NONE"}

CONDITION_FIELDS = {
    "tax_residency",
    "entity_person_classification",
    "beneficial_owner_category",
    "tax_exempt_status",
    "treaty_profile",
    "relief_at_source_status",
}

RULE_REQUIRED = {
    "rule_id", "jurisdiction", "income_type", "valid_from",
    "rate_source", "calculation_basis",
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


def validate_ruleset(doc: dict) -> list[str]:
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
        if r.get("rate_source") not in RATE_SOURCES:
            errors.append(f"{tag} rate_source desconocido")
        if r.get("calculation_basis") not in BASES:
            errors.append(f"{tag} calculation_basis desconocido")
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
        rs = r.get("rate_source")
        if rs in ("CONFIGURED_STATUTORY_RATE",
                  "CONFIGURED_TREATY_RATE"):
            if _dec(r.get("rate")) is None:
                errors.append(f"{tag} rate ausente/no decimal")
            if r.get("rate_unit") not in ("PERCENTAGE", "FRACTION"):
                errors.append(f"{tag} rate_unit debe ser "
                              f"PERCENTAGE|FRACTION")
        if rs == "CONFIGURED_TREATY_RATE" and not conds.get(
                "treaty_profile"):
            errors.append(f"{tag} TREATY_RATE sin "
                          f"conditions.treaty_profile")
        if rs in ("SOURCE_DECLARED_RATE", "EXEMPT") and r.get(
                "rate") is not None:
            errors.append(f"{tag} rate no aplica a {rs}")
        rnd = r.get("rounding")
        if rnd is None:
            errors.append(f"{tag} rounding ausente (obligatorio: "
                          f"explicito o NONE)")
        else:
            if rnd.get("mode") not in ROUNDING_MODES:
                errors.append(f"{tag} rounding.mode desconocido")
            if rnd.get("mode") != "NONE":
                scale = rnd.get("scale")
                if not isinstance(scale, int) or scale < 0:
                    errors.append(f"{tag} rounding.scale invalido")
        # calculo con basis explicita requiere evidence de basis
        if r.get("calculation_basis") == "EXPLICIT_BASIS" and not r.get(
                "basis_tax_type"):
            errors.append(f"{tag} EXPLICIT_BASIS sin basis_tax_type")

    # solapes: dos reglas del mismo (jurisdiction, income_type) con
    # ventanas que se tocan deben tener conditions disjuntas
    for i, a in enumerate(rules):
        for j, b in enumerate(rules):
            if j <= i:
                continue
            if (a.get("jurisdiction"), a.get("income_type")) != (
                    b.get("jurisdiction"), b.get("income_type")):
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


def rule_candidates(ruleset: dict, jurisdiction: str,
                    income_type: str, as_of: str) -> tuple[list, list]:
    """Reglas vigentes para (jurisdiction, income_type, fecha).

    Devuelve (reglas, reasons); la seleccion por profile ocurre en
    tax_entitlement (aqui no hay profile).
    """
    day = _iso_date(as_of)
    if day is None:
        return [], ["INVALID_CALCULATION_DATE"]
    active = []
    expired = 0
    for r in ruleset.get("rules") or []:
        if r.get("jurisdiction") != jurisdiction:
            continue
        if r.get("income_type") != income_type:
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


def conditions_satisfied(rule: dict, profile: dict) -> tuple[
        bool, list]:
    """(ok, missing_fields): cada condition debe estar presente en el
    profile y su valor dentro del vocabulario de la regla."""
    missing = []
    for field, allowed in (rule.get("conditions") or {}).items():
        value = profile.get(field)
        if value is None:
            missing.append(field.upper())
            continue
        if value not in allowed:
            return False, []
    return not missing, missing
