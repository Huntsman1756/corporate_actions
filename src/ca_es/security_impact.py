"""P8.1 — impacto de valores: securities entitlement -> impact doc.

docs/p8/p81-split.md:

    CA_ES_SECURITIES_ENTITLEMENT_V1 + CA_ES_POSITIONS_V1
        -> compute_security_impact()
        -> CA_ES_POSITION_IMPACT_V1  (mismo contrato P6.1)

Composicion, nunca recalculo: cada celda ENTITLED produce dos items
del impacto — SECURITY_DELIVERY sobre el source_isin y
SECURITY_RECEIPT sobre el target_isin; CASH_IN_LIEU_RECEIVABLE
cuando la DISF lo afirma. Estados propagados verbatim.

`canonical_event_id` puede ser null (event_basis
SWIFT_NOTIFICATION, D2): la provenance es el terms + entitlement,
no el canon.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .canonical import sha256_hex

IMPACT_SCHEMA = "CA_ES_POSITION_IMPACT_V1"
SEC_ENT_SCHEMA = "CA_ES_SECURITIES_ENTITLEMENT_V1"
POSITIONS_SCHEMA = "CA_ES_POSITIONS_V1"

PROJECTED = "PROJECTED"
INDETERMINATE = "INDETERMINATE"
UNSUPPORTED = "UNSUPPORTED"

SECURITY_DELIVERY = "SECURITY_DELIVERY"
SECURITY_RECEIPT = "SECURITY_RECEIPT"
CASH_IN_LIEU_RECEIVABLE = "CASH_IN_LIEU_RECEIVABLE"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _decimal(raw) -> Decimal | None:
    if raw is None or isinstance(raw, float):
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def _cells(ent_doc: dict, position: dict) -> list[dict]:
    """Binding fail-closed por identidad de posicion (mismo criterio
    que P6.1)."""
    account_id = position.get("account_id")
    isin = position.get("isin")
    quantity = _decimal(position.get("quantity"))
    quantity_raw = format(quantity, "f") if quantity is not None \
        else None
    as_of = position.get("as_of") or ent_doc.get("positions_as_of")
    return [
        c for c in ent_doc.get("entitlements", [])
        if c.get("account_id") == account_id
        and c.get("isin") == isin
        and c.get("position_quantity") == quantity_raw
        and c.get("position_as_of") == as_of
    ]


def _item(position: dict, impact_type: str, status: str,
          cell: dict | None, provenance: dict, **kw) -> dict:
    item = {
        "canonical_event_id": provenance["canonical_event_id"],
        "account_id": position.get("account_id"),
        "source_isin": position.get("isin"),
        "target_isin": None,
        "impact_type": impact_type,
        "status": status,
        "input_quantity": kw.get("input_quantity"),
        "output_quantity": kw.get("output_quantity"),
        "quantity_delta": kw.get("quantity_delta"),
        "cash_amount": kw.get("cash_amount"),
        "currency": kw.get("currency"),
        "rule_id": kw.get("rule_id"),
        "basis_date": kw.get("basis_date"),
        "reasons": kw.get("reasons") or [],
        **provenance["source_hashes"],
        "evidence": {
            "assertion_ids": [],
            "source_document_ids": [],
            "evidence_locators":
                ([f"securities_entitlement:{kw.get('cell_index')}"]
                 if cell is not None else []),
        },
    }
    return item


def compute_security_impact(
        ent_doc: dict, positions_doc: dict,
        now: str | None = None) -> dict:
    """securities entitlement + positions -> CA_ES_POSITION_IMPACT_V1."""
    if ent_doc.get("schema") != SEC_ENT_SCHEMA:
        raise ValueError(
            f"entitlement schema debe ser {SEC_ENT_SCHEMA}, "
            f"recibido {ent_doc.get('schema')!r}")
    if positions_doc.get("schema") != POSITIONS_SCHEMA:
        raise ValueError(
            f"positions schema debe ser {POSITIONS_SCHEMA}, "
            f"recibido {positions_doc.get('schema')!r}")

    provenance = {
        "canonical_event_id": ent_doc.get("canonical_event_id"),
        "source_hashes": {
            "source_canon_logical_sha256": None,
            "source_positions_logical_sha256": sha256_hex(
                positions_doc),
            "source_entitlement_sha256": sha256_hex(ent_doc),
        },
    }

    impacts: list[dict] = []
    for position in positions_doc.get("positions", []):
        cells = _cells(ent_doc, position)
        if not cells:
            impacts.append(_item(
                position, None, INDETERMINATE, None, provenance,
                reasons=["ENTITLEMENT_CELL_MISSING"],
                rule_id="SPLIT_POSITION_X_NEW_FOR_OLD_DISF"))
            continue
        if len(cells) > 1:
            impacts.append(_item(
                position, None, INDETERMINATE, None, provenance,
                reasons=["ENTITLEMENT_CELL_AMBIGUOUS"],
                rule_id="SPLIT_POSITION_X_NEW_FOR_OLD_DISF"))
            continue
        cell = cells[0]
        cell_index = ent_doc["entitlements"].index(cell)
        status = cell.get("status")
        basis = ((cell.get("basis") or {}).get("record_date"))
        if status == "ENTITLED":
            delivered = cell["delivered"]
            receivable = cell["receivable"]
            qty = _decimal(delivered["quantity"])
            impacts.append(_item(
                position, SECURITY_DELIVERY, PROJECTED, cell,
                provenance,
                input_quantity=delivered["quantity"],
                output_quantity="0",
                quantity_delta=(
                    format(-qty, "f") if qty is not None else None),
                basis_date=basis,
                rule_id="SPLIT_POSITION_X_NEW_FOR_OLD_DISF",
                cell_index=cell_index,
                reasons=list(cell.get("reasons") or [])))
            recv_item = _item(
                position, SECURITY_RECEIPT, PROJECTED, cell,
                provenance,
                input_quantity="0",
                output_quantity=receivable["quantity"],
                quantity_delta=receivable["quantity"],
                basis_date=basis,
                rule_id="SPLIT_POSITION_X_NEW_FOR_OLD_DISF",
                cell_index=cell_index,
                reasons=list(cell.get("reasons") or []))
            recv_item["target_isin"] = receivable["isin"]
            impacts.append(recv_item)
            cil = (cell.get("fraction") or {}).get("cash_in_lieu")
            if cil:
                impacts.append(_item(
                    position, CASH_IN_LIEU_RECEIVABLE, PROJECTED,
                    cell, provenance,
                    cash_amount=cil,
                    currency=cil.get("currency"),
                    basis_date=basis,
                    rule_id="SPLIT_POSITION_X_NEW_FOR_OLD_DISF",
                    cell_index=cell_index,
                    reasons=list(cell.get("reasons") or [])))
        elif status == "NOT_ENTITLED":
            impacts.append(_item(
                position, SECURITY_DELIVERY, PROJECTED, cell,
                provenance,
                input_quantity="0", output_quantity="0",
                quantity_delta="0", basis_date=basis,
                rule_id="SPLIT_POSITION_X_NEW_FOR_OLD_DISF",
                cell_index=cell_index,
                reasons=list(cell.get("reasons") or [])))
        elif status == "UNSUPPORTED":
            impacts.append(_item(
                position, None, UNSUPPORTED, cell, provenance,
                basis_date=basis,
                rule_id="SPLIT_POSITION_X_NEW_FOR_OLD_DISF",
                cell_index=cell_index,
                reasons=list(cell.get("reasons") or [])))
        else:
            impacts.append(_item(
                position, None, INDETERMINATE, cell, provenance,
                basis_date=basis,
                rule_id="SPLIT_POSITION_X_NEW_FOR_OLD_DISF",
                cell_index=cell_index,
                reasons=list(cell.get("reasons") or [])))

    summary = {"positions": len(impacts)}
    for status in (PROJECTED, INDETERMINATE, UNSUPPORTED):
        summary[status.casefold()] = sum(
            1 for i in impacts if i["status"] == status)

    return {
        "schema": IMPACT_SCHEMA,
        "generated_at": now or _now(),
        "canonical_event_id": ent_doc.get("canonical_event_id"),
        "event_type": ent_doc.get("event_type"),
        "event_basis": ent_doc.get("event_basis"),
        "positions_as_of": positions_doc.get("as_of"),
        "rule_id": "SPLIT_POSITION_X_NEW_FOR_OLD_DISF",
        "reasons": [],
        **provenance["source_hashes"],
        "impacts": impacts,
        "summary": summary,
    }
