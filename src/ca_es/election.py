"""P5.2 — Election Opportunity.

docs/p5/p52-scope.md:

    CA_ES_SWIFT_MT_FACTS_V1 (MT564) + BOUND canon event
    [+ CA_ES_ACTION_QUEUE_V1]
        -> CA_ES_ELECTION_OPPORTUNITY_V1

Solo responde: que opciones comunico explicitamente la fuente y que
deadline operativo conocido esta asociado. Sin positions, sin
instrucciones, sin MT565, sin mutar canon.

Reglas duras:

- ausencia de CAOPTN != NON_ELECTIVE -> INDETERMINATE
- ausencia de DFLT != "primera opcion default" -> UNKNOWN
- source_response_deadline (RDDT) != deadline operativo P5
- multiples deadlines operativos aplicables -> AMBIGUOUS, nunca el
  mas temprano
- whitelist option_kind cerrada: CASH->CASH, SECU->SECURITIES;
  cualquier otro CAOP -> UNSUPPORTED con option_code_raw preservado
- binding canon/queue fail-closed (P5.1.1)
"""

from __future__ import annotations

from .swift_ca import (
    BOUND,
    _now,
    _norm_date,
    bind_event,
    project_ca_message,
)

OPPORTUNITY_SCHEMA = "CA_ES_ELECTION_OPPORTUNITY_V1"

PROJECTED = "PROJECTED"
INDETERMINATE = "INDETERMINATE"
UNSUPPORTED = "UNSUPPORTED"

# whitelist cerrada SRU2025 (docs/p5/p52-scope.md)
OPTION_KIND = {
    "CASH": "CASH",
    "SECU": "SECURITIES",
}

OPTION_SEQ_MARKER = "/CAOPTN"


def _prov(fact):
    return {
        "source_tag": fact.get("source_tag"),
        "source_qualifier": fact.get("source_qualifier"),
        "sequence": fact.get("sequence"),
        "occurrence": fact.get("occurrence"),
        "evidence_locator": fact.get("evidence_locator"),
        "raw": fact.get("value"),
    }


def _is_caoptn(fact):
    return OPTION_SEQ_MARKER in (fact.get("sequence") or "")


def _is_direct(fact):
    """Fact directamente en el bloque CAOPTN (no en sub-secuencia)."""
    seq = fact.get("sequence") or ""
    return seq.endswith("CAOPTN")


def _match(fact, tag, qualifier):
    return (fact.get("source_tag") == tag
            and fact.get("source_qualifier") == qualifier)


def _single(facts, tag, qualifier, suffix):
    """Valores unicos de un campo directo; (value, conflicting)."""
    vals = {
        f.get("value") for f in facts
        if _is_direct(f) and _match(f, tag, qualifier)
        and (f.get("field_path") or "").endswith(suffix)
    }
    vals.discard(None)
    if len(vals) == 1:
        return next(iter(vals)), False
    return (None, len(vals) > 1)


def project_election(facts_doc: dict, canon_doc: dict,
                     queue_doc: dict | None = None,
                     deadline_types: tuple = (),
                     now: str | None = None) -> dict:
    """facts + canon [+ queue] -> CA_ES_ELECTION_OPPORTUNITY_V1.

    read-only: no muta facts, canon ni queue.
    """
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

    if facts_doc.get("message_identifier") != "MT564":
        return {**base, "projection_status": UNSUPPORTED,
                "reasons": ["UNSUPPORTED_MESSAGE_TYPE"]}

    msg = project_ca_message(facts_doc, now=now)
    if msg.get("status") == "UNSUPPORTED_CA_EVENT":
        return {**base, "projection_status": UNSUPPORTED,
                "reasons": ["UNSUPPORTED_CA_EVENT"]}

    binding = bind_event(msg, canon_doc, now=now)
    eid = binding.get("canonical_event_id")
    base["canonical_event_id"] = eid
    reasons = []
    if binding.get("binding_status") != BOUND:
        reasons.append("EVENT_NOT_BOUND")

    # --- opciones: anclas CAON en orden de documento -------------
    pos = {id(f): i for i, f in enumerate(facts)}
    caoptn_facts = [f for f in facts if _is_caoptn(f)]
    anchors = [
        f for f in caoptn_facts
        if _is_direct(f) and _match(f, "22F", "CAON")
    ]
    if not caoptn_facts:
        reasons.append("NO_OPTION_EVIDENCE")
    elif not anchors:
        reasons.append("MISSING_OPTION_IDENTITY")
    else:
        # facts de CAOPTN anteriores a la primera ancla: huerfanos
        first_anchor = pos[id(anchors[0])]
        if any(pos[id(f)] < first_anchor for f in caoptn_facts):
            reasons.append("ORPHAN_OPTION_FACTS")

    options = []
    if anchors:
        seen_ids = set()
        for i, anchor in enumerate(anchors):
            start = pos[id(anchor)]
            end = (pos[id(anchors[i + 1])]
                   if i + 1 < len(anchors) else len(facts))
            group = [
                f for f in caoptn_facts
                if start <= pos[id(f)] < end
            ]
            ident = anchor.get("value")
            if ident in seen_ids:
                reasons.append("CONFLICTING_OPTION_IDENTITY")
            seen_ids.add(ident)

            code, code_conflict = _single(group, "22F", "CAOP",
                                          ".indicator")
            dflt, dflt_conflict = _single(group, "17B", "DFLT",
                                          ".flag")
            rddt, rddt_conflict = _single(group, "98A", "RDDT",
                                          ".date")
            if not rddt:
                rddt, rddt_conflict2 = _single(group, "98C", "RDDT",
                                               ".date")
                rddt_conflict = rddt_conflict or rddt_conflict2
            if code_conflict or dflt_conflict or rddt_conflict:
                reasons.append("CONFLICTING_OPTION_FACTS")

            default_status = (
                "CONFLICTING" if dflt_conflict
                else {"Y": "DEFAULT", "N": "NOT_DEFAULT"}.get(
                    dflt, "UNKNOWN")
            )
            terms = [
                _prov(f) for f in group
                if not _is_direct(f)
            ]
            provenance = [
                _prov(f) for f in group if _is_direct(f)
            ]
            options.append({
                "option_key": f"{eid}|option:{ident}",
                "option_identifier": ident,
                "option_code_raw": code,
                "option_kind": OPTION_KIND.get(code, "UNSUPPORTED"),
                "default_status": default_status,
                "source_response_deadline": _norm_date(rddt),
                "terms": terms,
                "provenance": provenance,
            })

    base["options"] = options

    # deadline comunicado por la fuente: unico solo si todas coinciden
    rddts = {o["source_response_deadline"] for o in options}
    rddts.discard(None)
    if len(rddts) == 1:
        base["source_response_deadline"] = next(iter(rddts))

    # --- binding con queue operativa (sin recalcular) ------------
    if queue_doc is not None:
        if not deadline_types:
            raise ValueError("MISSING_DEADLINE_TYPE_CONFIG")
        if queue_doc.get("source_canon_logical_sha256") != canon_sha:
            raise ValueError("QUEUE_CANON_MISMATCH")
        applicable = [
            i for i in queue_doc.get("items", [])
            if i.get("canonical_event_id") == eid
            and i.get("deadline_type") in deadline_types
        ]
        base["operational_deadlines"] = applicable
        if len(applicable) == 1:
            base["deadline_binding_status"] = "BOUND"
        elif not applicable:
            base["deadline_binding_status"] = "MISSING"
        else:
            base["deadline_binding_status"] = "AMBIGUOUS"

    base["reasons"] = sorted(set(reasons))
    base["projection_status"] = (
        INDETERMINATE if reasons else PROJECTED
    )
    return base
