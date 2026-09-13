"""Facts canonicos, provenance a nivel de campo y conflictos explicitos.

Solo tres procedencias producen facts:

  SOURCE_ASSERTION
  DETERMINISTIC_DERIVATION
  REFERENCE_ENRICHMENT

Ninguna fuente sobrescribe silenciosamente a otra: dos valores distintos
para el mismo campo producen CONFLICTING y se conservan ambos.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .assertions import Assertion, canonical_value
from .canonical import canonical_json
from .numeric import FinancialAmount, ensure_exact
from .vocab import EvidenceMode, FactOrigin


@dataclass(frozen=True)
class Fact:
    event_id: str
    revision_id: str
    assertion_id: str
    field_path: str
    value: object
    source_document_id: str
    source_id: str
    evidence_locator: str
    raw_pointer: str
    evidence_mode: str
    fact_origin: str
    asserted_as_of: str | None = None
    date_kind: str | None = None

    def to_canonical(self) -> dict:
        ensure_exact(self.value)
        return {
            "event_id": self.event_id,
            "revision_id": self.revision_id,
            "assertion_id": self.assertion_id,
            "field_path": self.field_path,
            "value": canonical_value(self.value),
            "source_document_id": self.source_document_id,
            "source_id": self.source_id,
            "evidence_locator": self.evidence_locator,
            "raw_pointer": self.raw_pointer,
            "evidence_mode": self.evidence_mode,
            "fact_origin": self.fact_origin,
            "asserted_as_of": self.asserted_as_of,
            "date_kind": self.date_kind,
        }

    def with_mode(self, mode: str) -> "Fact":
        return Fact(**{**self.__dict__, "evidence_mode": mode})


def fact_from_assertion(
    assertion: Assertion, event_id: str, revision_id: str
) -> Fact:
    return Fact(
        event_id=event_id,
        revision_id=revision_id,
        assertion_id=assertion.id,
        field_path=assertion.field_path,
        value=assertion.value,
        source_document_id=assertion.document_id,
        source_id=assertion.source_id,
        evidence_locator=assertion.evidence_locator,
        raw_pointer=assertion.raw_pointer,
        evidence_mode=assertion.evidence_mode,
        fact_origin=assertion.fact_origin,
        asserted_as_of=assertion.asserted_as_of,
        date_kind=assertion.date_kind,
    )


def build_facts(
    assertions: list[Assertion], event_id: str, revision_id: str
) -> list[Fact]:
    return [fact_from_assertion(a, event_id, revision_id) for a in assertions]


def derived_fact(
    *,
    event_id: str,
    revision_id: str,
    field_path: str,
    value: object,
    base_assertion: Assertion,
    rule_id: str,
) -> Fact:
    """Fact derivado por definicion demostrada (nunca presentado como explicito)."""
    return Fact(
        event_id=event_id,
        revision_id=revision_id,
        assertion_id=f"derived:{rule_id}:{base_assertion.id}",
        field_path=field_path,
        value=value,
        source_document_id=base_assertion.document_id,
        source_id=base_assertion.source_id,
        evidence_locator=f"DERIVED_BY_DEFINITION rule={rule_id} base={base_assertion.evidence_locator}",
        raw_pointer=base_assertion.raw_pointer,
        evidence_mode=EvidenceMode.DERIVED_BY_DEFINITION.value,
        fact_origin=FactOrigin.DETERMINISTIC_DERIVATION.value,
        asserted_as_of=base_assertion.asserted_as_of,
    )


@dataclass(frozen=True)
class Conflict:
    event_id: str
    revision_id: str
    field_path: str
    asserted_as_of: str | None
    values: tuple[str, ...]
    assertion_ids: tuple[str, ...]

    def to_canonical(self) -> dict:
        return {
            "event_id": self.event_id,
            "revision_id": self.revision_id,
            "field_path": self.field_path,
            "asserted_as_of": self.asserted_as_of,
            "values": list(self.values),
            "assertion_ids": list(self.assertion_ids),
        }


@dataclass(frozen=True)
class ConflictReport:
    facts: tuple[Fact, ...] = field(default_factory=tuple)
    conflicts: tuple[Conflict, ...] = field(default_factory=tuple)


def _group_key(fact: Fact) -> tuple:
    return (fact.event_id, fact.revision_id, fact.field_path, fact.asserted_as_of)


def _economic_fingerprint(value: object) -> str:
    """Huella para comparar disentimiento economico, no formato.

    Dos importes con mismo valor normalizado y divisa no discrepan
    aunque cambie el lexema (0,1250 vs 0.1250) o la escala.
    """
    if isinstance(value, FinancialAmount):
        return canonical_json(
            {"normalized": value.normalized_str(), "currency": value.currency}
        )
    if isinstance(value, dict) and value.get("__financial__"):
        return canonical_json(
            {"normalized": value["normalized"], "currency": value["currency"]}
        )
    return canonical_json(canonical_value(value))


def detect_conflicts(facts: list[Fact]) -> ConflictReport:
    """Marca conflictos explicitos entre assertions del mismo campo.

    Se agrupan SOURCE_ASSERTION y DETERMINISTIC_DERIVATION: un derivado
    de una fuente que discrepa de otra es un conflicto real.
    REFERENCE_ENRICHMENT queda fuera (su multiplicidad es esperada).
    """
    groups: dict[tuple, list[Fact]] = {}
    for fact in facts:
        if fact.fact_origin == FactOrigin.REFERENCE_ENRICHMENT.value:
            continue
        groups.setdefault(_group_key(fact), []).append(fact)

    conflicting: dict[str, str] = {}
    conflicts: list[Conflict] = []
    for key, group in groups.items():
        distinct: dict[str, list[Fact]] = {}
        for fact in group:
            fingerprint = _economic_fingerprint(fact.value)
            distinct.setdefault(fingerprint, []).append(fact)
        if len(distinct) <= 1:
            continue
        for members in distinct.values():
            for member in members:
                conflicting[member.assertion_id] = member.evidence_mode
        conflicts.append(
            Conflict(
                event_id=key[0],
                revision_id=key[1],
                field_path=key[2],
                asserted_as_of=key[3],
                values=tuple(sorted(distinct.keys())),
                assertion_ids=tuple(
                    sorted(fact.assertion_id for fact in group)
                ),
            )
        )
    marked = tuple(
        fact.with_mode(EvidenceMode.CONFLICTING.value)
        if fact.assertion_id in conflicting
        else fact
        for fact in facts
    )
    return ConflictReport(
        facts=marked,
        conflicts=tuple(sorted(conflicts, key=lambda c: (c.event_id, c.field_path))),
    )
