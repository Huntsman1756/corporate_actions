"""Revisions y supersession.

Regla: un documento nuevo NO crea una revision por si mismo. Solo una
relacion explicita de sustitucion/correccion (SUPERSEDES o
EXPLICIT_PREDECESSOR_REFERENCE) genera una nueva generacion.

La generacion se calcula como la longitud del camino mas largo desde una
raiz en el DAG de supersession, de modo que la identidad de revision es
independiente del orden de ingestion.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .namespaces import candidate_event_id, revision_id
from .sources.parsers.base import DocumentReference
from .vocab import DocumentRelation

SUPERSESSION_RELATIONS = frozenset(
    {
        DocumentRelation.SUPERSEDES.value,
        DocumentRelation.EXPLICIT_PREDECESSOR_REFERENCE.value,
    }
)


@dataclass(frozen=True)
class MemberDocument:
    candidate_id: str
    document_id: str
    source_id: str
    official_document_id: str


@dataclass(frozen=True)
class Revision:
    revision_id: str
    canonical_event_id: str
    generation: int
    document_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    supersedes_revision_id: str | None
    evidence: tuple[str, ...] = field(default_factory=tuple)

    def to_canonical(self) -> dict:
        return {
            "revision_id": self.revision_id,
            "canonical_event_id": self.canonical_event_id,
            "generation": self.generation,
            "document_ids": list(self.document_ids),
            "candidate_ids": list(self.candidate_ids),
            "supersedes_revision_id": self.supersedes_revision_id,
            "evidence": list(self.evidence),
        }


def _resolve_reference_target(
    reference: DocumentReference, documented_ids: dict[tuple[str, str], str]
) -> str | None:
    if not reference.target_official_document_id:
        return None
    target_source = reference.target_source_id
    if target_source is None:
        return None
    key = (target_source, reference.target_official_document_id)
    return documented_ids.get(key)


def build_revisions(
    canonical_event_id: str,
    members: list[MemberDocument],
    references_by_document: dict[str, list[DocumentReference]],
) -> list[Revision]:
    documented_ids = {
        (member.source_id, member.official_document_id): member.candidate_id
        for member in members
    }
    # predecessor[successor] = (predecessor, evidence_locator)
    predecessors: dict[str, tuple[str, str]] = {}
    for member in members:
        for reference in references_by_document.get(member.document_id, []):
            if reference.relation not in SUPERSESSION_RELATIONS:
                continue
            target = _resolve_reference_target(reference, documented_ids)
            if target is None or target == member.candidate_id:
                continue
            predecessors[member.candidate_id] = (target, reference.evidence_locator)

    # generacion = camino mas largo desde una raiz; deteccion de ciclos.
    generations: dict[str, int] = {}

    def generation_of(candidate: str, stack: frozenset[str]) -> int:
        if candidate in generations:
            return generations[candidate]
        if candidate in stack:
            raise ValueError("ciclo de supersession detectado")
        if candidate not in predecessors:
            generations[candidate] = 0
            return 0
        pred = predecessors[candidate][0]
        value = generation_of(pred, stack | {candidate}) + 1
        generations[candidate] = value
        return value

    for member in members:
        generation_of(member.candidate_id, frozenset())

    by_generation: dict[int, list[MemberDocument]] = {}
    for member in members:
        by_generation.setdefault(generations[member.candidate_id], []).append(member)

    revisions: list[Revision] = []
    for generation in sorted(by_generation):
        bucket = sorted(by_generation[generation], key=lambda m: m.candidate_id)
        evidence = tuple(
            predecessors[member.candidate_id][1]
            for member in bucket
            if member.candidate_id in predecessors
        )
        supersedes = (
            revision_id(canonical_event_id, generation - 1)
            if generation > 0
            else None
        )
        revisions.append(
            Revision(
                revision_id=revision_id(canonical_event_id, generation),
                canonical_event_id=canonical_event_id,
                generation=generation,
                document_ids=tuple(sorted(m.document_id for m in bucket)),
                candidate_ids=tuple(m.candidate_id for m in bucket),
                supersedes_revision_id=supersedes,
                evidence=evidence,
            )
        )
    return revisions
