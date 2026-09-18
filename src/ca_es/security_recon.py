"""P6.4 — Securities reconciliation.

docs/p6/p64-scope.md:

    CA_ES_POSITION_IMPACT_V1 (expected, adjudicado)
    + CA_ES_SWIFT_SECURITY_MOVEMENT_CANDIDATE_V1[] (actual, P6.3)
        -> reconcile_security_movements()
        -> CA_ES_SECURITY_RECON_V1

Reglas duras:

- el conjunto esperado se deriva del doc de impacto ya adjudicado;
  nunca se recalcula impacto;
- clave de matching (account_id, isin, direction); comparacion Decimal
  exacta; sin tolerancia; sin agregacion entre claves;
- expected_set_authoritative = false si algun item de impacto es
  INDETERMINATE/UNSUPPORTED — un movimiento observado solo puede ser
  UNEXPECTED cuando el conjunto esperado esta completo;
- candidate docs deben estar BOUND y apuntar al mismo
  canonical_event_id;
- la moneda nunca es semantica de valores;
- read-only, determinista.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .canonical import sha256_hex

RECON_SCHEMA = "CA_ES_SECURITY_RECON_V1"
IMPACT_SCHEMA = "CA_ES_POSITION_IMPACT_V1"
CANDIDATE_SCHEMA = "CA_ES_SWIFT_SECURITY_MOVEMENT_CANDIDATE_V1"

MATCH = "MATCH"
QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
MISSING_SECURITY_MOVEMENT = "MISSING_SECURITY_MOVEMENT"
UNEXPECTED_SECURITY_MOVEMENT = "UNEXPECTED_SECURITY_MOVEMENT"
INDETERMINATE = "INDETERMINATE"

_PROJECTED = "PROJECTED"

# impact_type -> direction del movimiento esperado (preregistrado)
_IMPACT_DIRECTION = {
    "SECURITY_DELIVERY": "DELIVERY",
    "SECURITY_RECEIPT": "RECEIPT",
}


def _decimal(raw) -> Decimal | None:
    if raw is None or isinstance(raw, float):
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def _expected_movements(impact_doc: dict) -> tuple[list, list]:
    """(expected[], reasons_doc). expected: dict con clave
    (account, isin, direction) + quantity + ref + evidence."""
    expected = []
    for index, item in enumerate(impact_doc.get("impacts", [])):
        if item.get("status") != _PROJECTED:
            continue
        delta = _decimal(item.get("quantity_delta"))
        if delta is None:
            continue
        # P8.2: delta cero = posicion explicitamente inalterada o
        # NOT_ENTITLED; nunca es un movimiento esperado (un actual
        # con qty>0 seria UNEXPECTED, no MATCH contra 0)
        if delta == 0:
            continue
        direction = _IMPACT_DIRECTION.get(item.get("impact_type"))
        expected.append({
            "account_id": item.get("account_id"),
            "isin": item.get("target_isin") or item.get("source_isin"),
            "direction": direction,
            "quantity": abs(delta),
            "expected_ref": f"impacts[{index}]",
            "impact_type": item.get("impact_type"),
            "evidence": item.get("evidence"),
        })
    authoritative = not any(
        item.get("status") != _PROJECTED
        for item in impact_doc.get("impacts", [])
    )
    return expected, authoritative


def _actual_movements(candidate_docs: list[dict],
                      canonical_event_id: str) -> list[dict]:
    actuals = []
    for doc in candidate_docs:
        if doc.get("schema") != CANDIDATE_SCHEMA:
            raise ValueError(
                f"candidate schema debe ser {CANDIDATE_SCHEMA}, "
                f"recibido {doc.get('schema')!r}"
            )
        if doc.get("binding_status") != "BOUND":
            raise ValueError("CANDIDATE_NOT_BOUND")
        if doc.get("canonical_event_id") != canonical_event_id:
            raise ValueError("EVENT_MISMATCH")
        for movement in doc.get("movements", []):
            if movement.get("status") != "PROJECTABLE":
                continue
            actuals.append(movement)
    return actuals


def _key(account, isin, direction):
    return (account or "-", isin or "-", direction or "-")


def reconcile_security_movements(impact_doc: dict,
                                 candidate_docs: list[dict],
                                 now: str | None = None) -> dict:
    """expected impacts + actual candidates -> CA_ES_SECURITY_RECON_V1.

    Puro y read-only: ningun input se muta.
    """
    if impact_doc.get("schema") != IMPACT_SCHEMA:
        raise ValueError(
            f"impact schema debe ser {IMPACT_SCHEMA}, "
            f"recibido {impact_doc.get('schema')!r}"
        )
    canonical_event_id = impact_doc.get("canonical_event_id")
    expected, authoritative = _expected_movements(impact_doc)
    actuals = _actual_movements(candidate_docs, canonical_event_id)

    expected_by_key: dict[tuple, list] = {}
    for exp in expected:
        expected_by_key.setdefault(
            _key(exp["account_id"], exp["isin"], exp["direction"]),
            []).append(exp)
    actual_by_key: dict[tuple, list] = {}
    for act in actuals:
        actual_by_key.setdefault(
            _key(act["account_id"], act["isin"], act["direction"]),
            []).append(act)

    items = []
    for key in sorted(set(expected_by_key) | set(actual_by_key)):
        exps = expected_by_key.get(key, [])
        acts = actual_by_key.get(key, [])
        account, isin, direction = key
        base = {
            "account_id": None if account == "-" else account,
            "isin": None if isin == "-" else isin,
            "direction": None if direction == "-" else direction,
            "expected_quantity": None,
            "actual_quantity": None,
            "delta": None,
            "expected_ref": None,
            "movement_ids": [],
            "evidence": {"expected": None, "actual": []},
        }

        if len(exps) > 1:
            items.append({
                **base, "status": INDETERMINATE,
                "reasons": ["MULTIPLE_EXPECTED"],
                "expected_ref": [e["expected_ref"] for e in exps],
            })
            continue
        if len(acts) > 1:
            items.append({
                **base, "status": INDETERMINATE,
                "reasons": ["MULTIPLE_SECURITY_MOVEMENTS"],
                "movement_ids": [a["movement_id"] for a in acts],
                "evidence": {
                    "expected": exps[0]["evidence"] if exps else None,
                    "actual": [a.get("provenance") for a in acts],
                },
                "expected_ref": exps[0]["expected_ref"] if exps else None,
            })
            continue

        if exps and acts:
            exp, act = exps[0], acts[0]
            item = {
                **base,
                "expected_quantity": format(exp["quantity"], "f"),
                "actual_quantity": act.get("quantity"),
                "expected_ref": exp["expected_ref"],
                "movement_ids": [act["movement_id"]],
                "evidence": {
                    "expected": exp["evidence"],
                    "actual": [act.get("provenance")],
                },
            }
            if exp["direction"] is None:
                item["status"] = INDETERMINATE
                item["reasons"] = ["UNSUPPORTED_IMPACT_TYPE"]
            else:
                actual_qty = _decimal(act.get("quantity"))
                if actual_qty is None:
                    item["status"] = INDETERMINATE
                    item["reasons"] = ["INVALID_ACTUAL_QUANTITY"]
                elif actual_qty == exp["quantity"]:
                    item["status"] = MATCH
                    item["reasons"] = []
                    item["delta"] = "0"
                else:
                    item["status"] = QUANTITY_MISMATCH
                    item["delta"] = format(actual_qty - exp["quantity"],
                                           "f")
                    item["reasons"] = []
            items.append(item)
        elif exps:
            exp = exps[0]
            items.append({
                **base,
                "status": (
                    MISSING_SECURITY_MOVEMENT
                    if exp["direction"] is not None else INDETERMINATE
                ),
                "expected_quantity": format(exp["quantity"], "f"),
                "expected_ref": exp["expected_ref"],
                "evidence": {"expected": exp["evidence"], "actual": []},
                "reasons": (
                    [] if exp["direction"] is not None
                    else ["UNSUPPORTED_IMPACT_TYPE"]
                ),
            })
        else:
            act = acts[0]
            items.append({
                **base,
                "status": (
                    UNEXPECTED_SECURITY_MOVEMENT
                    if authoritative else INDETERMINATE
                ),
                "actual_quantity": act.get("quantity"),
                "movement_ids": [act["movement_id"]],
                "evidence": {"expected": None,
                             "actual": [act.get("provenance")]},
                "reasons": [] if authoritative else
                ["EXPECTED_SET_INCOMPLETE"],
            })

    summary = {"items": len(items)}
    for status in (MATCH, QUANTITY_MISMATCH, MISSING_SECURITY_MOVEMENT,
                   UNEXPECTED_SECURITY_MOVEMENT, INDETERMINATE):
        summary[status.casefold()] = sum(
            1 for i in items if i["status"] == status
        )

    return {
        "schema": RECON_SCHEMA,
        "generated_at": now,
        "canonical_event_id": canonical_event_id,
        "event_type": impact_doc.get("event_type"),
        "source_impact_sha256": sha256_hex(impact_doc),
        "source_candidate_sha256s": sorted(
            sha256_hex(d) for d in candidate_docs
        ),
        "source_canon_logical_sha256": impact_doc.get(
            "source_canon_logical_sha256"),
        "expected_set_authoritative": authoritative,
        "items": items,
        "summary": summary,
    }
