"""Alineamiento semantico con FIBO / Open Investment Model.

FIBO es referencia semantica, NO autoridad factual. Cada mapping se
declara y versiona. En G0 ningun mapping se marca PROVEN sin un extracto
de estandar verificado; por defecto, UNMAPPED. Esto es deliberado: es
preferible UNMAPPED con provenance perfecta que una equivalencia forzada.
"""
from __future__ import annotations

from dataclasses import dataclass

from .vocab import EventType, MappingStatus

FIBO_RELEASE_PIN = "FIBO-2024Q4"
FIBO_SOURCE = "https://spec.edmcouncil.org/fibo/"
SEMANTICS_VERSION = "CA_ES_SEMANTICS_V1"


@dataclass(frozen=True)
class SemanticRefs:
    fibo_release: str | None
    fibo_concept: str | None
    iso15022_caev: str | None
    mapping_status: str
    note: str


_MAPPINGS: dict[str, SemanticRefs] = {
    EventType.CASH_DIVIDEND.value: SemanticRefs(
        fibo_release=FIBO_RELEASE_PIN,
        fibo_concept=None,
        iso15022_caev=None,
        mapping_status=MappingStatus.UNMAPPED.value,
        note="G0 no certifica el concepto FIBO ni el CAEV sin extracto verificado.",
    ),
    EventType.SCRIP_DIVIDEND.value: SemanticRefs(
        fibo_release=FIBO_RELEASE_PIN,
        fibo_concept=None,
        iso15022_caev=None,
        mapping_status=MappingStatus.UNMAPPED.value,
        note="Scrip/rights: semantica operativa pendiente de corpus.",
    ),
    EventType.RIGHTS_ISSUE.value: SemanticRefs(
        fibo_release=FIBO_RELEASE_PIN,
        fibo_concept=None,
        iso15022_caev=None,
        mapping_status=MappingStatus.UNMAPPED.value,
        note="Rights issue: candidato RHTS, no certificado en G0.",
    ),
    EventType.CAPITAL_INCREASE.value: SemanticRefs(
        fibo_release=FIBO_RELEASE_PIN,
        fibo_concept=None,
        iso15022_caev=None,
        mapping_status=MappingStatus.UNMAPPED.value,
        note="No es un CAEV ISO 15022 directo.",
    ),
    EventType.CAPITAL_REDUCTION.value: SemanticRefs(
        fibo_release=FIBO_RELEASE_PIN,
        fibo_concept=None,
        iso15022_caev=None,
        mapping_status=MappingStatus.UNMAPPED.value,
        note="Reduccion de capital: mapping no certificado.",
    ),
    EventType.UNKNOWN.value: SemanticRefs(
        fibo_release=FIBO_RELEASE_PIN,
        fibo_concept=None,
        iso15022_caev=None,
        mapping_status=MappingStatus.UNMAPPED.value,
        note="Tipo desconocido; no se fuerza equivalencia.",
    ),
}


def semantics_for(event_type: str) -> SemanticRefs:
    return _MAPPINGS.get(event_type, _MAPPINGS[EventType.UNKNOWN.value])


def mapping_table() -> dict[str, dict]:
    return {
        event_type: {
            "fibo_release": refs.fibo_release,
            "fibo_concept": refs.fibo_concept,
            "iso15022_caev": refs.iso15022_caev,
            "mapping_status": refs.mapping_status,
            "note": refs.note,
        }
        for event_type, refs in sorted(_MAPPINGS.items())
    }
