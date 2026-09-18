"""P9.5 — Canon refresh sobre evidencia acumulada.

docs/p9/p95-canon-refresh.md. NO es un segundo canonicalizer:

* pasa de promocion: intenta parsear ``latest_content_sha256`` cuando
  difiere de ``chosen``; promociona solo si el parser devuelve OK;
* construye un ``CorpusManifest`` en memoria sobre TODOS los
  documentos con ``chosen`` (evidencia durable, no la descarga de
  hoy) y materializa los blobs en un corpus scratch determinista;
* ejecuta ``parse_manifest_corpus`` + ``pipeline_body`` +
  ``operational_canon`` + ``canon_payload`` — el mismo pipeline.

Invariantes: una caida de fuente no borra aserciones; un blob nuevo
que no parsea no desplaza al chosen anterior; ausencia != desaparicion.
"""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from .export import canon_payload, operational_canon
from .ops_sources import CONTRACT_REFRESH
from .pipeline import parse_manifest_corpus, pipeline_body
from .semantic_hash import byte_sha256, semantic_sha256
from .source_policy import load_source_policy
from .sources.documents import CorpusManifest, SourceDocument
from .sources.registry import PARSERS

CONTRACT_CANON_REFRESH = "CA_ES_CANON_REFRESH_V1"
CANON_CORPUS_ID = "live-accumulated"

_META_CANON_SHA = "current_canon_sha256"
_META_CANON_LOGICAL = "current_canon_logical_sha256"
_META_EVIDENCE = "canon_evidence_sha256"
_META_REFRESH_DOC = "current_canon_refresh_sha256"

_RELATED_REG_RE = re.compile(r"(\d{4,})")


def get_state_meta(conn, key: str) -> str | None:
    row = conn.execute(
        "SELECT value FROM state_meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_state_meta(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO state_meta(key, value) VALUES (?,?)",
        (key, value))


def _first_observation_for_sha(conn, source_id: str, doc_id: str,
                               sha: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM source_observations WHERE source_id=?"
        " AND source_document_id=? AND content_sha256=?"
        " AND retrieval_status='RETRIEVED'"
        " ORDER BY retrieved_at, rowid LIMIT 1",
        (source_id, doc_id, sha)).fetchone()
    return dict(row) if row else None


def _manifest_relations(metadata: dict, surface_id: str) -> tuple:
    """Convierte los enlaces 'Relacionado' capturados en discovery a
    relaciones de manifest. Solo si el registro destino se extrae de
    forma determinista; si no, sin relacion (fail-closed)."""
    relations = []
    for entry in metadata.get("related") or []:
        url = entry.get("url") or ""
        match = _RELATED_REG_RE.findall(url)
        if not match:
            continue
        target = match[-1]
        prefix = "CNMV-IP" if surface_id == "IP" else "CNMV-OIR"
        relations.append({
            "relation": "EXPLICIT_PREDECESSOR_REFERENCE",
            "target_source_id": "CNMV",
            "target_official_document_id": f"{prefix}-{target}",
            "evidence_locator": entry.get("text") or url,
        })
    return tuple(relations)


def _source_document_for(state, conn, row: dict, sha: str,
                         policy: dict, scratch_rel: str) -> SourceDocument:
    obs = _first_observation_for_sha(
        conn, row["source_id"], row["source_document_id"], sha)
    metadata = json.loads(row.get("metadata_json") or "{}")
    source_policy = policy.get(row["source_id"])
    return SourceDocument(
        source_id=row["source_id"],
        official_document_id=row["source_document_id"],
        content_sha256=sha,
        retrieved_at=(
            (obs or {}).get("retrieved_at")
            or row.get("first_seen_at") or "1970-01-01"),
        publication_date=row.get("publication_date"),
        media_type=(obs or {}).get("media_type") or "application/json",
        raw_relpath=scratch_rel,
        redistribution=(
            source_policy.redistribution if source_policy
            else "LOCAL_ONLY"),
        retrieval_status="OK",
        acquisition={
            "url": row.get("latest_locator"),
            "retrieval_method": "P9_SOURCE_REFRESH",
            "surface_id": row.get("surface_id"),
            "observation_id": (obs or {}).get("observation_id"),
        },
        relations=_manifest_relations(
            metadata, row.get("surface_id") or ""),
    )


def _promote_latest(state, conn, doc_row: dict, policy: dict,
                    now: str) -> tuple[str | None, dict | None]:
    """Intenta parsear latest != chosen. Devuelve
    (promoted_sha | None, failure | None)."""
    source_id = doc_row["source_id"]
    doc_id = doc_row["source_document_id"]
    latest = doc_row.get("latest_content_sha256")
    chosen = doc_row.get("chosen_content_sha256")
    if not latest or latest == chosen:
        return None, None
    parser = PARSERS.get(source_id)
    if parser is None:
        state.upsert_parse_result(
            conn, source_id, doc_id, latest, "NO_PARSER",
            f"NO_PARSER:{source_id}", now)
        return None, {
            "document_id": doc_id, "content_sha256": latest,
            "error": f"NO_PARSER:{source_id}"}
    try:
        payload = state.get_blob(latest)
        scratch = _source_document_for(
            state, conn, doc_row, latest, policy,
            f"raw/{source_id}/{doc_id}/{latest}.bin")
        parser(payload, scratch, policy)
    except Exception as exc:  # noqa: BLE001 — fail closed
        error = f"{exc.__class__.__name__}:{exc}"[:300]
        state.upsert_parse_result(
            conn, source_id, doc_id, latest, "PARSE_FAILED",
            error, now)
        return None, {
            "document_id": doc_id, "content_sha256": latest,
            "error": error}
    state.set_chosen_content(conn, source_id, doc_id, latest)
    state.upsert_parse_result(
        conn, source_id, doc_id, latest, "OK", None, now)
    return latest, None


def _diff_canons(previous: dict | None, new: dict) -> tuple[
        list, list, list]:
    """Eventos added/changed/unchanged por canonical_event_id +
    semantic hash por evento."""
    def key(evt: dict) -> str:
        return semantic_sha256(evt)

    prev_events = {
        e["canonical_event_id"]: e
        for e in (previous or {}).get("events", [])}
    added, changed, unchanged = [], [], []
    for event in new.get("events", []):
        event_id = event["canonical_event_id"]
        prev = prev_events.get(event_id)
        if prev is None:
            added.append(event_id)
        elif key(prev) != key(event):
            changed.append(event_id)
        else:
            unchanged.append(event_id)
    return sorted(added), sorted(changed), sorted(unchanged)


def build_accumulated_canon(
        state, conn, chosen_rows: list[dict], policy: dict,
        now: str, *, seed_ledger=None,
        adjudications_path: Path | None = None,
        resolver=None, instrument_index=None) -> dict:
    """Rebuild del canon sobre un conjunto de documentos chosen.

    Materializa los blobs en un corpus scratch determinista bajo
    ``state.root`` y ejecuta el pipeline existente. Devuelve el
    payload ``CA_ES_OPERATIONAL_CANON_V1``; no persiste nada —
    reusable por ``run_canon_refresh`` y por replay (P9.8).
    """
    documents: list[SourceDocument] = []
    with tempfile.TemporaryDirectory(
            prefix="caes-canon-", dir=state.root) as scratch:
        scratch_root = Path(scratch)
        for row in sorted(
                chosen_rows,
                key=lambda r: (r["source_id"], r["source_document_id"])):
            sha = row["chosen_content_sha256"]
            rel = (f"raw/{row['source_id']}/"
                   f"{row['source_document_id']}/{sha}.bin")
            target = scratch_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(state.get_blob(sha))
            documents.append(_source_document_for(
                state, conn, row, sha, policy, rel))

        manifest = CorpusManifest(
            manifest_version="CA_ES_SOURCE_MANIFEST_V1",
            corpus_id=CANON_CORPUS_ID,
            retrieved_at=now,
            documents=tuple(documents))
        corpus = parse_manifest_corpus(scratch_root, manifest, policy)
        result = pipeline_body(
            corpus, seed_ledger=seed_ledger,
            adjudications_path=adjudications_path,
            resolver=resolver, instrument_index=instrument_index)

    return canon_payload(
        operational_canon(result["body"], CANON_CORPUS_ID))


def replay_canon(state, conn, *, policy_path: Path,
                 source_id: str | None = None,
                 from_date: str | None = None,
                 to_date: str | None = None,
                 now: str | None = None,
                 seed_ledger=None,
                 adjudications_path: Path | None = None,
                 resolver=None, instrument_index=None) -> dict:
    """P9.8 — replay determinista sobre evidencia chosen almacenada.

    Sin red, sin mutacion: no promueve, no escribe ``state_meta``, no
    crea observaciones ni artefactos. ``from_date``/``to_date``
    filtran por ``publication_date`` (inclusivos); con ventana
    activa, documentos sin fecha quedan excluidos (fail-closed).
    Devuelve ``{schema, window, documents, canon}`` — el canon es el
    payload completo, byte-determinista para el mismo evidence set.
    """
    from .ops_sources import _now_iso

    now = now or _now_iso()
    policy = load_source_policy(Path(policy_path))
    window = from_date is not None or to_date is not None
    rows = []
    for row in state.list_source_documents(conn):
        if not row.get("chosen_content_sha256"):
            continue
        if source_id and row["source_id"] != source_id:
            continue
        if window:
            pub = row.get("publication_date")
            if not pub:
                continue
            if from_date and pub < from_date:
                continue
            if to_date and pub > to_date:
                continue
        rows.append(row)
    canon = build_accumulated_canon(
        state, conn, rows, policy, now,
        seed_ledger=seed_ledger,
        adjudications_path=adjudications_path,
        resolver=resolver, instrument_index=instrument_index)
    return {
        "schema": "CA_ES_SOURCE_REPLAY_V1",
        "generated_at": now,
        "source_id": source_id,
        "from_date": from_date,
        "to_date": to_date,
        "documents": len(rows),
        "canon": canon,
    }


def run_canon_refresh(state, conn, *, policy_path: Path,
                      source_refresh_id: str | None = None,
                      now: str | None = None,
                      resolver=None,
                      instrument_index=None,
                      seed_ledger=None,
                      adjudications_path: Path | None = None) -> dict:
    """Rebuild del canon sobre la evidencia acumulada durable.

    Devuelve ``CA_ES_CANON_REFRESH_V1`` (persistido como artefacto y
    puntero ``state_meta.current_canon_*`` actualizado).
    """
    from .ops_sources import _now_iso

    now = now or _now_iso()
    policy = load_source_policy(Path(policy_path))

    # -- 1. pase de promocion chosen <- latest ---------------------
    promotions: list[dict] = []
    parse_failures: list[dict] = []
    doc_rows = state.list_source_documents(conn)
    for row in doc_rows:
        promoted, failure = _promote_latest(
            state, conn, row, policy, now)
        if promoted:
            promotions.append({
                "document_id": row["source_document_id"],
                "from": row.get("chosen_content_sha256"),
                "to": promoted})
        if failure:
            parse_failures.append(failure)

    # -- 2. manifest sobre chosen (evidencia durable) --------------
    chosen_rows = [
        row for row in state.list_source_documents(conn)
        if row.get("chosen_content_sha256")]

    # Evidence set = identidad semantica del corpus acumulado. Si no
    # cambio respecto al rebuild anterior, devolvemos el MISMO
    # artefacto canon-refresh: mismo byte sha => mismo semantic hash
    # => el DAG marca downstream SKIPPED_UNCHANGED (P9.6).
    policy_bytes = Path(policy_path).read_bytes()
    evidence_sha = semantic_sha256({
        "documents": sorted(
            f"{r['source_id']}:{r['source_document_id']}:"
            f"{r['chosen_content_sha256']}" for r in chosen_rows),
        "policy_sha256": byte_sha256(policy_bytes),
    })
    prev_canon_sha = get_state_meta(conn, _META_CANON_SHA)
    prev_logical = get_state_meta(conn, _META_CANON_LOGICAL)
    latest_refresh = state.latest_source_refresh(conn)
    if (evidence_sha == get_state_meta(conn, _META_EVIDENCE)
            and prev_canon_sha and prev_logical):
        # Evidence set inalterado: NO se re-ejecuta el pipeline
        # (caro), pero se emite un doc NUEVO y veraz para esta
        # invocacion: UNCHANGED + parse failures de este pase.
        # El canon artifact es el mismo => el input ref canon que se
        # inyecta downstream es identico => SKIPPED_UNCHANGED.
        reasons = ["EVIDENCE_SET_IDENTICAL"]
        if parse_failures:
            reasons.append("PARSE_FAILURES_PRESENT")
        doc = {
            "schema": CONTRACT_CANON_REFRESH,
            "canon_refresh_id": "CRF-" + byte_sha256(json.dumps({
                "schema": CONTRACT_CANON_REFRESH,
                "started_at": now,
                "evidence_sha256": evidence_sha,
            }, sort_keys=True).encode("utf-8"))[:24],
            "previous_canon_logical_sha256": prev_logical,
            "new_canon_logical_sha256": prev_logical,
            "source_refresh_id": (
                source_refresh_id
                or (latest_refresh or {}).get("refresh_id")),
            "documents_considered": len(doc_rows),
            "documents_new": 0,
            "documents_changed": 0,
            "documents_unchanged": len(chosen_rows),
            "documents_failed": len(parse_failures),
            "parse_promotions": [],
            "parse_failures": parse_failures,
            "events_added": [],
            "events_changed": [],
            "events_unchanged": [],
            "refresh_status": "UNCHANGED",
            "reasons": reasons,
            "canon_artifact_sha256": prev_canon_sha,
            "source_refresh_contract": CONTRACT_REFRESH,
        }
        refresh_ref = state.store_artifact(
            conn, doc, CONTRACT_CANON_REFRESH, "V1")
        set_state_meta(conn, _META_REFRESH_DOC, refresh_ref["sha256"])
        return doc

    canon = build_accumulated_canon(
        state, conn, chosen_rows, policy, now,
        seed_ledger=seed_ledger,
        adjudications_path=adjudications_path,
        resolver=resolver, instrument_index=instrument_index)
    new_logical = canon["logical_sha256"]

    # -- 3. diff vs canon previo ------------------------------------
    prev_sha = get_state_meta(conn, _META_CANON_SHA)
    prev_logical = get_state_meta(conn, _META_CANON_LOGICAL)
    previous = state.get_artifact(prev_sha) if prev_sha else None
    added, changed, unchanged = _diff_canons(previous, canon)

    # -- 4. persistir -----------------------------------------------
    canon_ref = state.store_artifact(
        conn, canon, "CA_ES_OPERATIONAL_CANON_V1", "V1")
    set_state_meta(conn, _META_CANON_SHA, canon_ref["sha256"])
    set_state_meta(conn, _META_CANON_LOGICAL, new_logical)
    set_state_meta(conn, _META_EVIDENCE, evidence_sha)

    if prev_logical is None:
        status = "SUCCESS"
        reasons = ["FIRST_CANON"]
    elif new_logical == prev_logical:
        status = "UNCHANGED"
        reasons = ["CANON_IDENTICAL"]
    else:
        status = "SUCCESS"
        reasons = []
    if parse_failures:
        reasons.append("PARSE_FAILURES_PRESENT")

    latest_refresh = state.latest_source_refresh(conn)
    doc = {
        "schema": CONTRACT_CANON_REFRESH,
        "canon_refresh_id": "CRF-" + byte_sha256(json.dumps({
            "schema": CONTRACT_CANON_REFRESH,
            "source_refresh_id": source_refresh_id,
            "documents": sorted(
                f"{r['source_id']}:{r['source_document_id']}:"
                f"{r['chosen_content_sha256']}"
                for r in chosen_rows),
            "started_at": now,
        }, sort_keys=True).encode("utf-8"))[:24],
        "previous_canon_logical_sha256": prev_logical,
        "new_canon_logical_sha256": new_logical,
        "source_refresh_id": (
            source_refresh_id
            or (latest_refresh or {}).get("refresh_id")),
        "documents_considered": len(doc_rows),
        "documents_new": sum(
            1 for p in promotions if p["from"] is None),
        "documents_changed": sum(
            1 for p in promotions if p["from"] is not None),
        "documents_unchanged": sum(
            1 for r in doc_rows
            if r.get("chosen_content_sha256")
            and r["chosen_content_sha256"]
            == r.get("latest_content_sha256")),
        "documents_failed": len(parse_failures),
        "parse_promotions": promotions,
        "parse_failures": parse_failures,
        "events_added": added,
        "events_changed": changed,
        "events_unchanged": unchanged,
        "refresh_status": status,
        "reasons": reasons,
        "canon_artifact_sha256": canon_ref["sha256"],
        "source_refresh_contract": CONTRACT_REFRESH,
    }
    refresh_ref = state.store_artifact(
        conn, doc, CONTRACT_CANON_REFRESH, "V1")
    set_state_meta(conn, _META_REFRESH_DOC, refresh_ref["sha256"])
    return doc
