"""P4.4 — seev.031 (MX) -> contratos de dominio existentes.

docs/p4/p44-seev031-scope.md:

    CA_ES_SWIFT_MX_FACTS_V1 (seev.031.001.15 / seev.031.002.15)
        -> project_mx_message()   -> CA_ES_SWIFT_CA_MESSAGE_V1
        -> bind_event()           -> CA_ES_SWIFT_EVENT_BINDING_V1
        -> project_mx_election()  -> CA_ES_ELECTION_OPPORTUNITY_V1

Los contratos de destino son los ya cerrados en P4.1/P5.2: el mensaje
semantico, el binding y la oportunidad de eleccion son
transport-neutrales; solo cambia el origen de la provenance
(model_path en vez de source_tag/sequence).

Reglas duras: mismas que P4.1/P5.2. Nunca se elige una ocurrencia
arbitraria; DtCd no se interpreta como fecha; NetDstrbtnRate no es
gross; StgInstrInd no es indicador de default.
"""

from __future__ import annotations

import re

from .election import OPTION_KIND, _bind_queue
from .swift_ca import (
    BOUND,
    CA_MESSAGE_SCHEMA,
    CAEV_MAP,
    _norm_amount,
    _norm_date,
    _now,
    bind_event,
)

MX_FACTS_SCHEMA = "CA_ES_SWIFT_MX_FACTS_V1"
OPPORTUNITY_SCHEMA = "CA_ES_ELECTION_OPPORTUNITY_V1"

SUPPORTED_031 = {"seev.031.001.15", "seev.031.002.15"}

PROJECTED = "PROJECTED"
INDETERMINATE = "INDETERMINATE"
UNSUPPORTED = "UNSUPPORTED"

PRESENT = "PRESENT"
ABSENT = "ABSENT"
CONFLICTING = "CONFLICTING"

_OPTION_ANCHOR = re.compile(r"/CorpActnOptnDtls\[(\d+)\]")


def _mxprov(fact: dict) -> dict:
    return {
        "model_path": fact.get("model_path"),
        "occurrence": fact.get("occurrence"),
        "evidence_locator": fact.get("evidence_locator"),
        "raw": fact.get("value"),
    }


def _mf(facts: list[dict], suffix: str) -> list[dict]:
    """Facts cuyo model_path termina en el sufijo dado."""
    return [
        f for f in facts
        if (f.get("model_path") or "").endswith(suffix)
    ]


def _field(facts: list[dict], normalize=None) -> dict:
    """Campo semantico: mismo contrato PRESENT/ABSENT/CONFLICTING."""
    values = set()
    provenance = []
    raw = None
    for f in facts:
        provenance.append(_mxprov(f))
        raw = f.get("value")
        values.add(normalize(raw) if normalize else raw)
    if not facts:
        return {"value": None, "status": ABSENT, "raw": None,
                "provenance": []}
    if len(values) > 1:
        return {"value": None, "status": CONFLICTING, "raw": raw,
                "provenance": provenance}
    return {"value": next(iter(values)), "status": PRESENT,
            "raw": raw, "provenance": provenance}


def project_mx_message(facts_doc: dict, now: str | None = None,
                       supported_mids: set | None = None) -> dict:
    """CA_ES_SWIFT_MX_FACTS_V1 -> CA_ES_SWIFT_CA_MESSAGE_V1.

    ``supported_mids`` fija el gate de tipo de mensaje (default
    SUPPORTED_031); P4.7 lo usa para seev.036.
    """
    if facts_doc.get("schema_version") != MX_FACTS_SCHEMA:
        raise ValueError(
            f"facts schema debe ser {MX_FACTS_SCHEMA}, "
            f"recibido {facts_doc.get('schema_version')!r}"
        )
    mid = facts_doc.get("message_identifier")
    facts = facts_doc.get("facts") or []
    doc_facts = [
        f for f in facts
        if (f.get("model_path") or "").startswith("/Document/")
    ]

    caev = _field(
        _mf(doc_facts, "/CorpActnGnlInf/EvtTp/Cd"))
    caev_val = caev["value"]
    event_type = CAEV_MAP.get(caev_val) if caev_val else None

    if mid not in (supported_mids or SUPPORTED_031):
        status = "UNSUPPORTED_MESSAGE_TYPE"
    elif facts_doc.get("parse_status") != "PARSE_OK":
        status = "PARSE_NOT_OK"
    elif caev_val is None or caev_val not in CAEV_MAP:
        status = "UNSUPPORTED_CA_EVENT"
    else:
        status = "OK"

    fields = {
        "corporate_action_reference": _field(
            _mf(doc_facts, "/CorpActnGnlInf/CorpActnEvtId")),
        "related_reference": _field([]),
        "caev": caev,
        "isin": _field(
            _mf(doc_facts,
                "/CorpActnGnlInf/UndrlygScty/FinInstrmId/ISIN")
            + _mf(doc_facts,
                  "/CorpActnGnlInf/FinInstrmId/ISIN")),
        "ex_date": _field(
            _mf(doc_facts, "/CorpActnDtls/DtDtls/ExDvddDt/Dt"),
            normalize=_norm_date),
        "record_date": _field(
            _mf(doc_facts, "/CorpActnDtls/DtDtls/RcrdDt/Dt"),
            normalize=_norm_date),
        "payment_date": _field(
            _mf(doc_facts, "/CorpActnDtls/DtDtls/PmtDt/Dt"),
            normalize=_norm_date),
        "gross_per_share": _field(
            _mf(doc_facts, "/GrssDstrbtnRate/Amt"),
            normalize=_norm_amount),
        "currency": _field(
            _mf(doc_facts, "/GrssDstrbtnRate/Amt/@Ccy")),
        "message_function": _field(
            _mf(doc_facts, "/NtfctnGnlInf/NtfctnTp")),
        "processing_status": _field(
            _mf(doc_facts, "/CorpActnGnlInf/EvtPrcgTp/Cd")),
    }

    return {
        "schema": CA_MESSAGE_SCHEMA,
        "generated_at": now or _now(),
        "message_identifier": mid,
        "input_sha256": facts_doc.get("input_sha256"),
        "status": status,
        "caev": caev_val,
        "event_type": event_type,
        "fields": fields,
    }


def _option_groups(facts: list[dict]) -> dict[int, list[dict]]:
    """Agrupa facts por ocurrencia de CorpActnOptnDtls via locator."""
    groups: dict[int, list[dict]] = {}
    for f in facts:
        m = _OPTION_ANCHOR.search(f.get("evidence_locator") or "")
        if m:
            groups.setdefault(int(m.group(1)), []).append(f)
    return groups


def project_mx_election(facts_doc: dict, canon_doc: dict,
                        queue_doc: dict | None = None,
                        deadline_types: tuple = (),
                        now: str | None = None) -> dict:
    """MX facts + canon [+ queue] -> CA_ES_ELECTION_OPPORTUNITY_V1.

    read-only: no muta facts, canon ni queue.
    """
    if facts_doc.get("schema_version") != MX_FACTS_SCHEMA:
        raise ValueError(
            f"facts schema debe ser {MX_FACTS_SCHEMA}, "
            f"recibido {facts_doc.get('schema_version')!r}"
        )
    facts = facts_doc.get("facts") or []
    canon_sha = canon_doc.get("logical_sha256")

    base = {
        "schema": OPPORTUNITY_SCHEMA,
        "generated_at": now or _now(),
        "source_canon_logical_sha256": canon_sha,
        "source_message_identifier": facts_doc.get("message_identifier"),
        "input_sha256": facts_doc.get("input_sha256"),
        "canonical_event_id": None,
        "options": [],
        "source_response_deadline": None,
        "operational_deadlines": [],
        "deadline_binding_status": "NOT_APPLICABLE",
        "reasons": [],
    }

    if facts_doc.get("message_identifier") not in SUPPORTED_031:
        return {**base, "projection_status": UNSUPPORTED,
                "reasons": ["UNSUPPORTED_MESSAGE_TYPE"]}

    msg = project_mx_message(facts_doc, now=now)
    if msg.get("status") != "OK":
        return {**base, "projection_status": UNSUPPORTED,
                "reasons": [msg["status"]]}

    binding = bind_event(msg, canon_doc, now=now)
    eid = binding.get("canonical_event_id")
    base["canonical_event_id"] = eid
    reasons = []
    if binding.get("binding_status") != BOUND:
        reasons.append("EVENT_NOT_BOUND")

    groups = _option_groups(facts)
    if not groups:
        reasons.append("NO_OPTION_EVIDENCE")

    options = []
    seen_ids = set()
    for idx in sorted(groups):
        group = groups[idx]

        ident_facts = _mf(group, "/OptnNb")
        ident_vals = {f.get("value") for f in ident_facts}
        ident_vals.discard(None)
        ident = next(iter(ident_vals)) if len(ident_vals) == 1 else None
        if ident is None:
            reasons.append("MISSING_OPTION_IDENTITY")
            continue
        if len(ident_vals) > 1:
            reasons.append("CONFLICTING_OPTION_IDENTITY")
        if ident in seen_ids:
            reasons.append("CONFLICTING_OPTION_IDENTITY")
        seen_ids.add(ident)

        code = _field(
            _mf(group, "/OptnTp/Cd")
            or _mf(group, "/OptnTp/Prtry/Id"))
        dflt = _field(
            _mf(group, "/DfltPrcgOrStgInstr/DfltOptnInd"))
        rddt = _field(
            _mf(group, "/RspnDdln/Dt/Dt"),
            normalize=_norm_date)
        rddt_tm = _field(_mf(group, "/RspnDdln/Dt/DtTm"))
        if rddt["status"] != PRESENT and rddt_tm["status"] == PRESENT:
            rddt = rddt_tm
        code_v = code["value"] if code["status"] == PRESENT else None
        dflt_v = dflt["value"] if dflt["status"] == PRESENT else None
        if code["status"] == CONFLICTING or dflt["status"] == CONFLICTING \
                or rddt["status"] == CONFLICTING:
            reasons.append("CONFLICTING_OPTION_FACTS")

        default_status = (
            "CONFLICTING" if dflt["status"] == CONFLICTING
            else {"true": "DEFAULT", "false": "NOT_DEFAULT"}.get(
                dflt_v, "UNKNOWN")
        )
        identity_paths = (
            "/OptnNb", "/OptnTp/", "/DfltPrcgOrStgInstr/",
            "/RspnDdln",
        )
        options.append({
            "option_key": f"{eid}|option:{ident}",
            "option_identifier": ident,
            "option_code_raw": code_v,
            "option_kind": OPTION_KIND.get(code_v, "UNSUPPORTED"),
            "default_status": default_status,
            "source_response_deadline": (
                rddt["value"] if rddt["status"] == PRESENT else None),
            "terms": [
                _mxprov(f) for f in group
                if not any((f.get("model_path") or "").endswith(p)
                           or p in (f.get("model_path") or "")
                           for p in identity_paths)
            ],
            "provenance": [_mxprov(f) for f in ident_facts],
        })

    base["options"] = options

    rddts = {o["source_response_deadline"] for o in options}
    rddts.discard(None)
    if len(rddts) == 1:
        base["source_response_deadline"] = next(iter(rddts))

    _bind_queue(base, queue_doc, canon_sha, eid, deadline_types)

    base["reasons"] = sorted(set(reasons))
    base["projection_status"] = (
        INDETERMINATE if reasons else PROJECTED
    )
    return base
