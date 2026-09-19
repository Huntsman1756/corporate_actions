"""P17.1 — facts MT54x / sese.023-025 -> observaciones de
settlement normalizadas.

CA_ES_SWIFT_MT_FACTS_V1 (MT540-548) y CA_ES_SWIFT_MX_FACTS_V1
(sese.023/024/025, versiones del pin SRU2025) -> items
CA_ES_SETTLEMENT_OBSERVATION_V1.

Invariantes:

- INSTRUCTION != STATUS != CONFIRMATION (kind distinto).
- intended settlement date != actual settlement date.
- refs nunca derivadas de contenido: solo campos de referencia
  explicitos (SEME/RELA/TRRF/COMM/CORP/POOL/MITI/PCTI/PREV,
  AcctSvcr/AcctOwnr/MktInfrstrctr/CtrPty/PrcrTxId, CmonId,
  PoolId, TradId, UnqTxIdr, CorpActnEvtId, linkages).
- fechas solo de campos de fecha explicitos; nunca inferidas.
- una observacion = un mensaje; dedup posterior en el ledger.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

OBSERVATION_SCHEMA = "CA_ES_SETTLEMENT_OBSERVATION_V1"

INSTRUCTION = "INSTRUCTION"
STATUS = "STATUS"
CONFIRMATION = "CONFIRMATION"
UNSUPPORTED = "UNSUPPORTED"

MT_INSTRUCTIONS = {"MT540", "MT541", "MT542", "MT543"}
MT_CONFIRMATIONS = {"MT544", "MT545", "MT546", "MT547"}
MT_STATUS = {"MT548"}

# conjuntos publicos para el filtro de inbox (P7/CLI)
MT_SETTLEMENT_IDS = MT_INSTRUCTIONS | MT_CONFIRMATIONS | MT_STATUS
MX_SETTLEMENT_PREFIXES = ("sese.023.", "sese.024.", "sese.025.")

_SESE_023 = re.compile(r"^sese\.023\.")
_SESE_024 = re.compile(r"^sese\.024\.")
_SESE_025 = re.compile(r"^sese\.025\.")

# 20C::QUAL -> ref field interno
_MT_REFS = {
    "SEME": "acct_svcr_tx_id",
    "RELA": "related_tx_id",
    "TRRF": "trade_id",
    "COMM": "common_id",
    "CORP": "corp_actn_evt_id",
    "POOL": "pool_id",
    "MITI": "mkt_infrstrctr_tx_id",
    "CTRT": "ctr_pty_mkt_infrstrctr_tx_id",
    "PCTI": "prcr_tx_id",
    "PREV": "previous_tx_id",
    "PREC": "previous_tx_id",
    "CLTR": "client_collateral_tx_id",
    "CLCI": "client_collateral_instr_id",
    "TTCO": "triparty_collateral_tx_id",
    "COLR": "collateral_id",
    "CERT": "certification_id",
    "PACK": "package_id",
    "TRCA": "triparty_agent_tx_id",
    "SECI": "securities_instruction_id",
}

# path suffix MX -> ref field interno
_MX_REFS = {
    "/TxId/AcctOwnrTxId": "acct_ownr_tx_id",
    "/TxId/AcctSvcrTxId": "acct_svcr_tx_id",
    "/TxId/MktInfrstrctrTxId": "mkt_infrstrctr_tx_id",
    "/TxId/CtrPtyMktInfrstrctrTxId": "ctr_pty_mkt_infrstrctr_tx_id",
    "/TxId/PrcrTxId": "prcr_tx_id",
    "/TxId/CmonId": "common_id",
    "/TxId/NetgSvcPrvdrId": "netg_svc_provider_id",
    "/TxIdDtls/AcctOwnrTxId": "acct_ownr_tx_id",
    "/TxIdDtls/AcctSvcrTxId": "acct_svcr_tx_id",
    "/TxIdDtls/MktInfrstrctrTxId": "mkt_infrstrctr_tx_id",
    "/TxIdDtls/CtrPtyMktInfrstrctrTxId": "ctr_pty_mkt_infrstrctr_tx_id",
    "/TxIdDtls/PrcrTxId": "prcr_tx_id",
    "/TxIdDtls/CmonId": "common_id",
    "/TxIdDtls/PoolId": "pool_id",
    "/TxIdDtls/CorpActnEvtId": "corp_actn_evt_id",
    "/TxIdDtls/NonceId": "nonce_id",
    "/TxIdDtls/NetgSvcPrvdrId": "netg_svc_provider_id",
    "/TradDtls/TradId": "trade_id",
    "/TradDtls/UnqTxIdr": "unique_tx_idr",
    "/TradDtls/CollTxId": "collateral_tx_id",
    # sese.024 TxDtls (TransactionDetails166): refs directos
    "/TxDtls/TradId": "trade_id",
    "/TxDtls/UnqTxIdr": "unique_tx_idr",
    "/TxDtls/PoolId": "pool_id",
    "/TxDtls/CorpActnEvtId": "corp_actn_evt_id",
    "/TxDtls/NonceId": "nonce_id",
    "/SttlmTpAndAddtlParams/CmonId": "common_id",
    "/SttlmTpAndAddtlParams/CorpActnEvtId": "corp_actn_evt_id",
    "/SttlmTpAndAddtlParams/ClntCollInstrId": "client_collateral_instr_id",
    "/SttlmTpAndAddtlParams/ClntTrptyCollTxId": "client_collateral_tx_id",
    "/SttlmTpAndAddtlParams/TrptyAgtSvcPrvdrCollTxId": "triparty_agent_tx_id",
    "/Lnkgs/SctiesSttlmTxId": "linked_settlement_tx_id",
    "/AddtlParams/CmonId": "common_id",
    "/AddtlParams/CorpActnEvtId": "corp_actn_evt_id",
}
# sese.023: TxId (String) = account servicer tx id
_TXID_LEAF = ("/TxId",)

_PRCG_024 = {
    "AckdAccptd": "ACKNOWLEDGED_ACCEPTED",
    "PdgPrcg": "PENDING_PROCESSING",
    "Rjctd": "REJECTED",
    "Rpr": "REPAIR",
    "Canc": "CANCELLED",
    "PdgCxl": "PENDING_CANCELLATION",
    "CxlReqd": "CANCELLATION_REQUESTED",
    "ModReqd": "MODIFICATION_REQUESTED",
    "Prtry": "PROPRIETARY",
}
_MTCH_024 = {"Mtchd": "MATCHED", "Umtchd": "UNMATCHED",
             "Prtry": "PROPRIETARY"}
_STTLM_024 = {"Pdg": "PENDING", "Flng": "FAILING",
              "Prtry": "PROPRIETARY"}

_MT_IPRC = {
    "PACK": "ACKNOWLEDGED_ACCEPTED", "REPR": "REPAIR",
    "PPRC": "PENDING_PROCESSING", "INSP": "PENDING_PROCESSING",
    "DENR": "REJECTED", "CANC": "CANCELLED",
    "CGEN": "CANCELLED", "PRCX": "CANCELLED",
}
_MT_CPRC = {
    "CAND": "CANCELLED", "CPRC": "PENDING_CANCELLATION",
    "CPCA": "PENDING_CANCELLATION", "PACK":
    "ACKNOWLEDGED_ACCEPTED", "REPR": "REPAIR",
    "CANP": "CANCELLED",
}
_MT_MTCH = {"MACH": "MATCHED", "NMAT": "UNMATCHED"}
_MT_SETT = {"PEND": "PENDING", "PENF": "FAILING"}


def _prov(fact):
    return {
        "source_tag": fact.get("source_tag"),
        "source_qualifier": fact.get("source_qualifier"),
        "model_path": fact.get("model_path"),
        "field_path": fact.get("field_path"),
        "sequence": fact.get("sequence"),
        "occurrence": fact.get("occurrence"),
        "evidence_locator": fact.get("evidence_locator"),
        "raw": fact.get("value"),
    }


def _dec(raw):
    """Lexema SWIFT/ISO -> Decimal; None si no parsea."""
    if raw is None:
        return None
    text = str(raw).strip()
    sign = None
    if text[:1] in ("N", "D"):
        sign, text = text[0], text[1:]
    text = text.replace(",", ".")
    if text.endswith("."):
        text = text[:-1]
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if not value.is_finite():
        return None
    return -value if sign == "N" else value


def _fmt(value):
    return format(value, "f") if value is not None else None


def _iso_date(raw):
    """YYYYMMDD o YYYY-MM-DD -> ISO; else None."""
    if raw is None:
        return None
    t = str(raw).strip()
    m = re.match(r"^(\d{4})(\d{2})(\d{2})", t)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", t)
    return m.group(1) if m else None


def _last_token(raw):
    """'UNIT/1000,' -> '1000,'; 'MACH' -> 'MACH'."""
    if raw is None:
        return None
    return str(raw).strip().rsplit("/", 1)[-1].strip()


def _isin(raw):
    if raw is None:
        return None
    m = re.search(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", str(raw))
    return m.group(0) if m else None


def _mf(facts, suffix):
    return [f for f in facts
            if (f.get("model_path") or "").endswith(suffix)]


def _val(facts, *suffixes):
    for s in suffixes:
        found = _mf(facts, s)
        if found:
            return found[0].get("value"), [_prov(found[0])]
    return None, []


def _vals(facts, *suffixes):
    out, provs = [], []
    for s in suffixes:
        for f in _mf(facts, s):
            out.append(f.get("value"))
            provs.append(_prov(f))
    return out, provs


def _choice(facts, parent_suffix, mapping):
    """Primer hijo-choice presente bajo parent -> internal."""
    found = []
    for f in facts:
        mp = f.get("model_path") or ""
        idx = mp.rfind(parent_suffix + "/")
        if idx < 0:
            continue
        tag = mp[idx + len(parent_suffix) + 1:].split("/", 1)[0]
        if tag in mapping:
            found.append((tag, mapping[tag], _prov(f)))
    if not found:
        return None, None, []
    if len(found) > 1:
        tags = sorted({t for t, _, _ in found})
        return tags[0], "CONFLICTING_CHOICE", [p for _, _, p in found]
    tag, internal, prov = found[0]
    return tag, internal, [prov]


# ------------------------------------------------------------------
# MT540-548
# ------------------------------------------------------------------

def _mt_kind(mid):
    if mid in MT_INSTRUCTIONS:
        return INSTRUCTION
    if mid in MT_CONFIRMATIONS:
        return CONFIRMATION
    if mid in MT_STATUS:
        return STATUS
    return None


def _mt_obs(facts_doc, kind, now):
    facts = [f for f in facts_doc.get("facts") or []
             if f.get("source_tag")]
    prov: list = []

    refs = {}
    ref_provs: dict[str, list] = {}
    for f in facts:
        if f.get("source_tag") != "20C":
            continue
        field = _MT_REFS.get(f.get("source_qualifier"))
        if not field:
            continue
        value = _last_token(f.get("value"))
        if not value:
            continue
        if field in ("trade_id",):
            refs.setdefault(field, [])
            if value not in refs[field]:
                refs[field].append(value)
        else:
            refs.setdefault(field, value)
        ref_provs.setdefault(field, []).append(_prov(f))
    prov.extend(ref_provs.pop("acct_svcr_tx_id", [])[:2])

    # funcion del mensaje
    func = None
    for f in facts:
        if f.get("source_tag") == "23G":
            func = _last_token(f.get("value"))
            prov.append(_prov(f))
            break

    direction = None
    payment_type = None
    for f in facts:
        tag, qual = f.get("source_tag"), f.get("source_qualifier")
        if tag == "22H" and qual == "REDE":
            direction = _last_token(f.get("value"))
        elif tag == "22H" and qual == "PAYM":
            payment_type = _last_token(f.get("value"))
        elif tag == "22F" and qual == "SETR":
            pass  # settlement tx type preservado abajo
    if direction is None:
        mid = facts_doc.get("message_identifier")
        direction = ("RECE" if mid in
                     {"MT540", "MT541", "MT544", "MT545"}
                     else "DELI" if mid in
                     {"MT542", "MT543", "MT546", "MT547"}
                     else None)

    # fechas explicitas
    trade_date = intended = actual = None
    for f in facts:
        if f.get("source_tag") != "98A":
            continue
        qual = f.get("source_qualifier")
        d = _iso_date(_last_token(f.get("value")))
        if qual == "TRAD" and trade_date is None:
            trade_date = d
        elif qual == "SETT":
            if kind == CONFIRMATION:
                if actual is None:
                    actual = d
            elif intended is None:
                intended = d
        elif qual == "ESET" and intended is None:
            intended = d
        prov.append(_prov(f))

    # cantidades (SETT instruida; ESTT settled en confirmaciones)
    instructed_qty = settled_qty = prevsly_qty = remaining_qty = None
    for f in facts:
        if f.get("source_tag") != "36B":
            continue
        qual = f.get("source_qualifier")
        q = _dec(_last_token(f.get("value")))
        if qual in ("SETT", "ESTT"):
            if kind == CONFIRMATION or qual == "ESTT":
                settled_qty = q if settled_qty is None else settled_qty
            else:
                instructed_qty = q if instructed_qty is None else instructed_qty
        elif qual == "PSTA":
            prevsly_qty = q if prevsly_qty is None else prevsly_qty
        elif qual == "RSTT":
            remaining_qty = q if remaining_qty is None else remaining_qty
        prov.append(_prov(f))
    if kind == CONFIRMATION and instructed_qty is None:
        # en confirmaciones 36B::SETT = qty confirmada
        pass

    # importes (19A llega descompuesto por componentes: signo,
    # divisa, importe en facts separados del mismo qualifier)
    settle_amt = settle_ccy = None
    sign = Decimal(1)
    last_occ = None
    for f in facts:
        if f.get("source_tag") != "19A":
            continue
        prov.append(_prov(f))
        if f.get("source_qualifier") not in ("SETT", "ESTT"):
            continue
        occ_key = (f.get("sequence"), f.get("occurrence"))
        if occ_key != last_occ:
            last_occ = occ_key
            sign = Decimal(1)
        raw = str(f.get("value") or "").strip()
        if raw == "N":
            sign = Decimal(-1)
        elif raw == "D":
            sign = Decimal(1)
        elif re.fullmatch(r"[A-Z]{3}", raw):
            if settle_ccy is None:
                settle_ccy = raw
        else:
            amt = _dec(raw)
            if amt is not None and settle_amt is None:
                settle_amt = amt * sign

    account = None
    for f in facts:
        if f.get("source_tag") == "97A" and \
                f.get("source_qualifier") == "SAFE":
            account = _last_token(f.get("value"))
            prov.append(_prov(f))
            break

    isin = None
    for f in facts:
        if f.get("source_tag") == "35B":
            isin = _isin(f.get("value"))
            if isin:
                prov.append(_prov(f))
                break

    statuses = _mt_statuses(facts, prov)
    reasons = _mt_reasons(facts)

    return {
        "message_identifier": facts_doc.get("message_identifier"),
        "kind": kind,
        "function": func,
        "references": refs,
        "direction": direction,
        "payment_type": payment_type,
        "isin": isin,
        "account_id": account,
        "instructed_quantity": _fmt(instructed_qty),
        "settled_quantity": _fmt(settled_qty),
        "previously_settled_quantity": _fmt(prevsly_qty),
        "remaining_quantity": _fmt(remaining_qty),
        "settlement_amount": _fmt(settle_amt),
        "settlement_currency": settle_ccy,
        "trade_date": trade_date,
        "intended_settlement_date": intended,
        "actual_settlement_date": actual,
        "processing_status": statuses.get("processing_status"),
        "matching_status": statuses.get("matching_status"),
        "settlement_status": statuses.get("settlement_status"),
        "reason_codes": reasons,
        "status_semantics": ("CUMULATIVE"
                             if prevsly_qty is not None
                             else "THIS_MESSAGE"),
        "provenance": prov[:8],
        "input_sha256": facts_doc.get("input_sha256"),
    }


def _mt_statuses(facts, prov):
    out = {}
    for f in facts:
        if f.get("source_tag") != "25D":
            continue
        qual = f.get("source_qualifier")
        v = _last_token(f.get("value"))
        if qual == "IPRC" and "processing_status" not in out:
            out["processing_status"] = _MT_IPRC.get(v, v)
        elif qual == "CPRC" and "processing_status" not in out:
            out["processing_status"] = _MT_CPRC.get(v, v)
        elif qual == "MTCH" and "matching_status" not in out:
            out["matching_status"] = _MT_MTCH.get(v, v)
        elif qual == "SETT" and "settlement_status" not in out:
            out["settlement_status"] = _MT_SETT.get(v, v)
        prov.append(_prov(f))
    return out


def _mt_reasons(facts):
    out = []
    for f in facts:
        if f.get("source_tag") == "24B":
            v = _last_token(f.get("value"))
            if v and v not in out:
                out.append(v)
    return out


# ------------------------------------------------------------------
# sese.023/024/025
# ------------------------------------------------------------------

def _mx_kind(mid):
    if _SESE_023.match(mid or ""):
        return INSTRUCTION
    if _SESE_024.match(mid or ""):
        return STATUS
    if _SESE_025.match(mid or ""):
        return CONFIRMATION
    return None


def _mx_under(facts, suffix):
    """Facts cuyo model_path contiene suffix como segmento de
    path (boundary-aware; tolera anidamiento variable entre
    versiones del pin)."""
    out = []
    for f in facts:
        mp = f.get("model_path") or ""
        idx = mp.find(suffix)
        if idx < 0:
            continue
        tail = mp[idx + len(suffix):]
        if tail and not tail.startswith("/"):
            continue
        out.append(f)
    return out


def _mx_date(facts, *suffixes):
    """Date choice -> ISO (cualquier leaf de fecha bajo el
    segmento)."""
    for s in suffixes:
        for f in _mx_under(facts, s):
            d = _iso_date(f.get("value"))
            if d:
                return d
    return None


_QTY_LEAVES = {"Unit", "FaceAmt", "AmtsdVal", "DgtlTknUnit"}


def _mx_qty(facts, *suffixes):
    """Quantity choice -> Decimal (leaf de cantidad bajo el
    segmento, en cualquier profundidad)."""
    for s in suffixes:
        for f in _mx_under(facts, s):
            mp = f.get("model_path") or ""
            leaf = mp.rsplit("/", 1)[-1].lstrip("@")
            if leaf in _QTY_LEAVES:
                d = _dec(f.get("value"))
                if d is not None:
                    return d
    return None


def _mx_obs(facts_doc, kind, now):
    facts = [f for f in facts_doc.get("facts") or []
             if (f.get("model_path") or "").startswith("/Document/")]
    prov: list = []

    refs = {}
    for suffix, field in _MX_REFS.items():
        for f in _mf(facts, suffix):
            value = f.get("value")
            if not value:
                continue
            if field == "trade_id":
                refs.setdefault(field, [])
                if value not in refs[field]:
                    refs[field].append(value)
            else:
                refs.setdefault(field, value)
            prov.append(_prov(f))
    if kind == INSTRUCTION:
        # sese.023 TxId es String plano (account servicer tx id)
        for f in _mf(facts, "/SctiesSttlmTxInstr/TxId"):
            if f.get("value"):
                refs.setdefault("acct_svcr_tx_id", f["value"])
                prov.append(_prov(f))

    direction, _ = _val(facts, "/SctiesMvmntTp")
    payment_type, _ = _val(facts, "/SttlmTpAndAddtlParams/Pmt",
                           "/TxIdDtls/Pmt", "/TxDtls/Pmt",
                           "/SttlmParams/Pmt")
    isin, ip = _val(facts, "/FinInstrmId/ISIN")
    prov.extend(ip[:1])
    account, ap = _val(facts, "/QtyAndAcctDtls/SfkpgAcct/Id",
                       "/SfkpgAcct/Id")
    prov.extend(ap[:1])

    if kind == INSTRUCTION:
        instructed = _mx_qty(facts, "/QtyAndAcctDtls/SttlmQty")
        settled = prevsly = remaining = None
        intended = _mx_date(facts, "/TradDtls/SttlmDt")
        actual = None
        trade_date = _mx_date(facts, "/TradDtls/TradDt")
        prcg = mtch = sttlm = None
    elif kind == STATUS:
        # TransactionDetails166: SttlmQty (instruida) directo;
        # versiones que llevan QtyAndAcctDtls tambien cubiertas
        instructed = _mx_qty(facts, "/TxDtls/SttlmQty")
        settled = _mx_qty(facts, "/TxDtls/QtyAndAcctDtls/SttldQty",
                          "/TxDtls/SttldQty")
        prevsly = _mx_qty(
            facts, "/TxDtls/QtyAndAcctDtls/PrevslySttldQty",
            "/TxDtls/PrevslySttldQty")
        remaining = _mx_qty(
            facts, "/TxDtls/QtyAndAcctDtls/RmngToBeSttldQty",
            "/TxDtls/RmngToBeSttldQty")
        intended = _mx_date(facts, "/TxDtls/XpctdSttlmDt",
                            "/TxDtls/SttlmDt",
                            "/TxDtls/TradDtls/SttlmDt")
        actual = _mx_date(facts, "/TxDtls/FctvSttlmDt",
                          "/TxDtls/TradDtls/FctvSttlmDt")
        trade_date = _mx_date(facts, "/TxDtls/TradDt",
                              "/TxDtls/TradDtls/TradDt")
        _, prcg, _ = _choice(facts, "/PrcgSts", _PRCG_024)
        _, mtch, _ = _choice(facts, "/MtchgSts", _MTCH_024)
        if mtch is None:
            _, mtch, _ = _choice(facts, "/IfrdMtchgSts", _MTCH_024)
        _, sttlm, _ = _choice(facts, "/SttlmSts", _STTLM_024)
    else:
        instructed = None
        settled = _mx_qty(facts, "/QtyAndAcctDtls/SttldQty")
        prevsly = _mx_qty(
            facts, "/QtyAndAcctDtls/PrevslySttldQty")
        remaining = _mx_qty(
            facts, "/QtyAndAcctDtls/RmngToBeSttldQty")
        intended = _mx_date(facts, "/TradDtls/SttlmDt")
        actual = _mx_date(facts, "/TradDtls/FctvSttlmDt")
        trade_date = _mx_date(facts, "/TradDtls/TradDt")
        prcg = mtch = sttlm = None

    amt, ap2 = _val(facts, "/SttlmAmt/Amt", "/SttldAmt/Amt")
    ccy, _ = _val(facts, "/SttlmAmt/Amt/@Ccy", "/SttldAmt/Amt/@Ccy")
    prov.extend(ap2[:1])

    return {
        "message_identifier": facts_doc.get("message_identifier"),
        "kind": kind,
        "function": None,
        "references": refs,
        "direction": direction,
        "payment_type": payment_type,
        "isin": isin,
        "account_id": account,
        "instructed_quantity": _fmt(instructed),
        "settled_quantity": _fmt(settled),
        "previously_settled_quantity": _fmt(prevsly),
        "remaining_quantity": _fmt(remaining),
        "settlement_amount": _fmt(_dec(amt)),
        "settlement_currency": ccy,
        "trade_date": trade_date,
        "intended_settlement_date": intended,
        "actual_settlement_date": actual,
        "processing_status": prcg,
        "matching_status": mtch,
        "settlement_status": sttlm,
        "reason_codes": [],
        "status_semantics": ("CUMULATIVE"
                             if prevsly is not None
                             else "THIS_MESSAGE"),
        "provenance": prov[:8],
        "input_sha256": facts_doc.get("input_sha256"),
    }


# ------------------------------------------------------------------
# doc
# ------------------------------------------------------------------

def observe_message(facts_doc: dict, now: str | None = None) -> dict:
    """Un facts doc -> una observacion normalizada (o UNSUPPORTED)."""
    mid = facts_doc.get("message_identifier")
    kind = _mt_kind(mid) or _mx_kind(mid)
    if kind is None:
        return {"schema": OBSERVATION_SCHEMA,
                "generated_at": now,
                "status": UNSUPPORTED,
                "reasons": ["UNSUPPORTED_MESSAGE_TYPE"],
                "message_identifier": mid,
                "input_sha256": facts_doc.get("input_sha256"),
                "observation": None}
    obs = (_mt_obs if _mt_kind(mid) else _mx_obs)(
        facts_doc, kind, now)
    return {"schema": OBSERVATION_SCHEMA,
            "generated_at": now,
            "status": "PROJECTED",
            "reasons": [],
            "message_identifier": mid,
            "input_sha256": facts_doc.get("input_sha256"),
            "observation": obs}


def observations_doc(facts_docs: list[dict],
                     now: str | None = None) -> dict:
    """facts docs -> CA_ES_SETTLEMENT_OBSERVATION_V1."""
    items, unsupported = [], []
    for fd in facts_docs or []:
        p = observe_message(fd, now=now)
        if p.get("status") == UNSUPPORTED:
            unsupported.append(p.get("message_identifier"))
            continue
        p["observation"]["input_sha256"] = p.get("input_sha256")
        items.append(p["observation"])
    return {"schema": OBSERVATION_SCHEMA,
            "generated_at": now,
            "items": items,
            "summary": {
                "observed": len(items),
                "instructions": sum(1 for i in items
                                    if i["kind"] == INSTRUCTION),
                "status_advices": sum(1 for i in items
                                      if i["kind"] == STATUS),
                "confirmations": sum(1 for i in items
                                     if i["kind"] == CONFIRMATION),
                "unsupported": sorted(set(unsupported)),
            }}
