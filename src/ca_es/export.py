"""Vista operacional del canon: CA_ES_OPERATIONAL_CANON_V1 (G2).

Exporta una vista explicita y determinista del body canonico de
``run_pipeline``: no es el dump interno completo. El payload logico no
contiene metadata de runtime (run_id, executed_at, timestamps), de modo
que ``logical_sha256`` es byte-estable entre ejecuciones.

Orden total contractual (sin empates, sin orden incidental de Python):
  events           por canonical_event_id
  revisions        por (generation, revision_id)
  facts            por (field_path, revision_id, source_document_id,
                        assertion_id)
  conflicts        por (field_path, revision_id, asserted_as_of,
                        assertion_ids)
  source_documents por (source_id, official_document_id)

Contrato: docs/gates/g2-preregistered.json (tag g2-protocol).
"""
from __future__ import annotations

from .canonical import canonical_bytes, sha256_bytes

CANON_VERSION = "CA_ES_OPERATIONAL_CANON_V1"


def _fact_key(fact: dict) -> tuple:
    return (
        fact["field_path"],
        fact["revision_id"],
        fact["source_document_id"],
        fact["assertion_id"],
    )


def _conflict_key(conflict: dict) -> tuple:
    return (
        conflict["field_path"],
        conflict["revision_id"],
        conflict["asserted_as_of"] or "",
        tuple(conflict["assertion_ids"]),
    )


def _document_key(document: dict) -> tuple:
    return (document["source_id"], document["official_document_id"])


def _event_status(event: dict) -> str:
    return event["event_type_status"]


def operational_canon(body: dict, corpus_id: str) -> dict:
    """Construye el payload CA_ES_OPERATIONAL_CANON_V1 desde el body."""
    documents_by_id = {d["document_id"]: d for d in body["documents"]}
    resolutions_by_candidate = {
        r["candidate_id"]: r for r in body["identity"]["resolutions"]
    }
    facts_by_event: dict[str, list[dict]] = {}
    for fact in body["facts"]:
        facts_by_event.setdefault(fact["event_id"], []).append(fact)
    conflicts_by_event: dict[str, list[dict]] = {}
    for conflict in body["conflicts"]:
        conflicts_by_event.setdefault(conflict["event_id"], []).append(conflict)

    events = []
    for event in sorted(body["events"], key=lambda e: e["canonical_event_id"]):
        revisions = sorted(
            event["revisions"],
            key=lambda r: (r["generation"], r["revision_id"]),
        )
        document_ids = sorted(
            {doc_id for revision in revisions for doc_id in revision["document_ids"]}
        )
        source_documents = sorted(
            (documents_by_id[doc_id] for doc_id in document_ids),
            key=_document_key,
        )
        events.append(
            {
                "canonical_event_id": event["canonical_event_id"],
                "event_type": event["event_type"],
                "status": _event_status(event),
                "issuer": {
                    "issuer_name": event["issuer_name"],
                    "lei": event["lei"],
                },
                "affected_instrument": {
                    "isin": event["isin"],
                    "instrument_binding": event["instrument_binding"],
                },
                "revisions": revisions,
                "facts": sorted(
                    facts_by_event.get(event["canonical_event_id"], []),
                    key=_fact_key,
                ),
                "conflicts": sorted(
                    conflicts_by_event.get(event["canonical_event_id"], []),
                    key=_conflict_key,
                ),
                "temporal": event["temporal"],
                "provenance": {
                    "candidate_ids": event["candidate_ids"],
                    "event_type_evidence_locator": event[
                        "event_type_evidence_locator"
                    ],
                    "resolutions": [
                        resolutions_by_candidate[c]
                        for c in event["candidate_ids"]
                        if c in resolutions_by_candidate
                    ],
                },
                "source_documents": source_documents,
            }
        )

    return {
        "canon_version": CANON_VERSION,
        "corpus_id": corpus_id,
        "identity": {
            "relations": body["identity"]["ledger"]["relations"],
            "resolutions": body["identity"]["resolutions"],
        },
        "events": events,
    }


def canon_bytes(canon: dict) -> bytes:
    """Bytes canonicos del payload logico (byte-estables entre runs)."""
    return canonical_bytes(canon)


def logical_sha256(canon: dict) -> str:
    """sha256 del payload logico canonico."""
    return sha256_bytes(canonical_bytes(canon))
