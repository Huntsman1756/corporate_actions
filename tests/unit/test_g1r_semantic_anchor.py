"""Tests de la regla generica G1-R FALSE_FINANCIAL_SEMANTIC_ANCHOR.

El importe solo puede promoverse si su ancla lexica es compatible con
la familia del evento y su contexto no es rol-incompatible. Los casos
sinteticos reproducen el fenomeno documental (no un seed concreto).
"""
from __future__ import annotations

from ca_es.sources.documents import SourceDocument
from ca_es.sources.parsers import cnmv


def _doc(media_type: str = "text/html") -> SourceDocument:
    return SourceDocument(
        source_id="CNMV",
        official_document_id="TEST-ANCHOR",
        content_sha256="0" * 64,
        retrieved_at="2026-09-14",
        media_type=media_type,
    )


def _cnmv_html(text: str) -> bytes:
    return f"<html><body><p>{text}</p></body></html>".encode("utf-8")


def _claim(parsed, field_path):
    return [c for c in parsed.claims if c.field_path == field_path]


def test_opa_precio_oferta_no_precio_contexto():
    """En una OPA, "X euros por accion" sin ancla de oferta no es el
    importe del evento; el precio anclado a 'precio de la OPA' si."""
    parsed = cnmv.parse(
        _cnmv_html(
            "Neinor comunica una oferta publica voluntaria de adquisicion "
            "sobre la totalidad de las acciones. El acuerdo previo fue de "
            "27,15 euros por accion. El Oferente ha decidido mantener el "
            "precio de la OPA de 21,335 euros."
        ),
        _doc(),
        {},
    )
    assert parsed.event_type == "TAKEOVER_BID"
    gross = _claim(parsed, "amount.gross_per_share")
    assert len(gross) == 1
    assert str(gross[0].value.normalized) == "21.335"


def test_opa_sin_ancla_de_precio_abstiene():
    """OPA sin ancla "precio de la OPA/oferta": abstencion, no promover
    un "euros por accion" cualquiera."""
    parsed = cnmv.parse(
        _cnmv_html(
            "Se ha presentado una oferta publica de adquisicion de "
            "acciones. La referencia de cotizacion fue de 27,15 euros "
            "por accion."
        ),
        _doc(),
        {},
    )
    assert parsed.event_type == "TAKEOVER_BID"
    assert not _claim(parsed, "amount.gross_per_share")


def test_valor_nominal_no_es_importe_evento():
    """"acciones de X euros de valor nominal" no es gross_per_share
    aunque el documento mencione un dividendo."""
    parsed = cnmv.parse(
        _cnmv_html(
            "La sociedad comunica el reparto de un dividendo flexible. "
            "Las acciones nuevas tendran 0,01 euros de valor nominal."
        ),
        _doc(),
        {},
    )
    gross = _claim(parsed, "amount.gross_per_share")
    assert not gross or all(str(c.value.normalized) != "0.01" for c in gross)


def test_recompra_no_es_importe_evento():
    """Una magnitud bajo contexto de recompra no se promueve como
    importe del evento."""
    parsed = cnmv.parse(
        _cnmv_html(
            "La entidad comunica un programa de recompra de acciones "
            "propias por un importe maximo de 755 millones de euros."
        ),
        _doc(),
        {},
    )
    assert not _claim(parsed, "amount.max_total")
    assert not _claim(parsed, "amount.stated_amount")


def test_precio_emision_con_nominal_descompuesto():
    """"X euros por accion" en un aumento de capital es el precio de
    emision aunque la misma frase descomponga nominal/prima: el
    marcador de rol se liga al importe mas cercano."""
    parsed = cnmv.parse(
        _cnmv_html(
            "La sociedad acuerda un aumento de capital con exclusion "
            "del derecho de suscripcion preferente. Precio de emision: "
            "0,37 euros por accion, de los que 0,10 euros corresponden "
            "a valor nominal y 0,27 euros a prima de emision."
        ),
        _doc(),
        {},
    )
    assert parsed.event_type == "CAPITAL_INCREASE"
    gross = _claim(parsed, "amount.gross_per_share")
    assert gross and str(gross[0].value.normalized) == "0.37"


def test_nominal_ligado_al_ancla_bloquea():
    """El marcador se liga al importe mas cercano: 'valor nominal de
    dichas acciones (que asciende a 0,01 euros por accion)' bloquea el
    0,01 aunque el documento hable de dividendos."""
    parsed = cnmv.parse(
        _cnmv_html(
            "La sociedad comunica el reparto de un dividendo. "
            "Solo respecto del valor nominal de dichas acciones "
            "(que asciende a 0,01 euros por accion)."
        ),
        _doc(),
        {},
    )
    gross = _claim(parsed, "amount.gross_per_share")
    assert not gross or all(str(c.value.normalized) != "0.01" for c in gross)


def test_dividendo_real_sigue_emitiendo():
    """Regresion: un dividendo con ancla propia sigue emitiendo."""
    parsed = cnmv.parse(
        _cnmv_html(
            "La Junta General ha aprobado el pago de un dividendo "
            "complementario de 0,025 euros brutos por accion."
        ),
        _doc(),
        {},
    )
    assert parsed.event_type == "CASH_DIVIDEND"
    gross = _claim(parsed, "amount.gross_per_share")
    assert gross and gross[0].value.raw_lexeme == "0,025"


def test_magnitude_sin_bloqueo_sigue_emitiendo():
    """Regresion: magnitud con ancla de importe y sin contexto
    incompatible sigue promoviendose."""
    parsed = cnmv.parse(
        _cnmv_html(
            "La sociedad ha acordado un aumento de capital con exclusion "
            "del derecho de suscripcion preferente por un importe de "
            "255 millones de euros."
        ),
        _doc(),
        {},
    )
    assert parsed.event_type == "CAPITAL_INCREASE"
    total = _claim(parsed, "amount.stated_amount") + _claim(
        parsed, "amount.issue_total")
    assert total and total[0].value.normalized == 255_000_000
