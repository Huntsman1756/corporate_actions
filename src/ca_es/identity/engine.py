"""Resolucion canonica de identidad de corporate action.

Reglas congeladas:
  - El canonical de un componente es el menor candidate_event_id
    (orden lexicografico), funcion determinista del conjunto de inputs.
  - Solo las relaciones SAME_CORPORATE_ACTION fusionan.
  - DISTINCT nunca fusiona (prohibe fusiones futuras si se registran).
  - Un candidato sin relaciones resuelve a si mismo (DEFAULT_SPLIT).
  - Ningun candidato se elimina jamas.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..vocab import IdentityState, RelationType
from .ledger import IdentityLedger


@dataclass(frozen=True)
class CanonicalResolution:
    candidate_id: str
    canonical_event_id: str
    state: str
    linked: bool


class _UnionFind:
    def __init__(self, elements: list[str]) -> None:
        self.parent = {element: element for element in elements}

    def find(self, item: str) -> str:
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != root:
            self.parent[item], item = root, self.parent[item]
        return root

    def union(self, a: str, b: str) -> None:
        for element in (a, b):
            self.parent.setdefault(element, element)
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # El root es siempre el menor id: resolucion independiente
            # del orden de ingestion.
            low, high = sorted((ra, rb))
            self.parent[high] = low


def resolve_canonical(
    candidate_ids: list[str], ledger: IdentityLedger
) -> list[CanonicalResolution]:
    union = _UnionFind(list(candidate_ids))
    for a, b in ledger.same_pairs():
        union.union(a, b)
    linked_candidates = {
        candidate for pair in ledger.same_pairs() for candidate in pair
    }
    resolutions: list[CanonicalResolution] = []
    for candidate in candidate_ids:
        canonical = union.find(candidate)
        resolutions.append(
            CanonicalResolution(
                candidate_id=candidate,
                canonical_event_id=canonical,
                state=(
                    IdentityState.EXACT.value
                    if candidate in linked_candidates
                    else IdentityState.UNRESOLVED.value
                ),
                linked=candidate in linked_candidates,
            )
        )
    return sorted(resolutions, key=lambda item: item.candidate_id)


def group_by_canonical(
    resolutions: list[CanonicalResolution],
) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for resolution in resolutions:
        groups.setdefault(resolution.canonical_event_id, []).append(
            resolution.candidate_id
        )
    return {canonical: sorted(members) for canonical, members in sorted(groups.items())}


def aliases(resolutions: list[CanonicalResolution]) -> dict[str, str]:
    """Mapa candidate -> canonical; toda referencia historica resuelve."""
    return {r.candidate_id: r.canonical_event_id for r in resolutions}
