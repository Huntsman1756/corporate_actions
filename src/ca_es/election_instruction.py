"""P5.4 — Election Instruction Intent.

docs/p5/p54-scope.md:

    CA_ES_ELECTION_ELIGIBILITY_V1 + CA_ES_ELECTION_OPPORTUNITY_V1
    + instruction request explicita
        -> CA_ES_ELECTION_INSTRUCTION_V1

Artefacto de negocio interno: NO es MT565, no genera SWIFT, no es ack
del custodio y no muta eligibility, opportunity, positions ni canon.

Reglas duras:

- instruction_id es clave explicita del caller; nunca se sintetiza
- binding fail-closed eligibility<->opportunity (sha256 de canon y de
  input, y canonical_event_id): ELIGIBILITY_OPPORTUNITY_MISMATCH
- account_id+option_key debe resolver a exactamente una celda
- solo celdas ELIGIBLE producen READY
- requested == eligible unicamente; < -> UNSUPPORTED (terminos de
  eleccion parcial no modelados); > -> INDETERMINATE
- terms[] raw nunca se interpreta para permitir minimos, multiplos,
  ratios, fracciones, oversubscription ni prorrateo
- sin estados de workflow (SENT/ACKNOWLEDGED)
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .election import OPPORTUNITY_SCHEMA
from .election_eligibility import (
    ELIGIBILITY_SCHEMA,
    ELIGIBLE,
    INDETERMINATE,
    UNSUPPORTED,
)
from .swift_ca import _now

INSTRUCTION_SCHEMA = "CA_ES_ELECTION_INSTRUCTION_V1"

READY = "READY"

REQUEST_FIELDS = (
    "instruction_id",
    "account_id",
    "option_key",
    "requested_quantity",
    "actor",
    "instructed_at",
)


def _requested_quantity(value) -> Decimal | None:
    if isinstance(value, float) or value is None:
        return None
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return quantity if quantity.is_finite() else None


def build_instruction(eligibility_doc: dict, opportunity_doc: dict,
                      request: dict, now: str | None = None) -> dict:
    """eligibility + opportunity + request ->
    CA_ES_ELECTION_INSTRUCTION_V1.

    read-only: no muta ninguno de los tres inputs.
    """
    if eligibility_doc.get("schema") != ELIGIBILITY_SCHEMA:
        raise ValueError(
            f"eligibility schema debe ser {ELIGIBILITY_SCHEMA}, "
            f"recibido {eligibility_doc.get('schema')!r}"
        )
    if opportunity_doc.get("schema") != OPPORTUNITY_SCHEMA:
        raise ValueError(
            f"opportunity schema debe ser {OPPORTUNITY_SCHEMA}, "
            f"recibido {opportunity_doc.get('schema')!r}"
        )
    if not isinstance(request, dict):
        raise ValueError("INVALID_INSTRUCTION_REQUEST")
    for field in REQUEST_FIELDS:
        value = request.get(field)
        if value is None or (
            isinstance(value, str) and not value.strip()
        ):
            raise ValueError(
                f"INVALID_INSTRUCTION_REQUEST: {field}"
            )

    if (
        eligibility_doc.get("source_canon_logical_sha256")
        != opportunity_doc.get("source_canon_logical_sha256")
        or eligibility_doc.get("source_message_input_sha256")
        != opportunity_doc.get("input_sha256")
        or eligibility_doc.get("canonical_event_id")
        != opportunity_doc.get("canonical_event_id")
    ):
        raise ValueError("ELIGIBILITY_OPPORTUNITY_MISMATCH")

    quantity = _requested_quantity(request["requested_quantity"])

    base = {
        "schema": INSTRUCTION_SCHEMA,
        "generated_at": now or _now(),
        "instruction_id": request["instruction_id"],
        "canonical_event_id": eligibility_doc.get("canonical_event_id"),
        "account_id": request["account_id"],
        "isin": None,
        "option_key": request["option_key"],
        "option_identifier": None,
        "option_code_raw": None,
        "option_kind": None,
        "requested_quantity": (
            format(quantity, "f") if quantity is not None
            else request["requested_quantity"]
        ),
        "eligible_quantity": None,
        "reasons": [],
        "actor": request["actor"],
        "instructed_at": request["instructed_at"],
        "source_canon_logical_sha256": eligibility_doc.get(
            "source_canon_logical_sha256"
        ),
        "source_positions_logical_sha256": eligibility_doc.get(
            "source_positions_logical_sha256"
        ),
        "source_message_input_sha256": eligibility_doc.get(
            "source_message_input_sha256"
        ),
        "eligibility_key": None,
        "eligibility_rule_id": None,
        "evidence": {},
    }

    def fail(status: str, reason: str) -> dict:
        return {**base, "instruction_status": status,
                "reasons": [reason]}

    matches = [
        cell for cell in eligibility_doc.get("eligibilities") or []
        if cell.get("account_id") == request["account_id"]
        and cell.get("option_key") == request["option_key"]
    ]
    if not matches:
        return fail(INDETERMINATE, "ELIGIBILITY_CELL_NOT_FOUND")
    if len(matches) > 1:
        return fail(INDETERMINATE, "AMBIGUOUS_ELIGIBILITY_CELL")

    cell = matches[0]
    base.update({
        "isin": cell.get("isin"),
        "option_identifier": cell.get("option_identifier"),
        "option_code_raw": cell.get("option_code_raw"),
        "option_kind": cell.get("option_kind"),
        "eligible_quantity": cell.get("eligible_quantity"),
        "eligibility_key": cell.get("eligibility_key"),
        "eligibility_rule_id": cell.get("rule_id"),
        "evidence": {
            "assertion_ids": (
                (cell.get("evidence") or {}).get("assertion_ids") or []
            ),
            "option_provenance": (
                (cell.get("evidence") or {}).get("option_provenance")
                or []
            ),
            "position_index": (
                (cell.get("evidence") or {}).get("position_index")
            ),
        },
    })

    option = next(
        (
            o for o in opportunity_doc.get("options") or []
            if o.get("option_key") == request["option_key"]
        ),
        None,
    )
    if option is None:
        return fail(INDETERMINATE, "OPTION_NOT_IN_OPPORTUNITY")
    if cell.get("option_kind") == UNSUPPORTED:
        return fail(UNSUPPORTED, "UNSUPPORTED_OPTION_KIND")
    if cell.get("eligibility_status") != ELIGIBLE:
        return fail(INDETERMINATE, "CELL_NOT_ELIGIBLE")

    if quantity is None:
        return fail(INDETERMINATE, "INVALID_REQUESTED_QUANTITY")
    if quantity <= 0:
        return fail(INDETERMINATE, "NON_POSITIVE_REQUESTED_QUANTITY")
    eligible = Decimal(cell["eligible_quantity"])
    if quantity > eligible:
        return fail(
            INDETERMINATE, "REQUEST_EXCEEDS_ELIGIBLE_QUANTITY"
        )
    if quantity < eligible:
        return fail(UNSUPPORTED, "PARTIAL_ELECTION_TERMS_NOT_MODELED")
    return {**base, "instruction_status": READY}
