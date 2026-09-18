"""P7.1 — SQLite state store del runtime operativo.

docs/p7/p71-state-store.md. SQLite stdlib unico; el DB es metadata
operativa — la verdad de negocio vive en los artefactos
content-addressed bajo ``<state>/artifacts/``.

Escritura de artefacto atomica: temp -> fsync -> os.replace ->
commit DB. Lectura re-verifica byte SHA-256.

Single-writer: conexion dedicada sostiene ``BEGIN IMMEDIATE``
durante el run; si el proceso muere el lock desaparece (no hay PID
files). Segundo writer -> ``OpsRunAlreadyActive``.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .semantic_hash import byte_sha256, semantic_sha256

OPS_STATE_SCHEMA_VERSION = "4"

# v2: tablas P9 (source refresh). Aditivas — los estados v1 se
# migran al vuelo en open()/init() sin perdida.
SOURCE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS source_documents (
    source_id TEXT NOT NULL,
    surface_id TEXT NOT NULL,
    source_document_id TEXT NOT NULL,
    first_seen_at TEXT,
    last_seen_at TEXT,
    publication_date TEXT,
    latest_content_sha256 TEXT,
    chosen_content_sha256 TEXT,
    latest_locator TEXT,
    metadata_json TEXT,
    PRIMARY KEY (source_id, source_document_id)
);
CREATE TABLE IF NOT EXISTS source_observations (
    observation_id TEXT PRIMARY KEY,
    refresh_id TEXT,
    source_id TEXT,
    surface_id TEXT,
    source_document_id TEXT,
    source_locator TEXT,
    discovered_at TEXT,
    retrieved_at TEXT,
    retrieval_status TEXT,
    http_status INTEGER,
    media_type TEXT,
    content_sha256 TEXT,
    byte_length INTEGER,
    change_status TEXT,
    source_metadata_json TEXT
);
CREATE TABLE IF NOT EXISTS source_parse_results (
    source_id TEXT NOT NULL,
    source_document_id TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    parse_status TEXT,
    error TEXT,
    parsed_at TEXT,
    PRIMARY KEY (source_id, source_document_id, content_sha256)
);
CREATE TABLE IF NOT EXISTS source_checkpoints (
    source_id TEXT NOT NULL,
    surface_id TEXT NOT NULL,
    cursor_json TEXT,
    updated_at TEXT,
    PRIMARY KEY (source_id, surface_id)
);
CREATE TABLE IF NOT EXISTS source_refreshes (
    refresh_id TEXT PRIMARY KEY,
    started_at TEXT,
    completed_at TEXT,
    status TEXT,
    summary_json TEXT
);
"""

# v3: tablas P10 (alert delivery ledger). Aditivas — ninguna tabla
# P7/P9 se altera; sin secretos; attempts/transitions append-only.
# docs/p10/p102-delivery-ledger.md
DELIVERY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS deliveries (
    delivery_key TEXT PRIMARY KEY,
    alert_key TEXT NOT NULL,
    alert_semantic_sha256 TEXT,
    alert_state TEXT,
    payload_semantic_sha256 TEXT,
    payload_json TEXT,
    destination_id TEXT NOT NULL,
    adapter_type TEXT NOT NULL,
    generation INTEGER NOT NULL,
    status TEXT NOT NULL,
    next_attempt_after TEXT,
    attempt_count INTEGER DEFAULT 0,
    first_created_at TEXT,
    delivered_at TEXT,
    last_attempt_at TEXT,
    external_receipt_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_deliveries_alert
    ON deliveries(alert_key);
CREATE INDEX IF NOT EXISTS idx_deliveries_status
    ON deliveries(status);
CREATE TABLE IF NOT EXISTS delivery_attempts (
    attempt_id TEXT PRIMARY KEY,
    delivery_key TEXT NOT NULL
        REFERENCES deliveries(delivery_key),
    attempt_number INTEGER NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    status TEXT,
    retryable INTEGER,
    error_code TEXT,
    error_detail_safe TEXT,
    transport_metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_attempts_delivery
    ON delivery_attempts(delivery_key);
CREATE TABLE IF NOT EXISTS delivery_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delivery_key TEXT NOT NULL,
    at TEXT,
    from_status TEXT,
    to_status TEXT,
    actor TEXT,
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_transitions_delivery
    ON delivery_transitions(delivery_key);
"""

# v4: tablas P11 (instruction send ledger). Aditivas — ninguna
# tabla P7/P9/P10 se altera; attempts/transitions/receipts
# append-only; transport_reference solo desde receipt externo.
# docs/p11/p112-send-ledger.md
SEND_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sends (
    delivery_id           TEXT PRIMARY KEY,
    instruction_id        TEXT NOT NULL,
    message_reference     TEXT,
    message_schema        TEXT NOT NULL,
    message_text          TEXT NOT NULL,
    content_sha256        TEXT NOT NULL,
    destination_id        TEXT NOT NULL,
    adapter_type          TEXT NOT NULL,
    generation            INTEGER NOT NULL,
    status                TEXT NOT NULL,
    transport_reference   TEXT,
    attempt_count         INTEGER NOT NULL DEFAULT 0,
    first_prepared_at     TEXT NOT NULL,
    spooled_at            TEXT,
    last_attempt_at       TEXT,
    next_attempt_after    TEXT,
    external_receipt_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_sends_instruction
    ON sends(instruction_id);
CREATE INDEX IF NOT EXISTS idx_sends_status
    ON sends(status);
CREATE TABLE IF NOT EXISTS send_attempts (
    attempt_id              TEXT PRIMARY KEY,
    delivery_id             TEXT NOT NULL
        REFERENCES sends(delivery_id),
    attempt_number          INTEGER NOT NULL,
    started_at              TEXT,
    completed_at            TEXT,
    status                  TEXT,
    retryable               INTEGER,
    error_code              TEXT,
    error_detail_safe       TEXT,
    transport_metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_send_attempts_delivery
    ON send_attempts(delivery_id);
CREATE TABLE IF NOT EXISTS send_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delivery_id      TEXT NOT NULL,
    at               TEXT,
    from_status      TEXT,
    to_status        TEXT NOT NULL,
    actor            TEXT,
    note             TEXT
);
CREATE INDEX IF NOT EXISTS idx_send_transitions_delivery
    ON send_transitions(delivery_id);
CREATE TABLE IF NOT EXISTS send_receipts (
    receipt_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    delivery_id       TEXT NOT NULL,
    receipt_sha256    TEXT NOT NULL,
    status            TEXT NOT NULL,
    gateway_reference TEXT,
    received_at       TEXT,
    reason            TEXT,
    source_path       TEXT,
    quarantine_reason TEXT,
    ingested_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_send_receipts_delivery
    ON send_receipts(delivery_id);
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS state_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    as_of TEXT,
    started_at TEXT,
    completed_at TEXT,
    run_status TEXT,
    config_sha256 TEXT,
    config_semantic_sha256 TEXT,
    previous_successful_run_id TEXT,
    manifest_json TEXT,
    error_summary TEXT
);
CREATE TABLE IF NOT EXISTS run_steps (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    step_id TEXT NOT NULL,
    step_version TEXT,
    status TEXT,
    started_at TEXT,
    completed_at TEXT,
    input_semantic_hashes_json TEXT,
    config_semantic_hash TEXT,
    expected_output_schema TEXT,
    expected_output_version TEXT,
    output_ref TEXT,
    output_sha256 TEXT,
    output_semantic_sha256 TEXT,
    cache_source_run_id TEXT,
    error_code TEXT,
    error_detail TEXT,
    PRIMARY KEY (run_id, step_id)
);
CREATE TABLE IF NOT EXISTS artifacts (
    sha256 TEXT PRIMARY KEY,
    semantic_sha256 TEXT,
    schema TEXT,
    schema_version TEXT,
    media_type TEXT,
    byte_length INTEGER,
    path TEXT,
    created_at TEXT,
    run_id TEXT
);
CREATE TABLE IF NOT EXISTS inbox_messages (
    input_sha256 TEXT PRIMARY KEY,
    semantic_fingerprint TEXT,
    standard_family TEXT,
    message_identifier TEXT,
    received_at TEXT,
    source_path TEXT,
    processing_status TEXT,
    duplicate_status TEXT,
    artifact_refs_json TEXT
);
CREATE TABLE IF NOT EXISTS inbox_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    input_sha256 TEXT NOT NULL,
    run_id TEXT,
    observed_at TEXT,
    transition TEXT,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS outbox (
    alert_key TEXT PRIMARY KEY,
    category TEXT,
    subject_type TEXT,
    subject_key TEXT,
    state TEXT,
    first_observed_run_id TEXT,
    last_observed_run_id TEXT,
    payload_json TEXT,
    evidence_refs_json TEXT,
    semantic_sha256 TEXT,
    delivery_state TEXT,
    delivery_attempts INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS run_lock (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    run_id TEXT,
    owner_token TEXT,
    acquired_at TEXT
);
"""


class OpsStateError(Exception):
    pass


class SchemaMismatch(OpsStateError):
    pass


class OpsRunAlreadyActive(OpsStateError):
    pass


class ArtifactCorrupted(OpsStateError):
    pass


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat(
    ).replace("+00:00", "Z")


class OpsState:
    """State store: SQLite metadata + artefactos content-addressed."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.db_path = self.root / "ops.db"
        self.artifacts_dir = self.root / "artifacts"
        self.blobs_dir = self.root / "blobs"
        self._lock_conn: sqlite3.Connection | None = None
        self._lock_run_id: str | None = None

    # ---------------- init / open ----------------

    def init(self) -> "OpsState":
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(exist_ok=True)
        self.blobs_dir.mkdir(exist_ok=True)
        (self.root / "inbox" / "incoming").mkdir(
            parents=True, exist_ok=True)
        (self.root / "inbox" / "processed").mkdir(exist_ok=True)
        (self.root / "inbox" / "failed").mkdir(exist_ok=True)
        conn = self._connect()
        try:
            conn.executescript(SCHEMA_SQL)
            conn.executescript(SOURCE_SCHEMA_SQL)
            conn.executescript(DELIVERY_SCHEMA_SQL)
            conn.executescript(SEND_SCHEMA_SQL)
            conn.execute(
                "INSERT OR REPLACE INTO state_meta(key, value)"
                " VALUES ('schema_version', ?)",
                (OPS_STATE_SCHEMA_VERSION,))
            conn.commit()
        finally:
            conn.close()
        return self

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def open(self):
        """Conexion de trabajo; valida schema_version."""
        conn = self._connect()
        try:
            self._check_or_migrate(conn)
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---------------- run lock (single writer) ----------------

    def _check_or_migrate(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT value FROM state_meta WHERE key='schema_version'"
        ).fetchone()
        version = row["value"] if row else None
        if version is None:
            raise SchemaMismatch(
                "ops.db sin schema_version (no inicializado)")
        if version == OPS_STATE_SCHEMA_VERSION:
            return
        if version in ("1", "2", "3"):
            # migraciones aditivas: v1 -> +P9+P10+P11,
            # v2 -> +P10+P11, v3 -> +P11
            conn.executescript(SOURCE_SCHEMA_SQL)
            conn.executescript(DELIVERY_SCHEMA_SQL)
            conn.executescript(SEND_SCHEMA_SQL)
            conn.execute(
                "UPDATE state_meta SET value=?"
                " WHERE key='schema_version'",
                (OPS_STATE_SCHEMA_VERSION,))
            return
        raise SchemaMismatch(
            f"ops.db schema_version={version!r}, "
            f"esperada {OPS_STATE_SCHEMA_VERSION!r}")

    def acquire_run_lock(self, run_id: str) -> sqlite3.Connection:
        """Adquiere el mutex (BEGIN IMMEDIATE) y devuelve la
        conexion del writer: el run escribe por esta misma
        conexion. ``checkpoint()`` commitea y re-adquiere el
        mutex por step; si el proceso muere, la conexion muere
        y el lock desaparece.
        """
        conn = sqlite3.connect(self.db_path, timeout=1)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        self._check_or_migrate(conn)
        conn.commit()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM run_lock")
            conn.execute(
                "INSERT INTO run_lock(id, run_id, owner_token,"
                " acquired_at) VALUES (1, ?, ?, ?)",
                (run_id, uuid.uuid4().hex, _utcnow()))
            # commit NO: la transaccion queda abierta = lock vivo
        except sqlite3.OperationalError as exc:
            conn.close()
            raise OpsRunAlreadyActive("OPS_RUN_ALREADY_ACTIVE") from exc
        self._lock_conn = conn
        self._lock_run_id = run_id
        return conn

    def checkpoint(self) -> None:
        """Commit del trabajo acumulado y re-adquisicion del mutex.

        Entre COMMIT y BEGIN IMMEDIATE otro writer podria
        interponerse; si ocurre, el BEGIN falla y el run aborta
        (fail-closed, nunca dos writers).
        """
        self._lock_conn.commit()
        try:
            self._lock_conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            raise OpsRunAlreadyActive("OPS_RUN_LOCK_LOST") from exc

    def release_run_lock(self) -> None:
        if self._lock_conn is not None:
            try:
                self._lock_conn.execute("DELETE FROM run_lock")
                self._lock_conn.commit()
            finally:
                self._lock_conn.close()
                self._lock_conn = None
                self._lock_run_id = None

    # ---------------- artifacts ----------------

    def store_artifact(self, conn: sqlite3.Connection, doc: dict,
                       schema: str, schema_version: str,
                       run_id: str | None = None,
                       media_type: str = "application/json") -> dict:
        """Persiste doc como fichero content-addressed + fila DB.

        Devuelve la referencia del artefacto. Idempotente por sha256.
        """
        data = json.dumps(
            doc, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True).encode("utf-8")
        sha = byte_sha256(data)
        sem = semantic_sha256(doc)
        rel = f"{sha[:2]}/{sha}.json"
        target = self.artifacts_dir / rel
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=target.parent, prefix=".tmp-")
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, target)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        conn.execute(
            "INSERT OR IGNORE INTO artifacts"
            " (sha256, semantic_sha256, schema, schema_version,"
            "  media_type, byte_length, path, created_at, run_id)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (sha, sem, schema, schema_version, media_type,
             len(data), rel, _utcnow(), run_id))
        return {
            "sha256": sha,
            "semantic_sha256": sem,
            "schema": schema,
            "schema_version": schema_version,
            "ref": rel,
        }

    def get_artifact(self, sha: str) -> dict:
        """Lee artefacto re-verificando byte SHA-256."""
        rel = f"{sha[:2]}/{sha}.json"
        path = self.artifacts_dir / rel
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise OpsStateError(f"ARTIFACT_MISSING:{sha[:16]}") from exc
        if byte_sha256(data) != sha:
            raise ArtifactCorrupted(f"ARTIFACT_CORRUPTED:{sha[:16]}")
        return json.loads(data.decode("utf-8"))

    # ---------------- raw source blobs (P9) -------------------

    def store_blob(self, data: bytes) -> dict:
        """Persiste bytes raw content-addressed (tmp+fsync+replace).

        No normaliza nada: PDF/HTML/JSON/text tal como llegaron.
        Idempotente por sha256.
        """
        sha = byte_sha256(data)
        rel = f"blobs/{sha[:2]}/{sha}.bin"
        target = self.root / rel
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=target.parent, prefix=".tmp-")
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, target)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        return {"sha256": sha, "ref": rel, "byte_length": len(data)}

    def get_blob(self, sha: str) -> bytes:
        """Lee blob raw re-verificando byte SHA-256. Fail closed."""
        rel = f"blobs/{sha[:2]}/{sha}.bin"
        path = self.root / rel
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise OpsStateError(f"BLOB_MISSING:{sha[:16]}") from exc
        if byte_sha256(data) != sha:
            raise ArtifactCorrupted(f"BLOB_CORRUPTED:{sha[:16]}")
        return data

    # ---------------- source refresh state (P9) ---------------

    def upsert_source_document(self, conn, doc: dict) -> None:
        conn.execute(
            "INSERT INTO source_documents"
            "(source_id, surface_id, source_document_id,"
            " first_seen_at, last_seen_at, publication_date,"
            " latest_content_sha256, chosen_content_sha256,"
            " latest_locator, metadata_json)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(source_id, source_document_id) DO UPDATE SET"
            " last_seen_at=excluded.last_seen_at,"
            " publication_date=COALESCE(excluded.publication_date,"
            "   source_documents.publication_date),"
            " latest_content_sha256=COALESCE("
            "   excluded.latest_content_sha256,"
            "   source_documents.latest_content_sha256),"
            " chosen_content_sha256=COALESCE("
            "   excluded.chosen_content_sha256,"
            "   source_documents.chosen_content_sha256),"
            " latest_locator=COALESCE(excluded.latest_locator,"
            "   source_documents.latest_locator),"
            " metadata_json=COALESCE(excluded.metadata_json,"
            "   source_documents.metadata_json)",
            (doc["source_id"], doc["surface_id"],
             doc["source_document_id"], doc.get("first_seen_at"),
             doc.get("last_seen_at"), doc.get("publication_date"),
             doc.get("latest_content_sha256"),
             doc.get("chosen_content_sha256"),
             doc.get("latest_locator"),
             json.dumps(doc.get("metadata") or {},
                        sort_keys=True)))

    def get_source_document(self, conn, source_id: str,
                            document_id: str) -> dict | None:
        row = conn.execute(
            "SELECT * FROM source_documents"
            " WHERE source_id=? AND source_document_id=?",
            (source_id, document_id)).fetchone()
        return dict(row) if row else None

    def list_source_documents(self, conn,
                              source_id: str | None = None
                              ) -> list[dict]:
        if source_id:
            rows = conn.execute(
                "SELECT * FROM source_documents WHERE source_id=?"
                " ORDER BY source_document_id", (source_id,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM source_documents"
                " ORDER BY source_id, source_document_id").fetchall()
        return [dict(r) for r in rows]

    def set_chosen_content(self, conn, source_id: str,
                           document_id: str, sha: str | None) -> None:
        conn.execute(
            "UPDATE source_documents SET chosen_content_sha256=?"
            " WHERE source_id=? AND source_document_id=?",
            (sha, source_id, document_id))

    def insert_source_observation(self, conn, obs: dict) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO source_observations"
            "(observation_id, refresh_id, source_id, surface_id,"
            " source_document_id, source_locator, discovered_at,"
            " retrieved_at, retrieval_status, http_status,"
            " media_type, content_sha256, byte_length,"
            " change_status, source_metadata_json)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (obs["observation_id"], obs.get("refresh_id"),
             obs["source_id"], obs["surface_id"],
             obs["source_document_id"], obs.get("source_locator"),
             obs.get("discovered_at"), obs.get("retrieved_at"),
             obs.get("retrieval_status"), obs.get("http_status"),
             obs.get("media_type"), obs.get("content_sha256"),
             obs.get("byte_length"), obs.get("change_status"),
             json.dumps(obs.get("source_metadata") or {},
                        sort_keys=True)))

    def list_source_observations(self, conn,
                                 source_id: str | None = None,
                                 document_id: str | None = None,
                                 refresh_id: str | None = None
                                 ) -> list[dict]:
        sql = "SELECT * FROM source_observations WHERE 1=1"
        params: list = []
        if source_id:
            sql += " AND source_id=?"
            params.append(source_id)
        if document_id:
            sql += " AND source_document_id=?"
            params.append(document_id)
        if refresh_id:
            sql += " AND refresh_id=?"
            params.append(refresh_id)
        sql += " ORDER BY discovered_at, rowid"
        return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def upsert_parse_result(self, conn, source_id: str,
                            document_id: str, content_sha: str,
                            status: str, error: str | None,
                            parsed_at: str) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO source_parse_results"
            "(source_id, source_document_id, content_sha256,"
            " parse_status, error, parsed_at)"
            " VALUES(?,?,?,?,?,?)",
            (source_id, document_id, content_sha, status, error,
             parsed_at))

    def get_checkpoint(self, conn, source_id: str,
                       surface_id: str) -> dict | None:
        row = conn.execute(
            "SELECT * FROM source_checkpoints"
            " WHERE source_id=? AND surface_id=?",
            (source_id, surface_id)).fetchone()
        if row is None:
            return None
        out = dict(row)
        try:
            out["cursor"] = json.loads(out.get("cursor_json") or "{}")
        except ValueError:
            out["cursor"] = {}
        return out

    def upsert_checkpoint(self, conn, source_id: str,
                        surface_id: str, cursor: dict,
                        updated_at: str) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO source_checkpoints"
            "(source_id, surface_id, cursor_json, updated_at)"
            " VALUES(?,?,?,?)",
            (source_id, surface_id,
             json.dumps(cursor, sort_keys=True), updated_at))

    def insert_source_refresh(self, conn, refresh: dict) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO source_refreshes"
            "(refresh_id, started_at, completed_at, status,"
            " summary_json) VALUES(?,?,?,?,?)",
            (refresh["refresh_id"], refresh.get("started_at"),
             refresh.get("completed_at"), refresh.get("status"),
             json.dumps(refresh.get("summary") or {},
                        sort_keys=True)))

    def latest_source_refresh(self, conn) -> dict | None:
        row = conn.execute(
            "SELECT * FROM source_refreshes"
            " ORDER BY started_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    # ---------------- runs ----------------

    def insert_run(self, conn, run: dict) -> None:
        conn.execute(
            "INSERT INTO runs(run_id, as_of, started_at, completed_at,"
            " run_status, config_sha256, config_semantic_sha256,"
            " previous_successful_run_id, manifest_json, error_summary)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (run["run_id"], run.get("as_of"), run.get("started_at"),
             run.get("completed_at"), run.get("run_status"),
             run.get("config_sha256"),
             run.get("config_semantic_sha256"),
             run.get("previous_successful_run_id"),
             json.dumps(run.get("manifest") or {}),
             run.get("error_summary")))

    def update_run(self, conn, run_id: str, **fields) -> None:
        allowed = {"completed_at", "run_status", "manifest_json",
                   "error_summary", "previous_successful_run_id"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if "manifest_json" in sets and not isinstance(
                sets["manifest_json"], str):
            sets["manifest_json"] = json.dumps(sets["manifest_json"])
        if not sets:
            return
        sql = "UPDATE runs SET " + ", ".join(
            f"{k}=?" for k in sets) + " WHERE run_id=?"
        conn.execute(sql, (*sets.values(), run_id))

    def get_run(self, conn, run_id: str) -> dict | None:
        row = conn.execute(
            "SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def latest_successful_run(self, conn) -> dict | None:
        row = conn.execute(
            "SELECT * FROM runs WHERE run_status='SUCCEEDED'"
            " ORDER BY started_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def latest_run(self, conn) -> dict | None:
        row = conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC, rowid DESC"
            " LIMIT 1").fetchone()
        return dict(row) if row else None

    # ---------------- steps ----------------

    def upsert_step(self, conn, run_id: str, step: dict) -> None:
        hashes = step.get("input_semantic_hashes") or []
        conn.execute(
            "INSERT OR REPLACE INTO run_steps"
            " (run_id, step_id, step_version, status, started_at,"
            "  completed_at, input_semantic_hashes_json,"
            "  config_semantic_hash, expected_output_schema,"
            "  expected_output_version, output_ref, output_sha256,"
            "  output_semantic_sha256, cache_source_run_id,"
            "  error_code, error_detail)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, step["step_id"], step.get("step_version"),
             step.get("status"), step.get("started_at"),
             step.get("completed_at"), json.dumps(hashes),
             step.get("config_semantic_hash"),
             step.get("expected_output_schema"),
             step.get("expected_output_version"),
             step.get("output_ref"), step.get("output_sha256"),
             step.get("output_semantic_sha256"),
             step.get("cache_source_run_id"),
             step.get("error_code"), step.get("error_detail")))

    def get_steps(self, conn, run_id: str) -> list[dict]:
        rows = conn.execute(
            "SELECT * FROM run_steps WHERE run_id=? ORDER BY rowid",
            (run_id,)).fetchall()
        return [dict(r) for r in rows]

    def find_cached_step(self, conn, step_id: str, step_version: str,
                         cache_key: str,
                         current_run_id: str | None = None) -> dict | None:
        """Ultimo step SUCCEEDED con la misma cache key y version.

        Elegible si pertenece a un run SUCCEEDED/PARTIAL o al propio
        run en curso (resume reutiliza sus propios pasos).
        """
        row = conn.execute(
            "SELECT s.* FROM run_steps s"
            " JOIN runs r ON r.run_id = s.run_id"
            " WHERE s.step_id=? AND s.step_version=?"
            " AND s.input_semantic_hashes_json=?"
            " AND s.status='SUCCEEDED'"
            " AND (r.run_status IN ('SUCCEEDED','PARTIAL')"
            "      OR s.run_id = ?)"
            " ORDER BY s.started_at DESC, s.rowid DESC LIMIT 1",
            (step_id, step_version, cache_key,
             current_run_id or "")).fetchone()
        return dict(row) if row else None

    def interrupted_steps(self, conn, run_id: str) -> list[dict]:
        rows = conn.execute(
            "SELECT * FROM run_steps WHERE run_id=?"
            " AND status IN ('RUNNING','PENDING')",
            (run_id,)).fetchall()
        return [dict(r) for r in rows]
