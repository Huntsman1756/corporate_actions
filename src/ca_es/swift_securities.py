"""P6.3 — MT566 -> security movement candidates.

docs/p6/p63-scope.md:

    CA_ES_SWIFT_MT_FACTS_V1 (MT566)
        -> P4.1 project_ca_message + bind_event (BOUND requerido)
        -> CA_ES_SWIFT_SECURITY_MOVEMENT_CANDIDATE_V1

Un candidato por subsecuencia SECMOVE del modelo SRU2025. Nunca se
combinan movimientos, nunca se infiere direccion por signo/CAEV y
nunca se toma el ISIN del canon (35B del SECMOVE es explicito).

Reglas duras:

- integridad de agrupacion: count(22H) == count(35B) en el path
  CACONF/SECMOVE; si difiere -> doc INDETERMINATE
  AMBIGUOUS_SECMOVE_STRUCTURE (un fieldset-22 repetido romperia la
  atribucion de ventanas);
- whitelist de direccion: 22H::CRDB//CRED -> RECEIPT,
  CRDB//DEBT -> DELIVERY (Euroclear spec + muestra real Erste);
  cualquier otro qualifier/codigo -> UNSUPPORTED_DIRECTION*;
- cantidad solo 36B::PSTA con quantity type UNIT; nunca 93B (balance)
  ni 92D (ratio);
- cuenta: 97A::SAFE (como P4.2); fechas: 98A::POST efectiva, PAYD
  provenance;
- binding BOUND obligatorio para PROJECTABLE; read-only.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .swift_ca import (
    BOUND,
    bind_event,
    project_ca_message,
)

CANDIDATE_SCHEMA = "CA_ES_SWIFT_SECURITY_MOVEMENT_CANDIDATE_V1"

PROJECTABLE = "PROJECTABLE"
INDETERMINATE = "INDETERMINATE"
UNSUPPORTED = "UNSUPPORTED"

RECEIPT = "RECEIPT"
DELIVERY = "DELIVERY"

SECMOVE_PATH = "CACONF/SECMOVE"
DIRECTION_CODES = {"CRED": RECEIPT, "DEBT": DELIVERY}
SUPPORTED_QUANTITY_TYPES = {"UNIT"}

_TAG_INDEX = re.compile(r"^block4\.tag\[(\d+)\]")


def _tag_index(fact: dict) -> int:
    match = _TAG_INDEX.match(fact.get("evidence_locator") or "")
    return int(match.group(1)) if match else -1


def _norm_qty(raw):
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


def _distinct(values):
    return next(iter(values)) if len(values) == 1 else None


def _movement_from_window(window: list[dict], index: int,
                          input_sha: str, account_id, account_reason,
                          binding_status: str) -> dict:
    """Una ventana SECMOVE -> candidato de movimiento."""
    reasons: list[str] = []
    movement = {
        "movement_id": f"SWIFT-{input_sha[:16]}-SECMOVE{index}",
        "account_id": account_id,
        "isin": None,
        "direction": None,
        "quantity": None,
        "quantity_type": None,
        "posting_date": None,
        "status": INDETERMINATE,
        "reasons": reasons,
        "provenance": [_prov(f) for f in window],
    }

    if binding_status != BOUND:
        reasons.append("EVENT_NOT_BOUND")
    if account_reason:
        reasons.append(account_reason)

    # direccion: unico 22H de la ventana (integridad garantizada por
    # el check doc-level count(22H)==count(35B))
    dir_facts = _find(window, "22H", label_suffix=".indicator")
    dir_fact = dir_facts[0] if dir_facts else None
    if dir_fact is None:
        reasons.append("MISSING_DIRECTION")
    elif dir_fact.get("source_qualifier") != "CRDB":
        reasons.append("UNSUPPORTED_DIRECTION_QUALIFIER")
        movement["status"] = UNSUPPORTED
    else:
        code = dir_fact.get("value")
        if code in DIRECTION_CODES:
            movement["direction"] = DIRECTION_CODES[code]
        else:
            reasons.append("UNSUPPORTED_DIRECTION_CODE")
            movement["status"] = UNSUPPORTED

    isin_facts = _find(window, "35B", label_suffix=".isin")
    isins = {f.get("value") for f in isin_facts}
    if not isins:
        reasons.append("MISSING_ISIN")
    elif len(isins) > 1:
        reasons.append("CONFLICTING_INSTRUMENT")
    else:
        movement["isin"] = next(iter(isins))

    qty_facts = _find(window, "36B", "PSTA", label_suffix=".quantity")
    type_facts = _find(
        window, "36B", "PSTA", label_suffix=".quantity type code")
    if not qty_facts:
        reasons.append("MISSING_QUANTITY")
    else:
        values = {_norm_qty(f.get("value")) for f in qty_facts}
        values.discard(None)
        if len(values) > 1:
            reasons.append("CONFLICTING_QUANTITY")
        elif not values:
            reasons.append("INVALID_QUANTITY")
        else:
            movement["quantity"] = next(iter(values))
    types = {f.get("value") for f in type_facts}
    qty_type = _distinct(types)
    movement["quantity_type"] = qty_type
    if qty_type is None and len(types) > 1:
        reasons.append("CONFLICTING_QUANTITY_TYPE")
    elif qty_type is not None and qty_type not in (
            SUPPORTED_QUANTITY_TYPES):
        reasons.append("UNSUPPORTED_QUANTITY_TYPE")
        movement["status"] = UNSUPPORTED

    post_facts = _find(window, "98A", "POST", label_suffix=".date")
    posts = {_norm_date(f.get("value")) for f in post_facts}
    if not posts:
        reasons.append("MISSING_POSTING_DATE")
    elif len(posts) > 1:
        reasons.append("CONFLICTING_POSTING_DATE")
    else:
        movement["posting_date"] = next(iter(posts))

    if movement["status"] == UNSUPPORTED:
        return movement
    if reasons:
        return movement
    movement["status"] = PROJECTABLE
    return movement


def security_movement_candidate(facts_doc: dict, canon_doc: dict,
                                now: str | None = None) -> dict:
    """facts + canon -> CA_ES_SWIFT_SECURITY_MOVEMENT_CANDIDATE_V1.

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
        "caev": None,
    }

    if facts_doc.get("message_identifier") != "MT566":
        return {
            **base,
            "status": UNSUPPORTED,
            "reasons": ["UNSUPPORTED_MESSAGE_TYPE"],
            "movements": [],
        }

    msg = project_ca_message(facts_doc, now=now)
    binding = bind_event(msg, canon_doc, now=now)
    base.update({
        "generated_at": binding["generated_at"],
        "canonical_event_id": binding.get("canonical_event_id"),
        "binding_status": binding.get("binding_status"),
        "event_type": binding.get("event_type"),
        "caev": (msg.get("caev")),
    })

    if msg.get("status") == "UNSUPPORTED_CA_EVENT":
        return {
            **base,
            "status": UNSUPPORTED,
            "reasons": ["UNSUPPORTED_CA_EVENT"],
            "movements": [],
        }

    doc_reasons = []
    if binding.get("binding_status") != BOUND:
        doc_reasons.append("EVENT_NOT_BOUND")

    caon = _distinct({f.get("value") for f in _find(
        facts, "13A", "CAON", label_suffix=".number id",
        seq="CACONF")})
    caop = _distinct({f.get("value") for f in _find(
        facts, "22F", "CAOP", label_suffix=".indicator",
        seq="CACONF")})
    base["caon"] = caon
    base["caop"] = caop

    account_facts = _find(facts, "97A", "SAFE",
                          label_suffix=".account number")
    accounts = {f.get("value") for f in account_facts}
    account_id = _distinct(accounts)
    account_reason = None
    if not account_facts:
        account_reason = "MISSING_ACCOUNT"
    elif account_id is None:
        account_reason = "CONFLICTING_ACCOUNT"

    secmove = sorted(
        [f for f in facts if f.get("sequence") == SECMOVE_PATH],
        key=_tag_index,
    )
    boundaries = [
        f for f in secmove
        if f.get("source_tag") == "22H"
        and (f.get("field_path") or "").endswith(".indicator")
    ]
    isin_count = len(_find(secmove, "35B", label_suffix=".isin"))

    if not secmove:
        return {
            **base,
            "status": INDETERMINATE,
            "reasons": doc_reasons + ["NO_SECMOVE_BLOCKS"],
            "movements": [],
        }
    if len(boundaries) != isin_count:
        return {
            **base,
            "status": INDETERMINATE,
            "reasons": doc_reasons + ["AMBIGUOUS_SECMOVE_STRUCTURE"],
            "movements": [],
        }

    # ventanas: cada SECMOVE arranca en su primer 22H (fieldset-22
    # inicial, M); fin = inicio del siguiente 22H o fin del path
    windows = []
    starts = [_tag_index(f) for f in boundaries]
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else None
        windows.append([
            f for f in secmove
            if start <= _tag_index(f)
            and (end is None or _tag_index(f) < end)
        ])

    movements = [
        _movement_from_window(
            window, i, facts_doc.get("input_sha256") or "",
            account_id, account_reason,
            binding.get("binding_status"))
        for i, window in enumerate(windows)
    ]

    if movements and all(m["status"] == PROJECTABLE for m in movements):
        status = PROJECTABLE
    else:
        status = INDETERMINATE

    return {
        **base,
        "status": status,
        "reasons": doc_reasons,
        "movements": movements,
    }
