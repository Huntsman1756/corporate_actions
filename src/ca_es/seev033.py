"""P4.5 — seev.033 projection y escritura via adapter JVM (Prowide).

    CA_ES_ELECTION_INSTRUCTION_V1 (READY)
    + facts de la notificacion fuente (MX seev.031 o MT MT564)
    + CA_ES_SWIFT_MX_ENVELOPE_V1 (BAH explicito)
        -> seev033_project() -> CA_ES_SEEV033_PROJECTION_V1
        -> write_seev033()   -> CA_ES_SEEV033_XML_V1

El XML lo ensambla exclusivamente el adapter JVM en modo ``seev033``
(modelo tipado MxSeev03300213 + BusinessAppHdrV02); el core nunca
genera XML (ADR-010, docs/p4/p45-seev033-scope.md).

No muta la instruccion, los facts ni el envelope.
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
from .mx_facts import FACTS_SCHEMA as MX_FACTS_SCHEMA
from .swift_mt import (
    FACTS_SCHEMA,
    AdapterUnavailable,
    default_adapter_jar,
)

ENVELOPE_SCHEMA = "CA_ES_SWIFT_MX_ENVELOPE_V1"
PROJECTION_SCHEMA = "CA_ES_SEEV033_PROJECTION_V1"
XML_SCHEMA = "CA_ES_SEEV033_XML_V1"

MESSAGE_ID = "seev.033.002.13"

PROJ_SERIALIZABLE = "SERIALIZABLE"
PROJ_NOT_SERIALIZABLE = "NOT_SERIALIZABLE"

SUPPORTED_OPTION_KINDS = ("CASH", "SECURITIES")
_SOURCE_031 = {"seev.031.001.15", "seev.031.002.15"}

_BIC_RE = re.compile(r"^[A-Z0-9]{8}([A-Z0-9]{3})?$")


def _utc_now() -> str:
    return (
        datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _require_doc(doc: dict | None, schema: str, kind: str,
                 key: str = "schema") -> dict:
    if not isinstance(doc, dict) or doc.get(key) != schema:
        raise ValueError(f"INVALID_{kind}_DOCUMENT")
    return doc


def _mx_envelope_transport(envelope: dict) -> dict[str, str]:
    out = {}
    for field in ("sender_bic", "receiver_bic"):
        raw = envelope.get(field)
        if not isinstance(raw, str) or not _BIC_RE.match(raw):
            raise ValueError(f"INVALID_ENVELOPE_FIELD:{field}")
        out[field] = raw if len(raw) == 11 else raw + "XXX"
    msg_def_idr = envelope.get("msg_def_idr")
    if msg_def_idr != MESSAGE_ID:
        raise ValueError("INVALID_ENVELOPE_FIELD:msg_def_idr")
    biz_svc = envelope.get("biz_svc")
    if not isinstance(biz_svc, str) or not biz_svc:
        raise ValueError("INVALID_ENVELOPE_FIELD:biz_svc")
    cre_dt = envelope.get("cre_dt")
    if not isinstance(cre_dt, str) or not cre_dt:
        raise ValueError("INVALID_ENVELOPE_FIELD:cre_dt")
    out["msg_def_idr"] = msg_def_idr
    out["biz_svc"] = biz_svc
    out["cre_dt"] = cre_dt
    return out


def _mx_single_path(facts_doc: dict, suffix: str, missing: str,
                    conflicting: str, reasons: list[str]) -> str | None:
    values = sorted({
        f.get("value") for f in facts_doc.get("facts") or []
        if (f.get("model_path") or "").endswith(suffix)
        and isinstance(f.get("value"), str)
    })
    if not values:
        reasons.append(missing)
        return None
    if len(values) > 1:
        reasons.append(conflicting)
        return None
    return values[0]


def _mt_single_fact(facts_doc: dict, tag: str, qualifier: str,
                    missing: str, conflicting: str,
                    reasons: list[str]) -> str | None:
    values = sorted({
        f.get("value") for f in facts_doc.get("facts") or []
        if f.get("sequence") == "GENL"
        and f.get("source_tag") == tag
        and f.get("source_qualifier") == qualifier
        and isinstance(f.get("value"), str)
    })
    if not values:
        reasons.append(missing)
        return None
    if len(values) > 1:
        reasons.append(conflicting)
        return None
    return values[0]


def _corp_caev(facts_doc: dict, reasons: list[str]):
    """CORP/CAEV desde facts MX (seev.031) o MT (MT564 GENL)."""
    if facts_doc.get("schema_version") == MX_FACTS_SCHEMA:
        corp = _mx_single_path(
            facts_doc, "/CorpActnGnlInf/CorpActnEvtId",
            "MISSING_CORP_REFERENCE", "CONFLICTING_CORP_REFERENCE",
            reasons)
        caev = _mx_single_path(
            facts_doc, "/CorpActnGnlInf/EvtTp/Cd",
            "MISSING_CAEV", "CONFLICTING_CAEV", reasons)
        return corp, caev
    if facts_doc.get("schema_version") == FACTS_SCHEMA:
        corp = _mt_single_fact(
            facts_doc, "20C", "CORP",
            "MISSING_CORP_REFERENCE", "CONFLICTING_CORP_REFERENCE",
            reasons)
        caev = _mt_single_fact(
            facts_doc, "22F", "CAEV",
            "MISSING_CAEV", "CONFLICTING_CAEV", reasons)
        return corp, caev
    raise ValueError("INVALID_SWIFT_FACTS_DOCUMENT")


def _decimal_quantity(raw: Any) -> str | None:
    try:
        qty = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    if not qty.is_finite() or qty <= 0:
        return None
    return format(qty, "f")


def seev033_project(instruction_doc: dict, facts_doc: dict,
                    envelope_doc: dict, *,
                    now: str | None = None) -> dict:
    """Instruccion READY + facts notificacion + envelope MX ->
    CA_ES_SEEV033_PROJECTION_V1."""
    _require_doc(instruction_doc, INSTRUCTION_SCHEMA, "INSTRUCTION")
    _require_doc(envelope_doc, ENVELOPE_SCHEMA, "ENVELOPE")

    if (instruction_doc.get("source_message_input_sha256")
            != facts_doc.get("input_sha256")):
        raise ValueError("INSTRUCTION_FACTS_MISMATCH")

    transport = _mx_envelope_transport(envelope_doc)

    reasons: list[str] = []
    if instruction_doc.get("instruction_status") != READY:
        reasons.append("INSTRUCTION_NOT_READY")
    if instruction_doc.get("option_kind") not in SUPPORTED_OPTION_KINDS:
        reasons.append("UNSUPPORTED_OPTION_KIND")

    corp, caev = _corp_caev(facts_doc, reasons)

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

    quantity = _decimal_quantity(
        instruction_doc.get("requested_quantity"))
    if quantity is None:
        reasons.append("INVALID_REQUESTED_QUANTITY")

    if reasons:
        status, elements = PROJ_NOT_SERIALIZABLE, []
    else:
        status = PROJ_SERIALIZABLE
        elements = [
            {"model_path": "CorpActnInstr/CorpActnGnlInf"
                           "/CorpActnEvtId",
             "value": corp,
             "source": "facts:CorpActnGnlInf/CorpActnEvtId"},
            {"model_path": "CorpActnInstr/CorpActnGnlInf/EvtTp/Cd",
             "value": caev,
             "source": "facts:CorpActnGnlInf/EvtTp/Cd"},
            {"model_path": "CorpActnInstr/CorpActnGnlInf/UndrlygScty"
                           "/FinInstrmId/ISIN",
             "value": isin,
             "source": "instruction.isin"},
            {"model_path": "CorpActnInstr/AcctDtls/SfkpgAcct",
             "value": account_id,
             "source": "instruction.account_id"},
            {"model_path": "CorpActnInstr/CorpActnInstr/OptnNb/Nb",
             "value": option_identifier,
             "source": "instruction.option_identifier"},
            {"model_path": "CorpActnInstr/CorpActnInstr/OptnTp/Cd",
             "value": option_code_raw,
             "source": "instruction.option_code_raw"},
            {"model_path": "CorpActnInstr/CorpActnInstr"
                           "/SctiesQtyOrInstdAmt/SctiesQty/InstdQty"
                           "/Qty/Unit",
             "value": quantity,
             "source": "instruction.requested_quantity"},
        ]

    return {
        "schema": PROJECTION_SCHEMA,
        "generated_at": now or _utc_now(),
        "message_identifier": MESSAGE_ID,
        "source_instruction_id": instruction_id,
        "source_canon_logical_sha256":
            instruction_doc.get("source_canon_logical_sha256"),
        "source_positions_logical_sha256":
            instruction_doc.get("source_positions_logical_sha256"),
        "source_message_input_sha256": facts_doc.get("input_sha256"),
        "canonical_event_id": instruction_doc.get("canonical_event_id"),
        "projection_status": status,
        "reasons": reasons,
        "envelope": {**transport, "biz_msg_idr": instruction_id},
        "elements": elements,
    }


def write_seev033(projection_doc: dict, jar: Path | None = None,
                  timeout: int = 120) -> tuple[dict, int]:
    """Projection doc -> (doc CA_ES_SEEV033_XML_V1, exit_code).

    Invoca ``java -jar <jar> seev033``; el projection viaja por stdin.
    """
    jar = jar or default_adapter_jar()
    if not jar.is_file():
        raise AdapterUnavailable(f"adapter jar no encontrado: {jar}")
    payload = json.dumps(projection_doc).encode("utf-8")
    try:
        proc = subprocess.run(
            ["java", "-jar", str(jar), "seev033"],
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
