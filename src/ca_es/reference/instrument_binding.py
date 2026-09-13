"""Binding instrumento<->evento (ADR-013).

Precedencia explicita. El nombre NUNCA enlaza de forma canonica; solo
genera candidatos.

  1. ISIN explicito en el documento del evento          -> EXPLICIT
  2. Relacion estructurada documento->instrumento de la
     misma fuente oficial (p.ej. Portfolio product page) -> SOURCE_CARRIED_INSTRUMENT_BINDING
  3. Referencia oficial cruzada entre fuentes            -> CROSS_SOURCE_BINDING
  4. Adjudicacion humana                                 -> relacion registrada
  5. Nombre                                              -> candidatos, nunca canonico
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..canonical import strict_json_loads

INSTRUMENTS_VERSION = "PORTFOLIO_INSTRUMENTS_V1"


@dataclass(frozen=True)
class InstrumentReference:
    isin: str
    ticker: str | None = None
    nif: str | None = None
    lei: str | None = None
    product_id: str | None = None
    canonical_url: str | None = None
    document_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class InstrumentBindingIndex:
    instrument_by_isin: dict[str, InstrumentReference] = field(default_factory=dict)
    document_bindings: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class InstrumentResolution:
    isin: str | None
    evidence_mode: str | None
    evidence_locator: str | None
    source_document_id: str | None = None


def load_instrument_bindings(path: Path) -> InstrumentBindingIndex:
    raw = strict_json_loads(path.read_text(encoding="utf-8"))
    if raw.get("artifact_version") != INSTRUMENTS_VERSION:
        raise ValueError(
            f"artifact_version inesperada: {raw.get('artifact_version')!r}"
        )
    by_isin: dict[str, InstrumentReference] = {}
    for entry in raw["instruments"]:
        by_isin[entry["isin"]] = InstrumentReference(
            isin=entry["isin"],
            ticker=entry.get("ticker"),
            nif=entry.get("nif"),
            lei=entry.get("lei"),
            product_id=entry.get("product_id"),
            canonical_url=entry.get("canonical_url"),
            document_ids=tuple(entry.get("document_ids", [])),
        )
    return InstrumentBindingIndex(
        instrument_by_isin=by_isin,
        document_bindings=dict(raw.get("document_bindings", {})),
    )


def resolve_event_instrument(
    documents: list, index: InstrumentBindingIndex | None
) -> InstrumentResolution:
    """Resuelve el ISIN del evento por precedencia; nunca por nombre."""
    # 1) ISIN explicito en el documento del evento.
    explicit = sorted({doc.isin for doc in documents if getattr(doc, "isin", None)})
    if len(explicit) == 1:
        return InstrumentResolution(
            isin=explicit[0],
            evidence_mode="EXPLICIT",
            evidence_locator="ISIN explicito en el documento del evento",
        )
    if index is None:
        return InstrumentResolution(None, None, None)

    # 2) Relacion estructurada documento->instrumento de la misma fuente.
    for document in documents:
        official_id = document.document.official_document_id
        isin = index.document_bindings.get(official_id)
        if isin:
            reference = index.instrument_by_isin.get(isin)
            evidence = (
                f"{reference.canonical_url} (product_id={reference.product_id})"
                if reference
                else "instrument binding"
            )
            return InstrumentResolution(
                isin=isin,
                evidence_mode="SOURCE_CARRIED_INSTRUMENT_BINDING",
                evidence_locator=evidence,
                source_document_id=f"PORTFOLIO-PRODUCT-{reference.product_id}"
                if reference
                else None,
            )
    return InstrumentResolution(None, None, None)
