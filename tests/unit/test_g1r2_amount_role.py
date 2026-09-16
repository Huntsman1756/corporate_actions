"""Tests de la cuarentena G1-R2 sobre issue_price_per_share (Portfolio).

Veredicto humano del holdout G1-R2 (FAIL, g1r2/results/holdout-verdict.json):
la semantica del precio de emision de Portfolio no generaliza con
seguridad (ISSUE_PRICE_COMPONENT_CONFUSION + ISSUE_PRICE_LEXEME_VARIANT).
Cuarentena fail-closed: el parser no emite amount.issue_price_per_share
en la familia CAPITAL_INCREASE/RIGHTS_ISSUE ni por el lexema
"por accion nueva"; la deteccion del evento y el routing de dividendos
no cambian. Casos sinteticos que reproducen el fenomeno documental,
no un seed concreto.
"""
from __future__ import annotations

from ca_es.sources.documents import SourceDocument
from ca_es.sources.parsers import portfolio


def _doc() -> SourceDocument:
    return SourceDocument(
        source_id="PORTFOLIO_STOCK_EXCHANGE",
        official_document_id="TEST-AMR",
        content_sha256="0" * 64,
        retrieved_at="2026-09-15",
        media_type="application/pdf",
    )


def _claim(parsed, field_path):
    return [c for c in parsed.claims if c.field_path == field_path]


def test_cuarentena_ancla_explicita_abstiene():
    """"Precio de suscripcion por accion nueva (nominal + prima) 4 EUR":
    bajo cuarentena no se emite issue_price_per_share aunque el ancla
    sea explicita; evento e issuer siguen detectandose."""
    parsed = portfolio._parse_text(
        "AMPLIACION DE CAPITAL CON DERECHOS DE SUSCRIPCIÓN PREFERENTE\n"
        "Emisor TESTCO, S.A.\n"
        "Ratio (derechos → acciones nuevas) 2 DERECHOS → 1 ACCIÓN NUEVA\n"
        "Precio de suscripción por acción nueva (nominal + prima) "
        "4€ POR ACCIÓN NUEVA\n"
        "(1€ DE VALOR NOMINAL + 3€ DE PRIMA DE EMISIÓN)\n",
        _doc(),
    )
    assert parsed.event_type == "CAPITAL_INCREASE"
    assert not _claim(parsed, "amount.issue_price_per_share")
    assert not _claim(parsed, "amount.gross_per_share")
    assert parsed.issuer_name == "TESTCO"


def test_cuarentena_precio_suscripcion_simple_abstiene():
    """"Precio de suscripción: 2,50€ por acción": la cuarentena no
    exige ancla inequivoca demostrada — abstencion."""
    parsed = portfolio._parse_text(
        "Aumento de capital de la sociedad.\n"
        "Precio de suscripción: 2,50€ por acción.\n",
        _doc(),
    )
    assert parsed.event_type == "CAPITAL_INCREASE"
    assert not _claim(parsed, "amount.issue_price_per_share")
    assert not _claim(parsed, "amount.gross_per_share")


def test_cuarentena_prima_no_es_issue_price():
    """El caso POEX-DOC-3507: prima de emision por accion nunca puede
    poblar issue_price_per_share; el documento se abstiene."""
    parsed = portfolio._parse_text(
        "Ampliación de capital social.\n"
        "Las acciones se emiten con una prima de emisión de 0,58€ "
        "por acción. El tipo de emisión es de 1,58€ por acción.\n",
        _doc(),
    )
    assert not _claim(parsed, "amount.issue_price_per_share")
    assert not _claim(parsed, "amount.gross_per_share")


def test_precio_descompuesto_sin_total_abstiene():
    """Si solo se publica la descomposicion nominal + prima sin total
    por accion, no hay precio unitario publicado: abstencion."""
    parsed = portfolio._parse_text(
        "Ampliación de capital social.\n"
        "Precio de suscripción: 1€ de valor nominal + 3€ de prima "
        "de emisión.\n",
        _doc(),
    )
    assert not _claim(parsed, "amount.issue_price_per_share")
    assert not _claim(parsed, "amount.gross_per_share")


def test_cuarentena_por_accion_nueva_abstiene():
    """"X euros por accion nueva" es lexema de emision: bajo cuarentena
    se abstiene aunque no exista la etiqueta 'precio de suscripcion'
    ni la familia este clara."""
    parsed = portfolio._parse_text(
        "Instrucción operativa de la operación.\n"
        "Cada solicitante desembolsará 1,25€ por acción nueva.\n",
        _doc(),
    )
    assert not _claim(parsed, "amount.issue_price_per_share")
    assert not _claim(parsed, "amount.gross_per_share")


def test_cuarentena_generico_por_accion_en_ampliacion_abstiene():
    """En una ampliacion, un "X euros por accion" sin ancla propia se
    abstiene: la familia no puede promoverlo a issue_price."""
    parsed = portfolio._parse_text(
        "Ampliación de capital con suscripción preferente.\n"
        "El desembolso será de 3,20€ por acción.\n",
        _doc(),
    )
    assert not _claim(parsed, "amount.issue_price_per_share")
    assert not _claim(parsed, "amount.gross_per_share")


def test_valor_nominal_ligado_bloquea_en_ampliacion():
    """"valor nominal de X euros por accion" en una ampliacion es el
    nominal, no el precio de emision: no se promueve."""
    parsed = portfolio._parse_text(
        "Ampliación de capital de la sociedad.\n"
        "Las acciones nuevas tendrán un valor nominal de 0,10€ "
        "por acción.\n",
        _doc(),
    )
    assert not _claim(parsed, "amount.issue_price_per_share")
    assert not _claim(parsed, "amount.gross_per_share")


def test_dividendo_sigue_emitiendo_gross_per_share():
    """Regresion: un dividendo con ancla propia sigue emitiendo
    gross_per_share — la cuarentena solo cubre el precio de emision."""
    parsed = portfolio._parse_text(
        "La sociedad acuerda el reparto de dividendo.\n"
        "Importe bruto de 0,75€ por acción.\n"
        "Fecha de pago 15/09/2026\n",
        _doc(),
    )
    assert parsed.event_type == "CASH_DIVIDEND"
    gross = _claim(parsed, "amount.gross_per_share")
    assert gross and str(gross[0].value.normalized) == "0.75"
    assert not _claim(parsed, "amount.issue_price_per_share")


def test_unknown_con_por_accion_sigue_siendo_gross():
    """Regresion: sin familia de emision, "X euros por accion" mantiene
    el routing previo a gross_per_share."""
    parsed = portfolio._parse_text(
        "La sociedad comunica una distribución con cargo a reservas.\n"
        "El abono será de 0,50€ por acción.\n",
        _doc(),
    )
    gross = _claim(parsed, "amount.gross_per_share")
    assert gross and str(gross[0].value.normalized) == "0.50"
