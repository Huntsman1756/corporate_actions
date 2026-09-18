"""P11.2 — send ledger (schema v4): migracion aditiva v1/v2/v3 -> v4,
tablas append-only, conservacion del estado previo."""
from __future__ import annotations

import sqlite3

from ca_es.ops_state import OPS_STATE_SCHEMA_VERSION, OpsState

SEND_TABLES = {"sends", "send_attempts", "send_transitions",
               "send_receipts"}


def _version(conn):
    return conn.execute(
        "SELECT value FROM state_meta"
        " WHERE key='schema_version'").fetchone()["value"]


def _tables(conn):
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def test_init_creates_send_tables(tmp_path):
    state = OpsState(tmp_path / "st").init()
    with state.open() as conn:
        assert _version(conn) == "4"
        assert SEND_TABLES <= _tables(conn)


def _build_legacy_state(tmp_path, version: str,
                        extra_scripts=()) -> OpsState:
    """Construye un state legacy con las tablas correspondientes."""
    import ca_es.ops_state as mod

    state = OpsState(tmp_path / "st")
    state.root.mkdir(parents=True, exist_ok=True)
    state.artifacts_dir.mkdir(exist_ok=True)
    state.blobs_dir.mkdir(exist_ok=True)
    conn = sqlite3.connect(state.db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(mod.SCHEMA_SQL)
    for script in extra_scripts:
        conn.executescript(script)
    conn.execute(
        "INSERT INTO state_meta(key, value)"
        " VALUES ('schema_version', ?)", (version,))
    conn.commit()
    conn.close()
    return state


def test_migration_v1_to_v4(tmp_path):
    import ca_es.ops_state as mod

    state = _build_legacy_state(tmp_path, "1")
    with state.open() as conn:
        assert _version(conn) == OPS_STATE_SCHEMA_VERSION == "4"
        tables = _tables(conn)
        assert SEND_TABLES <= tables
        # transitivo: tambien P9 + P10
        assert "source_documents" in tables
        assert "deliveries" in tables


def test_migration_v2_to_v4(tmp_path):
    import ca_es.ops_state as mod

    state = _build_legacy_state(
        tmp_path, "2", extra_scripts=(mod.SOURCE_SCHEMA_SQL,))
    with state.open() as conn:
        assert _version(conn) == "4"
        tables = _tables(conn)
        assert SEND_TABLES <= tables
        assert "deliveries" in tables


def test_migration_v3_to_v4_preserves_delivery_state(tmp_path):
    """State v3 real (con deliveries) migra sin perdida."""
    import ca_es.ops_state as mod

    state = _build_legacy_state(
        tmp_path, "3",
        extra_scripts=(mod.SOURCE_SCHEMA_SQL,
                       mod.DELIVERY_SCHEMA_SQL))
    # siembra una delivery previa
    conn = sqlite3.connect(state.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "INSERT INTO deliveries(delivery_key, alert_key,"
        " alert_semantic_sha256, alert_state, destination_id,"
        " adapter_type, generation, payload_json, status,"
        " attempt_count, first_created_at)"
        " VALUES ('DLV-x', 'k', 'aa', 'OPEN', 'd1', 'file', 1,"
        " '{}', 'DELIVERED', 1, '2026-01-01T00:00:00Z')")
    conn.commit()
    conn.close()

    with state.open() as conn:
        assert _version(conn) == "4"
        assert SEND_TABLES <= _tables(conn)
        d = conn.execute(
            "SELECT * FROM deliveries WHERE delivery_key='DLV-x'"
        ).fetchone()
        assert d["status"] == "DELIVERED"
