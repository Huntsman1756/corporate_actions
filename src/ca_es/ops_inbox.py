"""P7.3 — MT/MX inbox (CA_ES_INBOX_OBSERVATION_V1).

docs/p7/p73-inbox.md. Adapter filesystem: incoming -> dedup
exacta/semantica -> parse via boundary JVM -> processed|failed.
Solo sha256/fingerprints/refs viajan por el state; nunca FIN/XML
crudo en columnas de texto ni logs.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from .semantic_hash import byte_sha256, semantic_sha256

OBS_SCHEMA = "CA_ES_INBOX_OBSERVATION_V1"
INDEX_SCHEMA = "CA_ES_OPS_INBOX_V1"

OBSERVED = "OBSERVED"
PARSED = "PARSED"
PROCESSED = "PROCESSED"
FAILED = "FAILED"
EXACT_DUPLICATE = "EXACT_DUPLICATE"
DUPLICATE_SEMANTIC = "DUPLICATE_SEMANTIC"

EXIT_OK = 0
EXIT_PARSE_ERROR = 2
EXIT_UNSUPPORTED = 3
EXIT_ADAPTER_ERROR = 4


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat(
    ).replace("+00:00", "Z")


def detect_family(raw: bytes) -> str | None:
    """Familia por contenido (nunca por extension)."""
    head = raw[:512].lstrip()
    if head.startswith(b"<"):
        return "ISO_20022_MX"
    if raw.strip():
        return "ISO_15022_MT"
    return None


def semantic_fingerprint(facts_doc: dict) -> str | None:
    """Identidad de negocio = semantic sha256 del multiset
    normalizado de facts. Conservador: solo parse OK con facts."""
    if facts_doc.get("parse_status") not in ("OK", "PARSE_OK"):
        return None
    facts = facts_doc.get("facts") or []
    if not facts:
        return None
    norm = sorted(
        (
            f.get("field_path"),
            f.get("value"),
            f.get("source_tag"),
            f.get("source_qualifier"),
            f.get("sequence"),
            f.get("occurrence"),
        )
        for f in facts
    )
    return semantic_sha256({
        "standard_family": facts_doc.get("standard_family"),
        "message_identifier": facts_doc.get("message_identifier"),
        "facts": norm,
    })


def _parse(family: str, raw: bytes, jar):
    """Boundary JVM; devuelve (facts_doc, exit_code)."""
    if family == "ISO_20022_MX":
        from .mx_facts import parse_mx
        return parse_mx(raw, jar=jar)
    from .swift_mt import parse_mt
    return parse_mt(raw.decode("utf-8"), jar=jar)


def _observe(state, conn, sha: str, run_id: str | None,
             transition: str, detail: str | None = None,
             now: str | None = None) -> None:
    conn.execute(
        "INSERT INTO inbox_observations"
        " (input_sha256, run_id, observed_at, transition, detail)"
        " VALUES (?,?,?,?,?)",
        (sha, run_id, now or _utcnow(), transition, detail))


def _record(state, conn, msg: dict) -> None:
    conn.execute(
        "INSERT INTO inbox_messages"
        " (input_sha256, semantic_fingerprint, standard_family,"
        "  message_identifier, received_at, source_path,"
        "  processing_status, duplicate_status, artifact_refs_json)"
        " VALUES (?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(input_sha256) DO UPDATE SET"
        "   semantic_fingerprint=excluded.semantic_fingerprint,"
        "   processing_status=excluded.processing_status,"
        "   duplicate_status=excluded.duplicate_status,"
        "   artifact_refs_json=excluded.artifact_refs_json",
        (msg["input_sha256"], msg["semantic_fingerprint"],
         msg["standard_family"], msg["message_identifier"],
         msg["received_at"], msg["source_path"],
         msg["processing_status"], msg["duplicate_status"],
         json.dumps(msg["artifact_refs"], sort_keys=True)))


def _find_semantic_dup(conn, fingerprint: str, sha: str) -> str | None:
    row = conn.execute(
        "SELECT input_sha256 FROM inbox_messages"
        " WHERE semantic_fingerprint=? AND input_sha256!=?"
        " LIMIT 1", (fingerprint, sha)).fetchone()
    return row["input_sha256"] if row else None


def _move(path: Path, inbox_dir: Path, bucket: str) -> Path:
    target_dir = inbox_dir / bucket
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / path.name
    if target.exists():
        target = target_dir / f"{path.stem}-{path.stat().st_mtime_ns}{path.suffix}"
    shutil.move(str(path), str(target))
    return target


def process_inbox(state, conn, inbox_dir: Path,
                  run_id: str | None = None,
                  jar: Path | None = None,
                  parse_fn=None,
                  now: str | None = None) -> dict:
    """Escanea incoming/ y procesa cada fichero.

    ``parse_fn`` inyectable para tests: (family, raw_bytes) ->
    (facts_doc, exit_code). Movimiento de ficheros tras commit de
    la fila (crash -> EXACT_DUPLICATE idempotente en el proximo
    scan).
    """
    inbox_dir = Path(inbox_dir)
    incoming = inbox_dir / "incoming"
    processed = inbox_dir / "processed"
    failed = inbox_dir / "failed"
    for d in (incoming, processed, failed):
        d.mkdir(parents=True, exist_ok=True)

    parser = parse_fn or (lambda fam, raw: _parse(fam, raw, jar))
    seen = []
    for path in sorted(incoming.iterdir()):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        sha = byte_sha256(raw)
        ts = now or _utcnow()
        row = conn.execute(
            "SELECT * FROM inbox_messages WHERE input_sha256=?",
            (sha,)).fetchone()
        if row is not None:
            # bytes identicos -> duplicado exacto, no reprocesar
            _observe(state, conn, sha, run_id, EXACT_DUPLICATE,
                     now=ts)
            _move(path, inbox_dir, "processed")
            seen.append({"input_sha256": sha,
                         "processing_status": EXACT_DUPLICATE})
            continue

        _observe(state, conn, sha, run_id, OBSERVED, now=ts)
        family = detect_family(raw)
        msg = {
            "input_sha256": sha,
            "semantic_fingerprint": None,
            "standard_family": family,
            "message_identifier": None,
            "received_at": ts,
            "source_path": str(path),
            "processing_status": OBSERVED,
            "duplicate_status": "NONE",
            "artifact_refs": [],
        }
        raw_ref = state.store_artifact(
            conn, {"schema": "CA_ES_OPS_RAW_INPUT_V1",
                   "input_sha256": sha,
                   "byte_length": len(raw)},
            "CA_ES_OPS_RAW_INPUT_V1", "V1", run_id=run_id)
        raw_ref = dict(raw_ref)
        raw_ref["raw_path"] = str(
            _store_raw_blob(state, sha, raw))
        msg["artifact_refs"].append(raw_ref)

        if family is None:
            msg["processing_status"] = FAILED
            _record(state, conn, msg)
            _observe(state, conn, sha, run_id, FAILED,
                     detail="EMPTY_INPUT", now=ts)
            _move(path, inbox_dir, "failed")
            seen.append({"input_sha256": sha,
                         "processing_status": FAILED})
            continue

        try:
            facts_doc, code = parser(family, raw)
        except Exception as exc:
            msg["processing_status"] = FAILED
            _record(state, conn, msg)
            _observe(state, conn, sha, run_id, FAILED,
                     detail=f"{exc.__class__.__name__}", now=ts)
            _move(path, inbox_dir, "failed")
            seen.append({"input_sha256": sha,
                         "processing_status": FAILED})
            continue

        msg["message_identifier"] = facts_doc.get(
            "message_identifier")
        facts_ref = state.store_artifact(
            conn, facts_doc,
            facts_doc.get("schema_version") or "UNKNOWN", "V1",
            run_id=run_id)
        msg["artifact_refs"].append(facts_ref)

        if code != EXIT_OK:
            msg["processing_status"] = FAILED
            _record(state, conn, msg)
            _observe(state, conn, sha, run_id, FAILED,
                     detail=facts_doc.get("parse_status")
                     or f"EXIT_{code}", now=ts)
            _move(path, inbox_dir, "failed")
            seen.append({
                "input_sha256": sha,
                "processing_status": FAILED,
                "message_identifier": msg["message_identifier"],
            })
            continue

        _observe(state, conn, sha, run_id, PARSED, now=ts)
        fp = semantic_fingerprint(facts_doc)
        msg["semantic_fingerprint"] = fp
        if fp is not None:
            other = _find_semantic_dup(conn, fp, sha)
            if other is not None:
                msg["processing_status"] = DUPLICATE_SEMANTIC
                msg["duplicate_status"] = "SEMANTIC"
                _record(state, conn, msg)
                _observe(state, conn, sha, run_id,
                         DUPLICATE_SEMANTIC,
                         detail=f"same_fingerprint:{other[:16]}",
                         now=ts)
                _move(path, inbox_dir, "processed")
                seen.append({
                    "input_sha256": sha,
                    "processing_status": DUPLICATE_SEMANTIC,
                    "message_identifier":
                        msg["message_identifier"],
                })
                continue

        msg["processing_status"] = PROCESSED
        _record(state, conn, msg)
        _observe(state, conn, sha, run_id, PROCESSED, now=ts)
        _move(path, inbox_dir, "processed")
        seen.append({
            "input_sha256": sha,
            "processing_status": PROCESSED,
            "message_identifier": msg["message_identifier"],
            "semantic_fingerprint": fp,
        })

    return {
        "schema": INDEX_SCHEMA,
        "generated_at": now or _utcnow(),
        "messages": seen,
    }


def _store_raw_blob(state, sha: str, raw: bytes) -> Path:
    """Blob byte-exacto bajo <state>/blobs/<xx>/<sha>.bin."""
    rel = Path(f"{sha[:2]}") / f"{sha}.bin"
    target = state.root / "blobs" / rel
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(raw)
        tmp.replace(target)
    return target
