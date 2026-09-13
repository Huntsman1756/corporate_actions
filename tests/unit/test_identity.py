from __future__ import annotations

from pathlib import Path

import pytest

from ca_es.errors import AdjudicationBoundaryError
from ca_es.identity import (
    IdentityLedger,
    IdentityRelation,
    aliases,
    load_adjudications,
    resolve_canonical,
)
from ca_es.namespaces import candidate_event_id
from ca_es.vocab import DecisionBasis, RelationType


def _same(a: str, b: str) -> IdentityRelation:
    return IdentityRelation(
        relation=RelationType.SAME_CORPORATE_ACTION.value,
        a=a,
        b=b,
        decision_basis=DecisionBasis.DETERMINISTIC.value,
        evidence=("test",),
    )


def test_same_input_same_candidate_uuid():
    a = candidate_event_id("CNMV", "X-1")
    b = candidate_event_id("CNMV", "X-1")
    assert a == b


def test_canonical_resolution_is_order_independent():
    c1, c2, c3 = candidate_event_id("CNMV", "1"), candidate_event_id("CNMV", "2"), candidate_event_id("CNMV", "3")
    forward = IdentityLedger().append(_same(c1, c2)).append(_same(c2, c3))
    backward = IdentityLedger().append(_same(c2, c3)).append(_same(c1, c2))
    r1 = {r.candidate_id: r.canonical_event_id for r in resolve_canonical([c1, c2, c3], forward)}
    r2 = {r.candidate_id: r.canonical_event_id for r in resolve_canonical([c1, c2, c3], backward)}
    assert r1 == r2
    assert len(set(r1.values())) == 1


def test_manual_merge_does_not_delete_candidates():
    c1, c2 = candidate_event_id("CNMV", "1"), candidate_event_id("CNMV", "2")
    manual = IdentityRelation(
        relation="SAME_CORPORATE_ACTION",
        a=c1,
        b=c2,
        decision_basis=DecisionBasis.MANUAL_ADJUDICATION.value,
        evidence=("manual",),
        reviewed_at="2026-09-13",
        reviewer="analyst",
    )
    ledger = IdentityLedger().append(manual)
    resolutions = resolve_canonical([c1, c2], ledger)
    assert {r.candidate_id for r in resolutions} == {c1, c2}


def test_old_alias_remains_resolvable():
    c1, c2, c3 = candidate_event_id("CNMV", "1"), candidate_event_id("CNMV", "2"), candidate_event_id("CNMV", "3")
    ledger = IdentityLedger().append(_same(c1, c2))
    first = aliases(resolve_canonical([c1, c2, c3], ledger))
    assert first[c1] == first[c2]  # c1 y c2 ya comparten canonical
    merged = ledger.append(_same(c2, c3))
    second = aliases(resolve_canonical([c1, c2, c3], merged))
    # Toda referencia antigua sigue resolviendo a UN canonical unico.
    assert second[c1] == second[c2] == second[c3]
    assert second[c1] in {c1, c2, c3}


def test_human_adjudication_cannot_write_financial_fact(tmp_path: Path):
    path = tmp_path / "adj.json"
    path.write_text(
        '{"adjudications":[{"relation":"SAME_CORPORATE_ACTION","a":"x","b":"y",'
        '"reviewed_at":"2026-09-13","reviewer":"r","gross_amount":"1.0"}]}',
        encoding="utf-8",
    )
    with pytest.raises(AdjudicationBoundaryError):
        load_adjudications(path)


def test_name_only_cannot_auto_link():
    # Sin evidencia de identificador no hay relacion; nunca se fusiona.
    c1, c2 = candidate_event_id("CNMV", "1"), candidate_event_id("CNMV", "2")
    resolutions = resolve_canonical([c1, c2], IdentityLedger())
    assert {r.canonical_event_id for r in resolutions} == {c1, c2}
    assert all(not r.linked for r in resolutions)
