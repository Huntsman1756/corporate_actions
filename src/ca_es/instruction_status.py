"""P5.6 — MT567 status/advice: binding a instrucción emitida.

    MT567 FIN -> adapter JVM -> CA_ES_SWIFT_MT_FACTS_V1 (MT567)
    + CA_ES_ELECTION_INSTRUCTION_V1 (target)
        -> CA_ES_ELECTION_INSTRUCTION_STATUS_V1

La observación de status es separada del intent (P5.4): nunca muta
CA_ES_ELECTION_INSTRUCTION_V1, no es workflow humano y no reinterpreta
recon P3.5. Binding exclusivamente por referencias explícitas
`GENL/LINK 20C::PREV` (el SEME que P5.5 emitió = instruction_id);
nunca fuzzy matching.

docs/p5/p56-scope.md.
"""

from __future__ import annotations

import re
from typing import Any

from .election_instruction import INSTRUCTION_SCHEMA
from .swift_ca import _now
from .swift_mt import FACTS_SCHEMA

STATUS_DOC_SCHEMA = "CA_ES_ELECTION_INSTRUCTION_STATUS_V1"

BOUND = "BOUND"
AMBIGUOUS = "AMBIGUOUS"
NO_MATCH = "NO_MATCH"
INSUFFICIENT_IDENTITY = "INSUFFICIENT_IDENTITY"

# whitelist preregistrada: solo 25D qualifier IPRC
NORMALIZED_STATUS = {
    "PACK": "ACCEPTED",
    "REJT": "REJECTED",
    "PEND": "PENDING",
    "DFLA": "DEFAULT_ACTION_APPLIED",
}

_TAG_INDEX_RE = re.compile(r"block4\.tag\[(\d+)\]")


def _tag_index(fact: dict) -> int:
    match = _TAG_INDEX_RE.search(str(fact.get("evidence_locator") or ""))
    return int(match.group(1)) if match else -1


def _facts(facts_doc: dict) -> list[dict]:
    return [
        f for f in facts_doc.get("facts") or [] if isinstance(f, dict)
    ]


def _fact_values(
    facts: list[dict], seq: str, tag: str, qualifier: str
) -> list[str]:
    return [
        f["value"]
        for f in facts
        if f.get("sequence") == seq
        and f.get("source_tag") == tag
        and f.get("source_qualifier") == qualifier
        and isinstance(f.get("value"), str)
    ]


def bind_instruction_status(
    facts_doc: dict, instruction_doc: dict, *, now: str | None = None
) -> dict:
    """facts MT567 + instruction -> CA_ES_ELECTION_INSTRUCTION_STATUS_V1.

    read-only: no muta ningún input.
    """
    if (
        not isinstance(facts_doc, dict)
        or facts_doc.get("schema_version") != FACTS_SCHEMA
    ):
        raise ValueError("INVALID_SWIFT_FACTS_DOCUMENT")
    if facts_doc.get("message_identifier") != "MT567":
        raise ValueError("EXPECTED_MT567")
    if (
        not isinstance(instruction_doc, dict)
        or instruction_doc.get("schema") != INSTRUCTION_SCHEMA
    ):
        raise ValueError("INVALID_INSTRUCTION_DOCUMENT")

    facts = _facts(facts_doc)
    instruction_id = instruction_doc.get("instruction_id")

    # --- binding: solo LINK 20C::PREV explícito ---------------------
    prevs = sorted(
        set(_fact_values(facts, "GENL/LINK", "20C", "PREV"))
    )
    if not prevs:
        binding = INSUFFICIENT_IDENTITY
    elif instruction_id in prevs and len(prevs) == 1:
        binding = BOUND
    elif instruction_id in prevs:
        binding = AMBIGUOUS
    else:
        binding = NO_MATCH

    # --- función del mensaje (23G raw) ----------------------------
    functions = [
        f["value"]
        for f in facts
        if f.get("sequence") == "GENL"
        and f.get("source_tag") == "23G"
        and isinstance(f.get("value"), str)
    ]
    message_function = functions[0] if functions else None
    reasons: list[str] = []
    if message_function != "INST":
        reasons.append("MESSAGE_FUNCTION_NOT_INST")

    # --- statuses: un entry por 25D en GENL/STAT --------------------
    stat_25d = sorted(
        (
            f
            for f in facts
            if f.get("sequence") == "GENL/STAT"
            and f.get("source_tag") == "25D"
        ),
        key=_tag_index,
    )
    reas_facts = sorted(
        (
            f
            for f in facts
            if f.get("sequence") == "GENL/STAT/REAS"
        ),
        key=_tag_index,
    )
    stat_bounds = [_tag_index(f) for f in stat_25d]

    statuses: list[dict] = []
    for i, sf in enumerate(stat_25d):
        lo = stat_bounds[i]
        hi = (
            stat_bounds[i + 1]
            if i + 1 < len(stat_bounds)
            else 1 << 62
        )
        window = [
            r for r in reas_facts if lo < _tag_index(r) < hi
        ]
        reason_code = next(
            (r for r in window if r.get("source_tag") == "24B"), None
        )
        narrative = next(
            (r for r in window if r.get("source_tag") == "70D"), None
        )
        qualifier = sf.get("source_qualifier")
        code = sf.get("value")
        normalized = (
            NORMALIZED_STATUS.get(code)
            if qualifier == "IPRC"
            else None
        )
        statuses.append(
            {
                "sequence": "GENL/STAT",
                "sequence_occurrence": sf.get("occurrence"),
                "status_qualifier": qualifier,
                "status_code_raw": code,
                "normalized_status": normalized or "UNSUPPORTED",
                "reason_qualifier": (
                    reason_code.get("source_qualifier")
                    if reason_code
                    else None
                ),
                "reason_code_raw": (
                    reason_code.get("value") if reason_code else None
                ),
                "reason_narrative": (
                    narrative.get("value") if narrative else None
                ),
                "provenance": [
                    f["field_path"]
                    for f in [sf, *window]
                    if f.get("field_path")
                ],
            }
        )

    doc: dict[str, Any] = {
        "schema": STATUS_DOC_SCHEMA,
        "generated_at": now or _now(),
        "source_message_identifier": "MT567",
        "input_sha256": facts_doc.get("input_sha256"),
        "instruction_id": instruction_id,
        "instruction_binding_status": binding,
        "canonical_event_id": None,
        "source_canon_logical_sha256": None,
        "source_positions_logical_sha256": None,
        "source_message_input_sha256": None,
        "message_function": message_function,
        "reasons": reasons,
        "statuses": statuses,
    }
    if binding == BOUND:
        doc["canonical_event_id"] = instruction_doc.get(
            "canonical_event_id"
        )
        doc["source_canon_logical_sha256"] = instruction_doc.get(
            "source_canon_logical_sha256"
        )
        doc["source_positions_logical_sha256"] = instruction_doc.get(
            "source_positions_logical_sha256"
        )
        doc["source_message_input_sha256"] = instruction_doc.get(
            "source_message_input_sha256"
        )
    return doc
