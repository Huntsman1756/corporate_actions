"""Resolucion canonica de identidad de corporate action.

Reglas congeladas (G0-R):
  - `candidate_id`: determinista + inmutable.
  - `canonical_event_id`: determinista en la creacion + persistente. Una
    vez creado un componente, su canonical NO cambia por la llegada de un
    candidato con id menor.
  - `alias`: append-only; toda referencia historica resuelve.
  - Solo las relaciones SAME_CORPORATE_ACTION fusionan.
  - DISTINCT nunca fusiona.
  - Un candidato sin relaciones resuelve a si mismo (DEFAULT_SPLIT).
  - Ningun candidato se elimina jamas.

Estabilidad: se procesan las relaciones en orden de ledger (append-only)
y "gana el canonical ya establecido". Cuando ambos lados son nuevos, se
elige el menor id en ese momento; a partir de ahi queda fijado. Los
bindings persistidos (`pinned`) se aplican primero y son inmutables.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ..vocab import IdentityState, RelationType
from .ledger import IdentityLedger


@dataclass(frozen=True)
class CanonicalResolution:
    candidate_id: str
    canonical_event_id: str
    state: str
    linked: bool


def resolve_canonical(
    candidate_ids: list[str],
    ledger: IdentityLedger,
    pinned: dict[str, str] | None = None,
) -> list[CanonicalResolution]:
    members = list(dict.fromkeys(candidate_ids))
    parent: dict[str, str] = {candidate: candidate for candidate in members}
    canonical: dict[str, str] = {}
    seq: dict[str, int] = {}
    counter = [0]

    def find(item: str) -> str:
        parent.setdefault(item, item)
        root = item
        while parent[root] != root:
            root = parent[root]
        while parent[item] != root:
            parent[item], item = root, parent[item]
        return root

    def set_canonical(root: str, value: str) -> None:
        canonical[root] = value
        if value not in seq:
            seq[value] = counter[0]
            counter[0] += 1

    # 1) bindings persistidos: inmutables y previos a cualquier relacion.
    for candidate, value in sorted((pinned or {}).items()):
        parent.setdefault(candidate, candidate)
        parent.setdefault(value, value)
        rc, rv = find(candidate), find(value)
        if rc != rv:
            parent[rc] = rv
        set_canonical(find(value), value)

    # 2) relaciones en orden de ledger; "gana el canonical establecido".
    for a, b in ledger.same_pairs():
        parent.setdefault(a, a)
        parent.setdefault(b, b)
        ra, rb = find(a), find(b)
        if ra == rb:
            continue
        established_a, established_b = ra in canonical, rb in canonical
        ca = canonical.get(ra, ra)
        cb = canonical.get(rb, rb)
        if established_a and established_b:
            if seq[ca] <= seq[cb]:
                chosen, chosen_root = ca, ra
            else:
                chosen, chosen_root = cb, rb
        elif established_a:
            chosen, chosen_root = ca, ra
        elif established_b:
            chosen, chosen_root = cb, rb
        elif a <= b:
            chosen, chosen_root = a, ra
        else:
            chosen, chosen_root = b, rb
        other_root = rb if chosen_root == ra else ra
        parent[other_root] = chosen_root
        set_canonical(chosen_root, chosen)

    resolved = {
        candidate: canonical.get(find(candidate), find(candidate))
        for candidate in members
    }
    sizes = Counter(resolved.values())
    resolutions = [
        CanonicalResolution(
            candidate_id=candidate,
            canonical_event_id=value,
            state=(
                IdentityState.EXACT.value
                if sizes[value] > 1
                else IdentityState.UNRESOLVED.value
            ),
            linked=sizes[value] > 1,
        )
        for candidate, value in resolved.items()
    ]
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
