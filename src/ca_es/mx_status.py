"""P4.6 — seev.034 status/advice: binding a instrucción emitida.

    seev.034 XML -> adapter JVM -> CA_ES_SWIFT_MX_FACTS_V1
    + CA_ES_ELECTION_INSTRUCTION_V1 (target)
        -> CA_ES_ELECTION_INSTRUCTION_STATUS_V1

Mismo contrato que P5.6 (transport-neutral). La observación de status
es separada del intent: nunca muta CA_ES_ELECTION_INSTRUCTION_V1, no
es workflow humano y no reinterpreta recon P3.5. Binding exclusivamente
por `InstrId/Id` (el identificador del documento de instrucción
relacionado; P4.5 lo emite como BizMsgIdr == instruction_id); nunca
fuzzy matching, nunca `CorpActnEvtId` como clave.

El status seev.034 es estructural: el nombre del choice element bajo
`InstrPrcgSts[k]` es el status raw. Razones: leaf facts bajo la misma
ocurrencia con `Rsn`/`NoSpcfdRsn`/`AddtlRsnInf` en el path.

docs/p4/p46-seev034-scope.md.
"""

from __future__ import annotations

import re
from typing import Any

from .election_instruction import INSTRUCTION_SCHEMA
from .mx_facts import FACTS_SCHEMA as MX_FACTS_SCHEMA
from .swift_ca import _now

STATUS_DOC_SCHEMA = "CA_ES_ELECTION_INSTRUCTION_STATUS_V1"

BOUND = "BOUND"
AMBIGUOUS = "AMBIGUOUS"
NO_MATCH = "NO_MATCH"
INSUFFICIENT_IDENTITY = "INSUFFICIENT_IDENTITY"

# whitelist preregistrada: choice elements de
# InstructionProcessingStatus58Choice (seev.034.001/.002, javap-verificado)
NORMALIZED_STATUS = {
    "AccptdForFrthrPrcg": "ACCEPTED",
    "Rjctd": "REJECTED",
    "Pdg": "PENDING",
    "DfltActn": "DEFAULT_ACTION_APPLIED",
    "Canc": "UNSUPPORTED",
    "Fwdd": "UNSUPPORTED",
    "Rtrd": "UNSUPPORTED",
    "StgInstr": "UNSUPPORTED",
    "PrtrySts": "UNSUPPORTED",
    "RcvdByIssrOrOfferr": "UNSUPPORTED",
}

_STS_PREFIX = "/CorpActnInstrStsAdvc/InstrPrcgSts/"
_STS_OCC_RE = re.compile(r"InstrPrcgSts\[(\d+)\]")


def _facts(facts_doc: dict) -> list[dict]:
    return [
        f for f in facts_doc.get("facts") or [] if isinstance(f, dict)
    ]


def _values(facts: list[dict], path: str) -> list[str]:
    return [
        f["value"]
        for f in facts
        if f.get("model_path") == path and isinstance(f.get("value"), str)
    ]


def _sts_occurrence(fact: dict) -> int:
    m = _STS_OCC_RE.search(str(fact.get("evidence_locator") or ""))
    return int(m.group(1)) if m else -1


def bind_mx_instruction_status(
    facts_doc: dict, instruction_doc: dict, *, now: str | None = None
) -> dict:
    """facts seev.034 + instruction -> CA_ES_ELECTION_INSTRUCTION_STATUS_V1.

    read-only: no muta ningún input.
    """
    if (
        not isinstance(facts_doc, dict)
        or facts_doc.get("schema_version") != MX_FACTS_SCHEMA
    ):
        raise ValueError("INVALID_MX_FACTS_DOCUMENT")
    mid = facts_doc.get("message_identifier") or ""
    if not re.fullmatch(r"seev\.034\.\d{3}\.\d{2}", mid):
        raise ValueError("EXPECTED_SEEV034")
    if facts_doc.get("parse_status") != "PARSE_OK":
        raise ValueError("EXPECTED_PARSE_OK")
    if (
        not isinstance(instruction_doc, dict)
        or instruction_doc.get("schema") != INSTRUCTION_SCHEMA
    ):
        raise ValueError("INVALID_INSTRUCTION_DOCUMENT")

    facts = _facts(facts_doc)
    instruction_id = instruction_doc.get("instruction_id")

    # --- binding: solo InstrId/Id explícito -------------------------
    instr_ids = sorted(
        set(_values(facts, "/Document/CorpActnInstrStsAdvc/InstrId/Id"))
    )
    if not instr_ids:
        binding = INSUFFICIENT_IDENTITY
    elif instruction_id in instr_ids and len(instr_ids) == 1:
        binding = BOUND
    elif instruction_id in instr_ids:
        binding = AMBIGUOUS
    else:
        binding = NO_MATCH

    # --- statuses: un entry por ocurrencia InstrPrcgSts[k] ----------
    sts_facts = [
        f
        for f in facts
        if _STS_PREFIX in str(f.get("model_path") or "")
    ]
    groups: dict[int, list[dict]] = {}
    for f in sts_facts:
        groups.setdefault(_sts_occurrence(f), []).append(f)

    statuses: list[dict] = []
    for occ in sorted(groups):
        group = groups[occ]
        choices = sorted(
            {
                str(f["model_path"]).split(_STS_PREFIX, 1)[1].split("/")[0]
                for f in group
            }
        )
        choice = choices[0] if len(choices) == 1 else "CONFLICTING"
        normalized = NORMALIZED_STATUS.get(choice, "UNSUPPORTED")
        rsn_facts = [
            f
            for f in group
            if isinstance(f.get("value"), str)
            and (
                str(f["model_path"]).endswith("/NoSpcfdRsn")
                or "/RsnCd/" in str(f["model_path"])
                or str(f["model_path"]).endswith("/Rsn/Cd")
            )
        ]
        codes = sorted(f["value"] for f in rsn_facts)
        narratives = sorted(
            f["value"]
            for f in group
            if isinstance(f.get("value"), str)
            and str(f["model_path"]).endswith("/AddtlRsnInf")
        )
        statuses.append(
            {
                "sequence": "CorpActnInstrStsAdvc/InstrPrcgSts",
                "sequence_occurrence": occ,
                "status_qualifier": choice,
                "status_code_raw": choice,
                "normalized_status": normalized,
                "reason_qualifier": (
                    str(rsn_facts[0]["model_path"]).rsplit("/", 1)[-1]
                    if rsn_facts
                    else None
                ),
                "reason_code_raw": codes[0] if codes else None,
                "reason_narrative": narratives[0] if narratives else None,
                "provenance": [
                    f["model_path"] for f in group if f.get("model_path")
                ],
            }
        )

    doc: dict[str, Any] = {
        "schema": STATUS_DOC_SCHEMA,
        "generated_at": now or _now(),
        "source_message_identifier": mid,
        "input_sha256": facts_doc.get("input_sha256"),
        "instruction_id": instruction_id,
        "instruction_binding_status": binding,
        "canonical_event_id": None,
        "source_canon_logical_sha256": None,
        "source_positions_logical_sha256": None,
        "source_message_input_sha256": None,
        "message_function": mid,
        "reasons": [],
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
