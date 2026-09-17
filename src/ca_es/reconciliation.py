"""P3.0 Cash Reconciliation — expected entitlement vs actual cash.

Contrato:

    expected entitlements (CA_ES_ENTITLEMENT_V1)
        + actual cash movements (CA_ES_CASH_MOVEMENTS_V1)
        -> reconcile()
        -> MATCH / AMOUNT_MISMATCH / MISSING_CASH / UNEXPECTED_CASH
           / INDETERMINATE

Reglas estrictas (P3.0):

- solo se reconcilian entitlements ENTITLED; un entitlement
  INDETERMINATE/NOT_ENTITLED/UNSUPPORTED pasa a INDETERMINATE sin
  convertirse en excepcion monetaria falsa;
- clave de match: account_id + referencia de evento
  (movement.event_id == canonical_event_id, o movement.isin ==
  isin del entitlement) + currency;
- Decimal exclusivamente, sin tolerancias: expected gross_cash ==
  actual amount -> MATCH; distintos -> AMOUNT_MISMATCH con delta
  exacto (actual - expected);
- expected sin cash -> MISSING_CASH; cash sin expected ->
  UNEXPECTED_CASH;
- varios movimientos para una misma clave -> INDETERMINATE /
  MULTIPLE_CASH_MOVEMENTS (no se suma silenciosamente en v1);
- varios entitlements ENTITLED con la misma clave -> INDETERMINATE /
  DUPLICATE_ENTITLEMENT_KEY;
- value_date es informativa, nunca criterio de match;
- movimientos malformados (campos ausentes, amount no parseable,
  amount_basis fuera del vocabulario) -> invalid_movements, nunca
  participan en el match;
- amount_basis (V2): GROSS reconcilia contra gross_cash; NET o
  UNKNOWN -> INDETERMINATE, nunca un AMOUNT_MISMATCH conceptualmente
  falso;
- evidencia en ambos lados: provenance del entitlement +
  movement_id del actual.

reconcile() es pura sobre los dos artefactos: no toca canon ni
Surface; la provenance viaja dentro del documento de entitlements.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

from .canonical import load_strict_json_object

RECON_VERSION = "CA_ES_CASH_RECON_V1"
MOVEMENTS_SCHEMA_V1 = "CA_ES_CASH_MOVEMENTS_V1"
MOVEMENTS_SCHEMA = "CA_ES_CASH_MOVEMENTS_V2"
MOVEMENTS_SCHEMAS = {MOVEMENTS_SCHEMA_V1, MOVEMENTS_SCHEMA}

# P3.1 (ADR-018): base del importe observado. El canon solo produce
# expected GROSS (gross_cash); por tanto:
#   GROSS   -> reconciliable
#   NET     -> INDETERMINATE / NET_EXPECTED_NOT_AVAILABLE
#   UNKNOWN -> INDETERMINATE / UNKNOWN_AMOUNT_BASIS
# Un documento V1 (sin amount_basis) se acepta y cada movimiento se
# trata como UNKNOWN: nunca se asume bruto. Esto es compatibilidad
# de INGESTION, no de resultado: un V1 que antes producia MATCH ahora
# produce INDETERMINATE/UNKNOWN_AMOUNT_BASIS. Es una correccion del
# contrato, no una regresion; no "restaurar" tratando ausencia como
# GROSS.
AMOUNT_BASES = {"GROSS", "NET", "UNKNOWN"}

MATCH = "MATCH"
AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
MISSING_CASH = "MISSING_CASH"
UNEXPECTED_CASH = "UNEXPECTED_CASH"
INDETERMINATE = "INDETERMINATE"

MOVEMENT_REQUIRED = ("movement_id", "account_id", "currency", "amount")


def load_movements(path: Path) -> dict:
    doc = load_strict_json_object(path)
    schema = doc.get("schema")
    if not isinstance(schema, str) or schema not in MOVEMENTS_SCHEMAS:
        raise ValueError(
            f"movements schema debe ser {sorted(MOVEMENTS_SCHEMAS)}, "
            f"recibido {doc.get('schema')!r}"
        )
    movements = doc.get("movements")
    if not isinstance(movements, list) or any(
        not isinstance(movement, dict) for movement in movements
    ):
        raise ValueError("movements debe ser una lista de objetos")
    return doc


def _movement_amount(movement: dict) -> Decimal | None:
    raw = movement.get("amount")
    if isinstance(raw, float):
        return None
    try:
        amount = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite():
        return None
    return amount


def _money(normalized: Decimal, currency: str) -> dict:
    return {
        "normalized": format(normalized, "f"),
        "currency": currency,
        "scale": -normalized.as_tuple().exponent,
    }


def _references_event(movement: dict, canonical_event_id: str, isin) -> bool:
    if movement.get("event_id") is not None:
        return movement["event_id"] == canonical_event_id
    return bool(isin) and movement.get("isin") == isin


def _movement_key_match(
    movement: dict, canonical_event_id: str, entitlement: dict
) -> bool:
    """Clave completa: account + evento + currency."""
    if movement.get("account_id") != entitlement.get("account_id"):
        return False
    if not _references_event(
        movement, canonical_event_id, entitlement.get("isin")
    ):
        return False
    gross = entitlement.get("gross_cash") or {}
    return movement.get("currency") == gross.get("currency")


def _movement_linked(
    movement: dict, canonical_event_id: str, entitlement: dict
) -> bool:
    """Vinculo informativo (account + evento) para entitlements sin
    importe calculable; nunca produce excepcion."""
    if movement.get("account_id") != entitlement.get("account_id"):
        return False
    return _references_event(
        movement, canonical_event_id, entitlement.get("isin")
    )


def reconcile(entitlement_doc: dict, movements_doc: dict) -> dict:
    canonical_event_id = entitlement_doc["canonical_event_id"]

    valid_movements = []
    invalid_movements = []
    for movement in movements_doc.get("movements", []):
        missing = [k for k in MOVEMENT_REQUIRED if movement.get(k) is None]
        if not movement.get("event_id") and not movement.get("isin"):
            missing.append("event_id|isin")
        if _movement_amount(movement) is None:
            missing.append("amount(parseable)")
        basis = movement.get("amount_basis")
        if basis is not None and str(basis).upper() not in AMOUNT_BASES:
            missing.append("amount_basis(invalid)")
        if missing:
            invalid_movements.append(
                {"movement": movement, "reasons": sorted(set(missing))}
            )
        else:
            valid_movements.append(movement)

    used: set[int] = set()
    items = []

    # claves ENTITLED duplicadas: el cash no puede asignarse sin
    # ambiguedad -> INDETERMINATE para todos los del grupo
    entitled = [
        e for e in entitlement_doc.get("entitlements", [])
        if e.get("status") == "ENTITLED"
    ]
    key_counts: dict[tuple, int] = {}
    for ent in entitled:
        key = (
            ent["account_id"],
            canonical_event_id,
            (ent.get("gross_cash") or {}).get("currency"),
        )
        key_counts[key] = key_counts.get(key, 0) + 1

    for ent in entitlement_doc.get("entitlements", []):
        base = {
            "account_id": ent.get("account_id"),
            "isin": ent.get("isin"),
            "canonical_event_id": canonical_event_id,
            "movement_ids": [],
            "reasons": [],
            "evidence": {
                "entitlement": ent.get("evidence"),
                "movement_ids": [],
            },
        }
        if ent.get("status") != "ENTITLED":
            linked = [
                m
                for m in valid_movements
                if id(m) not in used
                and _movement_linked(m, canonical_event_id, ent)
            ]
            used.update(id(m) for m in linked)
            items.append(
                {
                    **base,
                    "status": INDETERMINATE,
                    "entitlement_status": ent.get("status"),
                    "reasons": [
                        f"ENTITLEMENT_{ent.get('status')}",
                        *ent.get("reasons", []),
                    ],
                    "linked_movement_ids": [
                        m["movement_id"] for m in linked
                    ],
                }
            )
            continue

        raw = (ent.get("gross_cash") or {}).get("normalized")
        if isinstance(raw, float):
            raise ValueError("expected gross_cash must be a finite Decimal")
        try:
            expected = Decimal(str(raw))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(
                "expected gross_cash must be a finite Decimal"
            ) from exc
        if not expected.is_finite():
            raise ValueError("expected gross_cash must be a finite Decimal")

        key = (
            ent["account_id"],
            canonical_event_id,
            ent["gross_cash"]["currency"],
        )
        if key_counts[key] > 1:
            linked = [
                m
                for m in valid_movements
                if _movement_key_match(m, canonical_event_id, ent)
            ]
            used.update(id(m) for m in linked)
            items.append(
                {
                    **base,
                    "status": INDETERMINATE,
                    "reasons": ["DUPLICATE_ENTITLEMENT_KEY"],
                    "expected_gross_cash": ent["gross_cash"],
                    "movement_ids": [m["movement_id"] for m in linked],
                    "evidence": {
                        "entitlement": ent.get("evidence"),
                        "movement_ids": [m["movement_id"] for m in linked],
                    },
                }
            )
            continue

        matched = [
            m
            for m in valid_movements
            if id(m) not in used
            and _movement_key_match(m, canonical_event_id, ent)
        ]
        currency = ent["gross_cash"]["currency"]

        if len(matched) > 1:
            used.update(id(m) for m in matched)
            items.append(
                {
                    **base,
                    "status": INDETERMINATE,
                    "reasons": ["MULTIPLE_CASH_MOVEMENTS"],
                    "expected_gross_cash": ent["gross_cash"],
                    "movement_ids": [m["movement_id"] for m in matched],
                    "evidence": {
                        "entitlement": ent.get("evidence"),
                        "movement_ids": [m["movement_id"] for m in matched],
                    },
                }
            )
        elif not matched:
            items.append(
                {
                    **base,
                    "status": MISSING_CASH,
                    "expected_gross_cash": ent["gross_cash"],
                }
            )
        else:
            movement = matched[0]
            used.add(id(movement))
            actual = _movement_amount(movement)
            basis = str(movement.get("amount_basis") or "UNKNOWN").upper()
            common = {
                **base,
                "expected_gross_cash": ent["gross_cash"],
                "actual_amount": format(actual, "f"),
                "amount_basis": basis,
                "movement_ids": [movement["movement_id"]],
                "value_date": movement.get("value_date"),
                "evidence": {
                    "entitlement": ent.get("evidence"),
                    "movement_ids": [movement["movement_id"]],
                },
            }
            if basis == "NET":
                items.append(
                    {
                        **common,
                        "status": INDETERMINATE,
                        "reasons": ["NET_EXPECTED_NOT_AVAILABLE"],
                    }
                )
            elif basis != "GROSS":
                items.append(
                    {
                        **common,
                        "status": INDETERMINATE,
                        "reasons": ["UNKNOWN_AMOUNT_BASIS"],
                    }
                )
            else:
                with localcontext() as context:
                    exponent = min(
                        actual.as_tuple().exponent,
                        expected.as_tuple().exponent,
                    )
                    context.prec = max(
                        len(actual.as_tuple().digits)
                        + actual.as_tuple().exponent - exponent,
                        len(expected.as_tuple().digits)
                        + expected.as_tuple().exponent - exponent,
                    ) + 1
                    delta = actual - expected
                items.append(
                    {
                        **common,
                        "status": (
                            MATCH if actual == expected else AMOUNT_MISMATCH
                        ),
                        "delta": _money(delta, currency),
                    }
                )

    for movement in valid_movements:
        if id(movement) in used:
            continue
        items.append(
            {
                "account_id": movement.get("account_id"),
                "isin": movement.get("isin"),
                "canonical_event_id": canonical_event_id,
                "status": UNEXPECTED_CASH,
                "actual_amount": format(_movement_amount(movement), "f"),
                "amount_basis": str(
                    movement.get("amount_basis") or "UNKNOWN"
                ).upper(),
                "currency": movement.get("currency"),
                "value_date": movement.get("value_date"),
                "movement_ids": [movement["movement_id"]],
                "reasons": [],
                "evidence": {
                    "entitlement": None,
                    "movement_ids": [movement["movement_id"]],
                },
            }
        )

    items.sort(
        key=lambda i: (
            i.get("account_id") or "",
            i["status"] == UNEXPECTED_CASH,
            ",".join(i.get("movement_ids") or []),
        )
    )

    summary = {"items": len(items), "invalid_movements": len(invalid_movements)}
    for status in (
        MATCH,
        AMOUNT_MISMATCH,
        MISSING_CASH,
        UNEXPECTED_CASH,
        INDETERMINATE,
    ):
        summary[status.casefold()] = sum(
            1 for i in items if i["status"] == status
        )

    return {
        "recon_version": RECON_VERSION,
        "canonical_event_id": canonical_event_id,
        "items": items,
        "invalid_movements": invalid_movements,
        "summary": summary,
    }
