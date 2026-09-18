"""P8.1 — CA_ES_SECURITIES_ENTITLEMENT_V1.

docs/p8/p81-split.md:

    CA_ES_EVENT_TERMS_V1 + CA_ES_POSITIONS_V1
        -> compute_securities_entitlements()
        -> CA_ES_SECURITIES_ENTITLEMENT_V1

Misma disciplina P2.0: Decimal exclusivamente, fail-closed,
POSITION_AT_RECORD_DATE contra basis_date del terms, estados
propagados verbatim, ningun input mutado.

V1 implementa la transformacion SPLIT (forward y REVERSE_SPLIT —
la direccion ya viene probada por el CAEV del mensaje):

    delivered  = posicion completa del source_isin
    receivable = qty x new/old, residuo resuelto por DISF

DISF (preregistrado, nunca estimado):
    RDDN -> floor          RDUP -> ceil
    STAN -> round-half-up  SECU/DIST -> cantidad exacta (fraccion
                            en valores)
    BUYU -> ceil + cash leg solo con precio afirmado
    CINL -> floor + cash leg solo con precio afirmado
    UKNW/ausente -> si hay fraccion real, INDETERMINATE
                    (FRACTION_DISPOSITION_UNKNOWN); si el resultado
                    es entero, la DISF es irrelevante -> ENTITLED
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, \
    ROUND_FLOOR, ROUND_HALF_UP

TERMS_SCHEMA = "CA_ES_EVENT_TERMS_V1"
SEC_ENT_SCHEMA = "CA_ES_SECURITIES_ENTITLEMENT_V1"
POSITIONS_SCHEMA = "CA_ES_POSITIONS_V1"

ENTITLED = "ENTITLED"
NOT_ENTITLED = "NOT_ENTITLED"
INDETERMINATE = "INDETERMINATE"
UNSUPPORTED = "UNSUPPORTED"

RULE_SPLIT = "SPLIT_POSITION_X_NEW_FOR_OLD_DISF"

_DISF_FLOOR = {"RDDN", "CINL"}
_DISF_CEIL = {"RDUP", "BUYU"}
_DISF_EXACT = {"SECU", "DIST"}
_DISF_CASH_LEG = {"BUYU", "CINL"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _decimal(raw) -> Decimal | None:
    if raw is None or isinstance(raw, float):
        return None
    try:
        value = Decimal(str(raw).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def _money(normalized: Decimal, currency: str) -> dict:
    return {
        "normalized": format(normalized, "f"),
        "currency": currency,
        "scale": -normalized.as_tuple().exponent,
    }


def _apply_disf(raw: Decimal, disf: str | None) -> tuple:
    """(resolved_qty, fraction, cash_leg_required, reason).

    cash_leg_required=True cuando la politica genera pago cash que
    requiere precio afirmado (BUYU/CINL)."""
    if raw == raw.to_integral_value():
        return raw, Decimal(0), False, None
    if disf is None or disf == "UKNW":
        return None, None, False, "FRACTION_DISPOSITION_UNKNOWN"
    if disf in _DISF_EXACT:
        return raw, raw - raw.to_integral_value(), False, None
    if disf in _DISF_FLOOR:
        resolved = raw.to_integral_value(rounding=ROUND_FLOOR)
        return resolved, raw - resolved, disf in _DISF_CASH_LEG, None
    if disf == "STAN":
        resolved = raw.to_integral_value(rounding=ROUND_HALF_UP)
        return resolved, raw - resolved, False, None
    if disf in _DISF_CEIL:
        resolved = raw.to_integral_value(rounding=ROUND_CEILING)
        return resolved, raw - resolved, disf in _DISF_CASH_LEG, None
    return None, None, False, f"UNSUPPORTED_DISF:{disf}"


def _entitlement(terms: dict, position: dict,
                 default_as_of: str | None) -> dict:
    reasons: list[str] = []
    account_id = position.get("account_id")
    isin = position.get("isin")
    quantity = _decimal(position.get("quantity"))
    position_as_of = position.get("as_of") or default_as_of

    base = {
        "account_id": account_id,
        "isin": isin,
        "position_quantity": (
            format(quantity, "f") if quantity is not None else None),
        "position_as_of": position_as_of,
        "reasons": reasons,
        "evidence": {
            "rule": RULE_SPLIT,
            "basis_date_kind": "RECORD_DATE",
        },
    }

    def fail(status: str, reason: str) -> dict:
        reasons.append(reason)
        return {**base, "status": status}

    if terms.get("terms_status") != "PROVEN":
        return fail(UNSUPPORTED,
                    f"TERMS_{terms.get('terms_status')}")
    if terms.get("event_type") != "SPLIT":
        return fail(UNSUPPORTED, "UNSUPPORTED_EVENT_TYPE")
    if account_id is None:
        return fail(INDETERMINATE, "MISSING_ACCOUNT_ID")
    if not isin:
        return fail(INDETERMINATE, "MISSING_ISIN")
    if quantity is None:
        return fail(INDETERMINATE, "INVALID_QUANTITY")
    if quantity < 0:
        return fail(INDETERMINATE, "NEGATIVE_QUANTITY_UNSUPPORTED")
    if position_as_of is None:
        return fail(INDETERMINATE, "MISSING_POSITION_AS_OF")
    if isin != terms.get("source_isin"):
        return fail(INDETERMINATE, "NO_POSITION_FOR_INSTRUMENT")
    if quantity == 0:
        return fail(NOT_ENTITLED, "ZERO_QUANTITY")

    basis_value = (terms.get("basis_date") or {}).get("value")
    try:
        basis_day = date.fromisoformat(basis_value)
        snapshot_day = date.fromisoformat(position_as_of)
    except (ValueError, TypeError):
        return fail(INDETERMINATE, "INVALID_BASIS_OR_POSITION_DATE")
    if snapshot_day != basis_day:
        return fail(
            INDETERMINATE,
            "POSITION_SNAPSHOT_BEFORE_RECORD"
            if snapshot_day < basis_day
            else "POSITION_SNAPSHOT_AFTER_RECORD")

    ratio = terms.get("ratio") or {}
    new_f = _decimal(ratio.get("new"))
    old_f = _decimal(ratio.get("old"))
    if new_f is None or old_f is None or old_f <= 0:
        return fail(INDETERMINATE, "INVALID_RATIO")

    disf = terms.get("fraction_disposition")
    raw_qty = quantity * new_f / old_f
    resolved, fraction, cash_leg, reason = _apply_disf(raw_qty, disf)
    if reason is not None:
        return fail(INDETERMINATE, reason)

    cash_in_lieu = None
    if cash_leg:
        price = terms.get("cash_in_lieu_price")
        if not price or price.get("normalized") is None:
            return fail(INDETERMINATE,
                        "CASH_IN_LIEU_PRICE_MISSING")
        amount = _decimal(price["normalized"])
        if amount is None:
            return fail(INDETERMINATE,
                        "INVALID_CASH_IN_LIEU_PRICE")
        cash_in_lieu = _money(
            amount * abs(fraction), price.get("currency"))

    return {
        **base,
        "status": ENTITLED,
        "delivered": {
            "isin": terms["source_isin"],
            "quantity": format(quantity, "f"),
        },
        "receivable": {
            "isin": terms["target_isin"],
            "quantity": format(resolved, "f"),
        },
        "raw_quantity": format(raw_qty, "f"),
        "fraction": {
            "amount": format(fraction, "f"),
            "disposition": disf or "NOT_REQUIRED",
            "cash_in_lieu": cash_in_lieu,
        },
        "calculation": "position_quantity x new_for_old + DISF",
        "basis": {
            "record_date": basis_value,
            "position_eligibility": "POSITION_AT_RECORD_DATE",
        },
    }


def compute_securities_entitlements(
        terms_doc: dict, positions_doc: dict,
        now: str | None = None) -> dict:
    """terms + positions -> CA_ES_SECURITIES_ENTITLEMENT_V1.

    Puro y read-only: ningun input se muta."""
    if terms_doc.get("schema") != TERMS_SCHEMA:
        raise ValueError(
            f"terms schema debe ser {TERMS_SCHEMA}, "
            f"recibido {terms_doc.get('schema')!r}")
    if positions_doc.get("schema") != POSITIONS_SCHEMA:
        raise ValueError(
            f"positions schema debe ser {POSITIONS_SCHEMA}, "
            f"recibido {positions_doc.get('schema')!r}")

    default_as_of = positions_doc.get("as_of")
    entitlements = [
        _entitlement(terms_doc, position, default_as_of)
        for position in positions_doc.get("positions", [])
    ]
    summary = {"positions": len(entitlements)}
    for status in (ENTITLED, NOT_ENTITLED, INDETERMINATE, UNSUPPORTED):
        summary[status.casefold()] = sum(
            1 for e in entitlements if e["status"] == status)

    return {
        "schema": SEC_ENT_SCHEMA,
        "generated_at": now or _now(),
        "event_basis": terms_doc.get("event_basis"),
        "canonical_event_id": terms_doc.get("canonical_event_id"),
        "message_identifier": terms_doc.get("message_identifier"),
        "input_sha256": terms_doc.get("input_sha256"),
        "caev": terms_doc.get("caev"),
        "event_type": terms_doc.get("event_type"),
        "mechanism": terms_doc.get("mechanism"),
        "terms_status": terms_doc.get("terms_status"),
        "positions_as_of": default_as_of,
        "entitlements": entitlements,
        "summary": summary,
    }
