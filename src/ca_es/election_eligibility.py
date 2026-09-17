"""P5.3 — Election Eligibility.

docs/p5/p53-scope.md:

    CA_ES_ELECTION_OPPORTUNITY_V1 + canonical event
    + CA_ES_POSITIONS_V1 + CA_ES_ELECTION_ELIGIBILITY_RULES_V1
        -> CA_ES_ELECTION_ELIGIBILITY_V1

Solo responde: que cantidad puede demostrarse elegible por posicion y
opcion explicita bajo una regla explicita. Sin eleccion del cliente,
sin instructed quantity, sin MT565; canon y positions intactos.

Reglas duras:

- binding fail-closed: opportunity.source_canon_logical_sha256 debe
  igualar canon.logical_sha256 (OPPORTUNITY_CANON_MISMATCH)
- matching de reglas por celda: 0 -> NO_APPLICABLE_RULE; 1 -> se
  usa; >1 -> AMBIGUOUS_ELIGIBILITY_RULE; nunca "la mas especifica"
- solo position_basis=POSITION_AT_DATE_FIELD + quantity_rule=
  FULL_POSITION; otra semantica -> UNSUPPORTED_ELIGIBILITY_RULE
- snapshot anterior/posterior nunca prueba titularidad
- opportunity != PROJECTED nunca produce ELIGIBLE
- option_kind UNSUPPORTED -> UNSUPPORTED; terms[] raw nunca se
  interpreta (minimos/ratios/prorrateo quedan para P5.4)
- clave de posicion duplicada -> DUPLICATE_POSITION_KEY; nunca suma
"""

from __future__ import annotations

from datetime import date

from .canonical import sha256_hex
from .election import OPPORTUNITY_SCHEMA, PROJECTED
from .entitlement_engine import POSITIONS_SCHEMA, _position_quantity
from .swift_ca import _current_dates, _event_isins, _now

ELIGIBILITY_SCHEMA = "CA_ES_ELECTION_ELIGIBILITY_V1"
RULES_SCHEMA = "CA_ES_ELECTION_ELIGIBILITY_RULES_V1"

ELIGIBLE = "ELIGIBLE"
NOT_ELIGIBLE = "NOT_ELIGIBLE"
INDETERMINATE = "INDETERMINATE"
UNSUPPORTED = "UNSUPPORTED"

POSITION_AT_DATE_FIELD = "POSITION_AT_DATE_FIELD"
FULL_POSITION = "FULL_POSITION"

_RULE_FIELDS = ("rule_id", "basis_field", "position_basis",
                "quantity_rule")
_RULE_FILTERS = ("event_types", "option_kinds", "option_codes")


def _parse_day(value):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _validate_rule(rule) -> None:
    if not isinstance(rule, dict):
        raise ValueError("INVALID_ELIGIBILITY_RULE")
    for field in _RULE_FIELDS:
        value = rule.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError("INVALID_ELIGIBILITY_RULE")
    for field in _RULE_FILTERS:
        value = rule.get(field)
        if value is not None and (
            not isinstance(value, list)
            or any(not isinstance(item, str) for item in value)
        ):
            raise ValueError("INVALID_ELIGIBILITY_RULE")


def _rule_matches(rule: dict, event_type, option: dict) -> bool:
    types = rule.get("event_types")
    if types is not None and event_type not in types:
        return False
    kinds = rule.get("option_kinds")
    if kinds is not None and option.get("option_kind") not in kinds:
        return False
    codes = rule.get("option_codes")
    if codes is not None and option.get("option_code_raw") not in codes:
        return False
    return True


def _eligibility(event, event_type, current, isins, rules,
                 position, position_index, position_as_of,
                 is_duplicate, option, projected) -> dict:
    reasons: list[str] = []
    account_id = position.get("account_id")
    isin = position.get("isin")
    quantity = _position_quantity(position)

    cell = {
        "eligibility_key": (
            f"{(event or {}).get('canonical_event_id')}"
            f"|{account_id}|{option.get('option_key')}"
        ),
        "account_id": account_id,
        "isin": isin,
        "option_key": option.get("option_key"),
        "option_identifier": option.get("option_identifier"),
        "option_code_raw": option.get("option_code_raw"),
        "option_kind": option.get("option_kind"),
        "rule_id": None,
        "position_basis": None,
        "basis_field": None,
        "basis_date": None,
        "position_quantity": (
            format(quantity, "f") if quantity is not None else None
        ),
        "position_as_of": position_as_of,
        "eligible_quantity": None,
        "reasons": reasons,
        "evidence": {
            "rule_id": None,
            "assertion_ids": [],
            "option_key": option.get("option_key"),
            "option_provenance": option.get("provenance") or [],
            "position_index": position_index,
        },
    }

    def fail(status: str, reason: str) -> dict:
        reasons.append(reason)
        return {**cell, "eligibility_status": status}

    if not projected:
        return fail(INDETERMINATE, "OPPORTUNITY_NOT_PROJECTED")
    if event is None:
        return fail(INDETERMINATE, "EVENT_NOT_IN_CANON")
    if option.get("option_kind") == UNSUPPORTED:
        return fail(UNSUPPORTED, "UNSUPPORTED_OPTION_KIND")
    if account_id is None:
        return fail(INDETERMINATE, "MISSING_ACCOUNT_ID")
    if not isin:
        return fail(INDETERMINATE, "MISSING_ISIN")
    if is_duplicate:
        return fail(INDETERMINATE, "DUPLICATE_POSITION_KEY")
    if not isins:
        return fail(INDETERMINATE, "MISSING_INSTRUMENT_IDENTITY")
    if isin not in isins:
        return fail(INDETERMINATE, "NO_POSITION_FOR_INSTRUMENT")
    if len(isins) > 1:
        return fail(INDETERMINATE, "AMBIGUOUS_INSTRUMENT_IDENTITY")

    applicable = [
        rule for rule in rules
        if _rule_matches(rule, event_type, option)
    ]
    if not applicable:
        return fail(INDETERMINATE, "NO_APPLICABLE_RULE")
    if len(applicable) > 1:
        cell["evidence"]["candidate_rule_ids"] = sorted(
            rule["rule_id"] for rule in applicable
        )
        return fail(INDETERMINATE, "AMBIGUOUS_ELIGIBILITY_RULE")
    rule = applicable[0]
    cell["rule_id"] = rule["rule_id"]
    cell["position_basis"] = rule["position_basis"]
    cell["basis_field"] = rule["basis_field"]
    cell["evidence"]["rule_id"] = rule["rule_id"]

    if (rule["position_basis"] != POSITION_AT_DATE_FIELD
            or rule["quantity_rule"] != FULL_POSITION):
        return fail(UNSUPPORTED, "UNSUPPORTED_ELIGIBILITY_RULE")

    cur = current.get(rule["basis_field"])
    if cur is None:
        return fail(INDETERMINATE, "MISSING_BASIS_DATE")
    cell["evidence"]["assertion_ids"] = cur.get("assertion_ids") or []
    if cur["status"] != "CURRENT":
        return fail(INDETERMINATE, "CONFLICTING_BASIS_DATE")
    cell["basis_date"] = cur.get("value")
    basis_day = _parse_day(cur.get("value"))
    if basis_day is None:
        return fail(INDETERMINATE, "INVALID_BASIS_DATE")

    if position_as_of is None:
        return fail(INDETERMINATE, "MISSING_POSITION_AS_OF")
    snapshot = _parse_day(position_as_of)
    if snapshot is None:
        return fail(INDETERMINATE, "INVALID_POSITION_AS_OF")
    if snapshot != basis_day:
        return fail(
            INDETERMINATE,
            "POSITION_SNAPSHOT_BEFORE_BASIS"
            if snapshot < basis_day
            else "POSITION_SNAPSHOT_AFTER_BASIS",
        )

    if quantity is None:
        return fail(INDETERMINATE, "INVALID_QUANTITY")
    if quantity < 0:
        return fail(INDETERMINATE, "NEGATIVE_QUANTITY_UNSUPPORTED")
    if quantity == 0:
        return fail(NOT_ELIGIBLE, "ZERO_QUANTITY")
    cell["eligible_quantity"] = format(quantity, "f")
    return {**cell, "eligibility_status": ELIGIBLE}


def compute_election_eligibility(
    opportunity_doc: dict,
    canon_doc: dict,
    positions_doc: dict,
    rules_doc: dict,
    now: str | None = None,
) -> dict:
    """opportunity + canon + positions + rules ->
    CA_ES_ELECTION_ELIGIBILITY_V1.

    read-only: no muta opportunity, canon, positions ni rules.
    """
    if opportunity_doc.get("schema") != OPPORTUNITY_SCHEMA:
        raise ValueError(
            f"opportunity schema debe ser {OPPORTUNITY_SCHEMA}, "
            f"recibido {opportunity_doc.get('schema')!r}"
        )
    if positions_doc.get("schema") != POSITIONS_SCHEMA:
        raise ValueError(
            f"positions schema debe ser {POSITIONS_SCHEMA}, "
            f"recibido {positions_doc.get('schema')!r}"
        )
    if rules_doc.get("schema") != RULES_SCHEMA:
        raise ValueError(
            f"rules schema debe ser {RULES_SCHEMA}, "
            f"recibido {rules_doc.get('schema')!r}"
        )
    if (
        opportunity_doc.get("source_canon_logical_sha256")
        != canon_doc.get("logical_sha256")
    ):
        raise ValueError("OPPORTUNITY_CANON_MISMATCH")

    rules = rules_doc.get("rules") or []
    for rule in rules:
        _validate_rule(rule)

    event_id = opportunity_doc.get("canonical_event_id")
    event = next(
        (
            e for e in canon_doc.get("events", [])
            if e.get("canonical_event_id") == event_id
        ),
        None,
    )
    event_type = (event or {}).get("event_type")
    current = _current_dates(event) if event is not None else {}
    isins = _event_isins(event) if event is not None else set()
    projected = opportunity_doc.get("projection_status") == PROJECTED

    positions = positions_doc.get("positions") or []
    default_as_of = positions_doc.get("as_of")

    counts: dict = {}
    for position in positions:
        key = (
            position.get("account_id"),
            position.get("isin"),
            position.get("as_of") or default_as_of,
        )
        counts[key] = counts.get(key, 0) + 1
    duplicates = {key for key, n in counts.items() if n > 1}

    eligibilities = []
    for index, position in enumerate(positions):
        position_as_of = position.get("as_of") or default_as_of
        is_duplicate = (
            position.get("account_id"),
            position.get("isin"),
            position_as_of,
        ) in duplicates
        for option in opportunity_doc.get("options") or []:
            eligibilities.append(
                _eligibility(
                    event, event_type, current, isins, rules,
                    position, index, position_as_of, is_duplicate,
                    option, projected,
                )
            )

    return {
        "schema": ELIGIBILITY_SCHEMA,
        "generated_at": now or _now(),
        "source_canon_logical_sha256": canon_doc.get("logical_sha256"),
        "source_positions_logical_sha256": sha256_hex(positions_doc),
        "source_message_input_sha256": opportunity_doc.get(
            "input_sha256"
        ),
        "canonical_event_id": event_id,
        "eligibilities": eligibilities,
    }
