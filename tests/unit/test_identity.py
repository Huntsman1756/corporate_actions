from __future__ import annotations

import json
from pathlib import Path

import pytest

from ca_es.errors import AdjudicationBoundaryError
from ca_es.identity import (
    IdentityLedger,
    IdentityRelation,
    aliases,
    group_by_canonical,
    load_adjudications,
    load_identity_ledger,
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


def test_component_membership_is_order_independent():
    # La PERTENENCIA al componente no depende del orden de las relaciones.
    c1, c2, c3 = candidate_event_id("CNMV", "1"), candidate_event_id("CNMV", "2"), candidate_event_id("CNMV", "3")
    forward = IdentityLedger().append(_same(c1, c2)).append(_same(c2, c3))
    backward = IdentityLedger().append(_same(c2, c3)).append(_same(c1, c2))
    p1 = sorted(tuple(sorted(v)) for v in group_by_canonical(resolve_canonical([c1, c2, c3], forward)).values())
    p2 = sorted(tuple(sorted(v)) for v in group_by_canonical(resolve_canonical([c1, c2, c3], backward)).values())
    assert p1 == p2


def test_canonical_resolution_deterministic_for_same_ledger():
    c1, c2, c3 = candidate_event_id("CNMV", "1"), candidate_event_id("CNMV", "2"), candidate_event_id("CNMV", "3")
    ledger = IdentityLedger().append(_same(c1, c2)).append(_same(c2, c3))
    r1 = aliases(resolve_canonical([c1, c2, c3], ledger))
    r2 = aliases(resolve_canonical([c1, c2, c3], ledger))
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


def _same_ids(a: str, b: str) -> IdentityRelation:
    return IdentityRelation(
        relation=RelationType.SAME_CORPORATE_ACTION.value,
        a=a,
        b=b,
        decision_basis=DecisionBasis.DETERMINISTIC.value,
        evidence=("test",),
    )


def test_canonical_stable_after_new_smaller_candidate():
    # Componente creado con canonical "A_name".
    ledger = IdentityLedger().append(_same_ids("A_name", "B_name"))
    first = aliases(resolve_canonical(["A_name", "B_name"], ledger))
    assert first["A_name"] == first["B_name"] == "A_name"
    # Llega despues un candidato lexicograficamente menor: NO cambia canonical.
    extended = ledger.append(_same_ids("0000", "A_name"))
    second = aliases(resolve_canonical(["A_name", "B_name", "0000"], extended))
    assert second["0000"] == second["A_name"] == second["B_name"] == "A_name"


def test_pinned_binding_is_immutable():
    ledger = IdentityLedger().append(_same_ids("0000", "zzz"))
    # Sin pinned, ambos nuevos: gana el menor ("0000").
    without = aliases(resolve_canonical(["0000", "zzz"], ledger))
    assert without["0000"] == "0000"
    # Con canonical persistido, se respeta el establecido.
    with_pinned = aliases(
        resolve_canonical(["0000", "zzz"], ledger, pinned={"zzz": "zzz"})
    )
    assert with_pinned["0000"] == with_pinned["zzz"] == "zzz"


def test_canonical_bindings_round_trip(tmp_path: Path):
    ledger = IdentityLedger().with_bindings({"c1": "c1", "c2": "c1"})
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(ledger.to_canonical()), encoding="utf-8")
    loaded, _ = load_identity_ledger(path)
    assert loaded.bindings() == {"c1": "c1", "c2": "c1"}
