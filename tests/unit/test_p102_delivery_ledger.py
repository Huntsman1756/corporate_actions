"""P10.2 — delivery ledger (schema v3): migracion aditiva v2->v3,
tablas append-only, conservacion del estado previo."""
from __future__ import annotations

import sqlite3

import pytest

from ca_es.ops_state import OPS_STATE_SCHEMA_VERSION, OpsState


def test_init_creates_delivery_tables(tmp_path):
    state = OpsState(tmp_path / "st").init()
    with state.open() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        version = conn.execute(
            "SELECT value FROM state_meta"
            " WHERE key='schema_version'").fetchone()["value"]
    assert version == "3"
    assert {"deliveries", "delivery_attempts",
            "delivery_transitions"} <= tables


def test_migration_v2_to_v3_preserves_state(tmp_path):
    """State v2 real (con outbox + source docs) migra sin perdida."""
    root = tmp_path / "st"
    # construye un state v2 a mano: schema v1 + tablas P9, sin P10
    import ca_es.ops_state as mod

    state = OpsState(root)
    state.root.mkdir(parents=True, exist_ok=True)
    state.artifacts_dir.mkdir(exist_ok=True)
    state.blobs_dir.mkdir(exist_ok=True)
    conn = sqlite3.connect(state.db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(mod.SCHEMA_SQL)
    conn.executescript(mod.SOURCE_SCHEMA_SQL)
    conn.execute(
        "INSERT INTO state_meta(key, value)"
        " VALUES ('schema_version', '2')")
    conn.execute(
        "INSERT INTO outbox(alert_key, category, subject_type,"
        " subject_key, state, first_observed_run_id,"
        " last_observed_run_id, payload_json, evidence_refs_json,"
        " semantic_sha256, delivery_state, delivery_attempts,"
        " created_at, updated_at)"
        " VALUES ('DEADLINE_OVERDUE|dk1', 'DEADLINE_OVERDUE',"
        " 'deadline', 'dk1', 'OPEN', 'r1', 'r1', '{}', '[]', 'aa',"
        " 'PENDING_DELIVERY', 0, '2026-01-01T00:00:00Z',"
        " '2026-01-01T00:00:00Z')")
    conn.commit()
    conn.close()

    with state.open() as conn:
        version = conn.execute(
            "SELECT value FROM state_meta"
            " WHERE key='schema_version'").fetchone()["value"]
        alert = conn.execute(
            "SELECT * FROM outbox WHERE alert_key=?",
            ("DEADLINE_OVERDUE|dk1",)).fetchone()
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert version == OPS_STATE_SCHEMA_VERSION == "3"
    assert alert["delivery_state"] == "PENDING_DELIVERY"
    assert {"deliveries", "delivery_attempts",
            "delivery_transitions"} <= tables


def test_migration_v1_to_v3(tmp_path):
    import ca_es.ops_state as mod

    state = OpsState(tmp_path / "st")
    state.root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(state.db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(mod.SCHEMA_SQL)
    conn.execute(
        "INSERT INTO state_meta(key, value)"
        " VALUES ('schema_version', '1')")
    conn.commit()
    conn.close()
    with state.open() as conn:
        version = conn.execute(
            "SELECT value FROM state_meta"
            " WHERE key='schema_version'").fetchone()["value"]
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert version == "3"
    assert {"source_documents", "deliveries"} <= tables
