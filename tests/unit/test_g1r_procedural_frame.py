"""FALSE_POSITIVE_EVENT: marco juridico-procedural no es evento.

Un lexema de familia dentro de una construccion de dispensa/exencion/
obligacion legal o del nombre de un regimen legal no es evidencia de un
corporate action sobre el titulo: el documento trata de la norma.
"""
from __future__ import annotations

from ca_es.sources.documents import SourceDocument
from ca_es.sources.parsers import cnmv


def _doc() -> SourceDocument:
    return SourceDocument(
        source_id="CNMV_OIR",
        official_document_id="TEST-FPE",
        content_sha256="0" * 64,
        retrieved_at="2026-09-14",
        media_type="application/pdf",
        publication_date="2025-12-01",
    )


def test_dispensa_obligacion_opa_no_es_evento() -> None:
    text = (
        "ha presentado ante la CNMV solicitud de autorizacion de la "
        "dispensa de la obligacion de formular oferta publica de "
        "adquisicion por la totalidad de las acciones de la sociedad, al "
        "amparo de lo previsto en los articulos 111.2 de la Ley 6/2023 y "
        "4.2 del Real Decreto 1066/2007, sobre el regimen de las ofertas "
        "publicas de adquisicion de valores."
    )
    assert cnmv._parse_text(text, _doc()).event_type == "UNKNOWN"


def test_opa_real_fuera_de_marco_si_es_evento() -> None:
    text = (
        "la sociedad informa del resultado de la oferta publica de "
        "adquisicion formulada sobre la totalidad de las acciones."
    )
    assert cnmv._parse_text(text, _doc()).event_type == "TAKEOVER_BID"


def test_marco_procedural_no_anula_otras_anclas() -> None:
    # Una mencion procedural de OPA no suprime una evidencia real
    # posterior fuera del marco.
    text = (
        "se solicito dispensa de la obligacion de formular oferta "
        "publica de adquisicion en su dia. "
        "Separadamente, la entidad anuncia la oferta publica de "
        "adquisicion formulada el dia de hoy sobre el 100 por ciento "
        "del capital con un precio de 2,50 euros por accion en efectivo "
        "para los accionistas que acepten la oferta presentada."
    )
    assert cnmv._parse_text(text, _doc()).event_type == "TAKEOVER_BID"


def test_documento_procedural_sin_otra_familia_abstiene() -> None:
    text = (
        "se presenta solicitud de exencion de la obligacion de formular "
        "oferta publica de adquisicion conforme al regimen de las "
        "ofertas publicas de adquisicion de valores."
    )
    parsed = cnmv._parse_text(text, _doc())
    assert parsed.event_type == "UNKNOWN"
    fields = {c.field_path for c in parsed.claims}
    assert "date.ex_date" not in fields
    assert "date.record_date" not in fields
