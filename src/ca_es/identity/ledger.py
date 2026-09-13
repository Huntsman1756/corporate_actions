"""Identity ledger append-only y adjudicacion de relaciones.

El ledger es un input autoritativo: con los mismos raw inputs, config,
identity ledger y adjudication ledger la resolucion canonica es la
misma. Los merges nunca destruyen candidatos: solo anaden relaciones.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..canonical import strict_json_loads
from ..errors import AdjudicationBoundaryError
from ..vocab import ADJUDICABLE_RELATIONS, DecisionBasis, RelationType

LEDGER_VERSION = "CA_ES_IDENTITY_LEDGER_V1"

# Campos financieros prohibidos en cualquier registro de adjudicacion
# humana. Un humano solo puede escribir relaciones de identidad.
_PROHIBITED_FINANCIAL_KEYS = frozenset(
    {
        "gross_amount",
        "net_amount",
        "payment_date",
        "record_date",
        "ex_date",
        "ratio",
        "rights_required",
        "currency",
        "isin",
        "shares",
        "price",
        "eligible_shares",
        "raw_lexeme",
        "normalized",
        "scale",
        "value",
    }
)


@dataclass(frozen=True)
class IdentityRelation:
    relation: str
    a: str
    b: str
    decision_basis: str
    evidence: tuple[str, ...] = field(default_factory=tuple)
    reviewed_at: str | None = None
    reviewer: str | None = None

    def to_canonical(self) -> dict:
        return {
            "relation": self.relation,
            "a": self.a,
            "b": self.b,
            "decision_basis": self.decision_basis,
            "evidence": list(self.evidence),
            "reviewed_at": self.reviewed_at,
            "reviewer": self.reviewer,
        }


def _validate_relation(relation: IdentityRelation) -> None:
    if relation.relation not in {r.value for r in RelationType}:
        raise ValueError(f"relation desconocida: {relation.relation!r}")
    if relation.a == relation.b:
        raise ValueError("una relacion consigo mismo no aporta identidad")
    if relation.decision_basis not in {
        DecisionBasis.DETERMINISTIC.value,
        DecisionBasis.MANUAL_ADJUDICATION.value,
    }:
        raise ValueError(f"decision_basis invalido: {relation.decision_basis!r}")
    if relation.decision_basis == DecisionBasis.MANUAL_ADJUDICATION.value:
        if relation.relation not in ADJUDICABLE_RELATIONS:
            raise AdjudicationBoundaryError(
                f"la adjudicacion humana no puede emitir {relation.relation!r}"
            )
        if not relation.reviewer or not relation.reviewed_at:
            raise AdjudicationBoundaryError(
                "toda adjudicacion humana requiere reviewer y reviewed_at"
            )


@dataclass(frozen=True)
class IdentityLedger:
    relations: tuple[IdentityRelation, ...] = field(default_factory=tuple)
    # canonical persistido (candidate_id -> canonical_event_id). Una vez
    # asignado, es inmutable: la llegada de un candidato menor no lo cambia.
    canonical_bindings: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def append(self, relation: IdentityRelation) -> "IdentityLedger":
        """Append-only: nunca elimina ni reescribe relaciones previas."""
        _validate_relation(relation)
        # Idempotente: una relacion identica no se duplica, pero tampoco
        # se colapsan relaciones distintas.
        payload = relation.to_canonical()
        if any(existing.to_canonical() == payload for existing in self.relations):
            return self
        return IdentityLedger(
            self.relations + (relation,), self.canonical_bindings
        )

    def extend(self, relations: list[IdentityRelation]) -> "IdentityLedger":
        ledger = self
        for relation in relations:
            ledger = ledger.append(relation)
        return ledger

    def with_bindings(self, bindings: dict[str, str]) -> "IdentityLedger":
        """Fija/persiste el canonical. Nunca borra bindings previos."""
        merged = dict(self.canonical_bindings)
        for candidate, value in bindings.items():
            merged.setdefault(candidate, value)
        return IdentityLedger(
            self.relations, tuple(sorted(merged.items()))
        )

    def bindings(self) -> dict[str, str]:
        return dict(self.canonical_bindings)

    def same_pairs(self) -> list[tuple[str, str]]:
        return [
            (r.a, r.b)
            for r in self.relations
            if r.relation == RelationType.SAME_CORPORATE_ACTION.value
        ]

    def to_canonical(self) -> dict:
        return {
            "ledger_version": LEDGER_VERSION,
            "relations": [r.to_canonical() for r in self.relations],
            "canonical_bindings": dict(self.canonical_bindings),
        }


def load_identity_ledger(path) -> tuple[IdentityLedger, list[dict]]:
    """Carga un ledger. Devuelve (ledger, adjudicaciones)."""
    raw = strict_json_loads(path.read_text(encoding="utf-8"))
    if raw.get("ledger_version") != LEDGER_VERSION:
        raise ValueError(f"ledger_version inesperada: {raw.get('ledger_version')!r}")
    ledger = IdentityLedger()
    for entry in raw.get("relations", []):
        relation = IdentityRelation(
            relation=entry["relation"],
            a=entry["a"],
            b=entry["b"],
            decision_basis=entry["decision_basis"],
            evidence=tuple(entry.get("evidence", [])),
            reviewed_at=entry.get("reviewed_at"),
            reviewer=entry.get("reviewer"),
        )
        ledger = ledger.append(relation)
    bindings = raw.get("canonical_bindings", {})
    if bindings:
        ledger = ledger.with_bindings(bindings)
    return ledger, list(raw.get("adjudications", []))


def load_adjudications(path) -> list[IdentityRelation]:
    """Carga adjudicaciones humanas y rechaza cualquier fact financiero."""
    raw = strict_json_loads(path.read_text(encoding="utf-8"))
    relations: list[IdentityRelation] = []
    for entry in raw.get("adjudications", []):
        _reject_financial_keys(entry)
        relations.append(
            IdentityRelation(
                relation=entry["relation"],
                a=entry["a"],
                b=entry["b"],
                decision_basis=DecisionBasis.MANUAL_ADJUDICATION.value,
                evidence=tuple(entry.get("evidence", [])),
                reviewed_at=entry["reviewed_at"],
                reviewer=entry["reviewer"],
            )
        )
    return relations


def _reject_financial_keys(entry: dict) -> None:
    for key in entry:
        if key.lower() in _PROHIBITED_FINANCIAL_KEYS:
            raise AdjudicationBoundaryError(
                f"la adjudicacion humana no puede escribir el campo {key!r}"
            )
