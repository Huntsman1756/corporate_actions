"""P13.6/P13.7/P13.8 — cash account observation.

CA_ES_SWIFT_MT_FACTS_V1 / CA_ES_SWIFT_MX_FACTS_V1
    -> CA_ES_CASH_ACCOUNT_OBSERVATION_V1

Observacion transport-neutral de un extracto/notificacion de
cuenta. NO es un cash movement: el binding a corporate action es
una capa posterior explicita (custody_bind.py) y solo emite
CA_ES_CASH_MOVEMENTS_V2 cuando la evidencia lo sostiene.

Reglas (docs/p13/p136-cash-observation.md):

- se preserva lo que el reporte prueba: entry refs, fechas
  booking/value, D/C, importe+moneda, narrativa como evidencia
  acotada (field 86 nunca se interpreta sin profile);
- credit != cobro de corporate action; debit != pago;
- fechas: value_date/booking_date EXPLICIT; entry_date de MT940
  (MMDD sin año) -> booking_date DERIVED_BY_DEFINITION con la
  regla registrada (mismo año que value_date);
- reversal explicito (RvslInd, mark RC/RD) viaja como reversal.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

OBS_SCHEMA = "CA_ES_CASH_ACCOUNT_OBSERVATION_V1"

CAMT053 = "camt.053.001.13"
CAMT054 = "camt.054.001.13"
CAMT_SUPPORTED = {CAMT053, CAMT054}
MT940 = "MT940"
MT950 = "MT950"
MT_SUPPORTED = {MT940, MT950}

NARRATIVE_MAX = 280  # field 86 evidencia acotada

CDT_TO_DIRECTION = {"CRDT": "CREDIT", "DBIT": "DEBIT"}
ENTRY_STATUS = {"BOOK": "BOOKED", "PDNG": "PENDING", "INFO": "INFO"}
DC_MARK = {
    "C": ("CREDIT", False), "D": ("DEBIT", False),
    "RC": ("CREDIT", True), "RD": ("DEBIT", True),
    "EC": ("CREDIT", False), "ED": ("DEBIT", False),
}


def _prov(fact):
    return {
        "source_tag": fact.get("source_tag"),
        "model_path": fact.get("model_path"),
        "occurrence": fact.get("occurrence"),
        "evidence_locator": fact.get("evidence_locator"),
        "raw": fact.get("value"),
    }


def _tag_index(fact):
    loc = fact.get("evidence_locator") or ""
    m = re.search(r"block4\.tag\[(\d+)\]", loc)
    return int(m.group(1)) if m else None


def _locator_group(fact, element):
    loc = fact.get("evidence_locator") or ""
    m = re.search(re.escape(element) + r"\[(\d+)\]", loc)
    return int(m.group(1)) if m else None


def _dec(raw):
    if raw is None:
        return None
    try:
        d = Decimal(str(raw).replace(",", ".").rstrip("."))
        return d if d.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _fmt(d):
    return format(d, "f") if d is not None else None


def _iso_date(raw):
    if raw and len(str(raw)) == 8 and str(raw).isdigit():
        s = str(raw)
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return raw


def _mt_date(raw):
    """YYMMDD -> YYYY-MM-DD. Siglo por proximidad (regla MT)."""
    if raw and len(str(raw)) == 6 and str(raw).isdigit():
        s = str(raw)
        return f"20{s[:2]}-{s[2:4]}-{s[4:]}"
    return raw


def _single(values):
    unique = {v for v in values if v is not None}
    return next(iter(unique)) if len(unique) == 1 else None


def _facts_at(facts, suffix):
    return [f for f in facts
            if (f.get("model_path") or "").endswith(suffix)]


def _find_label(facts, tag, label):
    return [f for f in facts
            if f.get("source_tag") == tag
            and (f.get("field_path") or "").endswith("." + label)]


def cash_observation(facts_doc: dict,
                     now: str | None = None) -> dict:
    """facts -> CA_ES_CASH_ACCOUNT_OBSERVATION_V1. Pura/read-only."""
    mid = facts_doc.get("message_identifier")
    base = {
        "schema": OBS_SCHEMA,
        "generated_at": now or facts_doc.get("generated_at"),
        "source_standard": facts_doc.get("standard_family"),
        "source_message_identifier": mid,
        "input_sha256": facts_doc.get("input_sha256"),
        "library": facts_doc.get("library"),
        "library_version": facts_doc.get("library_version"),
        "statement_reference": None,
        "account_id_raw": None,
        "entries": [],
        "balances": [],
        "parse_status": "OK",
        "reasons": [],
        "provenance": [],
    }
    if facts_doc.get("parse_status") not in ("OK", "PARSE_OK"):
        return {**base, "parse_status": "PARSE_ERROR",
                "reasons": ["SOURCE_PARSE_FAILED"]}
    if mid in MT_SUPPORTED:
        return _mt_statement(facts_doc, base, mt=mid)
    if mid in CAMT_SUPPORTED:
        return _camt(facts_doc, base)
    return {**base, "parse_status": "UNSUPPORTED",
            "reasons": ["UNSUPPORTED_MESSAGE_TYPE"]}


# ------------------------------------------------------------------
# MT940 / MT950

def _mt_statement(facts_doc, base, mt):
    facts = facts_doc.get("facts") or []
    reasons = list(base["reasons"])

    ref = _single(f.get("value") for f in _find_label(facts, "20",
                                                    "reference"))
    account = _single(f.get("value") for f in _find_label(facts, "25",
                                                        "account"))
    stmt_no = _single(f.get("value") for f in
                      _find_label(facts, "28C", "statement number"))
    seq_no = _single(f.get("value") for f in
                     _find_label(facts, "28C", "sequence number"))
    if ref is None and stmt_no is not None:
        ref = stmt_no + ("/" + seq_no if seq_no else "")
    if account is None:
        reasons.append("MISSING_ACCOUNT")

    # currency del statement via 60a/62a (consistente en todo el doc)
    currency = _single(
        f.get("value") for tag in ("60F", "60M", "62F", "62M")
        for f in _find_label(facts, tag, "currency"))

    # orden documental: 61[k] y 86[k] por tag index
    entries61 = sorted({f.get("occurrence", 0)
                        for f in _find_label(facts, "61",
                                             "value date")})
    first_tag_of_occ = {}
    for f in facts:
        if f.get("source_tag") == "61":
            occ = f.get("occurrence", 0)
            ti = _tag_index(f)
            if ti is not None:
                first_tag_of_occ[occ] = min(
                    ti, first_tag_of_occ.get(occ, ti))
    narratives = [
        (f.get("occurrence", 0), _tag_index(f), f.get("value"))
        for f in _find_label(facts, "86", "narrative")]

    entries = []
    for occ in entries61:
        mine = [f for f in facts
                if f.get("source_tag") == "61"
                and f.get("occurrence") == occ]
        def _lbl(label):
            return _single(f.get("value") for f in mine
                           if (f.get("field_path") or "")
                           .endswith("." + label))

        value_date = _mt_date(_lbl("value date"))
        entry_raw = _lbl("entry date")
        mark = _lbl("debit/credit mark") or ""
        direction, reversal = DC_MARK.get(
            mark.upper(), (None, False))
        amount = _dec(_lbl("amount"))
        booking = None
        booking_rule = None
        if entry_raw and value_date and len(str(entry_raw)) == 4:
            booking = value_date[:5] + str(entry_raw)[:2] + "-" + str(
                entry_raw)[2:]
            booking_rule = "DERIVED_BY_DEFINITION:SAME_YEAR_AS_VALUE_DATE"

        tag_i = first_tag_of_occ.get(occ)
        # 86 inmediatamente posterior a ESTE 61 y antes del siguiente
        next_tag = min((t for o, t in first_tag_of_occ.items()
                        if o > occ and t is not None),
                       default=None)
        narr = [v for _, ti, v in narratives
                if ti is not None and tag_i is not None
                and ti > tag_i
                and (next_tag is None or ti < next_tag)]
        entry = {
            "entry_id": _lbl("reference for the account owner"),
            "debit_credit": direction,
            "reversal": reversal,
            "status": "BOOKED",
            "amount": _fmt(amount),
            "amount_raw": _lbl("amount"),
            "currency": currency,
            "booking_date": booking,
            "booking_date_rule": booking_rule,
            "value_date": value_date,
            "transaction_type": (
                (_lbl("transaction type") or "")
                + (_lbl("identification code") or "")) or None,
            "customer_reference": _lbl(
                "reference for the account owner"),
            "account_servicer_reference": _lbl(
                "reference of the account servicing institution"),
            "supplementary_details": _lbl("supplementary details"),
            "narrative": [n[:NARRATIVE_MAX] for n in narr if n],
            "transaction_reference": None,
            "structured_details": {},
            "provenance": [_prov(f) for f in mine],
        }
        entries.append(entry)

    if not entries:
        reasons.append("NO_ENTRIES")

    balances = []
    for tag in ("60F", "60M", "62F", "62M", "64", "65"):
        for occ in sorted({f.get("occurrence", 0)
                           for f in _find_label(facts, tag, "date")}):
            mine = [f for f in facts if f.get("source_tag") == tag
                    and f.get("occurrence") == occ]
            def _lbl(label):
                return _single(f.get("value") for f in mine
                               if (f.get("field_path") or "")
                               .endswith("." + label))
            balances.append({
                "tag": tag,
                "mark": _lbl("d/c mark"),
                "date": _mt_date(_lbl("date")),
                "currency": _lbl("currency"),
                "amount": _fmt(_dec(_lbl("amount"))),
            })

    return {
        **base,
        "statement_reference": ref,
        "account_id_raw": account,
        "entries": entries,
        "balances": balances,
        "reasons": reasons,
        "provenance": [_prov(f) for f in (
            _find_label(facts, "20", "reference")
            + _find_label(facts, "25", "account")
            + _find_label(facts, "28C", "statement number"))],
    }


# ------------------------------------------------------------------
# camt.053 / camt.054

def _camt(facts_doc, base):
    facts = facts_doc.get("facts") or []
    reasons = list(base["reasons"])

    ref = _single(f.get("value") for f in (
        _facts_at(facts, "/Ntfctn/Id") or _facts_at(facts, "/Stmt/Id")))
    account = _single(
        f.get("value") for f in
        (_facts_at(facts, "/Acct/Id/IBAN")
         or _facts_at(facts, "/Acct/Id/Othr/Id")))
    if account is None:
        reasons.append("MISSING_ACCOUNT")

    entries = []
    groups = sorted({g for g in
                     (_locator_group(f, "Ntry") for f in facts)
                     if g is not None})
    for idx in groups:
        mine = [f for f in facts
                if _locator_group(f, "Ntry") == idx]

        def _one(suffix):
            return _single(f.get("value") for f in mine
                           if (f.get("model_path") or "")
                           .endswith(suffix))

        amount = _dec(_one("/Ntry/Amt"))
        ccy = _single(f.get("value") for f in mine
                      if (f.get("model_path") or "")
                      .endswith("/Ntry/Amt/@Ccy"))
        status_raw = _one("/Ntry/Sts/Cd")
        reversal = str(_one("/Ntry/RvslInd")).lower() == "true"
        refs = {}
        for f in mine:
            path = f.get("model_path") or ""
            m = re.search(r"/Refs/([A-Za-z0-9]+)$", path)
            if m and f.get("value"):
                refs[m.group(1)] = f["value"]
        entries.append({
            "entry_id": _one("/Ntry/NtryRef"),
            "debit_credit": CDT_TO_DIRECTION.get(_one("/Ntry/CdtDbtInd")),
            "reversal": reversal,
            "status": ENTRY_STATUS.get(status_raw, status_raw),
            "amount": _fmt(amount),
            "amount_raw": _one("/Ntry/Amt"),
            "currency": ccy,
            "booking_date": (
                _one("/Ntry/BookgDt/Dt")
                or _one("/Ntry/BookgDt/DtTm")),
            "booking_date_rule": "EXPLICIT" if (
                _one("/Ntry/BookgDt/Dt")
                or _one("/Ntry/BookgDt/DtTm")) else None,
            "value_date": (
                _one("/Ntry/ValDt/Dt")
                or _one("/Ntry/ValDt/DtTm")),
            "transaction_type": _one("/BkTxCd/Domn/Cd"),
            "customer_reference": refs.get("EndToEndId"),
            "account_servicer_reference": (
                _one("/Ntry/AcctSvcrRef") or refs.get("AcctSvcrRef")),
            "supplementary_details": _one("/Ntry/AddtlNtryInf"),
            "narrative": [],
            "transaction_reference": refs.get("TxId"),
            "structured_details": {"refs": refs} if refs else {},
            "provenance": [_prov(f) for f in mine],
        })

    if not entries:
        reasons.append("NO_ENTRIES")

    balances = []
    groups = sorted({g for g in
                     (_locator_group(f, "Bal") for f in facts)
                     if g is not None})
    for idx in groups:
        mine = [f for f in facts
                if _locator_group(f, "Bal") == idx]

        def _one(suffix):
            return _single(f.get("value") for f in mine
                           if (f.get("model_path") or "")
                           .endswith(suffix))
        balances.append({
            "tag": _one("/Bal/Tp/CdOrPrtry/Cd"),
            "mark": _one("/Bal/CdtDbtInd"),
            "date": _one("/Bal/Dt/Dt"),
            "currency": _single(f.get("value") for f in mine
                              if (f.get("model_path") or "")
                              .endswith("/Bal/Amt/@Ccy")),
            "amount": _fmt(_dec(_one("/Bal/Amt"))),
        })

    return {
        **base,
        "statement_reference": ref,
        "account_id_raw": account,
        "entries": entries,
        "balances": balances,
        "reasons": reasons,
        "provenance": [_prov(f) for f in (
            _facts_at(facts, "/Ntfctn/Id")
            + _facts_at(facts, "/Stmt/Id")
            + _facts_at(facts, "/Acct/Id/IBAN"))],
    }
