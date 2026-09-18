"""P9.2 — tests del state store v2 (source refresh state + blobs)."""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from ca_es.ops_state import (
    ArtifactCorrupted, OpsState, OpsStateError, SchemaMismatch,
    OPS_STATE_SCHEMA_VERSION, SCHEMA_SQL, SOURCE_SCHEMA_SQL)


def _meta_version(db: Path) -> str | None:
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT value FROM state_meta WHERE key='schema_version'"
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def test_fresh_init_creates_v2_and_blob_dir(tmp_path):
    state = OpsState(tmp_path / "st").init()
    assert _meta_version(state.db_path) == OPS_STATE_SCHEMA_VERSION
    assert (state.root / "blobs").is_dir()
    with state.open() as conn:
        for table in ("source_documents", "source_observations",
                      "source_parse_results", "source_checkpoints",
                      "source_refreshes"):
            assert conn.execute(
                "SELECT name FROM sqlite_master"
                " WHERE type='table' AND name=?",
                (table,)).fetchone()


def test_v1_db_migrates_additively_on_open(tmp_path):
    # Simula un state v1: schema P7 + version "1", sin tablas P9.
    root = tmp_path / "st"
    root.mkdir()
    db = root / "ops.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT INTO state_meta(key, value)"
        " VALUES ('schema_version', '1')")
    conn.execute(
        "INSERT INTO runs(run_id, run_status) VALUES ('r1', 'OK')")
    conn.commit()
    conn.close()

    state = OpsState(root)
    with state.open() as c:
        assert c.execute(
            "SELECT run_id FROM runs").fetchone()["run_id"] == "r1"
        assert c.execute(
            "SELECT name FROM sqlite_master WHERE name="
            "'source_checkpoints'").fetchone()
    assert _meta_version(db) == OPS_STATE_SCHEMA_VERSION


def test_run_lock_also_migrates_v1(tmp_path):
    root = tmp_path / "st"
    root.mkdir()
    db = root / "ops.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT INTO state_meta(key, value)"
        " VALUES ('schema_version', '1')")
    conn.commit()
    conn.close()

    state = OpsState(root)
    state.acquire_run_lock("run-x")
    try:
        assert _meta_version(db) == OPS_STATE_SCHEMA_VERSION
    finally:
        state.release_run_lock()


def test_unknown_schema_version_fails_closed(tmp_path):
    root = tmp_path / "st"
    root.mkdir()
    db = root / "ops.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT INTO state_meta(key, value)"
        " VALUES ('schema_version', '99')")
    conn.commit()
    conn.close()
    with pytest.raises(SchemaMismatch):
        with OpsState(root).open():
            pass


# ----------------------------- blobs -----------------------------

def test_blob_roundtrip_preserves_bytes_exactly(tmp_path):
    state = OpsState(tmp_path / "st").init()
    payload = b"%PDF-1.4\r\n\x00\xffbinary\r\n"
    meta = state.store_blob(payload)
    sha = hashlib.sha256(payload).hexdigest()
    assert meta["sha256"] == sha
    assert meta["byte_length"] == len(payload)
    assert (state.root / meta["ref"]).read_bytes() == payload
    assert state.get_blob(sha) == payload


def test_blob_store_idempotent_same_bytes(tmp_path):
    state = OpsState(tmp_path / "st").init()
    m1 = state.store_blob(b"abc")
    m2 = state.store_blob(b"abc")
    assert m1 == m2


def test_blob_missing_and_corrupt_fail_closed(tmp_path):
    state = OpsState(tmp_path / "st").init()
    with pytest.raises(OpsStateError, match="BLOB_MISSING"):
        state.get_blob("0" * 64)
    meta = state.store_blob(b"payload")
    (state.root / meta["ref"]).write_bytes(b"EVIL")
    with pytest.raises(ArtifactCorrupted, match="BLOB_CORRUPTED"):
        state.get_blob(meta["sha256"])


# ------------------------- source state --------------------------

def _doc(**kw):
    base = {
        "source_id": "CNMV", "surface_id": "OIR",
        "source_document_id": "CNMV-OIR-100",
        "first_seen_at": "2026-10-01T00:00:00Z",
        "last_seen_at": "2026-10-01T00:00:00Z",
        "publication_date": "2026-09-30",
        "latest_content_sha256": "a" * 64,
        "chosen_content_sha256": None,
        "latest_locator": "https://x/doc",
        "metadata": {"issuer": "X"},
    }
    base.update(kw)
    return base


def test_source_document_latest_vs_chosen(tmp_path):
    state = OpsState(tmp_path / "st").init()
    with state.open() as conn:
        state.upsert_source_document(conn, _doc())
        # Nuevo blob observado: latest avanza, chosen NO se mueve solo.
        state.upsert_source_document(conn, _doc(
            latest_content_sha256="b" * 64,
            last_seen_at="2026-10-02T00:00:00Z"))
        doc = state.get_source_document(conn, "CNMV", "CNMV-OIR-100")
        assert doc["latest_content_sha256"] == "b" * 64
        assert doc["chosen_content_sha256"] is None
        assert doc["first_seen_at"] == "2026-10-01T00:00:00Z"
        assert doc["last_seen_at"] == "2026-10-02T00:00:00Z"
        # Promocion explicita de chosen tras parse OK.
        state.set_chosen_content(
            conn, "CNMV", "CNMV-OIR-100", "a" * 64)
        doc = state.get_source_document(conn, "CNMV", "CNMV-OIR-100")
        assert doc["chosen_content_sha256"] == "a" * 64
        # latest sigue siendo el blob mas reciente aunque no parsee.
        assert doc["latest_content_sha256"] == "b" * 64


def test_observation_insert_and_dedup(tmp_path):
    state = OpsState(tmp_path / "st").init()
    obs = {
        "observation_id": "o1", "refresh_id": "r1",
        "source_id": "CNMV", "surface_id": "OIR",
        "source_document_id": "CNMV-OIR-1",
        "source_locator": "https://x/1",
        "discovered_at": "2026-10-01T00:00:00Z",
        "retrieved_at": "2026-10-01T00:00:01Z",
        "retrieval_status": "RETRIEVED", "http_status": 200,
        "media_type": "application/pdf",
        "content_sha256": "a" * 64, "byte_length": 10,
        "change_status": "NEW_DOCUMENT",
        "source_metadata": {"k": 1},
    }
    with state.open() as conn:
        state.insert_source_observation(conn, obs)
        state.insert_source_observation(conn, obs)  # OR IGNORE
        rows = state.list_source_observations(conn, source_id="CNMV")
        assert len(rows) == 1
        assert rows[0]["observation_id"] == "o1"
        rows = state.list_source_observations(
            conn, refresh_id="other")
        assert rows == []


def test_parse_result_upsert(tmp_path):
    state = OpsState(tmp_path / "st").init()
    with state.open() as conn:
        state.upsert_parse_result(
            conn, "CNMV", "D1", "a" * 64, "OK", None,
            "2026-10-01T00:00:00Z")
        state.upsert_parse_result(
            conn, "CNMV", "D1", "b" * 64, "PARSE_FAILED",
            "BAD_SHAPE", "2026-10-02T00:00:00Z")
        rows = conn.execute(
            "SELECT * FROM source_parse_results"
            " WHERE source_document_id='D1'"
            " ORDER BY content_sha256").fetchall()
        assert [r["parse_status"] for r in rows] == [
            "OK", "PARSE_FAILED"]


def test_checkpoint_roundtrip(tmp_path):
    state = OpsState(tmp_path / "st").init()
    with state.open() as conn:
        assert state.get_checkpoint(conn, "CNMV", "OIR") is None
        cursor = {"last_publication_date": "2026-09-30",
                  "window_days": 14, "documents_seen": 42}
        state.upsert_checkpoint(
            conn, "CNMV", "OIR", cursor, "2026-10-01T00:00:00Z")
        cp = state.get_checkpoint(conn, "CNMV", "OIR")
        assert cp["cursor"] == cursor
        assert cp["updated_at"] == "2026-10-01T00:00:00Z"
        # checkpoint es por (source, surface): OIR != IP
        assert state.get_checkpoint(conn, "CNMV", "IP") is None


def test_source_refresh_persistence(tmp_path):
    state = OpsState(tmp_path / "st").init()
    with state.open() as conn:
        state.insert_source_refresh(conn, {
            "refresh_id": "r1", "started_at": "2026-10-01T00:00:00Z",
            "completed_at": "2026-10-01T00:00:05Z",
            "status": "SUCCESS",
            "summary": {"new_documents": 3}})
        state.insert_source_refresh(conn, {
            "refresh_id": "r2", "started_at": "2026-10-02T00:00:00Z",
            "completed_at": "2026-10-02T00:00:05Z",
            "status": "PARTIAL",
            "summary": {"fetch_failures": 1}})
        latest = state.latest_source_refresh(conn)
        assert latest["refresh_id"] == "r2"
        assert latest["status"] == "PARTIAL"
