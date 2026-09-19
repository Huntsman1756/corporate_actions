"""P16.1 — CA_ES_MARKET_CLAIM_RULES_V1: reglas de mercado explicitas.

Una market claim NUNCA se infiere de
`trade_date < ex_date + settlement_date > record_date`. Eso es solo
la ventana de elegibilidad potencial; la claim exige una regla de
mercado declarada que demuestre:

- tipo de evento canon (event_type),
- ventana de elegibilidad sobre campos explicitos de la transaccion,
- direccion economica (BUYER_COMPENSATED | SELLER_COMPENSATED),
- regimen de claim (claim_type MKTC | RVMC),
- base del proceeds (ENTITLEMENT_RATE: la cuantia viene del
  entitlement P8 calculado, nunca re-derivada aqui),
- deadline operativo effective-dated (opcional pero explicito).

Sin regla aplicable -> MARKET_PRACTICE_REQUIRED. Datos, no codigo:
sin eval/exec; solapes -> error estatico.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

RULES_SCHEMA = "CA_ES_MARKET_CLAIM_RULES_V1"

CLAIM_TYPES = {"MKTC", "RVMC"}
CLAIM_DIRECTIONS = {"BUYER_COMPENSATED", "SELLER_COMPENSATED"}
PROCEEDS_KINDS = {"CASH", "SECURITIES"}

# relaciones temporales evaluables SOLO sobre fechas explicitas
TRADE_RELATIONS = {"BEFORE_EX_DATE", "ON_OR_BEFORE_EX_DATE"}
SETTLEMENT_RELATIONS = {"AFTER_RECORD_DATE", "ON_OR_AFTER_RECORD_DATE"}
SETTLEMENT_STATUSES = {"PENDING", "SETTLED", "SETTLED_LATE",
                       "FAILED", "CANCELLED"}

DEADLINE_BASES = {"RECORD_DATE", "PAYMENT_DATE"}

RULE_REQUIRED = {
    "rule_id", "jurisdiction", "event_type", "valid_from",
    "claim_type", "claim_direction", "eligibility", "proceeds",
}

ELIGIBILITY_REQUIRED = {
    "trade_date_relation", "settlement_status",
    "settlement_date_relation",
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


def validate_claim_ruleset(doc: dict) -> list[str]:
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
        if r.get("claim_type") not in CLAIM_TYPES:
            errors.append(f"{tag} claim_type desconocido")
        if r.get("claim_direction") not in CLAIM_DIRECTIONS:
            errors.append(f"{tag} claim_direction desconocido")
        elig = r.get("eligibility")
        if not isinstance(elig, dict):
            errors.append(f"{tag} eligibility no es objeto")
            elig = {}
        else:
            emiss = ELIGIBILITY_REQUIRED - set(elig)
            if emiss:
                errors.append(f"{tag} eligibility faltan "
                              f"{sorted(emiss)}")
            if elig.get("trade_date_relation") not in \
                    TRADE_RELATIONS:
                errors.append(f"{tag} trade_date_relation "
                              f"desconocido")
            if elig.get("settlement_date_relation") not in \
                    SETTLEMENT_RELATIONS:
                errors.append(f"{tag} settlement_date_relation "
                              f"desconocido")
            st = elig.get("settlement_status")
            if not isinstance(st, list) or not st or \
                    set(st) - SETTLEMENT_STATUSES:
                errors.append(f"{tag} settlement_status debe ser "
                              f"lista no vacia de estados conocidos")
        proceeds = r.get("proceeds")
        if not isinstance(proceeds, dict):
            errors.append(f"{tag} proceeds no es objeto")
        elif proceeds.get("kind") not in PROCEEDS_KINDS:
            errors.append(f"{tag} proceeds.kind desconocido")
        dl = r.get("deadline")
        if dl is not None:
            if not isinstance(dl, dict):
                errors.append(f"{tag} deadline no es objeto")
            else:
                if dl.get("basis") not in DEADLINE_BASES:
                    errors.append(f"{tag} deadline.basis desconocido")
                days = dl.get("days")
                if not isinstance(days, int) or days < 0:
                    errors.append(f"{tag} deadline.days invalido")

    # solapes: misma (jurisdiction, event_type, claim_direction)
    # con ventanas que se tocan -> ambiguedad estatica prohibida
    for i, a in enumerate(rules):
        for j, b in enumerate(rules):
            if j <= i:
                continue
            key_a = (a.get("jurisdiction"), a.get("event_type"),
                     a.get("claim_direction"))
            key_b = (b.get("jurisdiction"), b.get("event_type"),
                     b.get("claim_direction"))
            if key_a != key_b:
                continue
            avf = _iso_date(a.get("valid_from"))
            avt = _iso_date(a.get("valid_to")) or date.max
            bvf = _iso_date(b.get("valid_from"))
            bvt = _iso_date(b.get("valid_to")) or date.max
            if avf is None or bvf is None or avf > bvt or bvf > avt:
                continue
            errors.append(
                f"rules[{i}] y rules[{j}] solapan en ventana "
                f"({a.get('rule_id')} vs {b.get('rule_id')})")
    return errors


def claim_rule_candidates(ruleset: dict, jurisdiction: str,
                          event_type: str, as_of: str,
                          direction: str | None = None) -> tuple[
                              list, list]:
    """Reglas vigentes para (jurisdiction, event_type, fecha[,
    direction]). Devuelve (reglas, reasons)."""
    day = _iso_date(as_of)
    if day is None:
        return [], ["INVALID_ASSESSMENT_DATE"]
    active = []
    expired = 0
    for r in ruleset.get("rules") or []:
        if r.get("jurisdiction") != jurisdiction:
            continue
        if r.get("event_type") != event_type:
            continue
        if direction is not None and \
                r.get("claim_direction") != direction:
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


def claim_deadline(rule: dict, basis_date: str) -> str | None:
    """Fecha limite explicita = basis_date + deadline.days."""
    dl = rule.get("deadline") or {}
    if dl.get("basis") not in DEADLINE_BASES:
        return None
    base = _iso_date(basis_date)
    days = dl.get("days")
    if base is None or not isinstance(days, int):
        return None
    return (base + timedelta(days=days)).isoformat()
