"""P6.1 — Expected position / security impact.

docs/p6/p61-scope.md:

    canonical event + CA_ES_POSITIONS_V1 + CA_ES_IMPACT_RULES_V1
    (+ CA_ES_ENTITLEMENT_V1 cuando la regla lo exige)
        -> compute_position_impact()
        -> CA_ES_POSITION_IMPACT_V1

Capacidad congelada por la auditoria P6.0: el unico tipo de impacto
implementable es CASH_RECEIVABLE para CASH_DIVIDEND, compuesto del
resultado P2.0 ya adjudicado (CA_ES_ENTITLEMENT_V1). Este modulo nunca
recalcula un entitlement ni implementa una segunda formula de cash.

Reglas duras:

- reglas explicitas (CA_ES_IMPACT_RULES_V1); event_type sin regla ->
  UNSUPPORTED/NO_RULE; regla UNSUPPORTED -> reason preregistrada;
- binding fail-closed del doc de entitlements por evento y por celda
  (account_id, isin, position_quantity, position_as_of);
- los estados del entitlement se propagan verbatim: INDETERMINATE y
  UNSUPPORTED nunca se reinterpretan;
- Decimal exclusivamente; ningun input se muta; sin rounding,
  fracciones, cash-in-lieu, retencion, FX, netting ni agregacion;
- el source ISIN nunca se sustituye por un target ausente.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

from .canonical import load_strict_json_object, sha256_hex

IMPACT_SCHEMA = "CA_ES_POSITION_IMPACT_V1"
RULES_SCHEMA = "CA_ES_IMPACT_RULES_V1"
CANON_SCHEMA = "CA_ES_OPERATIONAL_CANON_V1"
POSITIONS_SCHEMA = "CA_ES_POSITIONS_V1"
ENTITLEMENT_SCHEMA = "CA_ES_ENTITLEMENT_V1"

PROJECTED = "PROJECTED"
INDETERMINATE = "INDETERMINATE"
UNSUPPORTED = "UNSUPPORTED"

CASH_RECEIVABLE = "CASH_RECEIVABLE"

_RULE_SUPPORTED = "SUPPORTED"
_RULE_UNSUPPORTED = "UNSUPPORTED"


def load_impact_rules(path: Path) -> dict:
    doc = load_strict_json_object(path)
    if doc.get("schema") != RULES_SCHEMA:
        raise ValueError(
            f"impact rules schema debe ser {RULES_SCHEMA}, "
            f"recibido {doc.get('schema')!r}"
        )
    rules = doc.get("rules")
    if not isinstance(rules, list) or any(
        not isinstance(rule, dict) for rule in rules
    ):
        raise ValueError("rules debe ser una lista de objetos")
    for rule in rules:
        if not rule.get("rule_id") or not rule.get("event_type"):
            raise ValueError("cada regla requiere rule_id y event_type")
    return doc


def _require_doc(doc: dict, schema: str, name: str,
                 key: str = "schema") -> None:
    if doc.get(key) != schema:
        raise ValueError(
            f"{name} schema debe ser {schema}, "
            f"recibido {doc.get(key)!r}"
        )


def _position_quantity(position: dict) -> Decimal | None:
    raw = position.get("quantity")
    if isinstance(raw, float):  # nunca float en el contrato
        return None
    try:
        quantity = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return quantity if quantity.is_finite() else None


def _find_rule(rules_doc: dict, event_type: str) -> dict | None:
    matches = [
        r for r in rules_doc.get("rules", [])
        if r.get("event_type") == event_type
    ]
    return matches[0] if len(matches) == 1 else None


def _entitlement_cell(entitlements_doc: dict, position: dict) -> tuple:
    """(cell, reason): binding fail-closed por identidad de posicion."""
    account_id = position.get("account_id")
    isin = position.get("isin")
    quantity = _position_quantity(position)
    quantity_raw = format(quantity, "f") if quantity is not None else None
    as_of = position.get("as_of")
    cells = [
        c for c in entitlements_doc.get("entitlements", [])
        if c.get("account_id") == account_id
        and c.get("isin") == isin
        and c.get("position_quantity") == quantity_raw
        and c.get("position_as_of") == (as_of or entitlements_doc.get(
            "positions_as_of"))
    ]
    if not cells:
        return None, "ENTITLEMENT_CELL_MISSING"
    if len(cells) > 1:
        return None, "ENTITLEMENT_CELL_AMBIGUOUS"
    return cells[0], None


def _impact_item(position: dict, rule: dict | None, event_type: str,
                 entitlements_doc: dict | None,
                 provenance: dict,
                 entitlement_error: str | None = None) -> dict:
    reasons: list[str] = []
    item = {
        "canonical_event_id": provenance["canonical_event_id"],
        "account_id": position.get("account_id"),
        "source_isin": position.get("isin"),
        "target_isin": None,
        "impact_type": None,
        "status": None,
        "input_quantity": None,
        "output_quantity": None,
        "quantity_delta": None,
        "cash_amount": None,
        "currency": None,
        "rule_id": rule.get("rule_id") if rule else None,
        "basis_date": None,
        "reasons": reasons,
        **provenance["source_hashes"],
        "evidence": {
            "assertion_ids": [],
            "source_document_ids": [],
            "evidence_locators": [],
        },
    }

    quantity = _position_quantity(position)
    if quantity is not None:
        item["input_quantity"] = format(quantity, "f")

    if rule is None:
        reasons.append("NO_RULE")
        item["status"] = UNSUPPORTED
        return item
    if rule.get("status") != _RULE_SUPPORTED:
        reasons.append(rule.get("reason") or "RULE_UNSUPPORTED")
        item["status"] = UNSUPPORTED
        return item

    # unica regla implementable en V1: CASH_RECEIVABLE por composicion
    # del entitlement P2.0 ya adjudicado
    item["impact_type"] = rule.get("impact_type")
    if rule.get("impact_type") != CASH_RECEIVABLE:
        reasons.append("UNSUPPORTED_IMPACT_TYPE")
        item["status"] = UNSUPPORTED
        return item
    if entitlement_error is not None:
        reasons.append(entitlement_error)
        item["status"] = INDETERMINATE
        return item
    if entitlements_doc is None:
        reasons.append("MISSING_ENTITLEMENT_INPUT")
        item["status"] = INDETERMINATE
        return item

    cell, reason = _entitlement_cell(entitlements_doc, position)
    if cell is None:
        reasons.append(reason)
        item["status"] = INDETERMINATE
        return item

    cell_status = cell.get("status")
    item["basis_date"] = (cell.get("basis") or {}).get("record_date")
    for key in ("assertion_ids", "source_document_ids",
                "evidence_locators"):
        item["evidence"][key] = list(
            (cell.get("evidence") or {}).get(key) or []
        )
    reasons.extend(cell.get("reasons") or [])

    if cell_status == "ENTITLED":
        item["status"] = PROJECTED
        item["cash_amount"] = cell.get("gross_cash")
        item["currency"] = (cell.get("gross_cash") or {}).get("currency")
    elif cell_status == "NOT_ENTITLED":
        item["status"] = PROJECTED
        currency = (cell.get("gross_per_share") or {}).get("currency")
        item["cash_amount"] = {
            "normalized": "0",
            "currency": currency,
            "scale": 0,
        }
        item["currency"] = currency
    elif cell_status == "UNSUPPORTED":
        item["status"] = UNSUPPORTED
    else:
        item["status"] = INDETERMINATE
    return item


def compute_position_impact(canon_doc: dict, canonical_event_id: str,
                            positions_doc: dict, rules_doc: dict,
                            entitlements_doc: dict | None = None,
                            now: str | None = None) -> dict:
    """canon + positions + rules (+ entitlement) -> impact doc.

    Puro y read-only: ningun input se muta.
    """
    _require_doc(canon_doc, CANON_SCHEMA, "canon",
                 key="canon_version")
    _require_doc(positions_doc, POSITIONS_SCHEMA, "positions")
    _require_doc(rules_doc, RULES_SCHEMA, "impact rules")

    events = {
        e.get("canonical_event_id"): e
        for e in canon_doc.get("events", [])
    }
    event = events.get(canonical_event_id)
    if event is None:
        raise ValueError(
            f"canonical_event_id no existe en el canon: "
            f"{canonical_event_id!r}"
        )
    event_type = event.get("event_type")

    if entitlements_doc is not None:
        _require_doc(entitlements_doc, ENTITLEMENT_SCHEMA,
                     "entitlements", key="entitlement_version")

    rule = _find_rule(rules_doc, event_type)
    entitlement_sha = (
        sha256_hex(entitlements_doc)
        if entitlements_doc is not None else None
    )
    provenance = {
        "canonical_event_id": canonical_event_id,
        "source_hashes": {
            "source_canon_logical_sha256": canon_doc.get(
                "logical_sha256"),
            "source_positions_logical_sha256": sha256_hex(
                positions_doc),
            "source_entitlement_sha256": entitlement_sha,
        },
    }

    doc_reasons: list[str] = []
    entitlement_error = None
    if (
        rule is not None
        and rule.get("status") == _RULE_SUPPORTED
        and CASH_RECEIVABLE == rule.get("impact_type")
    ):
        if entitlements_doc is None:
            doc_reasons.append("MISSING_ENTITLEMENT_INPUT")
        elif (
            entitlements_doc.get("canonical_event_id")
            != canonical_event_id
            or entitlements_doc.get("event_type") != event_type
        ):
            doc_reasons.append("ENTITLEMENT_EVENT_MISMATCH")
            entitlement_error = "ENTITLEMENT_EVENT_MISMATCH"
            entitlements_doc = None

    impacts = [
        _impact_item(
            position, rule, event_type, entitlements_doc, provenance,
            entitlement_error=entitlement_error)
        for position in positions_doc.get("positions", [])
    ]

    summary = {"positions": len(impacts)}
    for status in (PROJECTED, INDETERMINATE, UNSUPPORTED):
        summary[status.casefold()] = sum(
            1 for i in impacts if i["status"] == status
        )

    return {
        "schema": IMPACT_SCHEMA,
        "generated_at": now,
        "canonical_event_id": canonical_event_id,
        "event_type": event_type,
        "positions_as_of": positions_doc.get("as_of"),
        "rule_id": rule.get("rule_id") if rule else None,
        "reasons": doc_reasons,
        **provenance["source_hashes"],
        "impacts": impacts,
        "summary": summary,
    }
