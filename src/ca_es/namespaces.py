"""Namespaces UUIDv5 estables e inmutables de ca-es.

Cambiar estos valores cambiaria todas las identidades historicas; por
eso son constantes derivadas de una raiz fija.
"""
from __future__ import annotations

import uuid

_ROOT = uuid.uuid5(uuid.NAMESPACE_DNS, "ca-es.opensource")

SOURCE_DOCUMENT_NAMESPACE = uuid.uuid5(_ROOT, "source-document")
CANDIDATE_NAMESPACE = uuid.uuid5(_ROOT, "candidate-event")
ASSERTION_NAMESPACE = uuid.uuid5(_ROOT, "assertion")
REVISION_NAMESPACE = uuid.uuid5(_ROOT, "event-revision")


def assertion_id(document_id: str, field_path: str, raw_pointer: str) -> str:
    return str(uuid.uuid5(ASSERTION_NAMESPACE, f"{document_id}:{field_path}:{raw_pointer}"))


def revision_id(canonical_event_id: str, generation: int) -> str:
    return str(uuid.uuid5(REVISION_NAMESPACE, f"{canonical_event_id}:gen:{generation}"))


def source_document_id(source_id: str, official_document_id: str) -> str:
    """Identidad estable del documento: solo source + id oficial."""
    return str(uuid.uuid5(SOURCE_DOCUMENT_NAMESPACE, f"{source_id}:{official_document_id}"))


def candidate_event_id(source_id: str, official_document_id: str) -> str:
    """Identidad inmutable de candidato, independiente del orden de ingestion.

    Nunca se deriva de fecha, importe, ratio, ticker ni nombre: esos
    atributos pueden rectificarse.
    """
    return str(uuid.uuid5(CANDIDATE_NAMESPACE, f"{source_id}:{official_document_id}"))
