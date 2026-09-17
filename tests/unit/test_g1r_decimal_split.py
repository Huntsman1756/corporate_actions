"""Tests de la regla generica G1-R DECIMAL_SPLIT_PDF.

La extraccion de texto PDF puede fracturar un decimal con whitespace
("0. 53", "0, 47"): la cola no es un entero promocionable. Regla:
span roto -> la ancla se conserva como evidencia pero el valor no
promueve; un canal intacto del mismo documento si puede emitir.
"""
from __future__ import annotations

from decimal import Decimal

from ca_es.sources.documents import SourceDocument
from ca_es.sources.parsers import cnmv
from ca_es.sources.parsers.span_integrity import interrupted_decimal


def _doc(media_type: str = "text/html") -> SourceDocument:
    return SourceDocument(
        source_id="CNMV",
        official_document_id="TEST-SPLIT",
        content_sha256="0" * 64,
        retrieved_at="2026-09-14",
        media_type=media_type,
    )


def _cnmv_html(text: str) -> bytes:
    return f"<html><body><p>{text}</p></body></html>".encode("utf-8")


def _claim(parsed, field_path):
    return [c for c in parsed.claims if c.field_path == field_path]


def test_interrupted_decimal_detecta_fractura():
    assert interrupted_decimal("importe fijo de 0. 53 euros", 19)
    assert interrupted_decimal("de 0, 47 euros", 6)
    assert not interrupted_decimal("de 0,53 euros", 3)
    assert not interrupted_decimal("accion. 53 euros", 8)


def test_decimal_roto_punto_abstiene():
    """'0. 53 euros brutos por accion' no emite 53 ni 0.53 sin
    evidencia intacta."""
    parsed = cnmv.parse(
        _cnmv_html(
            "La sociedad ha aprobado la distribucion de un dividendo "
            "a cuenta por un importe fijo de 0. 53 euros brutos por "
            "accion."
        ),
        _doc(),
        {},
    )
    assert parsed.event_type == "CASH_DIVIDEND"
    gross = _claim(parsed, "amount.gross_per_share")
    assert not gross or all(
        str(c.value.normalized) not in ("53", "0.53") for c in gross)


def test_decimal_roto_coma_con_canal_intacto():
    """'0, 47' roto no promueve, pero 'Importe bruto unitario: 0,4700
    Euros' intacto del mismo documento si emite 0.47."""
    parsed = cnmv.parse(
        _cnmv_html(
            "La Junta acordo un dividendo complementario de 0, 47 "
            "euros brutos por accion. Importe bruto unitario: "
            "0,4700 Euros. Retencion: 0,0893 Euros."
        ),
        _doc(),
        {},
    )
    gross = _claim(parsed, "amount.gross_per_share")
    assert len(gross) == 1
    assert gross[0].value.normalized == Decimal("0.47")


def test_decimal_roto_magnitud_abstiene():
    """'1. 088,2 millones' fracturado no emite '088,2' como total."""
    parsed = cnmv.parse(
        _cnmv_html(
            "La sociedad ha aprobado un dividendo complementario por "
            "un importe total de 1. 088,2 millones de euros."
        ),
        _doc(),
        {},
    )
    total = _claim(parsed, "amount.gross_total") + _claim(
        parsed, "amount.stated_amount") + _claim(parsed, "amount.issue_total")
    assert not total or all(
        c.value.normalized != 88.2 for c in total)


def test_unit_gross_exige_familia_dividendo():
    """El canal etiquetado no promueve bajo event_type UNKNOWN."""
    parsed = cnmv.parse(
        _cnmv_html(
            "Se comunica la siguiente informacion registrada. "
            "Importe bruto unitario: 0,5000 Euros."
        ),
        _doc(),
        {},
    )
    assert parsed.event_type == "UNKNOWN"
    assert not _claim(parsed, "amount.gross_per_share")


def test_gross_net_no_confunde_bruto_y_neto():
    """Deuda pre-iter-2: 'X brutos y Y netos' debe emitir gross=X y
    net=Y, no duplicar el bruto en el neto."""
    parsed = cnmv.parse(
        _cnmv_html(
            "La Junta acordo un dividendo complementario: 0,53 "
            "euros brutos y 0,43 euros netos por accion."
        ),
        _doc(),
        {},
    )
    gross = _claim(parsed, "amount.gross_per_share")
    net = _claim(parsed, "amount.net_per_share")
    assert gross and gross[0].value.normalized == Decimal("0.53")
    assert net and net[0].value.normalized == Decimal("0.43")


def test_decimal_intacto_sigue_emitiendo():
    """Regresion: un decimal intacto promueve con normalidad."""
    parsed = cnmv.parse(
        _cnmv_html(
            "La Junta General ha aprobado el pago de un dividendo "
            "complementario de 0,53 euros brutos por accion."
        ),
        _doc(),
        {},
    )
    gross = _claim(parsed, "amount.gross_per_share")
    assert gross and str(gross[0].value.normalized) == "0.53"
