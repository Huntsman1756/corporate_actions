"""P5.5 — MT565 projection y envío al writer JVM (Prowide).

Proyección determinista:

    CA_ES_ELECTION_INSTRUCTION_V1 (READY)
    + CA_ES_SWIFT_MT_FACTS_V1      (el MT564 fuente)
    + CA_ES_SWIFT_MT565_ENVELOPE_V1 (transporte explícito)
        -> CA_ES_MT565_PROJECTION_V1 (SERIALIZABLE | NOT_SERIALIZABLE)

El FIN lo ensambla exclusivamente el adapter JVM
(``java -jar iso-adapter.jar mt565``); el core nunca genera SWIFT
(ADR-010, docs/p5/p55-scope.md).

No muta la instrucción, los facts ni el envelope.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .election_instruction import INSTRUCTION_SCHEMA, READY
from .swift_mt import (
    FACTS_SCHEMA,
    AdapterUnavailable,
    default_adapter_jar,
)

ENVELOPE_SCHEMA = "CA_ES_SWIFT_MT565_ENVELOPE_V1"
PROJECTION_SCHEMA = "CA_ES_MT565_PROJECTION_V1"
FIN_SCHEMA = "CA_ES_MT565_FIN_V1"

PROJ_SERIALIZABLE = "SERIALIZABLE"
PROJ_NOT_SERIALIZABLE = "NOT_SERIALIZABLE"

SUPPORTED_OPTION_KINDS = ("CASH", "SECURITIES")

_BIC_RE = re.compile(r"^[A-Z0-9]{8}([A-Z0-9]{3})?$")
_SESSION_RE = re.compile(r"^[0-9]{4}$")
_SEQUENCE_RE = re.compile(r"^[0-9]{6}$")
_PRIORITIES = ("N", "S", "U")


def _utc_now() -> str:
    return (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _require_doc(
    doc: dict | None, schema: str, kind: str,
    key: str = "schema",
) -> dict:
    if not isinstance(doc, dict) or doc.get(key) != schema:
        raise ValueError(f"INVALID_{kind}_DOCUMENT")
    return doc


def _bic11(raw: Any, name: str) -> str:
    if not isinstance(raw, str) or not _BIC_RE.match(raw):
        raise ValueError(f"INVALID_ENVELOPE_FIELD:{name}")
    return raw if len(raw) == 11 else raw + "XXX"


def _envelope_transport(envelope: dict) -> dict[str, str]:
    sender = _bic11(envelope.get("sender_bic"), "sender_bic")
    receiver = _bic11(envelope.get("receiver_bic"), "receiver_bic")
    session = envelope.get("session_number")
    if not isinstance(session, str) or not _SESSION_RE.match(session):
        raise ValueError("INVALID_ENVELOPE_FIELD:session_number")
    sequence = envelope.get("sequence_number")
    if not isinstance(sequence, str) or not _SEQUENCE_RE.match(sequence):
        raise ValueError("INVALID_ENVELOPE_FIELD:sequence_number")
    priority = envelope.get("priority")
    if priority not in _PRIORITIES:
        raise ValueError("INVALID_ENVELOPE_FIELD:priority")
    return {
        "sender_lt": sender + "X",
        "receiver_lt": receiver + "X",
        "session_number": session,
        "sequence_number": sequence,
        "priority": priority,
    }


def _genl_fact_values(
    facts_doc: dict, tag: str, qualifier: str
) -> list[str]:
    out: list[str] = []
    for fact in facts_doc.get("facts") or []:
        if not isinstance(fact, dict):
            continue
        if (
            fact.get("sequence") == "GENL"
            and fact.get("source_tag") == tag
            and fact.get("source_qualifier") == qualifier
        ):
            value = fact.get("value")
            if isinstance(value, str):
                out.append(value)
    return out


def _single_fact(
    facts_doc: dict,
    tag: str,
    qualifier: str,
    missing_reason: str,
    conflicting_reason: str,
    reasons: list[str],
) -> str | None:
    values = _genl_fact_values(facts_doc, tag, qualifier)
    distinct = sorted(set(values))
    if not distinct:
        reasons.append(missing_reason)
        return None
    if len(distinct) > 1:
        reasons.append(conflicting_reason)
        return None
    return distinct[0]


def _swift_quantity(raw: Any) -> tuple[str | None, Decimal | None]:
    try:
        qty = Decimal(str(raw))
    except InvalidOperation:
        return None, None
    if not qty.is_finite():
        return None, None
    text = format(qty, "f").replace(".", ",")
    if "," not in text:
        text += ","
    return text, qty


def mt565_project(
    instruction_doc: dict,
    facts_doc: dict,
    envelope_doc: dict,
    *,
    now: str | None = None,
) -> dict:
    """Instrucción READY + facts MT564 + envelope -> projection doc.

    Fail closed: schema distinto, mismatch facts/instrucción o envelope
    malformado -> ValueError. Resto -> NOT_SERIALIZABLE + reasons.
    """
    _require_doc(instruction_doc, INSTRUCTION_SCHEMA, "INSTRUCTION")
    _require_doc(
        facts_doc, FACTS_SCHEMA, "SWIFT_FACTS", key="schema_version"
    )
    _require_doc(envelope_doc, ENVELOPE_SCHEMA, "ENVELOPE")

    if (
        instruction_doc.get("source_message_input_sha256")
        != facts_doc.get("input_sha256")
    ):
        raise ValueError("INSTRUCTION_FACTS_MISMATCH")

    transport = _envelope_transport(envelope_doc)

    reasons: list[str] = []
    if instruction_doc.get("instruction_status") != READY:
        reasons.append("INSTRUCTION_NOT_READY")
    if facts_doc.get("message_identifier") != "MT564":
        reasons.append("UNSUPPORTED_MESSAGE_TYPE")
    if instruction_doc.get("option_kind") not in SUPPORTED_OPTION_KINDS:
        reasons.append("UNSUPPORTED_OPTION_KIND")

    corp = _single_fact(
        facts_doc, "20C", "CORP",
        "MISSING_CORP_REFERENCE", "CONFLICTING_CORP_REFERENCE",
        reasons,
    )
    seme = _single_fact(
        facts_doc, "20C", "SEME",
        "MISSING_SOURCE_SEME", "CONFLICTING_SOURCE_SEME",
        reasons,
    )
    caev = _single_fact(
        facts_doc, "22F", "CAEV",
        "MISSING_CAEV", "CONFLICTING_CAEV",
        reasons,
    )

    instruction_id = instruction_doc.get("instruction_id")
    isin = instruction_doc.get("isin")
    account_id = instruction_doc.get("account_id")
    option_identifier = instruction_doc.get("option_identifier")
    option_code_raw = instruction_doc.get("option_code_raw")
    for name, value in (
        ("instruction_id", instruction_id),
        ("isin", isin),
        ("account_id", account_id),
        ("option_identifier", option_identifier),
        ("option_code_raw", option_code_raw),
    ):
        if not isinstance(value, str) or not value:
            reasons.append(f"MISSING_INSTRUCTION_FIELD:{name}")

    quantity_swift: str | None = None
    raw_qty = instruction_doc.get("requested_quantity")
    if raw_qty is None:
        reasons.append("MISSING_INSTRUCTION_FIELD:requested_quantity")
    else:
        quantity_swift, qty = _swift_quantity(raw_qty)
        if quantity_swift is None or qty is None or qty <= 0:
            reasons.append("INVALID_REQUESTED_QUANTITY")
            quantity_swift = None

    if reasons:
        status, fields = PROJ_NOT_SERIALIZABLE, []
    else:
        status = PROJ_SERIALIZABLE
        fields = [
            {"tag": "16R", "value": "GENL", "source": "constant"},
            {"tag": "20C", "value": f":SEME//{instruction_id}",
             "source": "instruction.instruction_id"},
            {"tag": "20C", "value": f":CORP//{corp}",
             "source": "facts:GENL:20C:CORP"},
            {"tag": "23G", "value": "NEWM", "source": "constant"},
            {"tag": "22F", "value": f":CAEV//{caev}",
             "source": "facts:GENL:22F:CAEV"},
            {"tag": "16R", "value": "LINK", "source": "constant"},
            {"tag": "13A", "value": ":LINK//564", "source": "constant"},
            {"tag": "20C", "value": f":RELA//{seme}",
             "source": "facts:GENL:20C:SEME"},
            {"tag": "16S", "value": "LINK", "source": "constant"},
            {"tag": "16S", "value": "GENL", "source": "constant"},
            {"tag": "16R", "value": "USECU", "source": "constant"},
            {"tag": "35B", "value": f"ISIN {isin}",
             "source": "instruction.isin"},
            {"tag": "16R", "value": "ACCTINFO", "source": "constant"},
            {"tag": "97A", "value": f":SAFE//{account_id}",
             "source": "instruction.account_id"},
            {"tag": "16S", "value": "ACCTINFO", "source": "constant"},
            {"tag": "16S", "value": "USECU", "source": "constant"},
            {"tag": "16R", "value": "CAINST", "source": "constant"},
            {"tag": "13A", "value": f":CAON//{option_identifier}",
             "source": "instruction.option_identifier"},
            {"tag": "22F", "value": f":CAOP//{option_code_raw}",
             "source": "instruction.option_code_raw"},
            {"tag": "36B", "value": f":QINS//UNIT/{quantity_swift}",
             "source": "instruction.requested_quantity"},
            {"tag": "16S", "value": "CAINST", "source": "constant"},
        ]

    return {
        "schema": PROJECTION_SCHEMA,
        "generated_at": now or _utc_now(),
        "source_instruction_id": instruction_id,
        "source_canon_logical_sha256":
            instruction_doc.get("source_canon_logical_sha256"),
        "source_positions_logical_sha256":
            instruction_doc.get("source_positions_logical_sha256"),
        "source_message_input_sha256": facts_doc.get("input_sha256"),
        "canonical_event_id": instruction_doc.get("canonical_event_id"),
        "projection_status": status,
        "reasons": reasons,
        "envelope": transport,
        "fields": fields,
    }


def write_mt565(
    projection_doc: dict,
    jar: Path | None = None,
    timeout: int = 120,
) -> tuple[dict, int]:
    """Projection doc -> (doc CA_ES_MT565_FIN_V1, exit_code).

    Invoca ``java -jar <jar> mt565``; el projection viaja solo por stdin.
    """
    jar = jar or default_adapter_jar()
    if not jar.is_file():
        raise AdapterUnavailable(f"adapter jar no encontrado: {jar}")
    payload = json.dumps(projection_doc).encode("utf-8")
    try:
        proc = subprocess.run(
            ["java", "-jar", str(jar), "mt565"],
            input=payload,
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise AdapterUnavailable("java no esta en PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise AdapterUnavailable(f"adapter timeout ({timeout}s)") from exc
    try:
        doc = json.loads(proc.stdout.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AdapterUnavailable(
            f"stdout del adapter no es JSON del contrato: {exc}"
        ) from exc
    return doc, proc.returncode
