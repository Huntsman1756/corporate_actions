"""P4.7 — seev.036 -> cash/security movement candidates.

docs/p4/p47-seev036-scope.md:

    CA_ES_SWIFT_MX_FACTS_V1 (seev.036.001.16 / seev.036.002.16)
        -> project_mx_message + bind_event (BOUND requerido)
        -> CA_ES_SWIFT_CASH_CANDIDATE_V1
        -> CA_ES_SWIFT_SECURITY_MOVEMENT_CANDIDATE_V1

Mismos contratos que P4.2/P6.3: la semantica de candidato es
transport-neutral; solo cambia la provenance (model_path en vez de
source_tag/sequence). Un candidato por ocurrencia, nunca agregacion;
basis y direccion solo desde elementos explicitos.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .mx_ca import _field, _mf, _mxprov, project_mx_message
from .swift_ca import BOUND, bind_event

CASH_CANDIDATE_SCHEMA = "CA_ES_SWIFT_CASH_CANDIDATE_V1"
SEC_CANDIDATE_SCHEMA = "CA_ES_SWIFT_SECURITY_MOVEMENT_CANDIDATE_V1"

SUPPORTED_036 = {"seev.036.001.16", "seev.036.002.16"}

PROJECTABLE = "PROJECTABLE"
INDETERMINATE = "INDETERMINATE"
UNSUPPORTED = "UNSUPPORTED"

RECEIPT = "RECEIPT"
DELIVERY = "DELIVERY"

DIRECTION_CODES = {"CRDT": RECEIPT, "DBIT": DELIVERY}

# prioridad determinista (espejo de P4.2 POSTING_PRIORITY):
# importe abonado -> neto explicito -> bruto explicito
AMOUNT_BASIS = {
    "PstngAmt": "UNKNOWN",
    "NetAmt": "NET",
    "GrssAmt": "GROSS",
}
AMOUNT_PRIORITY = ("PstngAmt", "NetAmt", "GrssAmt")

_CSH_ANCHOR = re.compile(r"/CshMvmntDtls\[(\d+)\]")
_SEC_ANCHOR = re.compile(r"/SctiesMvmntDtls\[(\d+)\]")


def _norm_amount(raw):
    try:
        return format(Decimal(str(raw).replace(",", ".")), "f")
    except (InvalidOperation, AttributeError):
        return None


def _occurrence_groups(facts, anchor):
    groups: dict[int, list[dict]] = {}
    for f in facts:
        m = anchor.search(f.get("evidence_locator") or "")
        if m:
            groups.setdefault(int(m.group(1)), []).append(f)
    return groups


def _doc_facts(facts_doc):
    return [
        f for f in facts_doc.get("facts") or []
        if (f.get("model_path") or "").startswith("/Document/")
    ]


def _bound(facts_doc, canon_doc, now):
    """Proyeccion + binding compartidos; devuelve (msg, binding)."""
    msg = project_mx_message(
        facts_doc, now=now, supported_mids=SUPPORTED_036)
    binding = bind_event(msg, canon_doc, now=now)
    return msg, binding


def _account(facts):
    acct = _field(_mf(facts, "/AcctDtls/SfkpgAcct"))
    return acct


def _conf_optn(facts):
    """caon/caop a nivel CorpActnConfDtls."""
    caon = _field(_mf(facts, "/CorpActnConfDtls/OptnNb/Nb"))
    caop = _field(_mf(facts, "/CorpActnConfDtls/OptnTp/Cd"))
    return (
        caon["value"] if caon["status"] == "PRESENT" else None,
        caop["value"] if caop["status"] == "PRESENT" else None,
    )


def mx_cash_candidate(facts_doc: dict, canon_doc: dict,
                      now: str | None = None) -> dict:
    """facts seev.036 + canon -> CA_ES_SWIFT_CASH_CANDIDATE_V1.

    read-only: no muta canon ni facts.
    """
    if facts_doc.get("schema_version") != "CA_ES_SWIFT_MX_FACTS_V1":
        raise ValueError("INVALID_MX_FACTS_DOCUMENT")
    facts = _doc_facts(facts_doc)

    base = {
        "schema": CASH_CANDIDATE_SCHEMA,
        "generated_at": now or facts_doc.get("generated_at"),
        "message_identifier": facts_doc.get("message_identifier"),
        "input_sha256": facts_doc.get("input_sha256"),
        "canonical_event_id": None,
        "binding_status": None,
        "event_type": None,
    }

    if facts_doc.get("message_identifier") not in SUPPORTED_036:
        return {
            **base,
            "status": UNSUPPORTED,
            "reasons": ["UNSUPPORTED_MESSAGE_TYPE"],
            "movement": None,
            "provenance": [],
        }

    msg, binding = _bound(facts_doc, canon_doc, now)
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

    acct = _account(facts)
    account_id = acct["value"] if acct["status"] == "PRESENT" else None
    if acct["status"] == "ABSENT":
        reasons.append("MISSING_ACCOUNT")
    elif acct["status"] == "CONFLICTING":
        reasons.append("CONFLICTING_ACCOUNT")

    groups = _occurrence_groups(facts, _CSH_ANCHOR)
    if len(groups) > 1:
        reasons.append("MULTIPLE_CASH_MOVEMENTS")
    group = groups[sorted(groups)[0]] if groups else []

    chosen = None
    amount_facts: list[dict] = []
    for elem in AMOUNT_PRIORITY:
        found = [
            f for f in group
            if (f.get("model_path") or "").endswith(
                f"/AmtDtls/{elem}")
        ]
        if found:
            chosen = elem
            amount_facts = found
            break
    amount = None
    if chosen is None:
        reasons.append("MISSING_AMOUNT")
    else:
        values = {_norm_amount(f.get("value")) for f in amount_facts}
        values.discard(None)
        if len(values) > 1:
            reasons.append("CONFLICTING_AMOUNT")
        elif not values:
            reasons.append("MISSING_AMOUNT")
        else:
            amount = next(iter(values))

    currency = None
    if chosen is not None:
        ccy_facts = [
            f for f in group
            if (f.get("model_path") or "").endswith(
                f"/AmtDtls/{chosen}/@Ccy")
        ]
        currencies = {f.get("value") for f in ccy_facts}
        if len(currencies) == 1:
            currency = next(iter(currencies))
        elif len(currencies) > 1:
            reasons.append("CONFLICTING_CURRENCY")
        else:
            reasons.append("MISSING_CURRENCY")

    direction_facts = [
        f for f in group
        if (f.get("model_path") or "").endswith("/CdtDbtInd")
    ]
    directions = {f.get("value") for f in direction_facts}
    direction = next(iter(directions)) if len(directions) == 1 else None
    if len(directions) > 1:
        reasons.append("CONFLICTING_DIRECTION")

    vd_facts = [
        f for f in group
        if (f.get("model_path") or "").endswith("/DtDtls/PstngDt/Dt")
        or (f.get("model_path") or "").endswith("/DtDtls/PmtDt")
    ]
    vd_values = {f.get("value") for f in vd_facts}
    value_date = next(iter(vd_values)) if len(vd_values) == 1 else None

    basis = AMOUNT_BASIS.get(chosen)
    basis_reason = (
        "UNKNOWN_AMOUNT_BASIS" if basis == "UNKNOWN" else None
    )

    provenance = [*acct["provenance"],
                  *(_mxprov(f) for f in group)]

    movement = None
    if not reasons and basis is not None:
        movement = {
            "movement_id": "MX-" + (facts_doc.get("input_sha256")
                                    or "")[:16],
            "account_id": account_id,
            "event_id": binding.get("canonical_event_id"),
            "currency": currency,
            "amount": amount,
            "amount_basis": basis,
            "value_date": value_date,
            "direction": direction,
        }

    return {
        **base,
        "status": PROJECTABLE if movement else INDETERMINATE,
        "reasons": reasons,
        "amount_source_qualifier": chosen,
        "amount_basis": basis,
        "basis_reason": basis_reason,
        "value_date": value_date,
        "movement": movement,
        "provenance": provenance,
    }


def _sec_movement(group: list[dict], index: int, input_sha: str,
                  account_id, account_reason: str | None,
                  binding_status: str) -> dict:
    reasons: list[str] = []
    movement = {
        "movement_id": f"MX-{input_sha[:16]}-SECMOVE{index}",
        "account_id": account_id,
        "isin": None,
        "direction": None,
        "quantity": None,
        "quantity_type": None,
        "posting_date": None,
        "status": INDETERMINATE,
        "reasons": reasons,
        "provenance": [_mxprov(f) for f in group],
    }

    if binding_status != BOUND:
        reasons.append("EVENT_NOT_BOUND")
    if account_reason:
        reasons.append(account_reason)

    dir_facts = [
        f for f in group
        if (f.get("model_path") or "").endswith("/CdtDbtInd")
    ]
    dirs = {f.get("value") for f in dir_facts}
    if not dir_facts:
        reasons.append("MISSING_DIRECTION")
    elif len(dirs) > 1:
        reasons.append("CONFLICTING_DIRECTION")
    else:
        code = next(iter(dirs))
        if code in DIRECTION_CODES:
            movement["direction"] = DIRECTION_CODES[code]
        else:
            reasons.append("UNSUPPORTED_DIRECTION_CODE")
            movement["status"] = UNSUPPORTED

    isin_facts = [
        f for f in group
        if (f.get("model_path") or "").endswith("/FinInstrmId/ISIN")
    ]
    isins = {f.get("value") for f in isin_facts}
    if not isins:
        reasons.append("MISSING_ISIN")
    elif len(isins) > 1:
        reasons.append("CONFLICTING_INSTRUMENT")
    else:
        movement["isin"] = next(iter(isins))

    unit_facts = [
        f for f in group
        if (f.get("model_path") or "").endswith("/PstngQty/Qty/Unit")
    ]
    qty_other = [
        f for f in group
        if "/PstngQty/" in (f.get("model_path") or "")
        and not str(f["model_path"]).endswith("/PstngQty/Qty/Unit")
    ]
    if unit_facts:
        values = {_norm_amount(f.get("value")) for f in unit_facts}
        values.discard(None)
        if len(values) > 1:
            reasons.append("CONFLICTING_QUANTITY")
        elif not values:
            reasons.append("INVALID_QUANTITY")
        else:
            movement["quantity"] = next(iter(values))
            movement["quantity_type"] = "UNIT"
    elif qty_other:
        reasons.append("UNSUPPORTED_QUANTITY_TYPE")
        movement["status"] = UNSUPPORTED
    else:
        reasons.append("MISSING_QUANTITY")

    post_facts = [
        f for f in group
        if (f.get("model_path") or "").endswith("/DtDtls/PstngDt/Dt")
        or (f.get("model_path") or "").endswith("/DtDtls/PstngDt/DtTm")
    ]
    posts = {f.get("value") for f in post_facts}
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


def mx_security_movement_candidate(facts_doc: dict, canon_doc: dict,
                                   now: str | None = None) -> dict:
    """facts seev.036 + canon ->
    CA_ES_SWIFT_SECURITY_MOVEMENT_CANDIDATE_V1.

    read-only: no muta canon ni facts.
    """
    if facts_doc.get("schema_version") != "CA_ES_SWIFT_MX_FACTS_V1":
        raise ValueError("INVALID_MX_FACTS_DOCUMENT")
    facts = _doc_facts(facts_doc)

    base = {
        "schema": SEC_CANDIDATE_SCHEMA,
        "generated_at": now or facts_doc.get("generated_at"),
        "message_identifier": facts_doc.get("message_identifier"),
        "input_sha256": facts_doc.get("input_sha256"),
        "canonical_event_id": None,
        "binding_status": None,
        "event_type": None,
        "caev": None,
    }

    if facts_doc.get("message_identifier") not in SUPPORTED_036:
        return {
            **base,
            "status": UNSUPPORTED,
            "reasons": ["UNSUPPORTED_MESSAGE_TYPE"],
            "movements": [],
        }

    msg, binding = _bound(facts_doc, canon_doc, now)
    base.update({
        "generated_at": binding["generated_at"],
        "canonical_event_id": binding.get("canonical_event_id"),
        "binding_status": binding.get("binding_status"),
        "event_type": binding.get("event_type"),
        "caev": msg.get("caev"),
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

    caon, caop = _conf_optn(facts)
    base["caon"] = caon
    base["caop"] = caop

    acct = _account(facts)
    account_id = acct["value"] if acct["status"] == "PRESENT" else None
    account_reason = None
    if acct["status"] == "ABSENT":
        account_reason = "MISSING_ACCOUNT"
    elif acct["status"] == "CONFLICTING":
        account_reason = "CONFLICTING_ACCOUNT"

    groups = _occurrence_groups(facts, _SEC_ANCHOR)
    if not groups:
        return {
            **base,
            "status": INDETERMINATE,
            "reasons": doc_reasons + ["NO_SECMOVE_BLOCKS"],
            "movements": [],
        }

    movements = [
        _sec_movement(
            groups[k], k, facts_doc.get("input_sha256") or "",
            account_id, account_reason,
            binding.get("binding_status"))
        for k in sorted(groups)
    ]

    if movements and all(m["status"] == PROJECTABLE
                         for m in movements):
        status = PROJECTABLE
    else:
        status = INDETERMINATE

    return {
        **base,
        "status": status,
        "reasons": doc_reasons,
        "movements": movements,
    }
