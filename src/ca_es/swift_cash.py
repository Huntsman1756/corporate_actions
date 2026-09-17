"""P4.2 — MT566 -> cash movement candidate.

docs/p4/p42-scope.md:

    CA_ES_SWIFT_MT_FACTS_V1
        -> CA_ES_SWIFT_CA_MESSAGE_V1 + binding (P4.1)
        -> CA_ES_SWIFT_CASH_CANDIDATE_V1
        -> movement CA_ES_CASH_MOVEMENTS_V2 (solo si PROJECTABLE)

Reglas duras:

- binding BOUND obligatorio; el candidato nunca modifica el canon
- whitelist cerrada de qualifiers de posting (19B): PSTA/NETO/GRSS;
  cualquier otro 19B no es importe reconciliable
- basis desde qualifier explicito: GRSS->GROSS, NETO->NET,
  PSTA->UNKNOWN; nunca se infiere (ni MT566=>NET ni
  actual<gross=>NET)
- importe/moneda unicos; occurrences del qualifier elegido con
  valores distintos -> CONFLICTING_AMOUNT; varias sub-secuencias de
  cash movement -> MULTIPLE_CASH_MOVEMENTS (P3 no agrega)
- UNKNOWN sigue siendo PROJECTABLE: el movement se emite con
  amount_basis UNKNOWN y P3.1 lo trata honestamente
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .swift_ca import (
    BOUND,
    bind_event,
    project_ca_message,
)

CANDIDATE_SCHEMA = "CA_ES_SWIFT_CASH_CANDIDATE_V1"

PROJECTABLE = "PROJECTABLE"
INDETERMINATE = "INDETERMINATE"
UNSUPPORTED = "UNSUPPORTED"

# whitelist SRU2025 cerrada: qualifier -> amount_basis.
# PSTA = importe abonado; el qualifier no declara base -> UNKNOWN.
POSTING_BASIS = {
    "PSTA": "UNKNOWN",
    "NETO": "NET",
    "GRSS": "GROSS",
}
# prioridad determinista: importe efectivamente abonado primero
POSTING_PRIORITY = ("PSTA", "NETO", "GRSS")


def _norm_amount(raw):
    try:
        return format(Decimal(str(raw).replace(",", ".")), "f")
    except (InvalidOperation, AttributeError):
        return None


def _norm_date(raw):
    if raw and len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw


def _prov(fact):
    return {
        "source_tag": fact.get("source_tag"),
        "source_qualifier": fact.get("source_qualifier"),
        "sequence": fact.get("sequence"),
        "occurrence": fact.get("occurrence"),
        "evidence_locator": fact.get("evidence_locator"),
        "raw": fact.get("value"),
    }


def _find(facts, tag, qualifier=None, label_suffix=None, seq=None):
    return [
        f for f in facts
        if f.get("source_tag") == tag
        and (qualifier is None or f.get("source_qualifier") == qualifier)
        and (seq is None or f.get("sequence") == seq)
        and (
            label_suffix is None
            or (f.get("field_path") or "").endswith(label_suffix)
        )
    ]


def cash_candidate(facts_doc: dict, canon_doc: dict,
                   now: str | None = None) -> dict:
    """facts + canon -> CA_ES_SWIFT_CASH_CANDIDATE_V1.

    read-only: no muta canon ni facts.
    """
    facts = facts_doc.get("facts") or []
    generated_at = now or facts_doc.get("generated_at")

    base = {
        "schema": CANDIDATE_SCHEMA,
        "generated_at": generated_at,
        "message_identifier": facts_doc.get("message_identifier"),
        "input_sha256": facts_doc.get("input_sha256"),
        "canonical_event_id": None,
        "binding_status": None,
        "event_type": None,
    }

    if facts_doc.get("message_identifier") != "MT566":
        return {
            **base,
            "status": UNSUPPORTED,
            "reasons": ["UNSUPPORTED_MESSAGE_TYPE"],
            "movement": None,
            "provenance": [],
        }

    msg = project_ca_message(facts_doc, now=now)
    binding = bind_event(msg, canon_doc, now=now)
    base.update({
        "generated_at": binding["generated_at"],
        "canonical_event_id": binding.get("canonical_event_id"),
        "binding_status": binding.get("binding_status"),
        "event_type": binding.get("event_type"),
    })

    if msg.get("status") == "UNSUPPORTED_CA_EVENT":
        return {
            **base,
            "status": UNSUPPORTED,
            "reasons": ["UNSUPPORTED_CA_EVENT"],
            "movement": None,
            "provenance": [],
        }

    reasons = []
    if binding.get("binding_status") != BOUND:
        reasons.append("EVENT_NOT_BOUND")

    # cuenta de custodia: 97A::SAFE (cualquier secuencia)
    account_facts = _find(facts, "97A", "SAFE",
                          label_suffix=".account number")
    accounts = {f.get("value") for f in account_facts}
    account_id = next(iter(accounts)) if len(accounts) == 1 else None
    if not account_facts:
        reasons.append("MISSING_ACCOUNT")
    elif account_id is None:
        reasons.append("CONFLICTING_ACCOUNT")

    # importe del posting: whitelist por prioridad; cada occurrence es
    # un cash movement distinto (sequence path no distingue CSMV
    # repetidos -> occurrence lo hace)
    chosen_qual = None
    amount_facts = []
    for qual in POSTING_PRIORITY:
        found = _find(facts, "19B", qual, label_suffix=".amount")
        if found:
            chosen_qual = qual
            amount_facts = found
            break
    amount = None
    if chosen_qual is None:
        reasons.append("MISSING_AMOUNT")
    else:
        occs = {f.get("occurrence", 0) for f in amount_facts}
        if len(occs) > 1:
            reasons.append("MULTIPLE_CASH_MOVEMENTS")
        values = {_norm_amount(f.get("value")) for f in amount_facts}
        values.discard(None)
        if len(values) == 1:
            amount = next(iter(values))
        elif len(values) > 1:
            reasons.append("CONFLICTING_AMOUNT")
        else:
            reasons.append("MISSING_AMOUNT")

    currency_facts = []
    currency = None
    if chosen_qual is not None:
        currency_facts = _find(facts, "19B", chosen_qual,
                               label_suffix=".currency code")
        currencies = {f.get("value") for f in currency_facts}
        if len(currencies) == 1:
            currency = next(iter(currencies))
        elif len(currencies) > 1:
            reasons.append("CONFLICTING_CURRENCY")
        else:
            reasons.append("MISSING_CURRENCY")

    # value_date informativa: VALU o PAYD en el mensaje
    vd_facts = (
        _find(facts, "98A", "VALU", label_suffix=".date")
        or _find(facts, "98A", "PAYD", label_suffix=".date")
    )
    vd_values = {_norm_date(f.get("value")) for f in vd_facts}
    value_date = next(iter(vd_values)) if len(vd_values) == 1 else None

    basis = POSTING_BASIS.get(chosen_qual)
    basis_reason = (
        "UNKNOWN_AMOUNT_BASIS" if basis == "UNKNOWN" else None
    )

    provenance = [
        _prov(f) for f in
        (*account_facts, *amount_facts, *currency_facts, *vd_facts)
    ]

    movement = None
    if not reasons and basis is not None:
        movement = {
            "movement_id": "SWIFT-" + (facts_doc.get("input_sha256")
                                       or "")[:16],
            "account_id": account_id,
            "event_id": binding.get("canonical_event_id"),
            "currency": currency,
            "amount": amount,
            "amount_basis": basis,
            "value_date": value_date,
        }

    return {
        **base,
        "status": PROJECTABLE if movement else INDETERMINATE,
        "reasons": reasons,
        "amount_source_qualifier": chosen_qual,
        "amount_basis": basis,
        "basis_reason": basis_reason,
        "value_date": value_date,
        "movement": movement,
        "provenance": provenance,
    }
