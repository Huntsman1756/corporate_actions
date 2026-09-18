"""P13.12 — custody feed dentro del runtime P7.

custody_inbox/incoming (MT535/semt.002/MT940/MT950/camt.053/054)
    -> process_custody_inbox (dedup + facts via boundary JVM)
    -> build_custody_index (observations + snapshots + index doc)
    -> CA_ES_CUSTODY_FEED_STATE_V1

Reusa el inbox P7 (blob byte-exacto, dedup exacta/semantica,
artifacts content-addressed). Ningun contenido de feed viaja por
logs ni columnas de texto — solo sha256/refs.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .custody_bind import bind_cash, movements_doc
from .custody_cash import cash_observation
from .custody_position import position_observation
from .custody_profile import account_map as profile_account_map
from .custody_profile import reference_map as profile_reference_map
from .custody_snapshot import build_snapshots, positions_doc
from .ops_inbox import process_inbox

INDEX_SCHEMA = "CA_ES_CUSTODY_FEED_STATE_V1"

POSITION_TYPES = {"MT535", "semt.002.001.12", "semt.002.002.11"}
CASH_TYPES = {"MT940", "MT950", "camt.053.001.13", "camt.054.001.13"}
CUSTODY_TYPES = POSITION_TYPES | CASH_TYPES


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat(
    ).replace("+00:00", "Z")


def process_custody_inbox(state, conn, inbox_dir: Path,
                          run_id: str | None = None,
                          jar: Path | None = None,
                          parse_fn=None, now: str | None = None) -> dict:
    """Escanea <inbox_dir>/incoming con la maquinaria P7 (dedup,
    parse JVM, blobs). inbox_dir = <state>/custody_inbox."""
    return process_inbox(state, conn, Path(inbox_dir), run_id=run_id,
                         jar=jar, parse_fn=parse_fn, now=now)


def _load_artifact(state, ref: dict) -> dict | None:
    sha = ref.get("sha256")
    if not sha:
        return None
    try:
        return state.get_artifact(sha)
    except Exception:
        return None


def _facts_docs(state, conn) -> list[tuple[str, dict]]:
    """(input_sha256, facts_doc) de mensajes custody procesados."""
    rows = conn.execute(
        "SELECT input_sha256, message_identifier, artifact_refs_json"
        " FROM inbox_messages"
        " WHERE processing_status IN ('PROCESSED','DUPLICATE_SEMANTIC')"
    ).fetchall()
    docs = []
    for row in rows:
        mid = row["message_identifier"]
        if mid not in CUSTODY_TYPES:
            continue
        try:
            refs = json.loads(row["artifact_refs_json"] or "[]")
        except json.JSONDecodeError:
            refs = []
        for ref in refs:
            if ref.get("schema") in ("CA_ES_SWIFT_MT_FACTS_V1",
                                     "CA_ES_SWIFT_MX_FACTS_V1"):
                doc = _load_artifact(state, ref)
                if doc is not None:
                    docs.append((row["input_sha256"], doc))
                break
    return docs


def build_custody_index(state, conn, profile: dict | None = None,
                        now: str | None = None) -> dict:
    """Facts custody -> observations -> snapshots/index/bindings.

    Persiste observations, snapshots, bindings y movements como
    artifacts; devuelve (y guarda) el index doc. Idempotente por
    contenido.
    """
    now = now or _utcnow()
    amap = profile_account_map(profile)
    rmap = profile_reference_map(profile)

    position_obs = []
    cash_obs = []
    skipped = []
    for input_sha, facts in _facts_docs(state, conn):
        mid = facts.get("message_identifier")
        if mid in POSITION_TYPES:
            obs = position_observation(facts, now=now)
            state.store_artifact(conn, obs, "CA_ES_POSITION_OBSERVATION_V1",
                                 "V1", run_id=None)
            position_obs.append(obs)
        elif mid in CASH_TYPES:
            obs = cash_observation(facts, now=now)
            state.store_artifact(conn, obs, "CA_ES_CASH_ACCOUNT_OBSERVATION_V1",
                                 "V1", run_id=None)
            cash_obs.append(obs)
        else:
            skipped.append({"input_sha256": input_sha,
                            "message_identifier": mid})

    index = build_snapshots(position_obs, now=now)
    positions_docs = []
    for snap in index["snapshots"]:
        ref = state.store_artifact(
            conn, snap, "CA_ES_POSITION_SNAPSHOT_V1", "V1", run_id=None)
        snap["artifact_sha256"] = ref["sha256"]
        if snap["completeness"] == "COMPLETE":
            doc = positions_doc(snap, amap, now=now)
            if doc["positions"]:
                pref = state.store_artifact(
                    conn, doc, "CA_ES_POSITIONS_V1", "V1", run_id=None)
                doc["artifact_sha256"] = pref["sha256"]
                positions_docs.append(doc)

    bindings = []
    movements = []
    for obs in cash_obs:
        binding = bind_cash(obs, rmap, amap, now=now)
        state.store_artifact(conn, binding, "CA_ES_CASH_BINDING_V1",
                             "V1", run_id=None)
        bindings.append(binding)
        mdoc = movements_doc(binding, now=now)
        if mdoc["movements"]:
            mref = state.store_artifact(
                conn, mdoc, "CA_ES_CASH_MOVEMENTS_V2", "V2", run_id=None)
            mdoc["artifact_sha256"] = mref["sha256"]
            movements.append(mdoc)

    unbound = sum(
        1 for b in bindings for item in b["bindings"]
        if item["status"] != "BOUND")

    index_doc = {
        "schema": INDEX_SCHEMA,
        "generated_at": now,
        "profile_id": (profile or {}).get("profile_id"),
        "statements": [
            {
                "snapshot_id": s["snapshot_id"],
                "account_id_raw": s["account_id_raw"],
                "account_id": amap.get(s["account_id_raw"]),
                "statement_reference": s["statement_reference"],
                "statement_as_of": s["statement_as_of"],
                "completeness": s["completeness"],
                "reasons": s["reasons"],
                "pages": s["pages"],
                "artifact_sha256": s.get("artifact_sha256"),
            } for s in index["snapshots"]],
        "conflicting_slots": index["conflicting_slots"],
        "positions_docs": [
            {"as_of": d["as_of"],
             "positions": len(d["positions"]),
             "artifact_sha256": d.get("artifact_sha256")}
            for d in positions_docs],
        "cash_reports": [
            {
                "statement_reference": o.get("statement_reference"),
                "account_id_raw": o.get("account_id_raw"),
                "account_id": amap.get(o.get("account_id_raw")),
                "entries": len(o.get("entries") or []),
                "input_sha256": o.get("input_sha256"),
            } for o in cash_obs],
        "bindings_summary": {
            "bound": sum(b["summary"]["bound"] for b in bindings),
            "unbound_entries": unbound,
            "movements": sum(len(m["movements"]) for m in movements),
        },
        "movements_docs": [
            {"movements": len(m["movements"]),
             "artifact_sha256": m.get("artifact_sha256")}
            for m in movements],
        "skipped_messages": skipped,
    }
    state.store_artifact(conn, index_doc, INDEX_SCHEMA, "V1",
                         run_id=None)
    return index_doc


def latest_index(state, conn) -> dict | None:
    row = conn.execute(
        "SELECT sha256 FROM artifacts WHERE schema=?"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (INDEX_SCHEMA,)).fetchone()
    if row is None:
        return None
    return _load_artifact(state, {"sha256": row["sha256"]})
