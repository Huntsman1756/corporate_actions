"""P11 — FileSpoolTransport (docs/p11/p113).

Outbox duradero REAL sobre filesystem — no un simple file write:

    <spool>/
        outbox/
            <delivery_id>.msg         bytes exactos del mensaje
            <delivery_id>.meta.json   CA_ES_SEND_META_V1
        receipts/                     evidencia EXTERNA entrante
            <delivery_id>.ack.json
            <delivery_id>.nak.json
            processed/
        quarantine/

Protocolo de escritura (atomicidad):
    1. tmp en el MISMO directorio outbox (mismo filesystem)
    2. write + flush + fsync
    3. os.replace -> nombre final (atomico en POSIX/Windows)
    4. .msg primero, .meta.json despues -> meta es el commit
    5. fsync del directorio outbox para durabilidad del rename

Semantica idempotente:
    delivery_id inexistente                 -> crear
    delivery_id existente + mismo sha256    -> replay no-op
    delivery_id existente + sha256 distinto -> FAIL CLOSED
                                               (DELIVERY_ID_COLLISION)

Nunca sobrescribe silenciosamente. `.msg` sin `.meta` (crash
entre pasos) -> verify()=NOT_SPOOLED -> reintento seguro:
el contenido huérfano se compara antes de cualquier write;
mismo sha -> completar con meta; sha distinto -> COLLISION.

Esta convencion de directorios es PROTOCOLO DE ADAPTER propio —
no un estandar SWIFT. GATEWAY_* requiere receipts creados por un
consumidor externo real.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ..ops_send import (
    O_FAILED_PERMANENT,
    O_FAILED_RETRYABLE,
    O_SPOOLED,
    SCHEMA_SEND_META,
    SendAdapterResult,
    SendRequest,
    V_COLLISION,
    V_NOT_SPOOLED,
    V_SPOOLED,
    V_UNKNOWN,
    content_sha256_of,
)
from ..semantic_hash import canonical_json

CONFIG_KEYS = frozenset({"spool_directory"})


def _paths(spool: Path, delivery_id: str) -> tuple[Path, Path]:
    return (spool / "outbox" / f"{delivery_id}.msg",
            spool / "outbox" / f"{delivery_id}.meta.json")


def _fsync_dir(path: Path):
    """fsync del directorio para persistir el rename. En Windows
    os.open de un dir no esta soportado -> best-effort."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_atomic(path: Path, data: bytes):
    """tmp mismo-dir -> write+flush+fsync -> os.replace atomico."""
    fd, tmp = tempfile.mkstemp(
        dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_meta(meta_path: Path) -> dict | None:
    import json
    try:
        doc = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def _sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------
# adapter contract
# ------------------------------------------------------------------

def deliver(request: SendRequest, dest_config: dict) \
        -> SendAdapterResult:
    """Handoff durable al boundary. Exclusivo por delivery_id.

    El write a tmp es pre-commit: un fallo ahi es retryable.
    Entre .msg renombrado y .meta renombrado el outcome real es
    UNKNOWN (verify() lo resuelve en la siguiente pasada).
    """
    spool = (dest_config or {}).get("spool_directory")
    if not spool:
        return SendAdapterResult(
            O_FAILED_PERMANENT, error_code="MISSING_SPOOL_DIRECTORY")
    actual_sha = content_sha256_of(request.message_text)
    if actual_sha != request.content_sha256:
        # hash binding roto: nunca se escribe nada en el spool
        return SendAdapterResult(
            O_FAILED_PERMANENT, error_code="CONTENT_HASH_MISMATCH",
            error_detail_safe="message_text no casa con "
                              "content_sha256 del ledger")
    spool_path = Path(spool)
    try:
        outbox = spool_path / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        (spool_path / "receipts").mkdir(exist_ok=True)
        (spool_path / "quarantine").mkdir(exist_ok=True)
    except OSError as exc:
        return SendAdapterResult(
            O_FAILED_PERMANENT, error_code="SPOOL_NOT_CREATABLE",
            error_detail_safe=str(exc)[:200])

    msg_path, meta_path = _paths(spool_path, request.delivery_id)
    body = request.message_text.encode("utf-8")

    # ---- idempotencia ------------------------------------------------
    if meta_path.exists():
        meta = _read_meta(meta_path)
        if meta is None:
            return SendAdapterResult(
                O_FAILED_PERMANENT, error_code="META_UNREADABLE")
        if meta.get("content_sha256") == request.content_sha256 \
                and msg_path.exists():
            # hash binding sobre los BYTES reales, no solo el meta
            if _sha256_file(msg_path) == request.content_sha256:
                return SendAdapterResult(
                    O_SPOOLED,
                    receipt={"replayed": True,
                             "msg_path": str(msg_path)})
            return SendAdapterResult(
                O_FAILED_PERMANENT,
                error_code="DELIVERY_ID_COLLISION",
                error_detail_safe=(
                    ".msg no casa con content_sha256 del ledger"))
        return SendAdapterResult(
            O_FAILED_PERMANENT, error_code="DELIVERY_ID_COLLISION",
            error_detail_safe=(
                "delivery_id reutilizado con sha distinto"))

    if msg_path.exists():
        # crash entre .msg y .meta en un intento anterior
        existing = _sha256_file(msg_path)
        if existing != request.content_sha256:
            return SendAdapterResult(
                O_FAILED_PERMANENT,
                error_code="DELIVERY_ID_COLLISION",
                error_detail_safe=(
                    ".msg huerfano con sha distinto"))
        # mismo sha: completar el commit escribiendo solo meta
        meta_doc = _meta_doc(request)
        try:
            _write_atomic(
                meta_path, canonical_json(meta_doc).encode("utf-8"))
            _fsync_dir(outbox)
        except OSError as exc:
            return SendAdapterResult(
                O_FAILED_RETRYABLE, error_code="SPOOL_IO",
                error_detail_safe=str(exc)[:200])
        return SendAdapterResult(
            O_SPOOLED, receipt={"replayed": False,
                                "completed_orphan": True,
                                "msg_path": str(msg_path)})

    # ---- escritura transaccional -------------------------------------
    try:
        _write_atomic(msg_path, body)
    except OSError as exc:
        return SendAdapterResult(
            O_FAILED_RETRYABLE, error_code="SPOOL_IO",
            error_detail_safe=str(exc)[:200])
    # punto de no retorno parcial: .msg existe, .meta aun no.
    # Un fallo aqui es UNKNOWN — verify() lo resuelve despues.
    meta_doc = _meta_doc(request)
    try:
        _write_atomic(
            meta_path, canonical_json(meta_doc).encode("utf-8"))
        _fsync_dir(outbox)
    except OSError as exc:
        return SendAdapterResult(
            "UNKNOWN", error_code="SPOOL_IO_POST_MSG",
            error_detail_safe=str(exc)[:200])

    return SendAdapterResult(
        O_SPOOLED,
        receipt={"replayed": False, "msg_path": str(msg_path)})


def _meta_doc(request: SendRequest) -> dict:
    return {
        "schema": SCHEMA_SEND_META,
        "delivery_id": request.delivery_id,
        "instruction_id": request.instruction_id,
        "message_reference": request.message_reference,
        "message_schema": request.message_schema,
        "content_sha256": request.content_sha256,
        "destination_id": request.destination_id,
        "adapter_type": request.adapter_type,
        "generation": request.generation,
    }


def verify(request: SendRequest, dest_config: dict) -> str:
    """Verificacion post-crash para orphan STARTED.

    SPOOLED      msg+meta presentes y meta.content_sha256 casa
    NOT_SPOOLED  sin evidencia comprometida (reintento seguro)
    COLLISION    evidencia con sha distinto del ledger
    UNKNOWN      no se puede determinar
    """
    spool = (dest_config or {}).get("spool_directory")
    if not spool:
        return V_UNKNOWN
    spool_path = Path(spool)
    msg_path, meta_path = _paths(spool_path, request.delivery_id)

    if meta_path.exists():
        meta = _read_meta(meta_path)
        if meta is None:
            return V_UNKNOWN
        if meta.get("content_sha256") == request.content_sha256:
            if not msg_path.exists():
                return V_UNKNOWN
            # meta declara el sha pero el .msg debe acreditarlo
            return V_SPOOLED if _sha256_file(
                msg_path) == request.content_sha256 \
                else V_COLLISION
        return V_COLLISION
    if msg_path.exists():
        existing = _sha256_file(msg_path)
        if existing == request.content_sha256:
            # msg comprometido, meta ausente: entregable pero
            # no verificado completo -> el adapter puede completar
            # el meta en el reintento; reportamos NOT_SPOOLED
            # (reintento seguro e idempotente)
            return V_NOT_SPOOLED
        return V_COLLISION
    return V_NOT_SPOOLED
