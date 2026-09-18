"""P12.5 — FIN service ACK/NAK (service id 21) -> evidencia L4.

    bytes FIN crudos
        -> adapter JVM modo ``finsvc`` (Prowide)
        -> CA_ES_FIN_SERVICE_RECEIPT_V1 (campos extraidos)
        -> correlacion determinista contra sends almacenados
        -> SWIFT_ACKED | SWIFT_NAKED

La correlacion usa el MIR (LT+session+sequence de block1) que la
red identifica como el mensaje input, con cross-check SEME cuando
la copia embebida lo trae. Sin fuzzy matching: 0 -> NO_MATCH,
>1 -> AMBIGUOUS, contento divergente -> CONFLICTING.

Trust source registrado: FILE_INGEST (el operador deposito el
fichero — ejerce parseo y correlacion reales, pero la fuerza de
la evidencia depende del canal). Un ingestor de red futuro usaria
NETWORK_FIN.

Nunca se implementa parseo FIN en Python (ADR-010): solo se extrae
el MIR de block1 con regex estructural sobre message_text.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .ops_send import (
    SCHEMA_TRANSPORT_RECEIPT, S_ABANDONED, S_GATEWAY_ACCEPTED,
    S_GATEWAY_REJECTED, S_PREPARED, S_SPOOLED, S_SWIFT_ACKED,
    S_SWIFT_NAKED, get_send, list_sends, _insert_transition,
    _set_send_status, _truncate, _utcnow,
)
from .semantic_hash import canonical_json
from .swift_mt import AdapterUnavailable, default_adapter_jar

SCHEMA_FIN_RECEIPT = "CA_ES_FIN_SERVICE_RECEIPT_V1"
SCHEMA_FIN_INGEST_RESULT = "CA_ES_FIN_INGEST_RESULT_V1"

# estados desde los que una evidencia de red es admisible
_NETWORK_EVIDENCE_FROM = frozenset({
    S_SPOOLED, S_GATEWAY_ACCEPTED, S_GATEWAY_REJECTED})

# receipt statuses persistidos en send_receipts
R_SWIFT_ACK = "SWIFT_ACK"
R_SWIFT_NAK = "SWIFT_NAK"
R_CONFLICTING = "CONFLICTING"
R_QUARANTINED = "QUARANTINED"

# {1:F01<LT12><SESS4><SEQ6>} — MIR estructural, nada semantico
_MIR_RE = re.compile(r"\{1:F01([A-Z0-9]{12})(\d{4})(\d{6})\}")


def mir_of(message_text: str) -> tuple[str, str, str] | None:
    """(lt, session, sequence) del block1 de un FIN almacenado."""
    if not isinstance(message_text, str):
        return None
    m = _MIR_RE.search(message_text)
    return (m.group(1), m.group(2), m.group(3)) if m else None


# ------------------------------------------------------------------
# adapter JVM boundary
# ------------------------------------------------------------------

def parse_fin_service(raw: bytes, jar: Path | None = None,
                      timeout: int = 120) -> tuple[dict, int]:
    """bytes FIN -> (doc CA_ES_FIN_SERVICE_RECEIPT_V1, exit_code).

    Invoca ``java -jar <jar> finsvc``; el service message viaja
    solo por stdin.
    """
    jar = jar or default_adapter_jar()
    if not jar.is_file():
        raise AdapterUnavailable(f"adapter jar no encontrado: {jar}")
    try:
        proc = subprocess.run(
            ["java", "-jar", str(jar), "finsvc"],
            input=raw, capture_output=True, timeout=timeout)
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


# ------------------------------------------------------------------
# ingestion
# ------------------------------------------------------------------

def ingest_fin_service_file(conn, path: Path, *, jar: Path | None = None,
                            now: str | None = None) -> dict:
    """Parsea un fichero de service message FIN via JVM e ingiere el
    receipt. El resultado es un CA_ES_FIN_INGEST_RESULT_V1."""
    raw = Path(path).read_bytes()
    doc, code = parse_fin_service(raw, jar=jar)
    return ingest_fin_service_doc(
        conn, doc, receipt_sha=_sha_of_doc(doc, raw),
        source=f"FILE_INGEST:{path}", now=now)


def ingest_fin_service_doc(conn, doc: dict, *, receipt_sha: str,
                           source: str, now: str | None = None) -> dict:
    """Correlaciona un receipt ya parseado contra el send ledger.

    Cada receipt se registra en send_receipts — incluidos los
    rechazados (nunca se descarta evidencia).
    """
    now = now or _utcnow()
    outcome = {"schema": SCHEMA_FIN_INGEST_RESULT, "generated_at": now,
               "receipt_sha256": receipt_sha, "source": source,
               "delivery_id": None, "result": None, "send_status": None}

    def record(delivery_id, status, reason, qreason):
        conn.execute(
            "INSERT INTO send_receipts"
            " (delivery_id, receipt_sha256, status, gateway_reference,"
            "  received_at, reason, source_path, quarantine_reason,"
            "  ingested_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (delivery_id, receipt_sha, status,
             _truncate(doc.get("mur"), 128),
             _truncate(doc.get("field_177"), 64),
             _truncate(reason, 300),
             _truncate(source, 300),
             _truncate(qreason, 128), now))

    if not isinstance(doc, dict) \
            or doc.get("schema") != SCHEMA_FIN_RECEIPT:
        record("?", R_QUARANTINED, None, "WRONG_SCHEMA")
        outcome["result"] = "QUARANTINED:WRONG_SCHEMA"
        return outcome
    if doc.get("parse_status") != "OK":
        record("?", R_QUARANTINED, doc.get("parse_status"),
               doc.get("parse_status"))
        outcome["result"] = f"QUARANTINED:{doc.get('parse_status')}"
        return outcome
    if not doc.get("is_ack") and not doc.get("is_nack"):
        record("?", R_QUARANTINED, None, "NOT_ACK_NAK")
        outcome["result"] = "QUARANTINED:NOT_ACK_NAK"
        return outcome

    kind = R_SWIFT_ACK if doc.get("is_ack") else R_SWIFT_NAK
    new_status = S_SWIFT_ACKED if doc.get("is_ack") else S_SWIFT_NAKED
    embedded = doc.get("embedded_copy") or {}
    if not embedded.get("present"):
        record("?", R_QUARANTINED, None, "NO_CORRELATION_EVIDENCE")
        outcome["result"] = "QUARANTINED:NO_CORRELATION_EVIDENCE"
        return outcome

    mir = (embedded.get("mir_lt"), embedded.get("mir_session"),
           embedded.get("mir_sequence"))
    candidates = [s for s in list_sends(conn)
                  if mir_of(s.get("message_text")) == tuple(mir)]
    if not candidates:
        record("?", R_QUARANTINED, None, "NO_MATCH")
        outcome["result"] = "QUARANTINED:NO_MATCH"
        return outcome

    seme = embedded.get("seme")
    if seme:
        bound = [s for s in candidates
                 if s.get("message_reference") == seme]
        if not bound:
            # la red ACKo un contenido distinto al que creemos haber
            # enviado bajo ese MIR — conflicto real, fail closed
            record(candidates[0]["delivery_id"], R_CONFLICTING,
                   doc.get("field_405"), "SEME_MISMATCH")
            outcome["delivery_id"] = candidates[0]["delivery_id"]
            outcome["result"] = "CONFLICTING:SEME_MISMATCH"
            return outcome
        candidates = bound
    if len(candidates) > 1:
        for s in candidates:
            record(s["delivery_id"], R_QUARANTINED, None, "AMBIGUOUS")
        outcome["result"] = "QUARANTINED:AMBIGUOUS"
        return outcome

    send = candidates[0]
    did = send["delivery_id"]
    outcome["delivery_id"] = did
    status = send["status"]

    # duplicado byte-identico ya registrado -> no-op idempotente
    prior = conn.execute(
        "SELECT status FROM send_receipts WHERE delivery_id=?"
        " AND receipt_sha256=?",
        (did, receipt_sha)).fetchone()
    if prior is not None:
        record(did, prior["status"], doc.get("field_405"),
               "DUPLICATE")
        outcome["result"] = f"DUPLICATE:{prior['status']}"
        outcome["send_status"] = status
        return outcome

    if status in (S_SWIFT_ACKED, S_SWIFT_NAKED):
        expected = R_SWIFT_ACK if status == S_SWIFT_ACKED \
            else R_SWIFT_NAK
        if kind == expected:
            # misma evidencia de red, receipt distinto: aceptar sin
            # transicion
            record(did, kind, doc.get("field_405"), None)
            outcome["result"] = f"RECONFIRMED:{kind}"
            outcome["send_status"] = status
            return outcome
        # evidencia de red contraria: preservar ambas, sin
        # precedencia inventada — el send conserva la primera
        record(did, R_CONFLICTING, doc.get("field_405"),
               "OPPOSING_NETWORK_EVIDENCE")
        outcome["result"] = "CONFLICTING:OPPOSING_NETWORK_EVIDENCE"
        outcome["send_status"] = status
        return outcome

    if status not in _NETWORK_EVIDENCE_FROM:
        record(did, R_QUARANTINED, doc.get("field_405"),
               "UNEXPECTED_STATE")
        outcome["result"] = f"QUARANTINED:UNEXPECTED_STATE:{status}"
        outcome["send_status"] = status
        return outcome

    record(did, kind, doc.get("field_405"), None)
    _set_send_status(
        conn, did, new_status, "send-ingest-fin", now,
        note=f"FIN_SERVICE_21:{kind}",
        external_receipt={
            "schema": SCHEMA_FIN_RECEIPT,
            "status": kind,
            "service_id": doc.get("service_id"),
            "field_177": doc.get("field_177"),
            "field_405": doc.get("field_405"),
            "mur": doc.get("mur"),
            "mir": "|".join(str(p) for p in mir),
            "embedded_sha256": embedded.get("sha256"),
            "receipt_sha256": receipt_sha,
            "source": source})
    outcome["result"] = kind
    outcome["send_status"] = new_status
    return outcome


def _sha_of_doc(doc: dict, raw: bytes) -> str:
    sha = (doc or {}).get("input_sha256")
    if isinstance(sha, str) and len(sha) == 64:
        return sha
    import hashlib
    return hashlib.sha256(raw).hexdigest()
