"""Phase C — Assertions: documento -> hechos observados, sin verdad global.

Una assertion es un hecho atomico que una fuente afirma en un fragmento
concreto. Todavia no es un fact canonico: no se ha reconciliado con
otras fuentes ni se le ha asignado revision.
"""
from __future__ import annotations

from dataclasses import dataclass

from .namespaces import assertion_id
from .numeric import FinancialAmount, ensure_exact
from .sources.parsers.base import ParsedDocument, _pointer
from .vocab import EvidenceMode, FactOrigin


def canonical_value(value: object) -> object:
    """Forma serializable determinista de un valor de fact."""
    if isinstance(value, FinancialAmount):
        return {"__financial__": True, **value.to_canonical()}
    if isinstance(value, dict):
        return {str(k): canonical_value(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [canonical_value(item) for item in value]
    ensure_exact(value)
    return value


@dataclass(frozen=True)
class Assertion:
    document_id: str
    source_id: str
    field_path: str
    value: object
    raw_value: object
    evidence_locator: str
    raw_pointer: str
    evidence_mode: str = EvidenceMode.EXPLICIT.value
    asserted_as_of: str | None = None
    date_kind: str | None = None
    fact_origin: str = FactOrigin.SOURCE_ASSERTION.value

    @property
    def id(self) -> str:
        return assertion_id(self.document_id, self.field_path, self.raw_pointer)

    def to_canonical(self) -> dict:
        ensure_exact(self.value)
        return {
            "assertion_id": self.id,
            "document_id": self.document_id,
            "source_id": self.source_id,
            "field_path": self.field_path,
            "value": canonical_value(self.value),
            "raw_value": canonical_value(self.raw_value),
            "evidence_locator": self.evidence_locator,
            "raw_pointer": self.raw_pointer,
            "evidence_mode": self.evidence_mode,
            "asserted_as_of": self.asserted_as_of,
            "date_kind": self.date_kind,
            "fact_origin": self.fact_origin,
        }


def build_assertions(parsed: ParsedDocument) -> list[Assertion]:
    """Documento parseado -> assertions (una por hecho observado)."""
    document_id = parsed.document.document_id
    assertions: list[Assertion] = []
    for claim in parsed.claims:
        assertions.append(
            Assertion(
                document_id=document_id,
                source_id=parsed.document.source_id,
                field_path=claim.field_path,
                value=claim.value,
                raw_value=_pointer(parsed.raw_record, claim.raw_pointer),
                evidence_locator=claim.evidence_locator,
                raw_pointer=claim.raw_pointer,
                evidence_mode=claim.evidence_mode,
                asserted_as_of=claim.asserted_as_of,
                date_kind=claim.date_kind,
            )
        )

    # El event_type es una assertion mas, con su propia provenance. Si la
    # fuente no lo declara, se preserva UNKNOWN (nunca se infiere).
    event_type_mode = (
        EvidenceMode.EXPLICIT.value
        if parsed.event_type != "UNKNOWN" and parsed.event_type_evidence_locator
        else EvidenceMode.UNKNOWN.value
    )
    assertions.append(
        Assertion(
            document_id=document_id,
            source_id=parsed.document.source_id,
            field_path="event_type",
            value=parsed.event_type,
            raw_value=parsed.event_type,
            evidence_locator=parsed.event_type_evidence_locator or "UNKNOWN",
            raw_pointer="/event_type",
            evidence_mode=event_type_mode,
        )
    )

    # Roles de infraestructura: cada rol conserva exactamente lo que la
    # fuente dijo. Nunca se eleva un canal a CSD.
    for index, role in enumerate(parsed.infrastructure_roles):
        assertions.append(
            Assertion(
                document_id=document_id,
                source_id=parsed.document.source_id,
                field_path=f"infrastructure_role.{role.role}",
                value=role.entity,
                raw_value=role.entity,
                evidence_locator=role.evidence_locator,
                raw_pointer=f"/infrastructure_roles/{index}",
                evidence_mode=role.evidence_mode,
            )
        )

    # Entitlement basis: assertion temporal con asserted_as_of obligatorio.
    if parsed.entitlement_basis is not None:
        eb = parsed.entitlement_basis
        assertions.append(
            Assertion(
                document_id=document_id,
                source_id=parsed.document.source_id,
                field_path="entitlement_basis",
                value={
                    "eligible_shares": eb.eligible_shares,
                    "components": eb.components,
                    "status": eb.status,
                    "adjustment_rule_present": eb.adjustment_rule_present,
                },
                raw_value=eb.eligible_shares,
                evidence_locator=eb.evidence_locator,
                raw_pointer=eb.raw_pointer,
                asserted_as_of=eb.asserted_as_of,
            )
        )
    return assertions
