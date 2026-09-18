"""P14.1/P14.2/P14.3/P14.4 — tax evidence projection.

CA_ES_SWIFT_MT_FACTS_V1 (MT564/MT566)
CA_ES_SWIFT_MX_FACTS_V1 (seev.031/seev.036)
    -> CA_ES_TAX_EVIDENCE_V1

Evidencia fiscal de transporte. NO calcula nada: preserva tasas,
importes y selectores exactamente como vienen en el mensaje, con
scope (EVENT/OPTION/CASH_MOVEMENT) y provenance por fact.

- evidence_role: EXPECTED para notificaciones (MT564/seev.031),
  ACTUAL para confirmaciones de movimiento (MT566/seev.036);
- nunca "first TAXR wins": ocurrencias repetidas producen items
  repetidos; la ambiguedad se resuelve en tax_entitlement;
- qualifiers no mapeados se conservan con tax_type=UNCLASSIFIED,
  nunca se traducen a una clase adivinada;
- FIN 92x rate -> kind=rate, rate_unit=PERCENTAGE (MRG: los rates
  FIN se expresan en puntos porcentuales);
- ISO 20022 xxxRate/Rate -> idem (PercentageRate es porcentaje);
- scopes de opcion: un rate de CASHMOVE bajo CAOPTN[k] queda ligado
  a esa opcion via option_occurrence; no contamina otras opciones.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

EVIDENCE_SCHEMA = "CA_ES_TAX_EVIDENCE_V1"

EXPECTED_MESSAGES = {"MT564"}
ACTUAL_MESSAGES = {"MT566"}
SEEV031_PREFIX = "seev.031."
SEEV036_PREFIX = "seev.036."

# normalized tax_type solo donde la semantica esta probada
# (docs/p14/p140-capability.md). El resto -> UNCLASSIFIED.
QUALIFIER_TAX_TYPE = {
    "TAXR": "WITHHOLDING_PRIMARY",
    "WITL": "WITHHOLDING_SECOND_LEVEL",
    "WTAX": "WITHHOLDING_PRIMARY",
    "WHHO": "WITHHOLDING_PRIMARY",
    "TAXC": "TAX_CREDIT",
    "TXDF": "TAX_FREE",
    "TXRC": "TAX_RECLAIM",
    "TAXB": "TAXABLE_BASIS",
    "GRSS": "GROSS_AMOUNT",
    "NETT": "NET_AMOUNT",
    "FISC": "OTHER_EXPLICIT",
    "NRAT": "OTHER_EXPLICIT",
    "CHAR": "OTHER_EXPLICIT",
    "OTHR": "OTHER_EXPLICIT",
    "FETC": "OTHER_EXPLICIT",
    "SOIC": "OTHER_EXPLICIT",
    "STAM": "OTHER_EXPLICIT",
    "STEX": "OTHER_EXPLICIT",
    "EXEC": "OTHER_EXPLICIT",
    "TAXE": "OTHER_EXPLICIT",
    "VATX": "OTHER_EXPLICIT",
    "LTRA": "OTHER_EXPLICIT",
    "REGR": "OTHER_EXPLICIT",
}

# 19B -> amount; 92x -> rate (92J expone el rate como .amount)
_RATE_TAGS = {"92A", "92D", "92F", "92H", "92J", "92K", "92L", "92M",
              "92N", "92P", "92R"}
_AMOUNT_TAGS = {"19B", "19F", "19J", "19K", "19L", "19N", "19P",
                "19R", "19T", "19U", "19W", "19Y"}

# model_path -> (tax_type, kind) para seev.031/036. Se matchea por
# sufijo del model_path; @Ccy se trata como componente de moneda.
# Nombres verificados contra el modelo SRU2025 pinneado
# (CorporateActionOption232/Rate42/CorporateActionAmounts72).
_SEEV_TAX_PATHS = [
    # rates (RateAndAmountFormat56Choice / RateFormat*)
    ("/WhldgTaxRate/RateTpAndRate/Rate", "WITHHOLDING_PRIMARY", "rate"),
    ("/WhldgTaxRate/RateTpAndRate/RateTp/Cd",
     "WITHHOLDING_PRIMARY", "rate_type"),
    ("/WhldgTaxRate/Rate", "WITHHOLDING_PRIMARY", "rate"),
    ("/WhldgTaxRate/Amt", "WITHHOLDING_PRIMARY", "amount"),
    ("/WhldgTaxRate/NotSpcfdRate", "WITHHOLDING_PRIMARY",
     "rate_unspecified"),
    ("/ScndLvlTax/RateTpAndRate/Rate", "WITHHOLDING_SECOND_LEVEL",
     "rate"),
    ("/ScndLvlTax/Rate", "WITHHOLDING_SECOND_LEVEL", "rate"),
    ("/ScndLvlTax/Amt", "WITHHOLDING_SECOND_LEVEL", "amount"),
    ("/ScndLvlTax/NotSpcfdRate", "WITHHOLDING_SECOND_LEVEL",
     "rate_unspecified"),
    ("/TaxCdtRate", "TAX_CREDIT", "rate"),
    ("/TaxRclmRate", "TAX_RECLAIM", "rate"),
    ("/TaxOnIncm", "OTHER_EXPLICIT", "other"),
    ("/TaxOnPrfts", "OTHER_EXPLICIT", "other"),
    ("/AddtlTax", "OTHER_EXPLICIT", "other"),
    ("/AplblRate", "OTHER_EXPLICIT", "other"),
    ("/FsclStmp", "OTHER_EXPLICIT", "other"),
    ("/ChrgsFees", "OTHER_EXPLICIT", "other"),
    # amounts (CorporateActionAmounts72)
    ("/WhldgTaxAmt", "WITHHOLDING_PRIMARY", "amount"),
    ("/ScndLvlTaxAmt", "WITHHOLDING_SECOND_LEVEL", "amount"),
    ("/TaxCdtAmt", "TAX_CREDIT", "amount"),
    ("/TaxRclmAmt", "TAX_RECLAIM", "amount"),
    ("/AddtlTaxAmt", "OTHER_EXPLICIT", "amount"),
    ("/TaxFreeAmt", "TAX_FREE", "amount"),
    ("/TaxDfrrdAmt", "OTHER_EXPLICIT", "amount"),
    ("/ValAddedTaxAmt", "OTHER_EXPLICIT", "amount"),
    ("/StmpDtyAmt", "OTHER_EXPLICIT", "amount"),
    ("/FsclStmpAmt", "OTHER_EXPLICIT", "amount"),
    ("/GrssAmt", "GROSS_AMOUNT", "amount"),
    ("/NetAmt", "NET_AMOUNT", "amount"),
    ("/GrssDstrbtnRate/Amt", "GROSS_AMOUNT", "amount"),
    ("/GrssDstrbtnRate/Rate", "GROSS_AMOUNT", "rate"),
    ("/NetDstrbtnRate/Amt", "NET_AMOUNT", "amount"),
    ("/NetDstrbtnRate/Rate", "NET_AMOUNT", "rate"),
    ("/SlctnFees", "OTHER_EXPLICIT", "amount"),
    ("/SndryOrOthrAmt", "OTHER_EXPLICIT", "amount"),
    ("/TaxblIncmPerDvddShr/Amt", "TAXABLE_BASIS", "amount"),
    ("/TaxblIncmPerShrCaltd", "TAXABLE_BASIS", "amount"),
    # selectores
    ("/XmptnTp/Cd", "EXEMPTION_TYPE", "selector"),
    ("/XmptnTp/Id", "EXEMPTION_TYPE", "selector"),
    ("/CtryOfIncmSrc", "JURISDICTION", "selector"),
    ("/IncmTp/Id", "INCOME_TYPE", "selector"),
    ("/IncmTp/Issr", "INCOME_TYPE", "selector"),
]


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
    """Lexema SWIFT ('0,125', 'N1562,5') o ISO ('0.125') -> Decimal."""
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


def _parent_occurrence(fact, parent):
    """Ocurrencia del sequence padre (CAOPTN[k]/CACASH[k]/CshOptnDtls[k]
    /CorpActnOptnDtls[k]) dentro del field_path/evidence_locator."""
    for key in ("field_path", "evidence_locator"):
        text = fact.get(key) or ""
        m = re.search(re.escape(parent) + r"\[(\d+)\]", text)
        if m:
            return int(m.group(1))
    return None


def _locator_group(fact, element):
    loc = fact.get("evidence_locator") or ""
    m = re.search(re.escape(element) + r"\[(\d+)\]", loc)
    return int(m.group(1)) if m else None


def tax_evidence(facts_doc: dict,
                 canonical_event_id: str | None = None,
                 now: str | None = None) -> dict:
    """facts -> CA_ES_TAX_EVIDENCE_V1. Pura/read-only."""
    mid = facts_doc.get("message_identifier")
    base = {
        "schema": EVIDENCE_SCHEMA,
        "generated_at": now or facts_doc.get("generated_at"),
        "canonical_event_id": canonical_event_id,
        "source_message_identifier": mid,
        "source_standard": facts_doc.get("standard_family"),
        "input_sha256": facts_doc.get("input_sha256"),
        "library": facts_doc.get("library"),
        "library_version": facts_doc.get("library_version"),
        "evidence_role": None,
        "event_references": [],
        "scopes": [],
        "status": "OK",
        "reasons": [],
    }
    if facts_doc.get("parse_status") not in ("OK", "PARSE_OK", None):
        return {**base, "status": "PARSE_ERROR",
                "reasons": ["SOURCE_PARSE_FAILED"]}
    if mid in EXPECTED_MESSAGES or (
            isinstance(mid, str) and mid.startswith(SEEV031_PREFIX)):
        base["evidence_role"] = "EXPECTED"
    elif mid in ACTUAL_MESSAGES or (
            isinstance(mid, str) and mid.startswith(SEEV036_PREFIX)):
        base["evidence_role"] = "ACTUAL"
    else:
        return {**base, "status": "UNSUPPORTED",
                "reasons": ["UNSUPPORTED_MESSAGE_TYPE"]}
    if isinstance(mid, str) and mid.startswith("seev."):
        return _seev(facts_doc, base)
    return _mt(facts_doc, base)


# ------------------------------------------------------------------
# FIN (MT564/MT566)

def _mt_event_refs(facts):
    refs = []
    for f in facts:
        if f.get("source_tag") == "20C" and f.get(
                "source_qualifier") in ("CORP", "SEME", "PREV"):
            label = (f.get("field_path") or "").rsplit(".", 1)[-1]
            if label == "reference":
                refs.append({
                    "qualifier": f.get("source_qualifier"),
                    "reference": f.get("value"),
                    "provenance": [_prov(f)],
                })
    return refs


def _mt_option_meta(facts, parents, occ):
    """option_number (11A:OPTN) y option_type (22F:CAOP) del padre."""
    number = option_type = None
    for parent in parents:
        for f in facts:
            seq = f.get("sequence") or ""
            if seq != parent and not seq.endswith("/" + parent):
                continue
            if (_parent_occurrence(
                    f, parent.rsplit("/", 1)[-1]) or 0) != occ:
                continue
            if f.get("source_tag") in ("11A", "13A") and f.get(
                    "source_qualifier") in ("OPTN", "CAON"):
                number = f.get("value")
            elif f.get("source_tag") in ("22F", "22H") and f.get(
                    "source_qualifier") == "CAOP":
                option_type = f.get("value")
    return number, option_type


def _mt(facts_doc, base):
    facts = facts_doc.get("facts") or []
    base["event_references"] = _mt_event_refs(facts)

    # scope key: (scope, option_parent, option_occurrence, sequence)
    scope_map = {}
    reasons = []

    def _bucket(scope, parent, occ, seq):
        key = (scope, parent, occ, seq)
        if key not in scope_map:
            number, otype = (None, None)
            if parent:
                number, otype = _mt_option_meta(
                    facts, (parent,), occ or 0)
            scope_map[key] = {
                "scope": scope,
                "sequence": seq,
                "sequence_occurrence": occ,
                "option_parent": parent,
                "option_number": number,
                "option_type": otype,
                "items": [],
            }
        return scope_map[key]

    tax_facts = [f for f in facts
                 if f.get("source_qualifier") in QUALIFIER_TAX_TYPE
                 or (f.get("source_qualifier") not in (None,)
                     and f.get("source_tag") in
                     (_RATE_TAGS | _AMOUNT_TAGS))]
    for f in tax_facts:
        seq = f.get("sequence") or ""
        tag = f.get("source_tag")
        qual = f.get("source_qualifier")
        field_path = f.get("field_path") or ""
        leaf = field_path.rsplit(".", 1)[-1]

        # scope: ultimo padre de opcion presente en el path
        # (MT564: CAOPTN/CACASH->CSMV; MT566: CACONF->CSHMOVE)
        segs = seq.split("/")
        parent = None
        for cand in ("CAOPTN", "CACASH", "CACONF", "CASHMOVE",
                     "CSMV", "CSHMOVE", "SECMOVE"):
            if cand in segs:
                parent = cand
        if parent in ("CASHMOVE", "CSMV", "CSHMOVE", "SECMOVE"):
            # el propio sequence es el movimiento; el padre de
            # opcion es el segmento anterior
            opt_parent = segs[-2] if len(segs) > 1 else None
            bucket = _bucket("CASH_MOVEMENT", opt_parent,
                             _parent_occurrence(
                                 f, opt_parent) if opt_parent
                             else None, seq)
        elif parent in ("CAOPTN", "CACASH", "CACONF"):
            parent_occ = _parent_occurrence(f, parent)
            bucket = _bucket("OPTION", parent, parent_occ, seq)
        else:
            bucket = _bucket("EVENT", None, None, seq or "GENL")

        if tag in _RATE_TAGS:
            # 92J expone el rate como componente 'amount'
            if leaf not in ("rate", "amount", "rate type code"):
                continue
            if leaf == "rate type code":
                continue  # se adjunta como rate_type del hermano
            value = _dec(f.get("value"))
            item = {
                "tax_type": QUALIFIER_TAX_TYPE.get(
                    qual, "UNCLASSIFIED"),
                "raw_qualifier": qual,
                "kind": "rate",
                "rate": _fmt(value),
                "rate_lexeme": f.get("value"),
                "rate_unit": "PERCENTAGE",
                "rate_type": _mt_rate_type(facts, f),
                "amount": None,
                "currency": None,
                "jurisdiction_code": None,
                "provenance": [_prov(f)],
            }
            bucket["items"].append(item)
        elif tag in _AMOUNT_TAGS:
            if leaf not in ("amount", "currency code"):
                continue
            if leaf == "currency code":
                continue  # se adjunta como currency del hermano
            amount = _dec(f.get("value"))
            item = {
                "tax_type": QUALIFIER_TAX_TYPE.get(
                    qual, "UNCLASSIFIED"),
                "raw_qualifier": qual,
                "kind": "amount",
                "rate": None,
                "rate_lexeme": None,
                "rate_unit": None,
                "rate_type": None,
                "amount": _fmt(amount),
                "amount_lexeme": f.get("value"),
                "currency": _mt_currency(facts, f),
                "jurisdiction_code": None,
                "provenance": [_prov(f)],
            }
            bucket["items"].append(item)
        else:
            # qualifier fiscal en tag no-rate/no-amount: preservar
            bucket["items"].append({
                "tax_type": "UNCLASSIFIED",
                "raw_qualifier": qual,
                "kind": "other",
                "rate": None,
                "rate_lexeme": None,
                "rate_unit": None,
                "rate_type": None,
                "amount": None,
                "amount_lexeme": None,
                "currency": None,
                "jurisdiction_code": None,
                "provenance": [_prov(f)],
            })

    base["scopes"] = sorted(
        scope_map.values(),
        key=lambda s: (s["option_parent"] or "",
                       s["option_number"] or "",
                       s["sequence_occurrence"] or 0,
                       s["sequence"]))
    if not base["scopes"]:
        base["status"] = "INDETERMINATE"
        reasons.append("NO_TAX_EVIDENCE")
    base["reasons"] = reasons
    return base


def _mt_currency(facts, amount_fact):
    """componente 'currency code' del mismo 19B (mismo tag+occurrence)."""
    for g in facts:
        if (g.get("sequence") == amount_fact.get("sequence")
                and g.get("occurrence") == amount_fact.get("occurrence")
                and g.get("source_tag") == amount_fact.get("source_tag")
                and g.get("source_qualifier")
                == amount_fact.get("source_qualifier")
                and (g.get("field_path") or "").endswith(
                    ".currency code")):
            return g.get("value")
    return None


def _mt_rate_type(facts, rate_fact):
    """componente 'rate type code' hermano (92J/92K variables)."""
    for g in facts:
        if (g.get("sequence") == rate_fact.get("sequence")
                and g.get("occurrence") == rate_fact.get("occurrence")
                and g.get("source_tag") == rate_fact.get("source_tag")
                and g.get("source_qualifier")
                == rate_fact.get("source_qualifier")
                and (g.get("field_path") or "").endswith(
                    ".rate type code")):
            return g.get("value")
    return None


# ------------------------------------------------------------------
# ISO 20022 (seev.031/036)

def _seev_parent(fact):
    """Devuelve (parent_element, occurrence) del contenedor de
    opcion/movimiento mas interno: CshMvmntDtls > CorpActnOptnDtls."""
    for element in ("CshMvmntDtls", "CorpActnOptnDtls",
                    "CorpActnConfDtls", "CorpActnMvmntDtls"):
        occ = _locator_group(fact, element)
        if occ is not None:
            return element, occ
    return None, None


# contenedores que llevan OptnNb/OptnTp como hijos directos:
# seev.031 -> CorpActnOptnDtls; seev.036 -> CorpActnConfDtls
_SEV_OPTION_CONTAINERS = ("CorpActnOptnDtls", "CorpActnConfDtls",
                         "CorpActnMvmntDtls")


def _seev_option_meta(facts, element, occ):
    number = option_type = None
    for f in facts:
        if _locator_group(f, element) != occ:
            continue
        path = f.get("model_path") or ""
        if path.endswith("/OptnNb") or path.endswith("/OptnNb/Nb"):
            number = f.get("value")
        elif path.endswith("/OptnTp/Cd"):
            option_type = f.get("value")
    return number, option_type


def _seev(facts_doc, base):
    facts = facts_doc.get("facts") or []
    reasons = []
    for f in facts:
        if (f.get("model_path") or "").endswith("/CorpActnEvtId"):
            base["event_references"].append({
                "qualifier": "CorpActnEvtId",
                "reference": f.get("value"),
                "provenance": [_prov(f)],
            })

    scope_map = {}
    items_seen = {}  # item por (scope_key, path_sufijo, locator)
    for f in facts:
        path = f.get("model_path") or ""
        if path.endswith("/@Ccy"):
            continue  # componente de moneda del hermano
        matched = None
        for suffix, tax_type, kind in _SEEV_TAX_PATHS:
            if path.endswith(suffix):
                matched = (suffix, tax_type, kind)
                break
        if matched is None:
            leaf = path.rsplit("/", 1)[-1]
            if "Tax" not in leaf and "Whldg" not in leaf:
                continue
            # elemento fiscal no mapeado: preservar sin clasificar
            matched = ("/" + leaf, "UNCLASSIFIED", "other")
        suffix, tax_type, kind = matched
        parent, occ = _seev_parent(f)
        scope = ("CASH_MOVEMENT" if parent == "CshMvmntDtls"
                 else "OPTION" if parent else "EVENT")
        key = (scope, parent, occ)
        if key not in scope_map:
            number, otype = (None, None)
            if parent == "CshMvmntDtls":
                for container in _SEV_OPTION_CONTAINERS:
                    opt_occ = _locator_group(f, container)
                    if opt_occ is not None:
                        number, otype = _seev_option_meta(
                            facts, container, opt_occ)
                        break
            elif parent in _SEV_OPTION_CONTAINERS:
                number, otype = _seev_option_meta(facts, parent, occ)
            scope_map[key] = {
                "scope": scope,
                "sequence": parent,
                "sequence_occurrence": occ,
                "option_parent": parent,
                "option_number": number,
                "option_type": otype,
                "items": [],
            }
        bucket = scope_map[key]
        item_key = (key, suffix, f.get("evidence_locator"))
        if kind == "rate_type":
            # se adjunta al item rate del mismo grupo
            continue
        currency = None
        if kind == "amount":
            ccy_path = path + "/@Ccy"
            loc = f.get("evidence_locator") or ""
            # el @Ccy es atributo del propio elemento: su locator
            # cuelga del locator del Amt
            currency = next(
                (g.get("value") for g in facts
                 if (g.get("model_path") or "") == ccy_path
                 and (g.get("evidence_locator") or "").startswith(
                     loc + "/")),
                None)
            if currency is None:
                currency = next(
                    (g.get("value") for g in facts
                     if (g.get("model_path") or "") == ccy_path),
                    None)
        value = _dec(f.get("value"))
        item = {
            "tax_type": tax_type,
            "raw_qualifier": suffix.rsplit("/", 1)[-1],
            "kind": {"rate_unspecified": "rate",
                     "selector": "selector"}.get(kind, kind),
            "rate": _fmt(value) if kind == "rate" else None,
            "rate_lexeme": f.get("value") if kind in (
                "rate", "rate_unspecified") else None,
            "rate_unit": "PERCENTAGE" if kind == "rate" else None,
            "rate_type": (
                "NOT_SPECIFIED" if kind == "rate_unspecified"
                else _seev_rate_type(facts, f, suffix)),
            "amount": _fmt(value) if kind == "amount" else None,
            "amount_lexeme": f.get("value") if kind == "amount"
            else None,
            "currency": currency,
            "jurisdiction_code": (
                f.get("value") if tax_type == "JURISDICTION" else None),
            "selector_value": f.get("value") if kind == "selector"
            else None,
            "provenance": [_prov(f)],
        }
        items_seen[item_key] = item
        bucket["items"].append(item)

    base["scopes"] = sorted(
        scope_map.values(),
        key=lambda s: (s["option_parent"] or "",
                       s["option_number"] or "",
                       s["sequence_occurrence"] or 0))
    if not base["scopes"]:
        base["status"] = "INDETERMINATE"
        reasons.append("NO_TAX_EVIDENCE")
    base["reasons"] = reasons
    return base


def _seev_rate_type(facts, rate_fact, suffix):
    """RateTp/Cd hermano de WhldgTaxRate/RateTpAndRate/Rate."""
    if "RateTpAndRate" not in suffix:
        return None
    parent_loc = (rate_fact.get("evidence_locator") or "").rsplit(
        "/", 1)[0]
    for g in facts:
        if (g.get("model_path") or "").endswith("/RateTp/Cd") and (
                g.get("evidence_locator") or "").rsplit(
                    "/", 1)[0] == parent_loc:
            return g.get("value")
    return None
