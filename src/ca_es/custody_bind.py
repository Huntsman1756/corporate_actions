"""P13.9 — cash observation -> corporate-action binding.

CA_ES_CASH_ACCOUNT_OBSERVATION_V1
    -> CA_ES_CASH_BINDING_V1 (adjudicacion por entry)
    -> CA_ES_CASH_MOVEMENTS_V2 (solo entries BOUND)

La frontera semantica de P13. Solo se liga una entry a un evento
cuando una referencia EXPLICITA de la entry resuelve via el mapa de
referencias (config/profile o ledger). Jamas por:

- mismo importe / fecha / moneda / cuenta;
- narrativa parseada sin profile;
- coincidencia unica en el fixture.

Statuses por entry:

- BOUND: exactamente una referencia resuelve a un event_id;
- AMBIGUOUS: referencias resuelven a event_ids distintos;
- NO_MATCH: hay referencias pero ninguna resuelve;
- INSUFFICIENT_IDENTITY: no hay referencias utilizables.

amount_basis: declarado en el reference_map (el que registro la
referencia conoce la base); ausente -> UNKNOWN. Nunca se infiere
comparando con el esperado.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .semantic_hash import semantic_sha256

BINDING_SCHEMA = "CA_ES_CASH_BINDING_V1"
MOVEMENTS_SCHEMA = "CA_ES_CASH_MOVEMENTS_V2"

BOUND = "BOUND"
AMBIGUOUS = "AMBIGUOUS"
NO_MATCH = "NO_MATCH"
INSUFFICIENT_IDENTITY = "INSUFFICIENT_IDENTITY"

AMOUNT_BASES = {"GROSS", "NET", "UNKNOWN"}

# campos de una entry que pueden portar una referencia resoluble,
# en orden de especificidad.
REFERENCE_FIELDS = (
    "customer_reference",        # EndToEndId / field-61 owner ref
    "transaction_reference",     # TxId
    "account_servicer_reference",
)


def _dec(raw):
    try:
        d = Decimal(str(raw))
        return d if d.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _entry_refs(entry: dict) -> list[tuple[str, str]]:
    """(campo, valor) de todas las referencias utilizables."""
    refs = []
    for field in REFERENCE_FIELDS:
        value = entry.get(field)
        if value:
            refs.append((field, str(value)))
    structured = (entry.get("structured_details") or {}).get("refs") or {}
    for key, value in structured.items():
        if value and key not in ("AcctSvcrRef",):
            refs.append((f"refs.{key}", str(value)))
    # dedup conservando orden
    seen = set()
    unique = []
    for pair in refs:
        if pair not in seen:
            seen.add(pair)
            unique.append(pair)
    return unique


def bind_cash(observation: dict, reference_map: dict,
              account_map: dict | None = None,
              now: str | None = None) -> dict:
    """observation + reference_map -> CA_ES_CASH_BINDING_V1.

    reference_map: {referencia -> {"event_id": str,
                                   "amount_basis": GROSS|NET|UNKNOWN,
                                   "movement_id": str?}}
    account_map: {account_id_raw -> account_id} explicito.
    """
    reference_map = reference_map or {}
    account_map = account_map or {}
    account_raw = observation.get("account_id_raw")
    account_id = account_map.get(account_raw)

    bindings = []
    for i, entry in enumerate(observation.get("entries") or []):
        refs = _entry_refs(entry)
        hits = []
        for field, value in refs:
            target = reference_map.get(value)
            if target is not None:
                hits.append((field, value, target))
        events = {h[2].get("event_id") for h in hits
                  if h[2].get("event_id")}

        if not refs:
            status, reason = INSUFFICIENT_IDENTITY, "NO_USABLE_REFERENCE"
        elif len(events) > 1:
            status, reason = AMBIGUOUS, "REFERENCES_DISAGREE"
        elif hits:
            status, reason = BOUND, None
        else:
            status, reason = NO_MATCH, "REFERENCES_UNRESOLVED"

        target = hits[0][2] if status == BOUND else None
        basis = (target or {}).get("amount_basis")
        if basis not in AMOUNT_BASES:
            basis = "UNKNOWN"

        movement = None
        amount = _dec(entry.get("amount"))
        if status == BOUND and amount is not None and account_id:
            movement = {
                "movement_id": target.get("movement_id") or (
                    "CBND-" + semantic_sha256({
                        "input_sha256": observation.get("input_sha256"),
                        "entry_id": entry.get("entry_id"),
                        "amount": entry.get("amount"),
                        "event_id": target.get("event_id"),
                    })[:16]),
                "account_id": account_id,
                "event_id": target.get("event_id"),
                "currency": entry.get("currency"),
                "amount": format(amount, "f"),
                "amount_basis": basis,
                "value_date": entry.get("value_date"),
                "direction": entry.get("debit_credit"),
                "source_entry_id": entry.get("entry_id"),
                "source_reference": hits[0][1],
                "source_reference_field": hits[0][0],
            }
        elif status == BOUND and not account_id:
            status, reason = INSUFFICIENT_IDENTITY, "UNMAPPED_ACCOUNT"

        bindings.append({
            "entry_index": i,
            "entry_id": entry.get("entry_id"),
            "status": status,
            "reason": reason,
            "references_checked": [{"field": f, "value": v}
                                   for f, v in refs],
            "matched_reference": (
                {"field": hits[0][0], "value": hits[0][1],
                 "event_id": (target or {}).get("event_id")}
                if hits else None),
            "movement": movement,
            "amount_basis": basis if movement else None,
        })

    return {
        "schema": BINDING_SCHEMA,
        "generated_at": now,
        "source_message_identifier":
            observation.get("source_message_identifier"),
        "input_sha256": observation.get("input_sha256"),
        "account_id_raw": account_raw,
        "account_id": account_id,
        "bindings": bindings,
        "summary": {
            "bound": sum(1 for b in bindings
                         if b["status"] == BOUND),
            "ambiguous": sum(1 for b in bindings
                             if b["status"] == AMBIGUOUS),
            "no_match": sum(1 for b in bindings
                            if b["status"] == NO_MATCH),
            "insufficient_identity": sum(
                1 for b in bindings
                if b["status"] == INSUFFICIENT_IDENTITY),
        },
    }


def movements_doc(binding: dict, now: str | None = None) -> dict:
    """CA_ES_CASH_BINDING_V1 -> CA_ES_CASH_MOVEMENTS_V2 (BOUND)."""
    movements = [b["movement"] for b in binding.get("bindings", [])
                 if b.get("status") == BOUND and b.get("movement")]
    return {
        "schema": MOVEMENTS_SCHEMA,
        "movements": movements,
    }
