"""Capa de source documents inmutables.

Un source document se identifica por (source_id, official_document_id),
nunca por su posicion de ingestión. Su contenido se fija con SHA-256.
El documento es evidencia; no decide nada por si mismo.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..canonical import sha256_bytes, strict_json_loads
from ..namespaces import source_document_id
from ..source_policy import SourcePolicy

MANIFEST_VERSION = "CA_ES_SOURCE_MANIFEST_V1"


@dataclass(frozen=True)
class SourceDocument:
    source_id: str
    official_document_id: str
    content_sha256: str
    retrieved_at: str
    publication_date: str | None = None
    media_type: str = "application/json"
    raw_relpath: str | None = None
    redistribution: str = "LOCAL_ONLY"
    retrieval_status: str = "OK"
    synthetic: bool = False
    notes: str | None = None
    acquisition: dict | None = None

    @property
    def document_id(self) -> str:
        return source_document_id(self.source_id, self.official_document_id)

    def to_canonical(self) -> dict:
        return {
            "document_id": self.document_id,
            "source_id": self.source_id,
            "official_document_id": self.official_document_id,
            "content_sha256": self.content_sha256,
            "retrieved_at": self.retrieved_at,
            "publication_date": self.publication_date,
            "media_type": self.media_type,
            "raw_relpath": self.raw_relpath,
            "redistribution": self.redistribution,
            "retrieval_status": self.retrieval_status,
            "synthetic": self.synthetic,
            "acquisition": self.acquisition,
        }


@dataclass(frozen=True)
class CorpusManifest:
    manifest_version: str
    corpus_id: str
    retrieved_at: str
    documents: tuple[SourceDocument, ...]

    def by_id(self) -> dict[str, SourceDocument]:
        return {doc.document_id: doc for doc in self.documents}


def _document_from_entry(entry: dict, policy: dict[str, SourcePolicy]) -> SourceDocument:
    source_id = entry["source_id"]
    source_policy = policy.get(source_id)
    if source_policy is None:
        raise KeyError(f"documento referencia fuente sin policy: {source_id}")
    return SourceDocument(
        source_id=source_id,
        official_document_id=entry["official_document_id"],
        content_sha256=entry["content_sha256"],
        retrieved_at=entry["retrieved_at"],
        publication_date=entry.get("publication_date"),
        media_type=entry.get("media_type", "application/json"),
        raw_relpath=entry.get("raw_relpath"),
        redistribution=source_policy.redistribution,
        retrieval_status=entry.get("retrieval_status", "OK"),
        synthetic=bool(entry.get("synthetic", False)),
        notes=entry.get("notes"),
        acquisition=entry.get("acquisition"),
    )


def load_corpus_manifest(
    manifest_path: Path, policy: dict[str, SourcePolicy]
) -> CorpusManifest:
    raw = strict_json_loads(manifest_path.read_text(encoding="utf-8"))
    if raw.get("manifest_version") != MANIFEST_VERSION:
        raise ValueError(
            f"manifest_version inesperada: {raw.get('manifest_version')!r}"
        )
    documents = tuple(_document_from_entry(entry, policy) for entry in raw["documents"])
    return CorpusManifest(
        manifest_version=raw["manifest_version"],
        corpus_id=raw["corpus_id"],
        retrieved_at=raw["retrieved_at"],
        documents=documents,
    )


def load_raw_bytes(corpus_root: Path, document: SourceDocument) -> bytes:
    if document.raw_relpath is None:
        raise FileNotFoundError(f"documento sin raw_relpath: {document.document_id}")
    return (corpus_root / document.raw_relpath).read_bytes()


def verify_document(corpus_root: Path, document: SourceDocument) -> dict:
    """Verifica que los bytes en disco coinciden con el SHA-256 fijado."""
    if document.raw_relpath is None or document.retrieval_status != "OK":
        return {
            "document_id": document.document_id,
            "status": document.retrieval_status,
            "sha256_match": False,
        }
    payload = load_raw_bytes(corpus_root, document)
    observed = sha256_bytes(payload)
    return {
        "document_id": document.document_id,
        "status": "OK",
        "sha256_match": observed == document.content_sha256,
        "expected_sha256": document.content_sha256,
        "observed_sha256": observed,
    }
