"""Estructuras y parser comun de fixtures estructurados.

El formato raw de fixture es una transcripcion estructurada del
documento fuente. Cada claim declara:

  field_path        ruta semantica del campo (p.ej. ratio.rights_per_new_share)
  value             valor tal como lo publica la fuente
  evidence_locator  cita humana (documento + fragmento)
  raw_pointer       puntero JSON verificable dentro del fixture
  currency          divisa cuando aplica
  date_kind         semantica de fecha cuando aplica
  asserted_as_of    para facts temporales

El parser NO promociona valores: solo los transcribe a claims.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ...numeric import FinancialAmount
from ...source_policy import SourcePolicy
from ..documents import SourceDocument

PARSER_VERSION = "CA_ES_STRUCTURED_PARSER_V1"


@dataclass(frozen=True)
class Claim:
    field_path: str
    value: object
    evidence_locator: str
    raw_pointer: str
    currency: str | None = None
    date_kind: str | None = None
    asserted_as_of: str | None = None
    evidence_mode: str = "EXPLICIT"


@dataclass(frozen=True)
class DocumentReference:
    relation: str
    target_official_document_id: str | None
    target_source_id: str | None
    evidence_locator: str
    target_publication_date: str | None = None


@dataclass(frozen=True)
class InfrastructureClaim:
    role: str
    entity: str
    evidence_locator: str
    evidence_mode: str = "EXPLICIT"


@dataclass(frozen=True)
class EntitlementBasis:
    eligible_shares: int | None
    asserted_as_of: str
    status: str
    components: dict = field(default_factory=dict)
    adjustment_rule_present: bool = False
    evidence_locator: str = ""
    raw_pointer: str = ""


@dataclass(frozen=True)
class ParsedDocument:
    document: SourceDocument
    parser: str
    parser_version: str
    raw_record: dict
    event_type: str
    issuer_name: str | None
    isin: str | None
    lei: str | None
    claims: tuple[Claim, ...]
    references: tuple[DocumentReference, ...]
    infrastructure_roles: tuple[InfrastructureClaim, ...]
    entitlement_basis: EntitlementBasis | None
    event_type_evidence_locator: str | None = None


def _pointer(raw: dict, pointer: str) -> object:
    """Resuelve un JSON Pointer RFC 6901 restringido a objetos/arrays."""
    if pointer in ("", None):
        return raw
    if not pointer.startswith("/"):
        raise ValueError(f"pointer invalido: {pointer!r}")
    current: object = raw
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise KeyError(f"pointer fuera de rango: {pointer!r}")
    return current


def _value_from_entry(entry: dict) -> object:
    value = entry.get("value")
    currency = entry.get("currency")
    kind = entry.get("value_kind", "string")
    if kind == "financial" or currency is not None:
        return FinancialAmount.parse(str(value), currency=currency)
    if value is None:
        return None
    return value


def parse_structured(
    raw: dict,
    document: SourceDocument,
    policy: dict[str, SourcePolicy],
    parser_name: str,
) -> ParsedDocument:
    claims: list[Claim] = []
    for entry in raw.get("claims", []):
        claims.append(
            Claim(
                field_path=entry["field_path"],
                value=_value_from_entry(entry),
                evidence_locator=entry["evidence_locator"],
                raw_pointer=entry["raw_pointer"],
                currency=entry.get("currency"),
                date_kind=entry.get("date_kind"),
                asserted_as_of=entry.get("asserted_as_of"),
                evidence_mode=entry.get("evidence_mode", "EXPLICIT"),
            )
        )
    references = tuple(
        DocumentReference(
            relation=ref["relation"],
            target_official_document_id=ref.get("target_official_document_id"),
            target_source_id=ref.get("target_source_id"),
            evidence_locator=ref["evidence_locator"],
            target_publication_date=ref.get("target_publication_date"),
        )
        for ref in raw.get("references", [])
    )
    roles = tuple(
        InfrastructureClaim(
            role=role["role"],
            entity=role["entity"],
            evidence_locator=role["evidence_locator"],
            evidence_mode=role.get("evidence_mode", "EXPLICIT"),
        )
        for role in raw.get("infrastructure_roles", [])
    )
    entitlement = None
    if "entitlement_basis" in raw:
        eb = raw["entitlement_basis"]
        entitlement = EntitlementBasis(
            eligible_shares=eb.get("eligible_shares"),
            asserted_as_of=eb["asserted_as_of"],
            status=eb.get("status", "UNKNOWN"),
            components=eb.get("components", {}),
            adjustment_rule_present=bool(eb.get("adjustment_rule_present", False)),
            evidence_locator=eb.get("evidence_locator", ""),
            raw_pointer=eb.get("raw_pointer", "/entitlement_basis"),
        )
    instrument = raw.get("instrument", {})
    return ParsedDocument(
        document=document,
        parser=parser_name,
        parser_version=PARSER_VERSION,
        raw_record=raw,
        event_type=raw.get("event_type", "UNKNOWN"),
        issuer_name=instrument.get("issuer_name"),
        isin=instrument.get("isin"),
        lei=instrument.get("lei"),
        claims=tuple(claims),
        references=references,
        infrastructure_roles=roles,
        entitlement_basis=entitlement,
        event_type_evidence_locator=raw.get("event_type_evidence_locator"),
    )
