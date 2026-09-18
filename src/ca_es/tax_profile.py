"""P14.5 — CA_ES_TAX_PROFILE_V1: clasificacion fiscal configurada.

Perfil fiscal de cuenta, configurado explicitamente. NO se infiere:

- tax_residency nunca se deriva de IBAN/BIC/direccion/emisor;
- treaty_profile solo tiene efecto si esta explicitamente presente;
- un campo ausente es un campo ausente: la regla que lo requiera
  produce PROFILE_FIELD_MISSING, nunca un default;
- status (COMPLETE_FOR_RULE/INCOMPLETE/CONFLICTING) se evalua por
  regla en tax_entitlement, no aqui.

El documento es una coleccion versionada de perfiles por cuenta
(mismo patron que CA_ES_CUSTODY_PROFILE_V1 P13.8).
"""

from __future__ import annotations

from datetime import date

PROFILE_SCHEMA = "CA_ES_TAX_PROFILE_V1"

# campos permitidos; cualquier otro es un error de validacion
# (no silent-ignore de identidad fiscal)
PROFILE_FIELDS = {
    "account_id",
    "valid_from",
    "valid_to",
    "tax_residency",
    "beneficial_owner_category",
    "entity_person_classification",
    "tax_exempt_status",
    "treaty_profile",
    "relief_at_source_status",
    "reclaim_status",
    "provider_profile",
    "source",
    "evidence_refs",
}

ENUM_FIELDS = {
    "entity_person_classification": {"PERSON", "ENTITY"},
    "tax_exempt_status": {"NONE", "EXEMPT", "PARTIAL"},
    "relief_at_source_status": {"NONE", "APPLIED", "ELIGIBLE"},
    "reclaim_status": {"NONE", "FILED", "ELIGIBLE", "RECEIVED"},
    "beneficial_owner_category": {
        "RESIDENT_INDIVIDUAL", "RESIDENT_ENTITY",
        "NON_RESIDENT", "EXEMPT_ENTITY", "OTHER_EXPLICIT",
    },
}


def _iso_date(value):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def validate_profile(doc: dict) -> list[str]:
    """Errores estaticos del documento; [] = estructuralmente valido."""
    errors = []
    if doc.get("schema") != PROFILE_SCHEMA:
        return [f"schema debe ser {PROFILE_SCHEMA}"]
    if not doc.get("profile_id"):
        errors.append("profile_id ausente")
    profiles = doc.get("profiles")
    if not isinstance(profiles, list):
        errors.append("profiles debe ser una lista")
        return errors
    seen = set()
    for i, p in enumerate(profiles):
        if not isinstance(p, dict):
            errors.append(f"profiles[{i}] no es objeto")
            continue
        unknown = set(p) - PROFILE_FIELDS
        if unknown:
            errors.append(
                f"profiles[{i}] campos desconocidos: {sorted(unknown)}")
        account = p.get("account_id")
        if not account:
            errors.append(f"profiles[{i}] sin account_id")
        key = (account, p.get("valid_from"))
        if key in seen:
            errors.append(
                f"profiles[{i}] duplicado {account}/{p.get('valid_from')}")
        seen.add(key)
        vf, vt = _iso_date(p.get("valid_from")), _iso_date(
            p.get("valid_to"))
        if p.get("valid_from") is not None and vf is None:
            errors.append(f"profiles[{i}] valid_from no ISO")
        if p.get("valid_to") is not None and vt is None:
            errors.append(f"profiles[{i}] valid_to no ISO")
        if vf and vt and vf > vt:
            errors.append(f"profiles[{i}] valid_from > valid_to")
        for field, vocab in ENUM_FIELDS.items():
            value = p.get(field)
            if value is not None and value not in vocab:
                errors.append(
                    f"profiles[{i}] {field}={value!r} fuera de "
                    f"vocabulario {sorted(vocab)}")
    return errors


def profile_for_account(doc: dict, account_id: str,
                        as_of: str | None) -> tuple[dict | None, list]:
    """Perfil efectivo para (account, fecha) o (None, reasons).

    as_of=None -> se toma el perfil mas reciente por valid_from
    (solo para inspeccion; tax_entitlement siempre pasa fecha).
    """
    day = _iso_date(as_of) if as_of else None
    if as_of and day is None:
        return None, ["INVALID_AS_OF"]
    candidates = []
    for p in doc.get("profiles") or []:
        if p.get("account_id") != account_id:
            continue
        vf = _iso_date(p.get("valid_from"))
        vt = _iso_date(p.get("valid_to"))
        if day is not None:
            if vf and day < vf:
                continue
            if vt and day > vt:
                continue
        candidates.append(p)
    if not candidates:
        return None, ["NO_PROFILE_FOR_ACCOUNT"]
    if len(candidates) > 1:
        # ventanas disjuntas ya garantizan unicidad por fecha; si aun
        # asi hay solape es un conflicto de configuracion
        distinct = {id(p) for p in candidates}
        if len(distinct) > 1:
            return None, ["CONFLICTING_PROFILES"]
    return candidates[0], []
