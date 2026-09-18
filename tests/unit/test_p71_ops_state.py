"""P7.1 — SQLite state store (docs/p7/p71-state-store.md)."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

import pytest

from ca_es.ops_state import (
    ArtifactCorrupted,
    OpsRunAlreadyActive,
    OpsState,
    OpsStateError,
    SchemaMismatch,
)


@pytest.fixture()
def state(tmp_path):
    return OpsState(tmp_path / "state").init()


def _run(rid="r-1", status="SUCCEEDED", started="2026-09-18T08:00:00Z"):
    return {
        "run_id": rid, "as_of": "2026-09-18", "started_at": started,
        "completed_at": "2026-09-18T08:00:10Z", "run_status": status,
        "config_sha256": "a" * 64, "config_semantic_sha256": "b" * 64,
        "previous_successful_run_id": None, "manifest": {},
        "error_summary": None,
    }


def test_init_creates_schema(tmp_path):
    st = OpsState(tmp_path / "s").init()
    assert (tmp_path / "s" / "ops.db").is_file()
    with st.open() as conn:
        row = conn.execute(
            "SELECT value FROM state_meta WHERE key='schema_version'"
        ).fetchone()
        assert row["value"] == "3"


def test_reopen(state):
    with state.open() as conn:
        state.insert_run(conn, _run())
    with state.open() as conn:
        assert state.get_run(conn, "r-1")["run_status"] == "SUCCEEDED"


def test_rollback_on_error(state):
    with pytest.raises(RuntimeError):
        with state.open() as conn:
            state.insert_run(conn, _run())
            raise RuntimeError("boom")
    with state.open() as conn:
        assert state.get_run(conn, "r-1") is None


def test_schema_mismatch(state):
    conn = sqlite3.connect(state.db_path)
    conn.execute(
        "UPDATE state_meta SET value='999' WHERE key='schema_version'")
    conn.commit()
    conn.close()
    with pytest.raises(SchemaMismatch):
        with state.open():
            pass


def test_artifact_roundtrip(state):
    doc = {"schema": "X", "generated_at": "t0", "v": 1}
    with state.open() as conn:
        ref = state.store_artifact(conn, doc, "X", "V1", "r-1")
    out = state.get_artifact(ref["sha256"])
    assert out["v"] == 1
    # semantic hash ignora generated_at
    other = {"schema": "X", "generated_at": "t9", "v": 1}
    assert ref["semantic_sha256"] == __import__(
        "ca_es.semantic_hash", fromlist=["x"]).semantic_sha256(other)


def test_artifact_missing(state):
    with pytest.raises(OpsStateError, match="ARTIFACT_MISSING"):
        state.get_artifact("f" * 64)


def test_artifact_corrupted(state):
    with state.open() as conn:
        ref = state.store_artifact(conn, {"a": 1}, "X", "V1", "r-1")
    path = state.artifacts_dir / ref["ref"]
    path.write_bytes(b"tampered")
    with pytest.raises(ArtifactCorrupted):
        state.get_artifact(ref["sha256"])


def test_artifact_no_partial_on_disk(state, tmp_path):
    """Un temp abandonado nunca queda registrado como artefacto."""
    with state.open() as conn:
        ref = state.store_artifact(conn, {"a": 1}, "X", "V1", "r-1")
    leftovers = list(
        (state.artifacts_dir / ref["ref"][:2]).glob(".tmp-*"))
    assert leftovers == []


def test_duplicate_artifact_idempotent(state):
    doc = {"a": 1}
    with state.open() as conn:
        r1 = state.store_artifact(conn, doc, "X", "V1", "r-1")
        r2 = state.store_artifact(conn, doc, "X", "V1", "r-2")
    assert r1["sha256"] == r2["sha256"]
    with state.open() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM artifacts"
                         ).fetchone()["c"]
        assert n == 1


def test_steps_and_cache_lookup(state):
    with state.open() as conn:
        state.insert_run(conn, _run("r-1"))
        state.upsert_step(conn, "r-1", {
            "step_id": "deadlines", "step_version": "1",
            "status": "SUCCEEDED",
            "input_semantic_hashes": ["h1"],
            "output_ref": "ab/x.json", "output_sha256": "x" * 64,
        })
        hit = state.find_cached_step(
            conn, "deadlines", "1", json.dumps(["h1"]))
        assert hit is not None
        assert hit["output_sha256"] == "x" * 64
        # version distinta -> no hit
        assert state.find_cached_step(
            conn, "deadlines", "2", json.dumps(["h1"])) is None


def test_failed_run_not_in_cache(state):
    with state.open() as conn:
        state.insert_run(conn, _run("r-1", status="FAILED"))
        state.upsert_step(conn, "r-1", {
            "step_id": "s", "step_version": "1",
            "status": "SUCCEEDED",
            "input_semantic_hashes": ["h"],
        })
        assert state.find_cached_step(
            conn, "s", "1", json.dumps(["h"])) is None


def test_latest_successful_run(state):
    with state.open() as conn:
        state.insert_run(conn, _run("r-1", started="2026-09-18T08:00:00Z"))
        state.insert_run(conn, _run("r-2", status="FAILED",
                                    started="2026-09-18T09:00:00Z"))
        assert state.latest_successful_run(conn)["run_id"] == "r-1"
        assert state.latest_run(conn)["run_id"] == "r-2"


def test_single_writer_lock(state):
    state.acquire_run_lock("run-1")
    second = OpsState(state.root)
    with pytest.raises(OpsRunAlreadyActive):
        second.acquire_run_lock("run-2")
    state.release_run_lock()
    second.acquire_run_lock("run-2")   # liberado -> OK
    second.release_run_lock()


def test_lock_survives_process_death(state):
    """Si la conexion del lock muere (simulado con close), el
    siguiente writer entra."""
    state.acquire_run_lock("run-1")
    state._lock_conn.close()           # simula crash del proceso
    state._lock_conn = None
    second = OpsState(state.root)
    second.acquire_run_lock("run-2")
    second.release_run_lock()


def test_concurrent_read_allowed(state):
    state.acquire_run_lock("run-1")
    results = []
    def _read():
        with OpsState(state.root).open() as conn:
            results.append(state.latest_run(conn))
    t = threading.Thread(target=_read)
    t.start()
    t.join(timeout=10)
    assert not t.is_alive()
    state.release_run_lock()
