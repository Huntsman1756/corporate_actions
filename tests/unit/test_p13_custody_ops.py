"""P13.12 — custody inbox + build + health dentro del runtime P7.

parse_fn inyectado: el boundary JVM queda fuera del test pero el
flujo dedup/artifacts/index es el real.
"""

import json

import pytest

from ca_es.ops_custody import (
    build_custody_index,
    latest_index,
    process_custody_inbox,
)
from ca_es.ops_state import OpsState

from test_p13_custody_position import _mt535_facts  # noqa: E402
from test_p13_custody_cash import _camt_facts  # noqa: E402


@pytest.fixture()
def state(tmp_path):
    return OpsState(tmp_path / "st").init()


@pytest.fixture()
def conn(state):
    c = state.acquire_run_lock("test-run")
    yield c
    state.release_run_lock()


def _parser(docs_by_sha):
    def parse(family, raw):
        import hashlib
        sha = hashlib.sha256(raw).hexdigest()
        return docs_by_sha[sha], 0
    return parse


def _drop(inbox_dir, name, payload: bytes):
    target = inbox_dir / "incoming" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return target


class TestCustodyPipeline:
    def test_inbox_to_index_positions(self, state, conn, tmp_path):
        inbox = tmp_path / "custody_inbox"
        docs = {}
        mt = _mt535_facts(positions=[("ES0105448007", "12500,")])
        mt_bytes = json.dumps({"fin": "535"}).encode()
        docs[__import__("hashlib").sha256(mt_bytes).hexdigest()] = mt
        camt = _camt_facts(entries=[{
            "ntry_ref": "N-1", "amount": "10.00",
            "refs": {"EndToEndId": "EVT-1"}}])
        camt_bytes = json.dumps({"xml": "054"}).encode()
        docs[__import__("hashlib").sha256(camt_bytes).hexdigest()] = camt

        _drop(inbox, "a.fin", mt_bytes)
        _drop(inbox, "b.xml", camt_bytes)

        result = process_custody_inbox(
            state, conn, inbox, parse_fn=_parser(docs),
            now="2026-05-05T00:00:00Z")
        assert len(result["messages"]) == 2
        assert all(m["processing_status"] == "PROCESSED"
                   for m in result["messages"])

        index = build_custody_index(state, conn, profile={
            "schema": "CA_ES_CUSTODY_PROFILE_V1",
            "profile_id": "p",
            "account_map": {"SAFE-1": "A001", "IBAN-1": "ACC-1"},
            "reference_map": {"EVT-1": {"event_id": "evt-a"}},
        }, now="2026-05-05T00:00:00Z")

        assert index["schema"] == "CA_ES_CUSTODY_FEED_STATE_V1"
        assert len(index["statements"]) == 1
        stmt = index["statements"][0]
        assert stmt["completeness"] == "COMPLETE"
        assert stmt["account_id"] == "A001"
        assert index["positions_docs"][0]["positions"] == 1
        assert index["bindings_summary"]["bound"] == 1
        assert index["bindings_summary"]["movements"] == 1

        # latest_index round-trip
        latest = latest_index(state, conn)
        assert latest["schema"] == "CA_ES_CUSTODY_FEED_STATE_V1"

    def test_exact_duplicate_no_reprocess(self, state, conn, tmp_path):
        inbox = tmp_path / "custody_inbox"
        mt = _mt535_facts()
        payload = b"same bytes"
        import hashlib
        docs = {hashlib.sha256(payload).hexdigest(): mt}
        _drop(inbox, "a.fin", payload)
        _drop(inbox, "b.fin", payload)  # mismo sha en dos ficheros

        result = process_custody_inbox(
            state, conn, inbox, parse_fn=_parser(docs),
            now="2026-05-05T00:00:00Z")
        statuses = [m["processing_status"] for m in result["messages"]]
        assert "PROCESSED" in statuses
        assert "EXACT_DUPLICATE" in statuses

    def test_non_custody_message_skipped(self, state, conn, tmp_path):
        inbox = tmp_path / "custody_inbox"
        mt = _mt535_facts()
        mt["message_identifier"] = "MT564"  # CA type, no custody
        payload = b"x"
        import hashlib
        docs = {hashlib.sha256(payload).hexdigest(): mt}
        _drop(inbox, "a.fin", payload)
        process_custody_inbox(state, conn, inbox,
                              parse_fn=_parser(docs),
                              now="2026-05-05T00:00:00Z")
        index = build_custody_index(state, conn, now="2026-05-05")
        assert index["statements"] == []

    def test_idempotent_rebuild(self, state, conn, tmp_path):
        inbox = tmp_path / "custody_inbox"
        mt = _mt535_facts(positions=[("X", "1,")])
        payload = b"x"
        import hashlib
        docs = {hashlib.sha256(payload).hexdigest(): mt}
        _drop(inbox, "a.fin", payload)
        process_custody_inbox(state, conn, inbox,
                              parse_fn=_parser(docs),
                              now="2026-05-05T00:00:00Z")
        i1 = build_custody_index(state, conn, now="2026-05-05")
        i2 = build_custody_index(state, conn, now="2026-05-05")
        assert (i1["statements"][0]["snapshot_id"]
                == i2["statements"][0]["snapshot_id"])

    def test_unbound_cash_preserved_not_dropped(self, state, conn,
                                              tmp_path):
        inbox = tmp_path / "custody_inbox"
        camt = _camt_facts(entries=[{"ntry_ref": "N-1"}])  # sin refs
        payload = b"x"
        import hashlib
        docs = {hashlib.sha256(payload).hexdigest(): camt}
        _drop(inbox, "a.xml", payload)
        process_custody_inbox(state, conn, inbox,
                              parse_fn=_parser(docs),
                              now="2026-05-05T00:00:00Z")
        index = build_custody_index(state, conn, now="2026-05-05")
        assert index["bindings_summary"]["unbound_entries"] == 1
        assert index["bindings_summary"]["movements"] == 0
