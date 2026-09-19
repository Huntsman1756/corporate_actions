"""P16.2 — proyeccion seev.050-053 + binding determinista.

CA_ES_SWIFT_MX_FACTS_V1 (seev.050/051/052/053 en las versiones
presentes en el pin SRU2025) -> proyecciones normalizadas:

- seev.050 MarketClaimCreation -> claim observada: referencias
  TxRef, CorpActnEvtId, RltdSttlmInstrDtls, MktClmTp, MktClmDtls
  (cash/securities), AcctDtls, settlement parties.
- seev.052 MarketClaimStatusAdvice -> status event:
  MktClmPrcgSts choice (AccptdForFrthrPrcg/Pdg/MtchgSts/Rjctd/
  Canc/PrtrySts).
- seev.051 MarketClaimCancellationRequest -> cancel intent.
- seev.053 MarketClaimCancellationRequestStatusAdvice ->
  cancel outcome (CxlCmpltd/Accptd/Rjctd/PdgCxl/PrtrySts).

Binding SOLO por referencia explicita (claim_id, TxRef,
RltdSttlmInstrId, transaction_id): nunca por importe+fecha.
BOUND exige exactamente un claim candidato.
"""

from __future__ import annotations

import re

from .mx_ca import _field, _mf

MESSAGE_SCHEMA = "CA_ES_MARKET_CLAIM_MESSAGE_V1"

SUPPORTED_050 = {"seev.050.001.01", "seev.050.001.02",
                 "seev.050.001.03"}
SUPPORTED_051 = {"seev.051.001.01", "seev.051.001.02"}
SUPPORTED_052 = {"seev.052.001.01", "seev.052.001.02",
                 "seev.052.001.03"}
SUPPORTED_053 = {"seev.053.001.01", "seev.053.001.02",
                 "seev.053.001.03"}
SUPPORTED_ALL = (SUPPORTED_050 | SUPPORTED_051 | SUPPORTED_052
                 | SUPPORTED_053)

BOUND = "BOUND"
AMBIGUOUS = "AMBIGUOUS"
NO_MATCH = "NO_MATCH"
UNSUPPORTED = "UNSUPPORTED"

# choice status seev.052 -> estado interno
STATUS_052 = {
    "AccptdForFrthrPrcg": "ACCEPTED",
    "Pdg": "PENDING",
    "MtchgSts": "MATCHING",
    "Rjctd": "REJECTED",
    "Canc": "CANCELLED",
    "PrtrySts": "PROPRIETARY",
}
# choice status seev.053 -> outcome del cancel
STATUS_053 = {
    "CxlCmpltd": "CANCEL_COMPLETED",
    "Accptd": "CANCEL_ACCEPTED",
    "Rjctd": "CANCEL_REJECTED",
    "PdgCxl": "CANCEL_PENDING",
    "PrtrySts": "PROPRIETARY",
}

_CSH_ANCHOR = re.compile(
    r"/MktClmDtls(?:\[\d+\])?/CshMvmntDtls\[(\d+)\]")
_SEC_ANCHOR = re.compile(
    r"/MktClmDtls(?:\[\d+\])?/SctiesMvmntDtls\[(\d+)\]")


def _doc_facts(facts_doc):
    return [
        f for f in facts_doc.get("facts") or []
        if (f.get("model_path") or "").startswith("/Document/")
    ]


def _val(facts, suffix):
    f = _field(_mf(facts, suffix))
    return f["value"] if f["status"] == "PRESENT" else None


def _prov(facts, suffix):
    return (_field(_mf(facts, suffix)).get("provenance") or [])


def _choice(facts, parent_suffix, mapping):
    """Detecta el hijo-choice bajo parent; devuelve
    (choice_tag, internal_status)."""
    found = set()
    for f in facts:
        mp = f.get("model_path") or ""
        idx = mp.rfind(parent_suffix + "/")
        if idx < 0:
            continue
        rest = mp[idx + len(parent_suffix) + 1:]
        tag = rest.split("/", 1)[0]
        if tag in mapping:
            found.add(tag)
    if len(found) == 1:
        tag = next(iter(found))
        return tag, mapping[tag]
    if not found:
        return None, None
    return sorted(found)[0], "CONFLICTING_CHOICE"


def _grouped(facts, anchor):
    groups: dict[int, list] = {}
    for f in facts:
        m = anchor.search(f.get("evidence_locator") or "")
        if m:
            groups.setdefault(int(m.group(1)), []).append(f)
    return groups


def _claim_amounts(facts):
    """Importes/cantidades dentro de MktClmDtls por ocurrencia.

    CashOption106: EntitldAmt|NetCshAmt|GrssCshAmt (Ccy attr) +
    CdtDbtInd. SecuritiesOption76: EntitldQty/Unit +
    FinInstrmId/ISIN + CdtDbtInd.
    """
    cash = []
    for _, group in sorted(_grouped(facts, _CSH_ANCHOR).items()):
        amt = None
        for leaf in ("EntitldAmt", "NetCshAmt", "GrssCshAmt",
                     "WhldgTaxAmt"):
            amt = _val(group, "/" + leaf)
            if amt is not None:
                ccy = _val(group, "/" + leaf + "/@Ccy")
                break
        if amt is None:
            continue
        cdt = _val(group, "/CdtDbtInd")
        cash.append({
            "amount": amt, "currency": ccy,
            "credit_debit": cdt,
            "provenance": _prov(group, "/" + leaf)[:3],
        })
    sec = []
    for _, group in sorted(_grouped(facts, _SEC_ANCHOR).items()):
        qty = _val(group, "/EntitldQty/Unit") or _val(
            group, "/EntitldQty/FaceAmt")
        isin = _val(group, "/FinInstrmId/ISIN")
        cdt = _val(group, "/CdtDbtInd")
        sec.append({
            "quantity": qty, "isin": isin,
            "credit_debit": cdt,
            "provenance": _prov(group, "/EntitldQty/Unit")[:3],
        })
    return cash, sec


def _refs(facts):
    return {
        "account_servicer_tx_id": _val(facts, "/TxRef/AcctSvcrTxId"),
        "market_infrastructure_tx_id": _val(
            facts, "/TxRef/MktInfrstrctrTxId"),
        "processor_tx_id": _val(facts, "/TxRef/PrcrTxId"),
        "claim_creation_id": _val(facts, "/MktClmCreId/Id"),
        "cancellation_request_id": _val(facts, "/MktClmCxlReqId/Id"),
    }


def _base(facts_doc, facts):
    return {
        "message_identifier": facts_doc.get("message_identifier"),
        "input_sha256": facts_doc.get("input_sha256"),
        "canonical_event_reference": _val(
            facts, "/CorpActnGnlInf/CorpActnEvtId"),
        "official_event_reference": _val(
            facts, "/CorpActnGnlInf/OffclCorpActnEvtId"),
        "event_type_code": _val(
            facts, "/CorpActnGnlInf/EvtTp/Cd"),
        "isin": _val(facts, "/CorpActnGnlInf/FinInstrmId/ISIN")
        or _val(facts, "/CorpActnGnlInf/UndrlygScty/FinInstrmId/ISIN"),
        "safekeeping_account": _val(facts, "/AcctDtls/SfkpgAcct"),
        "references": _refs(facts),
    }


def project_market_claim(facts_doc: dict,
                         now: str | None = None) -> dict:
    """seev.050 facts -> claim observada normalizada."""
    mid = facts_doc.get("message_identifier")
    facts = _doc_facts(facts_doc)
    if mid not in SUPPORTED_050:
        return {"schema": MESSAGE_SCHEMA, "generated_at": now,
                "kind": "CLAIM_CREATION", "status": UNSUPPORTED,
                "reasons": ["UNSUPPORTED_MESSAGE_TYPE"],
                "message_identifier": mid,
                "input_sha256": facts_doc.get("input_sha256"),
                "projection": None}
    cash, sec = _claim_amounts(facts)
    proj = {
        **_base(facts_doc, facts),
        "related_settlement_instruction_id": _val(
            facts, "/RltdSttlmInstrDtls/RltdSttlmInstrId"),
        "related_settlement_quantity": _val(
            facts, "/RltdSttlmInstrDtls/RltdSttlmQty/Unit"),
        "transfer_of_proceeds": _val(
            facts, "/RltdSttlmInstrDtls/TrfOfPrcdsTpInd"),
        "market_claim_type": _val(facts, "/MktClmTp"),
        "option_number": _val(facts, "/MktClmDtls/OptnNb"),
        "option_type": _val(facts, "/MktClmDtls/OptnTp/Cd"),
        "cash_movements": cash,
        "securities_movements": sec,
        "delivering_party": _val(facts, "/DlvrgSttlmPties"),
        "receiving_party": _val(facts, "/RcvgSttlmPties"),
        "provenance": _prov(facts, "/TxRef/AcctSvcrTxId")
        + _prov(facts, "/RltdSttlmInstrDtls/RltdSttlmInstrId")
        + _prov(facts, "/MktClmTp"),
    }
    return {"schema": MESSAGE_SCHEMA, "generated_at": now,
            "kind": "CLAIM_CREATION", "status": "PROJECTED",
            "reasons": [], "message_identifier": mid,
            "input_sha256": facts_doc.get("input_sha256"),
            "projection": proj}


def project_claim_status(facts_doc: dict,
                         now: str | None = None) -> dict:
    """seev.052 facts -> status event normalizado."""
    mid = facts_doc.get("message_identifier")
    facts = _doc_facts(facts_doc)
    if mid not in SUPPORTED_052:
        return {"schema": MESSAGE_SCHEMA, "generated_at": now,
                "kind": "CLAIM_STATUS", "status": UNSUPPORTED,
                "reasons": ["UNSUPPORTED_MESSAGE_TYPE"],
                "message_identifier": mid,
                "input_sha256": facts_doc.get("input_sha256"),
                "projection": None}
    tag, internal = _choice(facts, "/MktClmPrcgSts", STATUS_052)
    proj = {
        **_base(facts_doc, facts),
        "status_choice": tag,
        "internal_status": internal,
        "status_reason": _val(facts, "/Rsn/Cd"),
        "provenance": _prov(facts, "/MktClmCreId/Id"),
    }
    reasons = [] if tag else ["STATUS_CHOICE_ABSENT"]
    if internal == "PROPRIETARY":
        reasons.append("PROPRIETARY_STATUS_NOT_MAPPED")
    if internal == "CONFLICTING_CHOICE":
        reasons.append("CONFLICTING_STATUS_CHOICE")
    return {"schema": MESSAGE_SCHEMA, "generated_at": now,
            "kind": "CLAIM_STATUS", "status": "PROJECTED",
            "reasons": reasons, "message_identifier": mid,
            "input_sha256": facts_doc.get("input_sha256"),
            "projection": proj}


def project_claim_cancellation(facts_doc: dict,
                               now: str | None = None) -> dict:
    """seev.051/.053 facts -> cancel intent / outcome."""
    mid = facts_doc.get("message_identifier")
    facts = _doc_facts(facts_doc)
    if mid in SUPPORTED_051:
        proj = {
            **_base(facts_doc, facts),
            "kind": "CANCELLATION_REQUEST",
            "provenance": _prov(facts, "/MktClmCreId/Id"),
        }
        return {"schema": MESSAGE_SCHEMA, "generated_at": now,
                "kind": "CANCELLATION_REQUEST",
                "status": "PROJECTED", "reasons": [],
                "message_identifier": mid,
                "input_sha256": facts_doc.get("input_sha256"),
                "projection": proj}
    if mid in SUPPORTED_053:
        tag, internal = _choice(facts, "/MktClmCxlReqSts",
                                STATUS_053)
        proj = {
            **_base(facts_doc, facts),
            "status_choice": tag,
            "internal_status": internal,
            "provenance": _prov(facts, "/MktClmCxlReqId/Id"),
        }
        reasons = [] if tag else ["STATUS_CHOICE_ABSENT"]
        if internal == "PROPRIETARY":
            reasons.append("PROPRIETARY_STATUS_NOT_MAPPED")
        if internal == "CONFLICTING_CHOICE":
            reasons.append("CONFLICTING_STATUS_CHOICE")
        return {"schema": MESSAGE_SCHEMA, "generated_at": now,
                "kind": "CANCELLATION_STATUS",
                "status": "PROJECTED", "reasons": reasons,
                "message_identifier": mid,
                "input_sha256": facts_doc.get("input_sha256"),
                "projection": proj}
    return {"schema": MESSAGE_SCHEMA, "generated_at": now,
            "kind": "CANCELLATION", "status": UNSUPPORTED,
            "reasons": ["UNSUPPORTED_MESSAGE_TYPE"],
            "message_identifier": mid,
            "input_sha256": facts_doc.get("input_sha256"),
            "projection": None}


def projection_refs(projection: dict | None) -> set[str]:
    """Referencias explicitas que una proyeccion puede ligar."""
    if not projection:
        return set()
    refs = set()
    r = projection.get("references") or {}
    for k in ("account_servicer_tx_id",
              "market_infrastructure_tx_id", "processor_tx_id",
              "claim_creation_id", "cancellation_request_id"):
        if r.get(k):
            refs.add(r[k])
    if projection.get("related_settlement_instruction_id"):
        refs.add(projection["related_settlement_instruction_id"])
    return refs


def bind_claim(projection: dict, claims_doc: dict) -> dict:
    """Liga la proyeccion a UN claim por referencia explicita."""
    refs = projection_refs(projection)
    candidates = []
    for claim in claims_doc.get("claims") or []:
        claim_refs = set(claim.get("binding_references") or [])
        claim_refs.add(claim.get("claim_id"))
        hit = refs & {r for r in claim_refs if r}
        if hit:
            candidates.append((claim.get("claim_id"),
                               sorted(hit)))
    if len(candidates) == 1:
        cid, hit = candidates[0]
        return {"binding_status": BOUND, "claim_id": cid,
                "matched_references": hit}
    if len(candidates) > 1:
        return {"binding_status": AMBIGUOUS, "claim_id": None,
                "candidates": sorted(c[0] for c in candidates),
                "matched_references": sorted(
                    {r for _, h in candidates for r in h})}
    return {"binding_status": NO_MATCH, "claim_id": None,
            "matched_references": []}
