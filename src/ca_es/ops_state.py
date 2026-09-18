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

OPS_STATE_SCHEMA_VERSION = "1"

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
        self._lock_conn: sqlite3.Connection | None = None
        self._lock_run_id: str | None = None

    # ---------------- init / open ----------------

    def init(self) -> "OpsState":
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(exist_ok=True)
        (self.root / "inbox" / "incoming").mkdir(
            parents=True, exist_ok=True)
        (self.root / "inbox" / "processed").mkdir(exist_ok=True)
        (self.root / "inbox" / "failed").mkdir(exist_ok=True)
        conn = self._connect()
        try:
            conn.executescript(SCHEMA_SQL)
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
            row = conn.execute(
                "SELECT value FROM state_meta WHERE key='schema_version'"
            ).fetchone()
            if row is None or row["value"] != OPS_STATE_SCHEMA_VERSION:
                raise SchemaMismatch(
                    f"ops.db schema_version="
                    f"{row['value'] if row else None!r}, "
                    f"esperada {OPS_STATE_SCHEMA_VERSION!r}")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---------------- run lock (single writer) ----------------

    def acquire_run_lock(self, run_id: str) -> None:
        """Sostiene BEGIN IMMEDIATE en una conexion propia.

        Si el proceso muere, la conexion muere y el lock desaparece.
        """
        conn = sqlite3.connect(self.db_path, timeout=1)
        conn.row_factory = sqlite3.Row
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
            " ORDER BY started_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def latest_run(self, conn) -> dict | None:
        row = conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
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
                         cache_key: str) -> dict | None:
        """Ultimo step SUCCEEDED de cualquier run con la misma
        cache key (input_semantic_hashes_json) y misma version."""
        row = conn.execute(
            "SELECT s.* FROM run_steps s"
            " JOIN runs r ON r.run_id = s.run_id"
            " WHERE s.step_id=? AND s.step_version=?"
            " AND s.input_semantic_hashes_json=?"
            " AND s.status='SUCCEEDED'"
            " AND r.run_status IN ('SUCCEEDED','PARTIAL')"
            " ORDER BY s.started_at DESC LIMIT 1",
            (step_id, step_version, cache_key)).fetchone()
        return dict(row) if row else None

    def interrupted_steps(self, conn, run_id: str) -> list[dict]:
        rows = conn.execute(
            "SELECT * FROM run_steps WHERE run_id=?"
            " AND status IN ('RUNNING','PENDING')",
            (run_id,)).fetchall()
        return [dict(r) for r in rows]
