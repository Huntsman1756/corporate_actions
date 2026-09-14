"""Tests de los fixes genericos de G1 Fase B: locators, BME Growth, CNMV."""
from __future__ import annotations

import json

from ca_es.sources.documents import SourceDocument
from ca_es.sources.locators import resolve_locator
from ca_es.sources.parsers import bme_growth, cnmv
from ca_es.sources.parsers.labeled_dates import find_labeled_date


def _doc(source_id: str, media_type: str = "application/json") -> SourceDocument:
    return SourceDocument(
        source_id=source_id,
        official_document_id="TEST-001",
        content_sha256="0" * 64,
        retrieved_at="2026-09-14",
        media_type=media_type,
    )


# --- locators -------------------------------------------------------


def test_locator_absolute_passthrough():
    url = "https://www.cnmv.es/webservices/verdocumento/ver?t=%7babc%7d"
    assert resolve_locator("CNMV_OIR", url) == url


def test_locator_relative_resolves_against_portal():
    assert resolve_locator(
        "CNMV_OIR", "../otra-informacion-regulada-corporativa/x.aspx?Nif=A-1"
    ) == (
        "https://www.cnmv.es/portal/otra-informacion-regulada-corporativa/"
        "x.aspx?Nif=A-1"
    )


def test_locator_invalid_returns_none():
    assert resolve_locator("CNMV_OIR", None) is None
    assert resolve_locator("CNMV_OIR", "") is None
    assert resolve_locator("CNMV_OIR", "javascript:void(0)") is None
    assert resolve_locator("UNKNOWN_SOURCE", "rel/path.aspx") is None


# --- BME Growth ------------------------------------------------------


def _bmeg_doc() -> SourceDocument:
    return _doc("BME_GROWTH", "application/json")


def _bmeg_payload(category: str, metadata: dict) -> bytes:
    return json.dumps(
        {
            "frame_item_id": "BMEG-TEST",
            "official_category": category,
            "issuer_raw": metadata.get("issuerName"),
            "instrument_isin": metadata.get("isin"),
            "publication_date": "2025-07-01",
            "metadata": metadata,
        }
    ).encode("utf-8")


def test_bmeg_dividend_maps_dates_and_amounts():
    parsed = bme_growth.parse(
        _bmeg_payload(
            "Dividends",
            {
                "exDate": "20250701",
                "paymentDate": "20250703",
                "grossAmount": "1.08828849",
                "netAmount": "0.88151368",
                "currency": "EUR",
                "isin": "ES0105030003",
                "company": "MERCAL INMUEBLES, SOCIMI, S.A.",
            },
        ),
        _bmeg_doc(),
        {},
    )
    assert parsed.event_type == "CASH_DIVIDEND"
    assert parsed.isin == "ES0105030003"
    by_field = {c.field_path: c for c in parsed.claims}
    assert by_field["date.ex_date"].value == "2025-07-01"
    assert by_field["date.payment_date"].value == "2025-07-03"
    gross = by_field["amount.gross_per_share"].value
    assert gross.raw_lexeme == "1.08828849"
    assert gross.scale == 8


def test_bmeg_capital_increase_with_rights_is_rights_issue():
    parsed = bme_growth.parse(
        _bmeg_payload(
            "CapitalIncreases",
            {
                "rightsIndicator": "S",
                "price": "0.8",
                "currency": "EUR",
                "isin": "ES0105425021",
                "issuerName": "PLASTICOS COMPUESTOS, S.A.",
                "startingDate": "20260223",
                "finishDate": "20260308",
            },
        ),
        _bmeg_doc(),
        {},
    )
    assert parsed.event_type == "RIGHTS_ISSUE"


def test_bmeg_takeover_price_text_stays_raw():
    parsed = bme_growth.parse(
        _bmeg_payload(
            "TakeoverBids",
            {
                "priceText": "1 ACC. BBVA + 0,70 EUR",
                "startingDate": "20250908",
                "companyName": "BANCO DE SABADELL, S.A.",
            },
        ),
        _bmeg_doc(),
        {},
    )
    assert parsed.event_type == "TAKEOVER_BID"
    by_field = {c.field_path: c for c in parsed.claims}
    assert by_field["takeover.price_text"].value == "1 ACC. BBVA + 0,70 EUR"


def test_bmeg_rejects_other_source():
    import pytest

    with pytest.raises(ValueError):
        bme_growth.parse(b"{}", _doc("CNMV"), {})


# --- CNMV generico ---------------------------------------------------


def _cnmv_html(text: str) -> bytes:
    return f"<html><body><p>{text}</p></body></html>".encode("utf-8")


def test_cnmv_dividendo_complementario_generico():
    parsed = cnmv.parse(
        _cnmv_html(
            "La Junta General ha aprobado el pago de un dividendo "
            "complementario de 0,025 euros brutos por accion. "
            "LIBERTAS 7, S.A."
        ),
        _doc("CNMV", "text/html"),
        {},
    )
    assert parsed.event_type == "CASH_DIVIDEND"
    gross = [c for c in parsed.claims if c.field_path == "amount.gross_per_share"]
    assert gross and gross[0].value.raw_lexeme == "0,025"


def test_cnmv_amortizacion_anticipada_con_isin_y_fecha():
    parsed = cnmv.parse(
        _cnmv_html(
            "BBVA comunica que va a proceder a la amortizacion anticipada "
            "total de la emision con codigo ISIN ES0413211A18, siendo la "
            "fecha valor el dia 29 de abril de 2025."
        ),
        _doc("CNMV", "text/html"),
        {},
    )
    assert parsed.event_type == "EARLY_REDEMPTION"
    assert parsed.isin == "ES0413211A18"
    dates = {c.field_path for c in parsed.claims if c.date_kind}
    assert "date.payment_date" in dates


def test_cnmv_document_date_cualquier_ciudad():
    parsed = cnmv.parse(
        _cnmv_html(
            "Bilbao, 31 de julio de 2025 A la Comision Nacional del "
            "Mercado de Valores comunicacion de informacion privilegiada"
        ),
        _doc("CNMV", "text/html"),
        {},
    )
    ann = [c for c in parsed.claims if c.field_path == "date.announcement_date"]
    assert ann and ann[0].value == "2025-07-31"


def test_cnmv_opa_detectada():
    parsed = cnmv.parse(
        _cnmv_html("Se ha presentado una oferta publica de adquisicion sobre la sociedad."),
        _doc("CNMV", "text/html"),
        {},
    )
    assert parsed.event_type == "TAKEOVER_BID"


def test_cnmv_unknown_cuando_no_hay_patron():
    parsed = cnmv.parse(
        _cnmv_html("Composicion de las comisiones del consejo de administracion."),
        _doc("CNMV", "text/html"),
        {},
    )
    assert parsed.event_type == "UNKNOWN"


# --- fechas etiquetadas (clase MISSING generica) ---------------------


def test_labeled_date_numeric_y_espaciada():
    text = "Record Date  02 / 07 / 2026\nEx–Date  03 / 07 / 2026"
    assert find_labeled_date(text, "RECORD_DATE")["iso"] == "2026-07-02"
    assert find_labeled_date(text, "EX_DATE")["iso"] == "2026-07-03"


def test_labeled_date_espanola():
    text = "Payment date  22 de julio de 2026"
    assert find_labeled_date(text, "PAYMENT_DATE")["iso"] == "2026-07-22"


def test_labeled_date_se_concreta_en_el_dia():
    text = (
        "Fecha de pago: 25 dias siguientes a la aprobacion del acuerdo "
        "(que se concreta en el dia 23 de junio de 2025)."
    )
    assert find_labeled_date(text, "PAYMENT_DATE")["iso"] == "2025-06-23"


def test_labeled_date_sin_etiqueta_no_extrae():
    assert find_labeled_date("La junta fue el 30 de abril de 2025.", "EX_DATE") is None


def test_labeled_date_descriptiva_no_promueve_fecha_ajena():
    # "en la fecha de pago" es referencia al concepto; la fecha siguiente
    # es la de firma del documento y no debe promoverse.
    text = (
        "por cada accion con derecho a percibirlo en la fecha de pago. "
        "Una vez se convoque la Junta se comunicara la fecha de reparto. "
        "En Madrid, a 25 de marzo de 2026."
    )
    assert find_labeled_date(text, "PAYMENT_DATE") is None


def test_labeled_date_segunda_ocurrencia():
    # La primera etiqueta es una mencion delegada sin fecha; la segunda
    # introduce el valor.
    text = (
        "para que fije la fecha de pago (payment date) y designe al "
        "agente. En el marco de lo anterior se fija el calendario: "
        "Fecha de pago (payment date): 26 de mayo de 2025."
    )
    assert find_labeled_date(text, "PAYMENT_DATE")["iso"] == "2025-05-26"


def test_cnmv_fechas_etiquetadas_parentesis():
    parsed = cnmv.parse(
        _cnmv_html(
            "Distribucion de dividendos ordinarios ascendente a "
            "10.753.259,44 euros brutos, equivalente a 0,01910633 euros "
            "brutos por accion. "
            "Fecha de pago del Dividendo (payment date): 26 de mayo de "
            "2025. La fecha desde la que las acciones se negociaran sin "
            "derecho (ex date) sera el 8 de mayo de 2025."
        ),
        _doc("CNMV", "text/html"),
        {},
    )
    assert parsed.event_type == "CASH_DIVIDEND"
    dates = {c.field_path: c.value for c in parsed.claims if c.date_kind}
    assert dates["date.ex_date"] == "2025-05-08"
    assert dates["date.payment_date"] == "2025-05-26"
    gross = [c for c in parsed.claims if c.field_path == "amount.gross_per_share"]
    assert gross and gross[0].value.raw_lexeme == "0,01910633"


def test_cnmv_propuesta_dividendo_detectada():
    parsed = cnmv.parse(
        _cnmv_html(
            "Ha acordado proponer a la Junta General repartir un "
            "dividendo por un importe fijo unitario de 1,57 euros brutos "
            "por cada accion."
        ),
        _doc("CNMV", "text/html"),
        {},
    )
    assert parsed.event_type == "CASH_DIVIDEND"
    gross = [c for c in parsed.claims if c.field_path == "amount.gross_per_share"]
    assert gross and gross[0].value.raw_lexeme == "1,57"


def test_magnitude_amounts_millones_normalizados():
    from ca_es.sources.parsers.magnitude_amounts import find_magnitude_amounts

    found = find_magnitude_amounts(
        "El importe en circulacion de las Obligaciones Existentes es de "
        "255 millones de euros, y la nueva emision tendra un importe "
        "nominal maximo de 262 millones de euros."
    )
    by_field = {item["field_path"]: item["amount"] for item in found}
    assert by_field["amount.outstanding"].normalized_str() == "255000000"
    assert by_field["amount.outstanding"].raw_lexeme == "255 millones de euros"
    assert by_field["amount.outstanding"].currency == "EUR"
    assert by_field["amount.max_total"].normalized_str() == "262000000"


def test_magnitude_amounts_decimal_coeficiente():
    from ca_es.sources.parsers.magnitude_amounts import find_magnitude_amounts

    found = find_magnitude_amounts("por un total de 1,2 millones de euros.")
    assert found and found[0]["amount"].normalized_str() == "1200000"


def test_magnitude_amounts_qualifier_no_promueve():
    from ca_es.sources.parsers.magnitude_amounts import find_magnitude_amounts

    assert not find_magnitude_amounts(
        "por un total de aproximadamente 255 millones de euros."
    )
    assert not find_magnitude_amounts(
        "El importe maximo de hasta 262 millones de euros."
    )
    assert not find_magnitude_amounts(
        "una emision por un importe de mas de 100 millones de euros."
    )
    assert not find_magnitude_amounts(
        "que podria alcanzar hasta un importe maximo de 262 millones de euros."
    )


def test_magnitude_amounts_sin_ancla_no_extrae():
    from ca_es.sources.parsers.magnitude_amounts import find_magnitude_amounts

    assert not find_magnitude_amounts(
        "La empresa cuenta con activos por 255 millones de euros."
    )


def test_cnmv_millones_de_euros_extrae_importe():
    parsed = cnmv.parse(
        _cnmv_html(
            "Amortizacion anticipada. El importe en circulacion de las "
            "Obligaciones Existentes es de 255 millones de euros."
        ),
        _doc("CNMV", "text/html"),
        {},
    )
    outstanding = [
        c for c in parsed.claims if c.field_path == "amount.outstanding"
    ]
    assert outstanding
    assert outstanding[0].value.normalized_str() == "255000000"
    assert outstanding[0].value.raw_lexeme == "255 millones de euros"
