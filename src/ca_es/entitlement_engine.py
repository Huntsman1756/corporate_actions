"""P2.0 Cash Dividend Entitlement — derecho monetario determinista.

Contrato:

    (position snapshot, canonical event, as_of) -> entitlement()

Solo dividendo cash simple: ``gross_per_share x entitled_quantity``.
Sin retenciones, sin netting, sin FX, sin market practice inventada.

Nota de nombre: ``ca_es.entitlement`` (core G0-G3) modela la
*entitlement basis* como assertion temporal; este modulo es la capa
de calculo P2 sobre el canon materializado por Surface.

Reglas:

- posicion/cuenta es un input separado del canon (CA_ES_POSITIONS_V1);
- Decimal exclusivamente; jamas float;
- entitlement calculado != instruccion != settlement;
- toda cifra se remonta a posicion + assertion del evento + regla;
- si falta record_date, posicion valida, importe o moneda:
  INDETERMINATE, no estimacion.

Elegibilidad P2.0 (unica regla, explicita):

    POSITION_AT_RECORD_DATE: la posicion esta datada exactamente en
    record_date (snapshot de custodia a fecha de registro). Un snapshot
    anterior no prueba titularidad en record (pudo venderse) y uno
    posterior no prueba adquisicion previa: ambos -> INDETERMINATE.
    Ampliaciones de elegibilidad quedan para P2.1 con reglas probadas.

Statuses: ENTITLED / NOT_ENTITLED / INDETERMINATE / UNSUPPORTED.
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

ENTITLEMENT_VERSION = "CA_ES_ENTITLEMENT_V1"
POSITIONS_SCHEMA = "CA_ES_POSITIONS_V1"

SUPPORTED_EVENT_TYPES = {"CASH_DIVIDEND"}

ENTITLED = "ENTITLED"
NOT_ENTITLED = "NOT_ENTITLED"
INDETERMINATE = "INDETERMINATE"
UNSUPPORTED = "UNSUPPORTED"

RULE_CASH_DIVIDEND = (
    "CASH_DIVIDEND_GROSS_PER_SHARE_X_POSITION_AT_RECORD_DATE"
)


def _money(normalized: Decimal, currency: str) -> dict:
    return {
        "normalized": format(normalized, "f"),
        "currency": currency,
        "scale": -normalized.as_tuple().exponent,
    }


def load_positions(path: Path) -> dict:
    """Carga un documento CA_ES_POSITIONS_V1 (input separado del
    canon; la validacion de campos es por posicion, en compute)."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != POSITIONS_SCHEMA:
        raise ValueError(
            f"positions schema debe ser {POSITIONS_SCHEMA}, "
            f"recibido {doc.get('schema')!r}"
        )
    return doc


def _current_value(state: dict, field_path: str) -> list[dict] | None:
    """Entradas vigentes de un field si el estado es CURRENT (un unico
    valor factual; puede estar afirmado por varias fuentes — todas van
    a evidencia). None si ausente o CONFLICTING."""
    field = state.get(field_path)
    if field is None or field["status"] != "CURRENT":
        return None
    return field["values"]


def _position_quantity(position: dict) -> Decimal | None:
    raw = position.get("quantity")
    if isinstance(raw, float):  # nunca float en el contrato
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def _entitlement(
    event: dict,
    event_isins: set[str],
    gross_entries: list[dict] | None,
    gross_reason: str | None,
    record_entries: list[dict] | None,
    record_reason: str | None,
    position: dict,
    default_as_of: str | None,
) -> dict:
    reasons: list[str] = []
    account_id = position.get("account_id")
    isin = position.get("isin")
    quantity = _position_quantity(position)
    position_as_of = position.get("as_of") or default_as_of

    base = {
        "account_id": account_id,
        "isin": isin,
        "position_quantity": (
            format(quantity, "f") if quantity is not None else None
        ),
        "position_as_of": position_as_of,
        "reasons": reasons,
        "evidence": {
            "rule": RULE_CASH_DIVIDEND,
            "assertion_ids": [],
            "source_document_ids": [],
            "evidence_locators": [],
        },
    }

    def fail(status: str, reason: str) -> dict:
        reasons.append(reason)
        return {**base, "status": status}

    if event["event_type"] not in SUPPORTED_EVENT_TYPES:
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
    if gross_reason is not None:
        return fail(INDETERMINATE, gross_reason)
    if record_reason is not None:
        return fail(INDETERMINATE, record_reason)
    if isin not in event_isins:
        return fail(INDETERMINATE, "NO_POSITION_FOR_INSTRUMENT")
    if quantity == 0:
        return fail(NOT_ENTITLED, "ZERO_QUANTITY")

    from datetime import date

    try:
        record_date = date.fromisoformat(record_entries[0]["value"])
    except (ValueError, TypeError):
        return fail(INDETERMINATE, "INVALID_RECORD_DATE")
    try:
        snapshot_day = date.fromisoformat(position_as_of)
    except (ValueError, TypeError):
        return fail(INDETERMINATE, "INVALID_POSITION_AS_OF")
    if snapshot_day != record_date:
        return fail(
            INDETERMINATE,
            "POSITION_SNAPSHOT_BEFORE_RECORD"
            if snapshot_day < record_date
            else "POSITION_SNAPSHOT_AFTER_RECORD",
        )

    gross_value = gross_entries[0]["value"]
    per_share = Decimal(gross_value["normalized"])
    currency = gross_value["currency"]
    gross_cash = per_share * quantity

    for entry in (*gross_entries, *record_entries):
        base["evidence"]["assertion_ids"].append(entry["assertion_id"])
        base["evidence"]["source_document_ids"].append(
            entry["source_document_id"]
        )
        base["evidence"]["evidence_locators"].append(
            entry["evidence_locator"]
        )

    return {
        **base,
        "status": ENTITLED,
        "entitled_quantity": format(quantity, "f"),
        "gross_per_share": {
            "normalized": gross_value["normalized"],
            "currency": currency,
            "scale": gross_value["scale"],
            "assertion_id": gross_entries[0]["assertion_id"],
        },
        "gross_cash": _money(gross_cash, currency),
        "calculation": "gross_per_share x entitled_quantity",
        "basis": {
            "record_date": record_entries[0]["value"],
            "position_eligibility": "POSITION_AT_RECORD_DATE",
        },
    }


def compute_entitlements(
    surface, canonical_event_id: str, positions_doc: dict
) -> dict | None:
    """Entitlements P2.0 para un evento canonico y un documento de
    posiciones. Nunca muta el canon ni las posiciones."""
    event = surface._find(canonical_event_id)
    if event is None:
        return None

    current = surface._current_state(event)
    event_isins = surface._event_isins(event)

    gross_entries = _current_value(current, "amount.gross_per_share")
    gross_reason = None
    if gross_entries is None:
        gross_reason = (
            "MISSING_GROSS_AMOUNT"
            if "amount.gross_per_share" not in current
            else "CONFLICTING_GROSS_AMOUNT"
        )
    elif not (
        isinstance(gross_entries[0]["value"], dict)
        and gross_entries[0]["value"].get("__financial__")
    ):
        gross_entries = None
        gross_reason = "NON_FINANCIAL_GROSS_AMOUNT"
    elif not gross_entries[0]["value"].get("currency"):
        gross_entries = None
        gross_reason = "MISSING_CURRENCY"

    record_entries = _current_value(current, "date.record_date")
    record_reason = None
    if record_entries is None:
        record_reason = (
            "MISSING_RECORD_DATE"
            if "date.record_date" not in current
            else "CONFLICTING_RECORD_DATE"
        )

    default_as_of = positions_doc.get("as_of")
    entitlements = [
        _entitlement(
            event,
            event_isins,
            gross_entries,
            gross_reason,
            record_entries,
            record_reason,
            position,
            default_as_of,
        )
        for position in positions_doc.get("positions", [])
    ]

    summary = {"positions": len(entitlements)}
    for status in (ENTITLED, NOT_ENTITLED, INDETERMINATE, UNSUPPORTED):
        summary[status.casefold()] = sum(
            1 for e in entitlements if e["status"] == status
        )

    return {
        "entitlement_version": ENTITLEMENT_VERSION,
        "canonical_event_id": canonical_event_id,
        "event_type": event["event_type"],
        "positions_as_of": default_as_of,
        "entitlements": entitlements,
        "summary": summary,
    }
