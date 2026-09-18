"""P13.5/P13.10 — custody reconciliation (capa aditiva).

CA_ES_POSITIONS_V1 (esperado) + snapshot COMPLETE
    -> CA_ES_POSITION_RECON_V1

CA_ES_CASH_MOVEMENTS_V2 (movimientos conocidos) +
CA_ES_CASH_ACCOUNT_OBSERVATION_V1
    -> CA_ES_CASH_FEED_RECON_V1

Reglas:

- Decimal exacto, sin tolerancias, sin netting, sin agregacion;
- PROJECTED_POSITION != BOOKED_CUSTODY_POSITION: el "expected" es
  otro documento de posiciones (snapshot previo o input manual),
  nunca expectativas economicas de P6;
- cash feed recon solo compara cuando la identidad es explicita
  (referencia del movement resuelta contra refs de la entry);
  importe/fecha no son identidad.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

POSITION_RECON_SCHEMA = "CA_ES_POSITION_RECON_V1"
CASH_FEED_RECON_SCHEMA = "CA_ES_CASH_FEED_RECON_V1"

MATCH = "MATCH"
QUANTITY_MISMATCH = "POSITION_QUANTITY_MISMATCH"
MISSING_AT_CUSTODIAN = "POSITION_MISSING_AT_CUSTODIAN"
UNEXPECTED_AT_CUSTODIAN = "POSITION_UNEXPECTED_AT_CUSTODIAN"
INDETERMINATE = "INDETERMINATE"

AMOUNT_MISMATCH = "CASH_ACCOUNT_AMOUNT_MISMATCH"
MISSING_IN_ACCOUNT_FEED = "CASH_MISSING_IN_ACCOUNT_FEED"
UNEXPECTED_ACCOUNT_ENTRY = "CASH_UNEXPECTED_ACCOUNT_ENTRY"


def _dec(value):
    if isinstance(value, float):
        return None
    try:
        d = Decimal(str(value))
        return d if d.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def position_recon(expected_doc: dict, custody_doc: dict,
                   now: str | None = None) -> dict:
    """expected CA_ES_POSITIONS_V1 vs custody CA_ES_POSITIONS_V1.

    Ambos lados son el mismo contrato: expected = posiciones
    internas/input previo; custody_doc = proyeccion del snapshot
    (positions_doc()). La completitud viaja en `_snapshot` —
    un doc proyectado desde snapshot no-COMPLETE es INDETERMINATE,
    nunca "vacio".
    """
    items = []
    snap_meta = custody_doc.get("_snapshot") or {}
    completeness = (snap_meta.get("completeness")
                    or custody_doc.get("completeness")
                    or "COMPLETE")
    if completeness != "COMPLETE":
        return {
            "schema": POSITION_RECON_SCHEMA,
            "generated_at": now,
            "snapshot_id": snap_meta.get("snapshot_id"),
            "case_scope": "custody-positions",
            "status": INDETERMINATE,
            "reason": "SNAPSHOT_NOT_COMPLETE",
            "items": [],
        }

    expected = {}
    for p in expected_doc.get("positions") or []:
        key = (p.get("account_id"), p.get("isin"))
        expected[key] = expected.get(key, Decimal(0)) + (
            _dec(p.get("quantity")) or Decimal(0))

    observed = {}
    doc_account = (custody_doc.get("account_id")
                   or custody_doc.get("account_id_raw"))
    for p in custody_doc.get("positions") or []:
        # snapshots crudos no llevan account por posicion: el doc
        # es mono-cuenta y su identidad top-level es la del slot
        key = (p.get("account_id") or doc_account, p.get("isin"))
        observed[key] = observed.get(key, Decimal(0)) + (
            _dec(p.get("quantity")) or Decimal(0))

    for key in sorted(set(expected) | set(observed)):
        account_id, isin = key
        exp, obs = expected.get(key), observed.get(key)
        if exp is not None and obs is not None:
            status = MATCH if exp == obs else QUANTITY_MISMATCH
        elif obs is None:
            status = MISSING_AT_CUSTODIAN
        else:
            status = UNEXPECTED_AT_CUSTODIAN
        item = {
            "account_id": account_id,
            "isin": isin,
            "status": status,
            "expected_quantity": format(exp, "f") if exp is not None
            else None,
            "actual_quantity": format(obs, "f") if obs is not None
            else None,
        }
        if exp is not None and obs is not None:
            item["delta"] = {
                "normalized": format(obs - exp, "f"),
                "scale": -(obs - exp).as_tuple().exponent,
            }
        items.append(item)

    return {
        "schema": POSITION_RECON_SCHEMA,
        "generated_at": now,
        "snapshot_id": (snap_meta.get("snapshot_id")
                        or custody_doc.get("snapshot_id")),
        "case_scope": "custody-positions",
        "status": "OK",
        "items": items,
        "summary": {
            status: sum(1 for i in items if i["status"] == status)
            for status in (MATCH, QUANTITY_MISMATCH,
                           MISSING_AT_CUSTODIAN, UNEXPECTED_AT_CUSTODIAN)
        },
    }


def cash_feed_recon(movements_doc: dict, observation: dict,
                    now: str | None = None) -> dict:
    """movimientos conocidos vs entries de la cuenta.

    Identidad explicita: movement.source_reference /
    source_entry_id contra refs de la entry. Si el movement no
    porta referencia resoluble -> INDETERMINATE, no "ausente".
    """
    entries = observation.get("entries") or []

    def _entry_ref_values(entry):
        values = {entry.get("entry_id"),
                  entry.get("customer_reference"),
                  entry.get("transaction_reference"),
                  entry.get("account_servicer_reference")}
        structured = (entry.get("structured_details") or {}).get(
            "refs") or {}
        values.update(structured.values())
        return {str(v) for v in values if v}

    items = []
    matched_entry_indexes = set()
    for m in movements_doc.get("movements") or []:
        # solo refs que el feed pueda devolver explicitamente;
        # movement_id solo cuenta si la entry lo repite verbatim
        feed_refs = {str(v) for v in (
            m.get("source_reference"), m.get("source_entry_id"))
            if v}
        mrefs = feed_refs | ({str(m["movement_id"])}
                             if m.get("movement_id") else set())
        hit = None
        for i, e in enumerate(entries):
            if mrefs & _entry_ref_values(e):
                hit = (i, e)
                break
        if hit is None:
            items.append({
                "movement_id": m.get("movement_id"),
                "account_id": m.get("account_id"),
                "status": INDETERMINATE if not feed_refs
                else MISSING_IN_ACCOUNT_FEED,
                "reason": ("NO_REFERENCE_ON_MOVEMENT" if not feed_refs
                           else "REFERENCED_ENTRY_ABSENT"),
                "expected_amount": m.get("amount"),
                "currency": m.get("currency"),
            })
            continue
        i, e = hit
        matched_entry_indexes.add(i)
        m_amt, e_amt = _dec(m.get("amount")), _dec(e.get("amount"))
        same_ccy = (not m.get("currency") or not e.get("currency")
                    or m["currency"] == e["currency"])
        if m_amt is not None and e_amt is not None and same_ccy:
            status = MATCH if m_amt == e_amt else AMOUNT_MISMATCH
        else:
            status = INDETERMINATE
        items.append({
            "movement_id": m.get("movement_id"),
            "account_id": m.get("account_id"),
            "entry_id": e.get("entry_id"),
            "status": status,
            "expected_amount": m.get("amount"),
            "actual_amount": e.get("amount"),
            "currency": e.get("currency") or m.get("currency"),
            "value_date": e.get("value_date"),
        })

    return {
        "schema": CASH_FEED_RECON_SCHEMA,
        "generated_at": now,
        "case_scope": "custody-cash",
        "source_message_identifier":
            observation.get("source_message_identifier"),
        "input_sha256": observation.get("input_sha256"),
        "items": items,
        "unmatched_feed_entries": sum(
            1 for i in range(len(entries))
            if i not in matched_entry_indexes),
        "summary": {
            s: sum(1 for i in items if i["status"] == s)
            for s in (MATCH, AMOUNT_MISMATCH, MISSING_IN_ACCOUNT_FEED,
                      INDETERMINATE)
        },
    }
