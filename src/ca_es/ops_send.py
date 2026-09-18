"""P11 — send ledger + dispatcher (docs/p11/p110-p113).

Boundary de envio de mensajes CA serializados (MT565 FIN /
seev.033 XML producidos por el adapter JVM, ADR-010) hacia un
integration boundary por transport adapter.

Separacion estricta de niveles:

    PREPARED -> SPOOLED -> GATEWAY_ACCEPTED | GATEWAY_REJECTED
    (SWIFT_ACKED/NAKED: contrato, sin ingestor en V1)

SPOOLED significa unicamente "bytes entregados durable y
atomicamente al boundary configurado" — NUNCA submission a SWIFT
ni aceptacion de gateway. GATEWAY_* requiere un receipt externo
real depositado en receipts/ por un consumidor externo.

MT567/seev.034 (status de negocio) vive en P5.6 — lifecycle
separado, jamas modelado como ACK de transporte.

Referencias separadas:

    delivery_id         identidad interna inmutable + idempotencia
    message_reference   MT565 20C::SEME / seev.033 BizMsgIdr
    transport_reference la devuelve el gateway cuando exista
    content_sha256      digest de los bytes exactos transmitidos
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .semantic_hash import canonical_json

# ------------------------------------------------------------------
# schemas / constants
# ------------------------------------------------------------------

SCHEMA_SEND = "CA_ES_INSTRUCTION_SEND_V1"
SCHEMA_TRANSPORT_RECEIPT = "CA_ES_TRANSPORT_RECEIPT_V1"
SCHEMA_SEND_META = "CA_ES_SEND_META_V1"
SCHEMA_SEND_RESULT = "CA_ES_SEND_RESULT_V1"
SCHEMA_SEND_STATUS = "CA_ES_SEND_STATUS_V1"
SCHEMA_SEND_PREPARE_RESULT = "CA_ES_SEND_PREPARE_RESULT_V1"

SEND_POLICY_VERSION = "CA_ES_INSTRUCTION_SEND_V1"

# estados del send
S_PREPARED = "PREPARED"
S_SPOOLED = "SPOOLED"
S_FAILED_RETRYABLE = "SPOOL_FAILED_RETRYABLE"
S_FAILED_PERMANENT = "SPOOL_FAILED_PERMANENT"
S_GATEWAY_ACCEPTED = "GATEWAY_ACCEPTED"
S_GATEWAY_REJECTED = "GATEWAY_REJECTED"
S_UNKNOWN = "UNKNOWN_OUTCOME"
S_ABANDONED = "ABANDONED"
# P12 — evidencia de red (L4): service message FIN 21 correlado
S_SWIFT_ACKED = "SWIFT_ACKED"
S_SWIFT_NAKED = "SWIFT_NAKED"

TERMINAL_STATES = frozenset({
    S_GATEWAY_ACCEPTED, S_GATEWAY_REJECTED, S_ABANDONED,
    S_SWIFT_ACKED, S_SWIFT_NAKED})

# estados del attempt
A_STARTED = "STARTED"
A_SUCCEEDED = "SUCCEEDED"
A_FAILED = "FAILED"
A_UNKNOWN = "UNKNOWN"

# outcomes del adapter
O_SPOOLED = "SPOOLED"
O_FAILED_RETRYABLE = "FAILED_RETRYABLE"
O_FAILED_PERMANENT = "FAILED_PERMANENT"
O_UNKNOWN = "UNKNOWN"

# verify() del adapter
V_SPOOLED = "SPOOLED"
V_NOT_SPOOLED = "NOT_SPOOLED"
V_COLLISION = "COLLISION"
V_UNKNOWN = "UNKNOWN"

# message docs soportados (schema -> campo de texto)
MESSAGE_FIELDS = {
    "CA_ES_MT565_FIN_V1": "fin",
    "CA_ES_SEEV033_XML_V1": "xml",
}
MESSAGE_HASH_FIELDS = {
    "CA_ES_MT565_FIN_V1": "fin_sha256",
    "CA_ES_SEEV033_XML_V1": "xml_sha256",
}

DEFAULT_MAX_MESSAGE_BYTES = 65536


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat(
    ).replace("+00:00", "Z")


def _truncate(text: object, limit: int = 200) -> str | None:
    if text is None:
        return None
    s = str(text)
    return s[:limit]


# ------------------------------------------------------------------
# identidad
# ------------------------------------------------------------------

def derive_delivery_id(instruction_id: str, content_sha256: str,
                       destination_id: str) -> str:
    """Identidad interna inmutable del envio logico (p111).

    Material: instruction_id + content_sha256 + destination_id +
    policy version. Mismo mensaje + mismo destino -> mismo
    delivery_id -> dedup. Bytes distintos -> nuevo delivery_id.
    """
    material = "|".join((
        "CA_ES_INSTRUCTION_SEND_V1",
        instruction_id,
        content_sha256,
        destination_id,
        SEND_POLICY_VERSION,
    ))
    return "SND-" + hashlib.sha256(
        material.encode("utf-8")).hexdigest()


def content_sha256_of(message_text: str) -> str:
    return hashlib.sha256(message_text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------
# adapter boundary
# ------------------------------------------------------------------

@dataclass
class SendAdapterResult:
    """Resultado de UN intento de transporte."""
    outcome: str
    error_code: str | None = None
    error_detail_safe: str | None = None
    retry_after_seconds: int | None = None
    receipt: dict | None = None


@dataclass
class SendRequest:
    delivery_id: str
    instruction_id: str
    message_reference: str | None
    message_schema: str
    message_text: str
    content_sha256: str
    destination_id: str
    adapter_type: str
    generation: int


def adapter_registry() -> dict:
    """adapter_type -> {"deliver": fn, "verify": fn}."""
    from .transport import filespool

    return {
        "filespool": {
            "deliver": filespool.deliver,
            "verify": filespool.verify,
        },
    }


# ------------------------------------------------------------------
# routing / config
# ------------------------------------------------------------------

def enabled_destinations(send_cfg: dict) -> list[dict]:
    if not (send_cfg or {}).get("enabled"):
        return []
    return [d for d in send_cfg.get("destinations") or []
            if d.get("enabled") and d.get("destination_id")]


def schema_routed(schemas: list[str], message_schema: str) -> bool:
    """`*` = todos; exacto en otro caso. Sin routing oculto."""
    for entry in schemas or []:
        if entry == "*" or entry == message_schema:
            return True
    return False


# ------------------------------------------------------------------
# message doc validation + prepare
# ------------------------------------------------------------------

def extract_message(message_doc: dict) -> tuple[str, str]:
    """(message_schema, message_text). Fail-closed."""
    schema = message_doc.get("schema_version") or \
        message_doc.get("schema")
    if schema not in MESSAGE_FIELDS:
        raise ValueError(
            f"UNSUPPORTED_MESSAGE_SCHEMA:{schema!r}")
    if message_doc.get("write_status") != "OK":
        raise ValueError(
            f"MESSAGE_NOT_WRITE_OK:{message_doc.get('write_status')}")
    text = message_doc.get(MESSAGE_FIELDS[schema])
    if not isinstance(text, str) or not text:
        raise ValueError("EMPTY_MESSAGE_TEXT")
    declared = message_doc.get(MESSAGE_HASH_FIELDS[schema])
    if declared is not None and declared != content_sha256_of(text):
        raise ValueError("MESSAGE_HASH_MISMATCH")
    return schema, text


def check_reference_binding(message_schema: str, message_text: str,
                            instruction_id: str) -> str:
    """message_reference = instruction_id; binding por contencion
    conservadora (nunca parseo del mensaje en el core)."""
    if message_schema == "CA_ES_MT565_FIN_V1":
        if f":20C::SEME//{instruction_id}" not in message_text:
            raise ValueError("MESSAGE_REFERENCE_MISMATCH:SEME")
    else:
        if instruction_id not in message_text:
            raise ValueError(
                "MESSAGE_REFERENCE_MISMATCH:BIZMSGIDR")
    return instruction_id


# ------------------------------------------------------------------
# ledger helpers
# ------------------------------------------------------------------

def _insert_transition(conn, delivery_id: str, from_status,
                       to_status: str, actor: str, note, now: str):
    conn.execute(
        "INSERT INTO send_transitions"
        " (delivery_id, at, from_status, to_status, actor, note)"
        " VALUES (?,?,?,?,?,?)",
        (delivery_id, now, from_status, to_status, actor,
         _truncate(note, 300)))


def get_send(conn, delivery_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM sends WHERE delivery_id=?",
        (delivery_id,)).fetchone()
    return dict(row) if row else None


def list_sends(conn, *, instruction_id: str | None = None,
               status: str | None = None) -> list[dict]:
    sql, params = "SELECT * FROM sends", []
    clauses = []
    if instruction_id:
        clauses.append("instruction_id=?")
        params.append(instruction_id)
    if status:
        clauses.append("status=?")
        params.append(status)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    return [dict(r) for r in conn.execute(
        sql + " ORDER BY first_prepared_at", params).fetchall()]


def list_send_attempts(conn, delivery_id: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM send_attempts WHERE delivery_id=?"
        " ORDER BY attempt_number",
        (delivery_id,)).fetchall()]


def list_send_transitions(conn, delivery_id: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM send_transitions WHERE delivery_id=?"
        " ORDER BY id",
        (delivery_id,)).fetchall()]


def list_send_receipts(conn, delivery_id: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM send_receipts WHERE delivery_id=?"
        " ORDER BY receipt_id",
        (delivery_id,)).fetchall()]


def _set_send_status(conn, delivery_id: str, to_status: str,
                     actor: str, now: str, *, note=None,
                     next_attempt_after=None,
                     transport_reference=None,
                     external_receipt=None):
    send = get_send(conn, delivery_id)
    if send is None:
        raise ValueError(f"SEND_NOT_FOUND:{delivery_id}")
    fields = {"status": to_status}
    if next_attempt_after is not None or \
            send.get("next_attempt_after"):
        fields["next_attempt_after"] = next_attempt_after
    if to_status == S_SPOOLED:
        fields["spooled_at"] = now
    if transport_reference is not None:
        fields["transport_reference"] = transport_reference
    if external_receipt is not None:
        fields["external_receipt_json"] = canonical_json(
            external_receipt)
    assignments = ", ".join(f"{k}=?" for k in fields)
    conn.execute(
        f"UPDATE sends SET {assignments} WHERE delivery_id=?",
        (*fields.values(), delivery_id))
    _insert_transition(
        conn, delivery_id, send["status"], to_status, actor, note,
        now)


# ------------------------------------------------------------------
# prepare (derivacion de sends)
# ------------------------------------------------------------------

def prepare_sends(conn, message_doc: dict, instruction_id: str,
                  send_cfg: dict, now: str | None = None,
                  adapters: dict | None = None) -> dict:
    """Crea filas PREPARED por destino habilitado y routed.

    Idempotente por delivery_id: mismo mensaje+destino -> reporta
    el send existente sin duplicar.
    """
    now = now or _utcnow()
    cfg = send_cfg or {}
    policy = cfg.get("send_policy") or {}
    adapters = adapters or adapter_registry()

    if not isinstance(instruction_id, str) or not instruction_id:
        raise ValueError("INVALID_INSTRUCTION_ID")
    message_schema, message_text = extract_message(message_doc)
    content_sha256 = content_sha256_of(message_text)
    message_reference = check_reference_binding(
        message_schema, message_text, instruction_id)

    max_bytes = int(policy.get(
        "max_message_bytes", DEFAULT_MAX_MESSAGE_BYTES))
    if len(message_text.encode("utf-8")) > max_bytes:
        raise ValueError("MESSAGE_TOO_LARGE")

    created, existing = [], []
    for dest in enabled_destinations(cfg):
        if dest["adapter"] not in adapters:
            continue
        if not schema_routed(
                dest.get("message_schemas") or [],
                message_schema):
            continue
        did = derive_delivery_id(
            instruction_id, content_sha256, dest["destination_id"])
        prior = get_send(conn, did)
        if prior is not None:
            existing.append(prior)
            continue
        priors = [s for s in list_sends(
            conn, instruction_id=instruction_id)
            if s["destination_id"] == dest["destination_id"]]
        generation = len(priors) + 1
        conn.execute(
            "INSERT INTO sends"
            " (delivery_id, instruction_id, message_reference,"
            "  message_schema, message_text, content_sha256,"
            "  destination_id, adapter_type, generation, status,"
            "  attempt_count, first_prepared_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,0,?)",
            (did, instruction_id, message_reference, message_schema,
             message_text, content_sha256, dest["destination_id"],
             dest["adapter"], generation, S_PREPARED, now))
        _insert_transition(
            conn, did, None, S_PREPARED, "send-prepare",
            "PREPARED", now)
        created.append(get_send(conn, did))

    return {
        "schema": SCHEMA_SEND_PREPARE_RESULT,
        "generated_at": now,
        "instruction_id": instruction_id,
        "message_schema": message_schema,
        "content_sha256": content_sha256,
        "created": [
            {"delivery_id": s["delivery_id"],
             "destination_id": s["destination_id"],
             "generation": s["generation"]} for s in created],
        "existing": [
            {"delivery_id": s["delivery_id"],
             "destination_id": s["destination_id"],
             "status": s["status"]} for s in existing],
    }


# ------------------------------------------------------------------
# retry scheduling
# ------------------------------------------------------------------

def _retry_delay_seconds(retry_cfg: dict, attempt_number: int) -> int:
    base = float(retry_cfg.get("base_delay_seconds", 300))
    factor = float(retry_cfg.get("backoff_factor", 2.0))
    cap = float(retry_cfg.get("max_delay_seconds", 3600))
    return int(min(base * (factor ** max(0, attempt_number - 1)), cap))


def _iso_plus_seconds(now_iso: str, seconds: int) -> str:
    base = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    return (base + timedelta(seconds=seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _is_eligible(send: dict, now: str, retry_cfg: dict) -> bool:
    status = send["status"]
    if status == S_PREPARED:
        return True
    if status != S_FAILED_RETRYABLE:
        return False
    max_attempts = int(retry_cfg.get("max_attempts", 5))
    if int(send["attempt_count"]) >= max_attempts:
        return False
    naa = send.get("next_attempt_after")
    return naa is None or naa <= now


# ------------------------------------------------------------------
# attempt recording
# ------------------------------------------------------------------

def _record_attempt(conn, send: dict, result: SendAdapterResult,
                    attempt_number: int, *, now: str,
                    retry_cfg: dict) -> str:
    """Persiste el outcome; devuelve el nuevo status del send."""
    dk = send["delivery_id"]
    outcome = result.outcome
    if outcome == O_SPOOLED:
        attempt_status, new_status, retryable = (
            A_SUCCEEDED, S_SPOOLED, None)
        next_after = None
    elif outcome == O_FAILED_RETRYABLE:
        attempt_status, new_status, retryable = (
            A_FAILED, S_FAILED_RETRYABLE, 1)
        delay = _retry_delay_seconds(retry_cfg, attempt_number)
        if result.retry_after_seconds is not None:
            delay = max(delay, result.retry_after_seconds)
        next_after = _iso_plus_seconds(now, delay)
    elif outcome == O_FAILED_PERMANENT:
        attempt_status, new_status, retryable = (
            A_FAILED, S_FAILED_PERMANENT, 0)
        next_after = None
    else:  # O_UNKNOWN
        attempt_status, new_status, retryable = (
            A_UNKNOWN, S_UNKNOWN, None)
        next_after = None

    conn.execute(
        "UPDATE send_attempts SET completed_at=?, status=?,"
        " retryable=?, error_code=?, error_detail_safe=?,"
        " transport_metadata_json=? WHERE attempt_id=?",
        (now, attempt_status, retryable,
         _truncate(result.error_code, 64),
         _truncate(result.error_detail_safe),
         canonical_json(result.receipt or {}),
         f"SNA-{dk}-{attempt_number}"))
    _set_send_status(
        conn, dk, new_status, "send-dispatch", now,
        note=result.error_code,
        next_attempt_after=next_after)
    # agotamiento de reintentos -> permanente
    if new_status == S_FAILED_RETRYABLE:
        max_attempts = int(retry_cfg.get("max_attempts", 5))
        if attempt_number >= max_attempts:
            _set_send_status(
                conn, dk, S_FAILED_PERMANENT, "send-dispatch", now,
                note="RETRY_EXHAUSTED", next_attempt_after=None)
            return S_FAILED_PERMANENT
    return new_status


# ------------------------------------------------------------------
# orphan recovery (crash tras STARTED durable)
# ------------------------------------------------------------------

def _recover_orphans(conn, adapters: dict, dest_by_id: dict,
                     now: str) -> dict:
    """Attempts STARTED huerfanos (proceso muerto).

    FileSpool puede VERIFICAR el side effect: msg+meta con hash
    del ledger -> SPOOLED (recovery); ausente/incompleto ->
    reintento seguro; hash distinto -> permanente COLLISION.
    Sin verify -> UNKNOWN_OUTCOME.
    """
    rows = conn.execute(
        "SELECT a.attempt_id, a.delivery_id, a.attempt_number"
        " FROM send_attempts a WHERE a.status='STARTED'"
    ).fetchall()
    recovered = unknown = 0
    for r in rows:
        send = get_send(conn, r["delivery_id"])
        if send is None:
            continue
        dest = dest_by_id.get(send["destination_id"])
        adapter = adapters.get(send["adapter_type"])
        verdict = V_UNKNOWN
        if dest is not None and adapter is not None:
            verify_fn = adapter.get("verify")
            if verify_fn is not None:
                request = SendRequest(
                    delivery_id=send["delivery_id"],
                    instruction_id=send["instruction_id"],
                    message_reference=send["message_reference"],
                    message_schema=send["message_schema"],
                    message_text=send["message_text"],
                    content_sha256=send["content_sha256"],
                    destination_id=send["destination_id"],
                    adapter_type=send["adapter_type"],
                    generation=send["generation"])
                try:
                    verdict = verify_fn(
                        request, dest.get("config") or {})
                except Exception:  # noqa: BLE001
                    verdict = V_UNKNOWN

        if verdict == V_SPOOLED:
            conn.execute(
                "UPDATE send_attempts SET status=?, completed_at=?,"
                " error_code=? WHERE attempt_id=?",
                (A_SUCCEEDED, now, "ORPHAN_RECOVERED",
                 r["attempt_id"]))
            _set_send_status(
                conn, send["delivery_id"], S_SPOOLED,
                "send-dispatch", now, note="ORPHAN_RECOVERED_SPOOLED")
            recovered += 1
        elif verdict == V_NOT_SPOOLED:
            conn.execute(
                "UPDATE send_attempts SET status=?, completed_at=?,"
                " retryable=1, error_code=? WHERE attempt_id=?",
                (A_FAILED, now, "ORPHAN_NOT_SPOOLED",
                 r["attempt_id"]))
            # el send vuelve a ser elegible en esta misma pasada
            _set_send_status(
                conn, send["delivery_id"], S_FAILED_RETRYABLE,
                "send-dispatch", now,
                note="ORPHAN_NOT_SPOOLED_RETRY", next_attempt_after=now)
        elif verdict == V_COLLISION:
            conn.execute(
                "UPDATE send_attempts SET status=?, completed_at=?,"
                " retryable=0, error_code=? WHERE attempt_id=?",
                (A_FAILED, now, "DELIVERY_ID_COLLISION",
                 r["attempt_id"]))
            _set_send_status(
                conn, send["delivery_id"], S_FAILED_PERMANENT,
                "send-dispatch", now, note="DELIVERY_ID_COLLISION")
        else:
            conn.execute(
                "UPDATE send_attempts SET status=?, completed_at=?"
                " WHERE attempt_id=?",
                (A_UNKNOWN, now, r["attempt_id"]))
            _set_send_status(
                conn, send["delivery_id"], S_UNKNOWN,
                "send-dispatch", now,
                note="ORPHANED_STARTED_ATTEMPT")
            unknown += 1
    return {"recovered": recovered, "marked_unknown": unknown}


# ------------------------------------------------------------------
# receipt ingestion (evidencia EXTERNA en receipts/)
# ------------------------------------------------------------------

def _quarantine_file(receipts_dir, quarantine_dir, path, sha8: str):
    """Mueve el fichero a quarantine/; sufijo sha ante colision."""
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    target = quarantine_dir / path.name
    if target.exists():
        target = quarantine_dir / f"{path.name}.{sha8}"
    try:
        path.replace(target)
    except OSError:
        return None
    return target


def _record_receipt(conn, *, delivery_id: str, receipt_sha256: str,
                    status: str, gateway_reference, received_at,
                    reason, source_path, quarantine_reason, now: str):
    conn.execute(
        "INSERT INTO send_receipts"
        " (delivery_id, receipt_sha256, status, gateway_reference,"
        "  received_at, reason, source_path, quarantine_reason,"
        "  ingested_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (delivery_id, receipt_sha256, status,
         _truncate(gateway_reference, 128),
         _truncate(received_at, 64), _truncate(reason, 300),
         str(source_path), _truncate(quarantine_reason, 128), now))


def _ingest_receipts_for_dest(conn, dest: dict, now: str) -> dict:
    """Escanea <spool>/receipts/*.ack.json|*.nak.json.

    Valido -> transicion SPOOLED -> GATEWAY_* + mover a
    receipts/processed/. Malformado/conflictivo -> quarantine/ +
    fila QUARANTINED. Nunca borra evidencia.
    """
    from pathlib import Path

    counts = {"ingested": 0, "quarantined": 0}
    cfg = dest.get("config") or {}
    spool = cfg.get("spool_directory")
    if not spool:
        return counts
    receipts_dir = Path(spool) / "receipts"
    processed_dir = receipts_dir / "processed"
    quarantine_dir = Path(spool) / "quarantine"
    if not receipts_dir.is_dir():
        return counts

    def quarantine(path, delivery_id, sha256, reason):
        receipt_sha = hashlib.sha256(
            path.read_bytes()).hexdigest()
        moved = _quarantine_file(
            receipts_dir, quarantine_dir, path, receipt_sha[:8])
        _record_receipt(
            conn, delivery_id=delivery_id or "?",
            receipt_sha256=receipt_sha, status="QUARANTINED",
            gateway_reference=None, received_at=None,
            reason=None,
            source_path=str(moved or path),
            quarantine_reason=reason, now=now)
        counts["quarantined"] += 1

    # ambos .ack.json y .nak.json para el mismo delivery -> conflicto
    files = sorted(
        p for p in receipts_dir.glob("SND-*.?*.json")
        if p.is_file())
    by_delivery: dict[str, list] = {}
    for p in files:
        name = p.name
        if name.endswith(".ack.json"):
            did = name[:-len(".ack.json")]
        elif name.endswith(".nak.json"):
            did = name[:-len(".nak.json")]
        else:
            continue
        by_delivery.setdefault(did, []).append(p)

    for delivery_id, paths in by_delivery.items():
        acks = [p for p in paths if p.name.endswith(".ack.json")]
        naks = [p for p in paths if p.name.endswith(".nak.json")]
        if acks and naks:
            for p in paths:
                quarantine(
                    p, delivery_id, None, "CONFLICTING_RECEIPTS")
            continue
        for p in paths:
            receipt_sha = hashlib.sha256(
                p.read_bytes()).hexdigest()
            expected_status = "ACCEPTED" if p in acks else "REJECTED"
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                quarantine(p, delivery_id, receipt_sha,
                           "MALFORMED_RECEIPT")
                continue
            if not isinstance(doc, dict) or doc.get(
                    "schema") != SCHEMA_TRANSPORT_RECEIPT:
                quarantine(p, delivery_id, receipt_sha,
                           "WRONG_SCHEMA")
                continue
            if doc.get("delivery_id") != delivery_id:
                quarantine(p, delivery_id, receipt_sha,
                           "ID_MISMATCH")
                continue
            if doc.get("status") != expected_status:
                quarantine(p, delivery_id, receipt_sha,
                           "STATUS_SUFFIX_MISMATCH")
                continue
            send = get_send(conn, delivery_id)
            if send is None:
                quarantine(p, delivery_id, receipt_sha,
                           "UNKNOWN_DELIVERY")
                continue
            if doc.get("content_sha256") != send["content_sha256"]:
                quarantine(p, delivery_id, receipt_sha,
                           "HASH_MISMATCH")
                continue
            if send["status"] != S_SPOOLED:
                # duplicado byte-identico de receipt ya ingerido:
                # consume idempotentemente sin transicion
                prior = conn.execute(
                    "SELECT 1 FROM send_receipts WHERE delivery_id=?"
                    " AND receipt_sha256=? AND status=?",
                    (delivery_id, receipt_sha,
                     send["status"].replace("GATEWAY_", ""))
                ).fetchone()
                if prior and send["status"] in TERMINAL_STATES:
                    processed_dir.mkdir(
                        parents=True, exist_ok=True)
                    p.replace(processed_dir / p.name)
                    continue
                quarantine(p, delivery_id, receipt_sha,
                           "UNEXPECTED_STATE")
                continue

            new_status = (S_GATEWAY_ACCEPTED if expected_status
                          == "ACCEPTED" else S_GATEWAY_REJECTED)
            processed_dir.mkdir(parents=True, exist_ok=True)
            target = processed_dir / p.name
            p.replace(target)
            _record_receipt(
                conn, delivery_id=delivery_id,
                receipt_sha256=receipt_sha, status=expected_status,
                gateway_reference=doc.get("gateway_reference"),
                received_at=doc.get("received_at"),
                reason=doc.get("reason"),
                source_path=str(target), quarantine_reason=None,
                now=now)
            _set_send_status(
                conn, delivery_id, new_status, "send-dispatch", now,
                note="TRANSPORT_RECEIPT",
                transport_reference=doc.get("gateway_reference"),
                external_receipt={
                    "schema": SCHEMA_TRANSPORT_RECEIPT,
                    "status": expected_status,
                    "gateway_reference": doc.get("gateway_reference"),
                    "received_at": doc.get("received_at"),
                    "reason": doc.get("reason"),
                    "receipt_sha256": receipt_sha})
            counts["ingested"] += 1
    return counts


# ------------------------------------------------------------------
# dispatcher
# ------------------------------------------------------------------

def run_send_dispatch(state, conn, send_cfg: dict,
                      *, now_fn=None, adapters: dict | None = None,
                      only_delivery_id: str | None = None) -> dict:
    """Una pasada del send dispatcher.

    Requiere conn single-writer (run lock del caller). Persiste
    STARTED via ``state.checkpoint()`` ANTES del side effect.
    """
    now = (now_fn or _utcnow)()
    cfg = send_cfg or {}
    retry_cfg = cfg.get("retry") or {}
    destinations = enabled_destinations(cfg)
    adapters = adapters or adapter_registry()
    dest_by_id = {d["destination_id"]: d for d in destinations}

    if not cfg.get("enabled"):
        return {
            "schema": SCHEMA_SEND_RESULT, "generated_at": now,
            "status": "DISABLED", "receipts_ingested": 0,
            "receipts_quarantined": 0, "attempted": 0, "spooled": 0,
            "failed_retryable": 0, "failed_permanent": 0,
            "unknown": 0, "skipped_terminal": 0,
            "orphan_attempts_recovered": 0,
            "orphan_attempts_marked_unknown": 0,
            "per_destination": []}

    # ---- orphan recovery --------------------------------------------
    orphan = _recover_orphans(conn, adapters, dest_by_id, now)
    if orphan["recovered"] or orphan["marked_unknown"]:
        state.checkpoint()

    # ---- receipt ingestion ------------------------------------------
    receipt_counts = {"ingested": 0, "quarantined": 0}
    for dest in destinations:
        if dest["adapter"] == "filespool":
            c = _ingest_receipts_for_dest(conn, dest, now)
            receipt_counts["ingested"] += c["ingested"]
            receipt_counts["quarantined"] += c["quarantined"]
    if receipt_counts["ingested"] or receipt_counts["quarantined"]:
        state.checkpoint()

    # ---- dispatch ----------------------------------------------------
    counters = {"attempted": 0, "spooled": 0,
                "failed_retryable": 0, "failed_permanent": 0,
                "unknown": 0, "skipped_terminal": 0}
    per_dest: dict[str, dict] = {}

    for send in list_sends(conn):
        dk = send["delivery_id"]
        if only_delivery_id and dk != only_delivery_id:
            continue
        if send["status"] in TERMINAL_STATES or \
                send["status"] in (S_SPOOLED, S_UNKNOWN):
            counters["skipped_terminal"] += 1
            continue
        dest = dest_by_id.get(send["destination_id"])
        if dest is None:
            continue
        adapter = adapters.get(send["adapter_type"])
        if adapter is None:
            continue
        if not _is_eligible(send, now, retry_cfg):
            continue

        attempt_number = int(send["attempt_count"]) + 1
        attempt_id = f"SNA-{dk}-{attempt_number}"
        started_at = (now_fn or _utcnow)()
        conn.execute(
            "INSERT INTO send_attempts"
            " (attempt_id, delivery_id, attempt_number, started_at,"
            "  status) VALUES (?,?,?,?,?)",
            (attempt_id, dk, attempt_number, started_at, A_STARTED))
        conn.execute(
            "UPDATE sends SET attempt_count=?, last_attempt_at=?"
            " WHERE delivery_id=?",
            (attempt_number, started_at, dk))
        state.checkpoint()  # STARTED durable ANTES del side effect

        request = SendRequest(
            delivery_id=dk,
            instruction_id=send["instruction_id"],
            message_reference=send["message_reference"],
            message_schema=send["message_schema"],
            message_text=send["message_text"],
            content_sha256=send["content_sha256"],
            destination_id=send["destination_id"],
            adapter_type=send["adapter_type"],
            generation=send["generation"])
        try:
            result = adapter["deliver"](
                request, dest.get("config") or {})
        except Exception as exc:  # noqa: BLE001 — bug => permanente
            result = SendAdapterResult(
                O_FAILED_PERMANENT, error_code="ADAPTER_ERROR",
                error_detail_safe=(
                    f"{exc.__class__.__name__}:{exc}")[:200])
        new_status = _record_attempt(
            conn, {**send, "attempt_count": attempt_number},
            result, attempt_number,
            now=(now_fn or _utcnow)(), retry_cfg=retry_cfg)
        counters["attempted"] += 1
        key = {S_SPOOLED: "spooled",
               S_FAILED_RETRYABLE: "failed_retryable",
               S_FAILED_PERMANENT: "failed_permanent",
               S_UNKNOWN: "unknown"}[new_status]
        counters[key] += 1
        pd = per_dest.setdefault(send["destination_id"], {
            "destination_id": send["destination_id"],
            "adapter": send["adapter_type"],
            "attempted": 0, "spooled": 0,
            "failed_retryable": 0, "failed_permanent": 0,
            "unknown": 0})
        pd["attempted"] += 1
        pd[key] += 1
        state.checkpoint()

    if (counters["attempted"] == 0
            and not orphan["recovered"]
            and not orphan["marked_unknown"]
            and receipt_counts["ingested"] == 0
            and receipt_counts["quarantined"] == 0):
        status = "UNCHANGED"
    elif counters["failed_permanent"] or counters["unknown"]:
        status = "PARTIAL"
    elif counters["failed_retryable"]:
        status = "PARTIAL"
    else:
        status = "SUCCESS"

    return {
        "schema": SCHEMA_SEND_RESULT,
        "generated_at": (now_fn or _utcnow)(),
        "status": status,
        "receipts_ingested": receipt_counts["ingested"],
        "receipts_quarantined": receipt_counts["quarantined"],
        "attempted": counters["attempted"],
        "spooled": counters["spooled"],
        "failed_retryable": counters["failed_retryable"],
        "failed_permanent": counters["failed_permanent"],
        "unknown": counters["unknown"],
        "skipped_terminal": counters["skipped_terminal"],
        "orphan_attempts_recovered": orphan["recovered"],
        "orphan_attempts_marked_unknown": orphan["marked_unknown"],
        "per_destination": [per_dest[k] for k in sorted(per_dest)],
    }


# ------------------------------------------------------------------
# operator controls
# ------------------------------------------------------------------

def send_retry(conn, delivery_id: str, *, now: str,
               actor: str = "operator",
               force_unknown: bool = False) -> dict:
    """Re-elegibiliza un send (nunca intenta inline).

    SPOOL_FAILED_*/PREPARED -> PREPARED (audit).
    UNKNOWN_OUTCOME solo con force_unknown.
    SPOOLED/GATEWAY_*/ABANDONED -> error.
    """
    d = get_send(conn, delivery_id)
    if d is None:
        raise ValueError(f"SEND_NOT_FOUND:{delivery_id}")
    status = d["status"]
    if status in (S_SPOOLED, S_GATEWAY_ACCEPTED, S_GATEWAY_REJECTED):
        raise ValueError(f"SEND_TERMINAL_STATE:{delivery_id}:{status}")
    if status == S_ABANDONED:
        raise ValueError(f"SEND_ABANDONED:{delivery_id}")
    if status == S_UNKNOWN and not force_unknown:
        raise ValueError(
            f"SEND_UNKNOWN_REQUIRES_FORCE:{delivery_id}")
    _set_send_status(
        conn, delivery_id, S_PREPARED, actor, now,
        note="MANUAL_RETRY" + (
            "_FORCE_UNKNOWN" if status == S_UNKNOWN else ""),
        next_attempt_after=None)
    return get_send(conn, delivery_id)


def send_abandon(conn, delivery_id: str, *, now: str,
                 actor: str = "operator",
                 note: str | None = None) -> dict:
    """ABANDONED: decision operadora terminal; nunca muta el
    mensaje ni la instruccion de negocio."""
    d = get_send(conn, delivery_id)
    if d is None:
        raise ValueError(f"SEND_NOT_FOUND:{delivery_id}")
    if d["status"] in (S_GATEWAY_ACCEPTED, S_GATEWAY_REJECTED):
        raise ValueError(f"SEND_TERMINAL_STATE:{delivery_id}")
    _set_send_status(
        conn, delivery_id, S_ABANDONED, actor, now,
        note=note or "MANUAL_ABANDON")
    return get_send(conn, delivery_id)


# ------------------------------------------------------------------
# status doc
# ------------------------------------------------------------------

def send_status_doc(state, conn, send_cfg: dict | None,
                    *, now: str | None = None) -> dict:
    """CA_ES_SEND_STATUS_V1 — salud del send ledger, separada del
    health del runtime de negocio."""
    now = now or _utcnow()
    cfg = send_cfg or {}
    enabled = bool(cfg.get("enabled"))
    destinations = enabled_destinations(cfg)

    rows = list_sends(conn)
    counts = {s: 0 for s in (
        S_PREPARED, S_SPOOLED, S_GATEWAY_ACCEPTED,
        S_GATEWAY_REJECTED, S_SWIFT_ACKED, S_SWIFT_NAKED,
        S_FAILED_RETRYABLE,
        S_FAILED_PERMANENT, S_UNKNOWN, S_ABANDONED)}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    spooled = [r["spooled_at"] for r in rows
               if r["status"] == S_SPOOLED and r.get("spooled_at")]
    oldest_spooled = min(spooled) if spooled else None

    attempts = conn.execute(
        "SELECT COUNT(*) c FROM send_attempts").fetchone()["c"]
    receipts = conn.execute(
        "SELECT COUNT(*) c FROM send_receipts").fetchone()["c"]
    quarantined = conn.execute(
        "SELECT COUNT(*) c FROM send_receipts"
        " WHERE status='QUARANTINED'").fetchone()["c"]

    per_dest: dict[str, dict] = {}
    for r in rows:
        e = per_dest.setdefault(r["destination_id"], {
            "destination_id": r["destination_id"],
            "adapter_type": r["adapter_type"],
            "configured": r["destination_id"] in {
                d["destination_id"] for d in destinations},
            "sends": 0})
        e["sends"] += 1
        e[r["status"].lower()] = e.get(r["status"].lower(), 0) + 1

    if not enabled:
        status = "DISABLED"
    elif counts[S_FAILED_PERMANENT] or counts[S_UNKNOWN] \
            or quarantined:
        status = "FAILED"
    elif counts[S_FAILED_RETRYABLE] or counts[S_PREPARED] \
            or counts[S_SPOOLED]:
        status = "DEGRADED"
    else:
        status = "HEALTHY"

    return {
        "schema": SCHEMA_SEND_STATUS,
        "generated_at": now,
        "status": status,
        "enabled": enabled,
        "prepared": counts[S_PREPARED],
        "spooled": counts[S_SPOOLED],
        "gateway_accepted": counts[S_GATEWAY_ACCEPTED],
        "gateway_rejected": counts[S_GATEWAY_REJECTED],
        "swift_acked": counts[S_SWIFT_ACKED],
        "swift_naked": counts[S_SWIFT_NAKED],
        "failed_retryable": counts[S_FAILED_RETRYABLE],
        "failed_permanent": counts[S_FAILED_PERMANENT],
        "unknown_outcome": counts[S_UNKNOWN],
        "abandoned": counts[S_ABANDONED],
        "oldest_spooled_at": oldest_spooled,
        "total_attempts": attempts,
        "total_receipts": receipts,
        "quarantined_receipts": quarantined,
        "destinations": [per_dest[k] for k in sorted(per_dest)],
    }
