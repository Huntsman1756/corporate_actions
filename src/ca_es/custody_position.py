"""P13.1/P13.2/P13.3 — custody position observation.

CA_ES_SWIFT_MT_FACTS_V1 / CA_ES_SWIFT_MX_FACTS_V1
    -> CA_ES_POSITION_OBSERVATION_V1

Transport facts en, observacion de posiciones out. NO es un
snapshot: la completitud de paginas/statements se decide en
custody_snapshot.py; la proyeccion a CA_ES_POSITIONS_V1 solo
ocurre sobre snapshots COMPLETE.

Reglas duras (docs/p13/p131-position-observation.md):

- nada se infiere: account_id_raw viaja verbatim; el mapping a
  account_id es configuracion explicita (profile), nunca aqui;
- quantity canonica = balance AGGR si existe y es unico; jamas se
  agregan sub-balances ni se elige "el mas grande";
- occurrence vincula 35B[N] con sus balances 93B/93C[N] (MT535) y
  evidence_locator indexa BalForAcct[k] (semt.002);
- ISIN ausente -> position con isin=None + reason; nunca nombre.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

OBS_SCHEMA = "CA_ES_POSITION_OBSERVATION_V1"

MT535 = "MT535"
SEMT002_PREFIX = "semt.002."
SEMT002_SUPPORTED = {"semt.002.001.12", "semt.002.002.11"}

# qualifiers de balance 93B/C -> availability semantica explicita.
# AGGR es el total de cabecera; el resto son sub-posiciones.
BALANCE_QUALIFIERS = {
    "AGGR": "AGGREGATE",
    "AVAI": "AVAILABLE",
    "NAVAI": "NOT_AVAILABLE",
    "NAVI": "NOT_AVAILABLE",
    "BLOK": "BLOCKED",
    "PLED": "PLEDGED",
    "LOAN": "ON_LOAN",
    "BORR": "BORROWED",
    "COLI": "COLLATERAL_IN",
    "COLO": "COLLATERAL_OUT",
    "PEND": "PENDING",
    "PDEN": "PENDING",
}

QUANTITY_TYPES = {"UNIT", "FAMT", "AMOR"}


def _prov(fact):
    return {
        "source_tag": fact.get("source_tag"),
        "source_qualifier": fact.get("source_qualifier"),
        "model_path": fact.get("model_path"),
        "sequence": fact.get("sequence"),
        "occurrence": fact.get("occurrence"),
        "evidence_locator": fact.get("evidence_locator"),
        "raw": fact.get("value"),
    }


def _tag_index(fact):
    """block4.tag[N] -> N (orden del mensaje, para asociar 86/61)."""
    loc = fact.get("evidence_locator") or ""
    m = re.search(r"block4\.tag\[(\d+)\]", loc)
    return int(m.group(1)) if m else None


def _locator_group(fact, element):
    """.../ELEMENT[k]/... -> k (agrupa filas repetidas del modelo)."""
    loc = fact.get("evidence_locator") or ""
    m = re.search(re.escape(element) + r"\[(\d+)\]", loc)
    return int(m.group(1)) if m else None


def _swift_amount(raw):
    """'12500,' / '1562,50' -> Decimal; signo 'N'/'D' si lo hubiera."""
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
        amount = Decimal(text)
    except InvalidOperation:
        return None
    if not amount.is_finite():
        return None
    return -amount if sign == "N" else amount


def _fmt(amount):
    return format(amount, "f") if amount is not None else None


def _iso_date(raw):
    """YYYYMMDD -> YYYY-MM-DD (EXPLICIT). Otro formato -> verbatim."""
    if raw and len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw


def _find(facts, tag=None, qualifier=None, label=None, seq=None):
    return [
        f for f in facts
        if (tag is None or f.get("source_tag") == tag)
        and (qualifier is None or f.get("source_qualifier") == qualifier)
        and (seq is None or f.get("sequence") == seq)
        and (label is None
             or (f.get("field_path") or "").endswith("." + label))
    ]


def _facts_at(facts, model_path_suffix):
    return [f for f in facts
            if (f.get("model_path") or "").endswith(model_path_suffix)]


def _single(values):
    unique = {v for v in values if v is not None}
    return next(iter(unique)) if len(unique) == 1 else None


def position_observation(facts_doc: dict,
                         now: str | None = None) -> dict:
    """facts -> CA_ES_POSITION_OBSERVATION_V1. Pura/read-only."""
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
        "statement_as_of": None,
        "account_id_raw": None,
        "pagination": None,
        "positions": [],
        "parse_status": "OK",
        "reasons": [],
        "provenance": [],
    }
    if facts_doc.get("parse_status") not in ("OK", "PARSE_OK"):
        return {**base, "parse_status": "PARSE_ERROR",
                "reasons": ["SOURCE_PARSE_FAILED"]}
    if mid == MT535:
        return _mt535(facts_doc, base)
    if isinstance(mid, str) and mid.startswith(SEMT002_PREFIX):
        if mid in SEMT002_SUPPORTED:
            return _semt002(facts_doc, base)
        return {**base, "parse_status": "UNSUPPORTED",
                "reasons": ["UNSUPPORTED_SEMT002_VERSION"]}
    return {**base, "parse_status": "UNSUPPORTED",
            "reasons": ["UNSUPPORTED_MESSAGE_TYPE"]}


# ------------------------------------------------------------------
# MT535

def _mt535(facts_doc, base):
    facts = facts_doc.get("facts") or []
    reasons = list(base["reasons"])

    ref = _single(f.get("value") for f in
                  _find(facts, "20C", "SEME", "reference", "GENL"))
    as_of = _single(
        _iso_date(f.get("value")) for f in
        (_find(facts, "98A", "STAT", "date", "GENL")
         or _find(facts, "98C", "STAT", "date/time", "GENL")))
    accounts = _find(facts, "97A", "SAFE", "account number")
    account = _single(f.get("value") for f in accounts)

    page = _single(f.get("value") for f in
                   _find(facts, "28E", label="page number", seq="GENL"))
    cont = _single(f.get("value") for f in
                   _find(facts, "28E", label="continuation indicator",
                         seq="GENL"))
    pagination = {
        "page": int(page.lstrip(":")) if page and page.lstrip(
            ":").isdigit() else None,
        "continuation": cont,          # ONLY / MORE / LAST
        "last_page": cont in ("ONLY", "LAST") if cont else None,
        "update_type": None,
    }

    if ref is None:
        reasons.append("MISSING_STATEMENT_REFERENCE")
    if as_of is None:
        reasons.append("MISSING_AS_OF")
    if account is None:
        reasons.append(
            "MISSING_ACCOUNT" if not accounts
            else "CONFLICTING_ACCOUNT")

    # FIN blocks: 35B occurrence = indice de instrumento dentro del
    # mensaje; los balances 93B/C comparten ese occurrence.
    isin_facts = _find(facts, "35B", "ISIN", "isin")
    desc_facts = _find(facts, "35B", "ISIN", "description")
    positions = []
    for idx in sorted({f.get("occurrence", 0) for f in isin_facts}):
        isin = _single(f.get("value") for f in isin_facts
                       if f.get("occurrence") == idx)
        desc = _single(f.get("value") for f in desc_facts
                       if f.get("occurrence") == idx)
        balances = []
        pos_reasons = []
        for f in _find(facts, seq="SUBSAFE/FIN/SUBBAL"):
            if f.get("occurrence") != idx:
                continue
            if f.get("source_tag") not in ("93B", "93C", "93E", "93F"):
                continue
            qual = f.get("source_qualifier")
            label = (f.get("field_path") or "").rsplit(".", 1)[-1]
            siblings = [g for g in _find(facts, f["source_tag"], qual,
                                         seq="SUBSAFE/FIN/SUBBAL")
                        if g.get("occurrence") == idx]
            qty_type = _single(g.get("value") for g in siblings
                               if (g.get("field_path") or "")
                               .endswith(".quantity type code"))
            amount_raw = _single(g.get("value") for g in siblings
                                 if (g.get("field_path") or "")
                                 .endswith(".balance"))
            if label == "balance":
                amount = _swift_amount(amount_raw)
                balances.append({
                    "qualifier": qual,
                    "availability_type": BALANCE_QUALIFIERS.get(
                        qual, qual),
                    "quantity_type": qty_type,
                    "quantity_raw": amount_raw,
                    "quantity": _fmt(amount),
                    "provenance": [_prov(g) for g in siblings],
                })
        aggr = [b for b in balances
                if b["qualifier"] == "AGGR" and b["quantity"]]
        canonical = aggr[0]["quantity"] if len(aggr) == 1 else None
        canonical_type = aggr[0]["quantity_type"] if len(
            aggr) == 1 else None
        if len(aggr) > 1:
            pos_reasons.append("CONFLICTING_AGGREGATE_BALANCE")
        elif not aggr:
            pos_reasons.append("MISSING_AGGREGATE_BALANCE")
        if isin is None:
            pos_reasons.append("MISSING_ISIN")
        prov = [p for b in balances for p in b["provenance"]]
        prov += [_prov(f) for f in isin_facts
                 if f.get("occurrence") == idx]
        positions.append({
            "instrument_index": idx,
            "source_instrument_id": "ISIN " + isin if isin else None,
            "isin": isin,
            "description": desc,
            "balances": balances,
            "quantity": canonical,
            "quantity_type": canonical_type,
            "availability": {
                b["qualifier"]: b["quantity"] for b in balances
                if b["qualifier"] != "AGGR"},
            "reasons": pos_reasons,
            "provenance": prov,
        })

    acty = _single(f.get("value") for f in
                   _find(facts, "17B", "ACTI", "flag", "GENL"))
    if not positions and acty == "Y":
        reasons.append("NO_HOLDINGS_SECTIONS")
    if not positions:
        reasons.append("EMPTY_STATEMENT")

    return {
        **base,
        "statement_reference": ref,
        "statement_as_of": as_of,
        "account_id_raw": account,
        "pagination": pagination,
        "activity_flag": acty,
        "positions": positions,
        "reasons": reasons,
        "provenance": [_prov(f) for f in (
            _find(facts, "28E", seq="GENL")
            + _find(facts, "20C", "SEME", "reference", "GENL")
            + _find(facts, "97A", "SAFE", "account number")
            + _find(facts, "98A", "STAT", "date", "GENL"))],
    }


# ------------------------------------------------------------------
# semt.002

def _semt002(facts_doc, base):
    facts = facts_doc.get("facts") or []
    reasons = list(base["reasons"])

    ref = _single(f.get("value") for f in
                  _facts_at(facts, "/StmtGnlDtls/StmtId"))
    as_of = _single(
        f.get("value") for f in
        (_facts_at(facts, "/StmtGnlDtls/StmtDtTm/Dt")
         or _facts_at(facts, "/StmtGnlDtls/StmtDtTm/DtTm")))
    account = _single(f.get("value") for f in
                      _facts_at(facts, "/SfkpgAcct/Id"))
    upd = _single(f.get("value") for f in
                  _facts_at(facts, "/StmtGnlDtls/UpdTp/Cd"))
    page = _single(f.get("value") for f in
                   _facts_at(facts, "/Pgntn/PgNb"))
    last = _single(f.get("value") for f in
                   _facts_at(facts, "/Pgntn/LastPgInd"))
    pagination = {
        "page": int(page) if page and page.isdigit() else None,
        "continuation": None,
        "last_page": {"true": True, "false": False}.get(
            str(last).lower()) if last is not None else None,
        "update_type": upd,            # COMP / DELT
    }

    if ref is None:
        reasons.append("MISSING_STATEMENT_REFERENCE")
    if as_of is None:
        reasons.append("MISSING_AS_OF")
    if account is None:
        reasons.append("MISSING_ACCOUNT")

    groups = sorted({
        g for g in (_locator_group(f, "BalForAcct") for f in facts)
        if g is not None})
    positions = []
    for idx in groups:
        mine = [f for f in facts if _locator_group(
            f, "BalForAcct") == idx]
        isin = _single(f.get("value") for f in mine
                       if (f.get("model_path") or "")
                       .endswith("/FinInstrmId/ISIN"))
        desc = _single(f.get("value") for f in mine
                       if (f.get("model_path") or "")
                       .endswith("/FinInstrmId/Desc"))
        pos_reasons = []
        balances = []

        def _bal(paths, qualifier):
            for p in paths:
                found = [f for f in mine
                         if (f.get("model_path") or "").endswith(p)]
                if found:
                    amount = _swift_amount(_single(
                        f.get("value") for f in found))
                    qty_type = p.rsplit("/", 1)[-1].upper()
                    qty_type = {
                        "UNIT": "UNIT", "FACEAMT": "FAMT",
                        "AMTSDVAL": "AMOR"}.get(qty_type, qty_type)
                    balances.append({
                        "qualifier": qualifier,
                        "availability_type": BALANCE_QUALIFIERS.get(
                            qualifier, qualifier),
                        "quantity_type": qty_type,
                        "quantity_raw": _single(
                            f.get("value") for f in found),
                        "quantity": _fmt(amount),
                        "provenance": [_prov(f) for f in found],
                    })
                    return

        _bal(["/AggtBal/Qty/Qty/Qty/Unit",
              "/AggtBal/Qty/Qty/Qty/FaceAmt",
              "/AggtBal/Qty/Qty/Qty/AmtsdVal",
              "/AggtBal/Qty/Qty/Qty/DgtlTknUnit"], "AGGR")
        _bal(["/AvlblBal/Qty/Qty/Unit",
              "/AvlblBal/Qty/Qty/FaceAmt"], "AVAI")
        _bal(["/NotAvlblBal/Qty/Unit",
              "/NotAvlblBal/Qty/FaceAmt"], "NAVAI")

        aggr = [b for b in balances
                if b["qualifier"] == "AGGR" and b["quantity"]]
        canonical = aggr[0]["quantity"] if len(aggr) == 1 else None
        canonical_type = aggr[0]["quantity_type"] if len(
            aggr) == 1 else None
        if not aggr:
            pos_reasons.append("MISSING_AGGREGATE_BALANCE")
        if isin is None:
            pos_reasons.append("MISSING_ISIN")
        prov = [p for b in balances for p in b["provenance"]]
        prov += [_prov(f) for f in mine
                 if "/FinInstrmId/" in (f.get("model_path") or "")]
        positions.append({
            "instrument_index": idx,
            "source_instrument_id": "ISIN " + isin if isin else None,
            "isin": isin,
            "description": desc,
            "balances": balances,
            "quantity": canonical,
            "quantity_type": canonical_type,
            "availability": {
                b["qualifier"]: b["quantity"] for b in balances
                if b["qualifier"] != "AGGR"},
            "reasons": pos_reasons,
            "provenance": prov,
        })

    if not positions:
        reasons.append("EMPTY_STATEMENT")

    return {
        **base,
        "statement_reference": ref,
        "statement_as_of": as_of,
        "account_id_raw": account,
        "pagination": pagination,
        "activity_flag": _single(
            f.get("value") for f in
            _facts_at(facts, "/StmtGnlDtls/ActvtyInd")),
        "positions": positions,
        "reasons": reasons,
        "provenance": [_prov(f) for f in (
            _facts_at(facts, "/Pgntn/PgNb")
            + _facts_at(facts, "/Pgntn/LastPgInd")
            + _facts_at(facts, "/StmtGnlDtls/StmtId")
            + _facts_at(facts, "/StmtGnlDtls/StmtDtTm/Dt")
            + _facts_at(facts, "/StmtGnlDtls/UpdTp/Cd")
            + _facts_at(facts, "/SfkpgAcct/Id"))],
    }
