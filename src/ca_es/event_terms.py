"""P8.1 — CA_ES_EVENT_TERMS_V1: operandos de evento normalizados.

docs/p8/p81-split.md:

    CA_ES_SWIFT_CA_MESSAGE_V1 (+ CA_ES_SWIFT_EVENT_BINDING_V1 opc.)
        -> build_event_terms() -> CA_ES_EVENT_TERMS_V1

El doc de terms es la frontera entre "lo que el mensaje afirma" y
"lo que el dominio puede computar". Ningun operando se rellena por
convencion: campo ausente -> reason explicita -> INCOMPLETE.

V1: familias MAND de transformacion de valores (SPLIT forward y
REVERSE_SPLIT via SPLR). Eventos CHOS/VOLU -> UNSUPPORTED en terms
(su outcome vive en el flujo P5, no aqui).
"""
from __future__ import annotations

from datetime import datetime, timezone

TERMS_SCHEMA = "CA_ES_EVENT_TERMS_V1"
CA_MESSAGE_SCHEMA = "CA_ES_SWIFT_CA_MESSAGE_V1"
BINDING_SCHEMA = "CA_ES_SWIFT_EVENT_BINDING_V1"

PROVEN = "PROVEN"
INCOMPLETE = "INCOMPLETE"
UNSUPPORTED = "UNSUPPORTED"

# familias cuyo outcome se computa desde terms en V1
SUPPORTED_FAMILIES = {"SPLIT", "RIGHTS_ISSUE", "STOCK_DIVIDEND",
                      "SCRIP_DIVIDEND", "CAPITAL_INCREASE"}

# mechanism -> camv admisible: RHDI/DVSE son MAND (como SPLIT);
# EXRI/DVOP son electivos por definicion (la eleccion la aporta la
# instruccion P5, no el terms). Un DVSE electivo es un scrip
# (P8.5), no un stock dividend
_MECHANISM_CAMV = {
    "RIGHTS_DISTRIBUTION": {"MAND"},
    "RIGHTS_EXERCISE": {"CHOS", "VOLU"},
    "STOCK_DIVIDEND": {"MAND"},
    "SCRIP_DIVIDEND": {"CHOS", "VOLU"},
    # BONU es la unica via demostrada de CAPITAL_INCREASE en V1
    # (ampliacion liberada); CAPI/CAPG/PRIO quedan UNMAPPED
    "BONUS_ISSUE": {"MAND"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _val(field: dict | None):
    f = field or {}
    return f.get("value") if f.get("status") == "PRESENT" else None


def _basis_date(fields: dict) -> dict:
    """La fecha base de elegibilidad MAND es record date (D3)."""
    rd = fields.get("record_date") or {}
    return {
        "value": rd.get("value"),
        "kind": "RECORD_DATE",
        "status": rd.get("status", "ABSENT"),
        "provenance": rd.get("provenance") or [],
    }


def build_event_terms(ca_message: dict, binding: dict | None = None,
                      now: str | None = None) -> dict:
    """CA message (+binding opcional) -> terms normalizados.

    binding ausente o NO_MATCH -> event_basis SWIFT_NOTIFICATION (D2).
    """
    if ca_message.get("schema") != CA_MESSAGE_SCHEMA:
        raise ValueError(
            f"ca_message schema debe ser {CA_MESSAGE_SCHEMA}, "
            f"recibido {ca_message.get('schema')!r}")
    if binding is not None and binding.get("schema") != BINDING_SCHEMA:
        raise ValueError(
            f"binding schema debe ser {BINDING_SCHEMA}, "
            f"recibido {binding.get('schema')!r}")

    fields = ca_message.get("fields") or {}
    event_type = ca_message.get("event_type")
    mechanism = ca_message.get("mechanism")
    camv = _val(fields.get("camv"))
    binding_status = (binding or {}).get("binding_status")
    canonical_event_id = (binding or {}).get("canonical_event_id")
    event_basis = (
        "CANON_BOUND" if binding_status == "BOUND"
        else "SWIFT_NOTIFICATION")

    reasons: list[str] = []
    if event_type not in SUPPORTED_FAMILIES:
        reasons.append("UNSUPPORTED_EVENT_TYPE")
    allowed_camv = _MECHANISM_CAMV.get(mechanism, {"MAND"})
    if camv is None:
        reasons.append("MISSING_CAMV")
    elif camv not in allowed_camv:
        reasons.append(
            f"NON_ADMISSIBLE_CAMV:{camv}"
            if mechanism else f"NON_MANDATORY_EVENT:{camv}")
    if ca_message.get("status") != "OK":
        reasons.append(
            f"MESSAGE_STATUS:{ca_message.get('status')}")

    basis = _basis_date(fields)
    if basis["value"] is None:
        reasons.append(
            "MISSING_BASIS_DATE"
            if basis["status"] == "ABSENT"
            else "CONFLICTING_BASIS_DATE")

    ratio_f = fields.get("new_for_old_ratio") or {}
    ratio = ratio_f.get("value") if ratio_f.get("status") == "PRESENT" \
        else None
    if ratio is None:
        reasons.append(
            "MISSING_RATIO"
            if ratio_f.get("status") == "ABSENT"
            else "CONFLICTING_RATIO")

    source_isin = _val(fields.get("isin"))
    if source_isin is None:
        reasons.append("MISSING_SOURCE_ISIN")
    target_f = fields.get("target_isin") or {}
    target_isin = target_f.get("value") \
        if target_f.get("status") == "PRESENT" else None
    if target_isin is None:
        reasons.append("MISSING_TARGET_INSTRUMENT")
    elif target_f.get("status") == "CONFLICTING":
        reasons.append("CONFLICTING_TARGET_INSTRUMENT")
        target_isin = None

    disf_f = fields.get("fraction_disposition") or {}
    disf = disf_f.get("value") if disf_f.get("status") == "PRESENT" \
        else None
    if disf_f.get("status") == "CONFLICTING":
        reasons.append("CONFLICTING_FRACTION_DISPOSITION")

    price_f = fields.get("subscription_price") or {}
    price = price_f.get("value") if price_f.get("status") == "PRESENT" \
        else None
    if mechanism == "RIGHTS_EXERCISE":
        if price is None:
            reasons.append(
                "MISSING_SUBSCRIPTION_PRICE"
                if price_f.get("status") == "ABSENT"
                else "CONFLICTING_SUBSCRIPTION_PRICE")

    # SCRIP: la pierna CASH tambien debe ser demostrable — ambas
    # opciones tienen que ser economicamente evaluables
    gross_f = fields.get("gross_per_share") or {}
    gross = gross_f.get("value") \
        if gross_f.get("status") == "PRESENT" else None
    ccy_f = fields.get("currency") or {}
    currency = ccy_f.get("value") \
        if ccy_f.get("status") == "PRESENT" else None
    if mechanism == "SCRIP_DIVIDEND":
        if gross is None:
            reasons.append(
                "MISSING_GROSS_PER_SHARE"
                if gross_f.get("status") == "ABSENT"
                else "CONFLICTING_GROSS_PER_SHARE")
        if currency is None:
            reasons.append(
                "MISSING_CURRENCY"
                if ccy_f.get("status") == "ABSENT"
                else "CONFLICTING_CURRENCY")

    if any(r.startswith("UNSUPPORTED") or r.startswith("NON_MAND")
           or r.startswith("NON_ADMISSIBLE")
           or r.startswith("MESSAGE_STATUS")
           for r in reasons):
        terms_status = UNSUPPORTED
    elif reasons:
        terms_status = INCOMPLETE
    else:
        terms_status = PROVEN

    return {
        "schema": TERMS_SCHEMA,
        "generated_at": now or _now(),
        "terms_status": terms_status,
        "reasons": reasons,
        "event_basis": event_basis,
        "canonical_event_id": canonical_event_id,
        "binding_status": binding_status,
        "message_identifier": ca_message.get("message_identifier"),
        "input_sha256": ca_message.get("input_sha256"),
        "caev": ca_message.get("caev"),
        "camv": camv,
        "event_type": event_type,
        "mechanism": ca_message.get("mechanism"),
        "basis_date": basis,
        "ratio": ratio,
        "source_isin": source_isin,
        "target_isin": target_isin,
        "fraction_disposition": disf,
        "subscription_price": price,
        "gross_per_share": gross,
        "currency": currency,
        "cash_in_lieu_price": None,
        "effective_date": _val(fields.get("effective_date")),
        "provenance": {
            "ratio": ratio_f.get("provenance") or [],
            "target_isin": target_f.get("provenance") or [],
            "fraction_disposition":
                disf_f.get("provenance") or [],
            "subscription_price":
                price_f.get("provenance") or [],
            "camv": (fields.get("camv") or {}).get("provenance") or [],
        },
    }
