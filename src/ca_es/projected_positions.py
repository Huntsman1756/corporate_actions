"""P6.2 — Projected post-event positions.

docs/p6/p62-scope.md:

    CA_ES_POSITIONS_V1 + CA_ES_POSITION_IMPACT_V1
        -> project_positions()
        -> CA_ES_PROJECTED_POSITIONS_V1

Una linea proyectada por posicion (orden preservado, sin agregacion
ni fusion de instrumentos). En V1 ninguna regla de impacto emite
quantity_delta (P6.0): toda proyeccion alcanzable es delta 0; el
aplicador de deltas es generico sobre el contrato.

Reglas duras:

- binding fail-closed: impact.source_positions_logical_sha256 debe
  igualar sha256(positions) — proyectar sobre otra posicion seria
  inventar;
- un item INDETERMINATE/UNSUPPORTED contamina su linea (la linea
  hereda el estado menos decidido: INDETERMINATE > UNSUPPORTED >
  PROJECTED);
- quantity_delta se aplica al instrumento target_isin (si set) o
  source_isin, en la misma cuenta;
- proyeccion economica esperada, nunca prueba de posicion anotada;
- Decimal exclusivamente; ningun input se muta.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .canonical import sha256_hex

PROJECTED_SCHEMA = "CA_ES_PROJECTED_POSITIONS_V1"
POSITIONS_SCHEMA = "CA_ES_POSITIONS_V1"
IMPACT_SCHEMA = "CA_ES_POSITION_IMPACT_V1"

PROJECTED = "PROJECTED"
INDETERMINATE = "INDETERMINATE"
UNSUPPORTED = "UNSUPPORTED"

# orden de severidad: el estado menos decidido contamina la linea
_SEVERITY = {PROJECTED: 0, UNSUPPORTED: 1, INDETERMINATE: 2}


def _decimal(raw) -> Decimal | None:
    if raw is None or isinstance(raw, float):
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def _item_target_isin(item: dict) -> str | None:
    return item.get("target_isin") or item.get("source_isin")


def project_positions(positions_doc: dict, impact_doc: dict,
                      now: str | None = None) -> dict:
    """positions + impact -> CA_ES_PROJECTED_POSITIONS_V1.

    Puro y read-only: ningun input se muta.
    """
    if positions_doc.get("schema") != POSITIONS_SCHEMA:
        raise ValueError(
            f"positions schema debe ser {POSITIONS_SCHEMA}, "
            f"recibido {positions_doc.get('schema')!r}"
        )
    if impact_doc.get("schema") != IMPACT_SCHEMA:
        raise ValueError(
            f"impact schema debe ser {IMPACT_SCHEMA}, "
            f"recibido {impact_doc.get('schema')!r}"
        )
    if (
        impact_doc.get("source_positions_logical_sha256")
        != sha256_hex(positions_doc)
    ):
        raise ValueError("POSITIONS_HASH_MISMATCH")

    # agrupa items de impacto por (account_id, instrumento destino)
    items_by_key: dict[tuple, list] = {}
    for index, item in enumerate(impact_doc.get("impacts", [])):
        key = (item.get("account_id"), _item_target_isin(item))
        items_by_key.setdefault(key, []).append((index, item))

    lines = []
    for position in positions_doc.get("positions", []):
        account_id = position.get("account_id")
        isin = position.get("isin")
        pre = _decimal(position.get("quantity"))

        reasons: list[str] = []
        line = {
            "account_id": account_id,
            "isin": isin,
            "pre_quantity": format(pre, "f") if pre is not None
            else None,
            "delta_quantity": None,
            "projected_quantity": None,
            "effective_date": None,
            "impact_refs": [],
            "status": INDETERMINATE,
            "reasons": reasons,
        }

        items = items_by_key.get((account_id, isin), [])
        if not items:
            reasons.append("MISSING_IMPACT_ITEM")
            lines.append(line)
            continue

        worst = PROJECTED
        delta = Decimal(0)
        effective_dates = []
        for index, item in items:
            line["impact_refs"].append(f"impacts[{index}]")
            reasons.extend(item.get("reasons") or [])
            status = item.get("status")
            if _SEVERITY.get(status, 2) > _SEVERITY[worst]:
                worst = status
            if status == PROJECTED:
                item_delta = _decimal(item.get("quantity_delta"))
                if item_delta is not None:
                    delta += item_delta
                if item.get("basis_date"):
                    effective_dates.append(item["basis_date"])

        line["status"] = worst
        if worst == PROJECTED:
            line["delta_quantity"] = format(delta, "f")
            line["projected_quantity"] = (
                format(pre + delta, "f") if pre is not None else None
            )
            dates = {d for d in effective_dates if d}
            line["effective_date"] = (
                next(iter(sorted(dates))) if len(dates) == 1 else None
            )
        else:
            line["delta_quantity"] = None
        lines.append(line)

    # items PROJECTED con delta cuyo instrumento no tiene posicion:
    # linea proyectada nueva (recepcion esperada, pre=0)
    matched = set()
    for position in positions_doc.get("positions", []):
        matched.add((position.get("account_id"),
                     position.get("isin")))
    for (account_id, isin), items in sorted(
            items_by_key.items(), key=lambda kv: (str(kv[0]))):
        if (account_id, isin) in matched:
            continue
        delta = Decimal(0)
        refs: list[str] = []
        reasons: list[str] = []
        dates = []
        for index, item in items:
            if item.get("status") != PROJECTED:
                continue
            item_delta = _decimal(item.get("quantity_delta"))
            if item_delta is None:
                continue
            delta += item_delta
            refs.append(f"impacts[{index}]")
            reasons.extend(item.get("reasons") or [])
            if item.get("basis_date"):
                dates.append(item["basis_date"])
        if not refs:
            continue
        reasons.append("NEW_INSTRUMENT_RECEIPT")
        unique_dates = {d for d in dates if d}
        lines.append({
            "account_id": account_id,
            "isin": isin,
            "pre_quantity": "0",
            "delta_quantity": format(delta, "f"),
            "projected_quantity": format(delta, "f"),
            "effective_date": (
                next(iter(sorted(unique_dates)))
                if len(unique_dates) == 1 else None
            ),
            "impact_refs": refs,
            "status": PROJECTED,
            "reasons": reasons,
        })

    summary = {"positions": len(lines)}
    for status in (PROJECTED, INDETERMINATE, UNSUPPORTED):
        summary[status.casefold()] = sum(
            1 for line in lines if line["status"] == status
        )

    return {
        "schema": PROJECTED_SCHEMA,
        "generated_at": now,
        "canonical_event_id": impact_doc.get("canonical_event_id"),
        "event_type": impact_doc.get("event_type"),
        "positions_as_of": positions_doc.get("as_of"),
        "source_canon_logical_sha256": impact_doc.get(
            "source_canon_logical_sha256"),
        "source_positions_logical_sha256": sha256_hex(positions_doc),
        "source_impact_sha256": sha256_hex(impact_doc),
        "lines": lines,
        "summary": summary,
    }
