"""P4.1 — SWIFT semantic projection + deterministic event binding.

docs/p4/p41-scope.md:

    CA_ES_SWIFT_MT_FACTS_V1  (P4.0, salida del adapter JVM)
        -> project_ca_message()  -> CA_ES_SWIFT_CA_MESSAGE_V1
        -> bind_event()          -> CA_ES_SWIFT_EVENT_BINDING_V1

Reglas duras:

- scope DVCA -> CASH_DIVIDEND; CAEV no mapeado -> UNSUPPORTED_CA_EVENT
- la proyeccion nunca modifica el canon; binding determinista, cero
  fuzzy matching
- BOUND/AMBIGUOUS/NO_MATCH/INSUFFICIENT_IDENTITY; comparacion por
  campo AGREES/DIFFERS/CANON_MISSING/SWIFT_MISSING/CANON_CONFLICTING,
  sin ganador
- cada campo proyectado conserva provenance de los facts originales
- read-only: sin cash movement projection, sin workflow
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

CA_MESSAGE_SCHEMA = "CA_ES_SWIFT_CA_MESSAGE_V1"
BINDING_SCHEMA = "CA_ES_SWIFT_EVENT_BINDING_V1"
FACTS_SCHEMA = "CA_ES_SWIFT_MT_FACTS_V1"

CAEV_MAP = {"DVCA": "CASH_DIVIDEND", "SPLF": "SPLIT",
            "SPLR": "SPLIT", "RHDI": "RIGHTS_ISSUE",
            "EXRI": "RIGHTS_ISSUE", "DVSE": "STOCK_DIVIDEND",
            "DVOP": "SCRIP_DIVIDEND",
            "BONU": "CAPITAL_INCREASE"}

# mechanism derivado del CAEV mismo (registry P8.0): SPLR es el
# codigo de reverso; SPLI es opcion de instruccion, no CAEV.
# RHDI/EXRI son las dos etapas enlazadas de una emision de
# derechos (P8.2); RHTS/PRIO quedan UNMAPPED. DVSE es la
# distribucion obligatoria de valores (P8.4); DVOP es el scrip
# electivo cash/valores (P8.5)
CAEV_MECHANISM = {"SPLR": "REVERSE_SPLIT",
                  "RHDI": "RIGHTS_DISTRIBUTION",
                  "EXRI": "RIGHTS_EXERCISE",
                  "DVSE": "STOCK_DIVIDEND",
                  "DVOP": "SCRIP_DIVIDEND",
                  "BONU": "BONUS_ISSUE"}

PRESENT = "PRESENT"
ABSENT = "ABSENT"
CONFLICTING = "CONFLICTING"

BOUND = "BOUND"
AMBIGUOUS = "AMBIGUOUS"
NO_MATCH = "NO_MATCH"
INSUFFICIENT_IDENTITY = "INSUFFICIENT_IDENTITY"
UNSUPPORTED_CA_EVENT = "UNSUPPORTED_CA_EVENT"

AGREES = "AGREES"
DIFFERS = "DIFFERS"
CANON_MISSING = "CANON_MISSING"
SWIFT_MISSING = "SWIFT_MISSING"
CANON_CONFLICTING = "CANON_CONFLICTING"

# campos del mensaje -> field_path canonico para comparacion
_COMPARE_FIELDS = (
    ("ex_date", "date.ex_date"),
    ("record_date", "date.record_date"),
    ("payment_date", "date.payment_date"),
    ("gross_per_share", "amount.gross_per_share"),
)

# fechas usadas para desambiguar cuando isin+event_type dan >1 evento
_DISAMBIG_DATES = ("ex_date", "record_date", "payment_date")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _prov(fact: dict) -> dict:
    return {
        "source_tag": fact.get("source_tag"),
        "source_qualifier": fact.get("source_qualifier"),
        "sequence": fact.get("sequence"),
        "occurrence": fact.get("occurrence"),
        "evidence_locator": fact.get("evidence_locator"),
        "raw": fact.get("value"),
    }


def _field(facts: list[dict], normalize=None) -> dict:
    """Un campo semantico a partir de los facts que lo afirman.

    Todas las ocurrencias se conservan como provenance; el value solo
    existe si hay un unico valor normalizado distinto.
    """
    values = set()
    provenance = []
    raw = None
    for f in facts:
        provenance.append(_prov(f))
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


def _norm_date(raw: str):
    """YYYYMMDD -> YYYY-MM-DD; no parseable -> se conserva raw (sin
    inferir)."""
    if raw and len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw


def _norm_amount(raw: str):
    """coma decimal SWIFT -> punto; no parseable -> raw."""
    try:
        return format(Decimal(raw.replace(",", ".")), "f")
    except (InvalidOperation, AttributeError):
        return raw


def _find(facts, tag, qualifier=None, seq=None, label_suffix=None,
          seq_contains=None):
    out = []
    for f in facts:
        if f.get("source_tag") != tag:
            continue
        if qualifier is not None and f.get("source_qualifier") != qualifier:
            continue
        if seq is not None and f.get("sequence") != seq:
            continue
        if seq_contains is not None and seq_contains not in (
                f.get("sequence") or ""):
            continue
        if label_suffix is not None and not (
            (f.get("field_path") or "").endswith(label_suffix)
        ):
            continue
        out.append(f)
    return out


def _new_for_old(facts: list[dict]) -> dict:
    """92D::NEWO -> {new, old} por (sequence, occurrence).

    quantity1 = new, quantity2 = old (spec ISO: ratio new-for-old).
    Multiples pares con valores distintos -> CONFLICTING.
    """
    q1 = [f for f in facts if f.get("source_qualifier") == "NEWO"
          and (f.get("field_path") or "").endswith(".quantity1")]
    q2 = [f for f in facts if f.get("source_qualifier") == "NEWO"
          and (f.get("field_path") or "").endswith(".quantity2")]
    pairs = {}
    provenance = []
    for f in (*q1, *q2):
        provenance.append(_prov(f))
    by_key = {}
    for f in q1:
        by_key.setdefault(
            (f.get("sequence"), f.get("occurrence")), {})["new"] = \
            f.get("value")
    for f in q2:
        by_key.setdefault(
            (f.get("sequence"), f.get("occurrence")), {})["old"] = \
            f.get("value")
    for _, v in by_key.items():
        if v.get("new") is not None and v.get("old") is not None:
            pairs[f"{v['new']}/{v['old']}"] = v
    if not pairs:
        return {"value": None, "status": ABSENT, "raw": None,
                "provenance": provenance}
    if len(pairs) > 1:
        return {"value": None, "status": CONFLICTING, "raw": None,
                "provenance": provenance}
    new_s, old_s = next(iter(pairs)).split("/")
    try:
        new = format(Decimal(new_s.replace(",", ".")), "f")
        old = format(Decimal(old_s.replace(",", ".")), "f")
    except InvalidOperation:
        return {"value": None, "status": CONFLICTING, "raw": None,
                "provenance": provenance}
    return {"value": {"new": new, "old": old}, "status": PRESENT,
            "raw": next(iter(pairs)), "provenance": provenance}


def _target_isin(facts: list[dict]) -> dict:
    """35B en SECMOVE distinto del USECU 35B -> instrumento destino.

    Si todos los SECMOVE 35B coinciden con el source, el target es el
    propio source (split sin cambio de ISIN)."""
    source_f = _field(
        _find(facts, "35B", seq="USECU", label_suffix=".isin")
        or _find(facts, "35B", seq="USEQ", label_suffix=".isin"))
    source = source_f["value"] if source_f["status"] == PRESENT \
        else None
    secmove_isins = _find(facts, "35B", label_suffix=".isin",
                          seq_contains="SECMOVE")
    others = [f for f in secmove_isins
              if f.get("value") and f.get("value") != source]
    if not others:
        if source is not None:
            return {"value": source, "status": PRESENT, "raw": source,
                    "provenance": source_f.get("provenance") or []}
        return {"value": None, "status": ABSENT, "raw": None,
                "provenance": []}
    return _field(others)


def _subscription_price(facts: list[dict]) -> dict:
    """90B::PRPP|OFFR -> {normalized, currency} por (seq, occurrence).

    Precio de suscripcion de una etapa de ejercicio (EXRI). Varias
    ocurrencias con valores distintos -> CONFLICTING."""
    prices = [f for f in facts
              if f.get("source_tag") == "90B"
              and f.get("source_qualifier") in ("PRPP", "OFFR")
              and (f.get("field_path") or "").endswith(".price")]
    ccy = [f for f in facts
           if f.get("source_tag") == "90B"
           and f.get("source_qualifier") in ("PRPP", "OFFR")
           and (f.get("field_path") or "").endswith(".currency code")]
    provenance = [_prov(f) for f in (*prices, *ccy)]
    ccy_by_key = {
        (f.get("sequence"), f.get("occurrence")): f.get("value")
        for f in ccy
    }
    pairs = {}
    for f in prices:
        key = (f.get("sequence"), f.get("occurrence"))
        pairs[f"{f.get('value')}|{ccy_by_key.get(key)}"] = (
            f.get("value"), ccy_by_key.get(key))
    if not pairs:
        return {"value": None, "status": ABSENT, "raw": None,
                "provenance": provenance}
    if len(pairs) > 1:
        return {"value": None, "status": CONFLICTING, "raw": None,
                "provenance": provenance}
    raw, currency = next(iter(pairs.values()))
    try:
        normalized = format(
            Decimal(str(raw).replace(",", ".")), "f")
    except InvalidOperation:
        return {"value": None, "status": CONFLICTING, "raw": None,
                "provenance": provenance}
    return {"value": {"normalized": normalized, "currency": currency},
            "status": PRESENT, "raw": raw, "provenance": provenance}


def project_ca_message(facts_doc: dict, now: str | None = None) -> dict:
    """CA_ES_SWIFT_MT_FACTS_V1 -> CA_ES_SWIFT_CA_MESSAGE_V1."""
    if facts_doc.get("schema_version") != FACTS_SCHEMA:
        raise ValueError(
            f"facts schema debe ser {FACTS_SCHEMA}, "
            f"recibido {facts_doc.get('schema_version')!r}"
        )
    facts = facts_doc.get("facts") or []
    genl = [f for f in facts if f.get("sequence") == "GENL"]

    caev_facts = _find(genl, "22F", "CAEV", label_suffix=".indicator")
    caev = _field(caev_facts)
    caev_val = caev["value"]
    event_type = CAEV_MAP.get(caev_val) if caev_val else None
    if facts_doc.get("parse_status") != "OK":
        status = "PARSE_NOT_OK"
    elif caev_val is None or caev_val not in CAEV_MAP:
        status = UNSUPPORTED_CA_EVENT
    else:
        status = "OK"

    fields = {
        "corporate_action_reference": _field(
            _find(genl, "20C", "CORP", label_suffix=".reference")),
        "related_reference": _field(
            _find(genl, "20C", "RELA", label_suffix=".reference")),
        "caev": caev,
        "isin": _field(
            # el ISIN de binding es el underlying (USECU; USEQ en
            # fixtures informales): un SECMOVE/CASHMOVE puede mover
            # un instrumento distinto sin contaminar la identidad
            _find(facts, "35B", seq="USECU", label_suffix=".isin")
            or _find(facts, "35B", seq="USEQ", label_suffix=".isin")
            or _find(facts, "35B", label_suffix=".isin")),
        "ex_date": _field(
            _find(facts, "98A", "XDTE", label_suffix=".date")
            + _find(facts, "98C", "XDTE", label_suffix=".date"),
            normalize=_norm_date),
        "record_date": _field(
            _find(facts, "98A", "RDTE", label_suffix=".date")
            + _find(facts, "98C", "RDTE", label_suffix=".date"),
            normalize=_norm_date),
        "payment_date": _field(
            _find(facts, "98A", "PAYD", label_suffix=".date")
            + _find(facts, "98C", "PAYD", label_suffix=".date"),
            normalize=_norm_date),
        "gross_per_share": _field(
            _find(facts, "92J", "GRSS", label_suffix=".amount")
            + _find(facts, "92B", "GRSS", label_suffix=".amount")
            + _find(facts, "92B", "GRSS", label_suffix=".rate"),
            normalize=_norm_amount),
        "currency": _field(
            _find(facts, "19B", "GRSS", label_suffix=".currency code")),
        "message_function": _field(
            _find(genl, "23G", label_suffix=".function")),
        "processing_status": _field(
            _find(genl, "25D", label_suffix=".status code")),
        # P8.1: operandos de familias de valores (SPLIT & co)
        "camv": _field(
            _find(genl, "22F", "CAMV", label_suffix=".indicator")),
        "new_for_old_ratio": _new_for_old(facts),
        "fraction_disposition": _field(
            _find(facts, "22F", "DISF", label_suffix=".indicator")),
        "target_isin": _target_isin(facts),
        "effective_date": _field(
            _find(facts, "98A", "PAYD", label_suffix=".date",
                  seq_contains="SECMOVE")
            + _find(facts, "98A", "EFFD", label_suffix=".date")
            + _find(facts, "98A", "POST", label_suffix=".date"),
            normalize=_norm_date),
        # P8.2: precio de suscripcion (EXRI; ausente en RHDI/SPLIT)
        "subscription_price": _subscription_price(facts),
    }

    return {
        "schema": CA_MESSAGE_SCHEMA,
        "generated_at": now or _now(),
        "message_identifier": facts_doc.get("message_identifier"),
        "input_sha256": facts_doc.get("input_sha256"),
        "status": status,
        "caev": caev_val,
        "event_type": event_type,
        "mechanism": CAEV_MECHANISM.get(caev_val),
        "fields": fields,
    }


def _event_isins(event: dict) -> set:
    isins = set()
    affected = (event.get("affected_instrument") or {}).get("isin")
    if affected:
        isins.add(affected)
    for fact in event.get("facts", []):
        if fact.get("field_path") in (
            "instrument.isin", "affected_instrument.isin"
        ) and isinstance(fact.get("value"), str):
            isins.add(fact["value"])
    return isins


def _current_dates(event: dict) -> dict:
    """field_path -> conjunto de valores vigentes (facts mas recientes
    por revision; conservador: todos los values del estado CURRENT)."""
    by_field: dict[str, list] = {}
    for fact in event.get("facts", []):
        by_field.setdefault(fact.get("field_path"), []).append(fact)
    current = {}
    for path, fs in by_field.items():
        rev = max(f.get("revision_id") or "" for f in fs)
        latest = [f for f in fs if (f.get("revision_id") or "") == rev]
        values = {json.dumps(f.get("value"), sort_keys=True) for f in latest}
        if len(values) == 1:
            f = latest[0]
            current[path] = {
                "value": f.get("value"),
                "assertion_ids": sorted(
                    x.get("assertion_id") for x in latest),
                "status": "CURRENT",
            }
        else:
            current[path] = {"value": None,
                             "assertion_ids": sorted(
                                 x.get("assertion_id") for x in latest),
                             "status": "CONFLICTING"}
    return current


def _swift_date(fields: dict, name: str):
    f = fields.get(name) or {}
    return f.get("value") if f.get("status") == PRESENT else None


def _date_consistent(swift_date, canon_current: dict, path: str) -> bool:
    """True si la fecha swift no contradice el canon: ausente en
    cualquiera de los dos lados, o igual."""
    if swift_date is None:
        return True
    cur = canon_current.get(path)
    if cur is None or cur["status"] != "CURRENT":
        return True
    return cur["value"] == swift_date


def bind_event(ca_message: dict, canon_doc: dict,
               now: str | None = None) -> dict:
    """CA_ES_SWIFT_CA_MESSAGE_V1 + canon -> CA_ES_SWIFT_EVENT_BINDING_V1."""
    if ca_message.get("schema") != CA_MESSAGE_SCHEMA:
        raise ValueError(
            f"message schema debe ser {CA_MESSAGE_SCHEMA}, "
            f"recibido {ca_message.get('schema')!r}"
        )
    fields = ca_message.get("fields") or {}
    event_type = ca_message.get("event_type")
    isin_f = fields.get("isin") or {}
    isin = isin_f.get("value") if isin_f.get("status") == PRESENT else None

    base = {
        "schema": BINDING_SCHEMA,
        "generated_at": now or _now(),
        "message_identifier": ca_message.get("message_identifier"),
        "input_sha256": ca_message.get("input_sha256"),
        "caev": ca_message.get("caev"),
        "event_type": event_type,
        "candidates": [],
        "canonical_event_id": None,
        "comparisons": [],
    }

    if ca_message.get("status") != "OK":
        return {**base, "binding_status": ca_message["status"],
                "reasons": ["MESSAGE_NOT_PROJECTABLE"]}

    reasons = []
    if event_type is None:
        reasons.append("MISSING_EVENT_TYPE")
    if not isin:
        reasons.append("MISSING_ISIN")
    if reasons:
        return {**base, "binding_status": INSUFFICIENT_IDENTITY,
                "reasons": reasons}

    events = canon_doc.get("events", [])
    candidates = [
        e for e in events
        if e.get("event_type") == event_type and isin in _event_isins(e)
    ]
    if not candidates:
        return {**base, "binding_status": NO_MATCH,
                "reasons": ["NO_EVENT_MATCHES_IDENTITY"]}

    if len(candidates) > 1:
        # desambiguacion por fechas disponibles: solo elimina cuando la
        # fecha existe en ambos lados y difiere
        narrowed = [
            e for e in candidates
            if all(
                _date_consistent(_swift_date(fields, n),
                                 _current_dates(e), "date." + n)
                for n in _DISAMBIG_DATES
            )
        ]
        if len(narrowed) == 1:
            candidates = narrowed
        elif not narrowed:
            return {
                **base,
                "binding_status": NO_MATCH,
                "candidates": sorted(
                    e["canonical_event_id"] for e in candidates),
                "reasons": ["DATES_EXCLUDE_ALL_CANDIDATES"],
            }
        else:
            return {
                **base,
                "binding_status": AMBIGUOUS,
                "candidates": sorted(
                    e["canonical_event_id"] for e in narrowed),
                "reasons": ["MULTIPLE_CANDIDATES"],
            }

    event = candidates[0]
    current = _current_dates(event)
    currency_f = fields.get("currency") or {}
    swift_currency = (
        currency_f.get("value")
        if currency_f.get("status") == PRESENT else None
    )
    comparisons = [
        _compare(name, fields.get(name), current.get(path),
                 swift_currency=swift_currency)
        for name, path in _COMPARE_FIELDS
    ]
    return {
        **base,
        "binding_status": BOUND,
        "candidates": [event["canonical_event_id"]],
        "canonical_event_id": event["canonical_event_id"],
        "comparisons": comparisons,
        "reasons": [],
    }


def _compare(field_name: str, swift_field: dict | None,
             canon_current, swift_currency: str | None = None) -> dict:
    swift = swift_field or {}
    entry = {
        "field": field_name,
        "swift_value": swift.get("value"),
        "swift_status": swift.get("status", ABSENT),
        "swift_provenance": swift.get("provenance") or [],
        "canon_value": (
            canon_current.get("value") if canon_current else None
        ),
        "canon_assertion_ids": (
            canon_current.get("assertion_ids") if canon_current else []
        ),
    }
    if swift.get("status") != PRESENT:
        entry["status"] = SWIFT_MISSING
    elif canon_current is None:
        entry["status"] = CANON_MISSING
    elif canon_current["status"] == "CONFLICTING":
        entry["status"] = CANON_CONFLICTING
    else:
        canon_val = canon_current["value"]
        swift_val = swift["value"]
        if isinstance(canon_val, dict) and canon_val.get("__financial__"):
            entry["canon_currency"] = canon_val.get("currency")
            try:
                amounts_equal = (
                    Decimal(str(canon_val["normalized"]))
                    == Decimal(str(swift_val))
                )
            except InvalidOperation:
                amounts_equal = False
            currency_conflict = (
                swift_currency is not None
                and canon_val.get("currency") is not None
                and swift_currency != canon_val["currency"]
            )
            entry["status"] = (
                AGREES
                if amounts_equal and not currency_conflict
                else DIFFERS
            )
        else:
            entry["status"] = (
                AGREES if canon_val == swift_val else DIFFERS
            )
    return entry


def project_and_bind(facts_doc: dict, canon_doc: dict,
                     now: str | None = None) -> dict:
    """Cadena completa facts -> message -> binding."""
    msg = project_ca_message(facts_doc, now=now)
    binding = bind_event(msg, canon_doc, now=now)
    binding["ca_message"] = msg
    return binding
