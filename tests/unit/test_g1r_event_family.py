"""Tests de la regla generica G1-R EVENT_TYPE_FAMILY_BOUNDARY.

La familia economica explicita gana al mecanismo/fase:
- "dividendo flexible"/"scrip dividend" -> SCRIP_DIVIDEND aunque el
  documento describa el mecanismo "aumento de capital liberado".
- fusion/OPA/amortizacion conservan su familia ante un lexema
  incidental de dividendo.
- BME NewListings + admissionType=Integration + referencia a
  ampliacion de capital -> CAPITAL_INCREASE (admision de fungibles,
  no incorporacion inicial).
"""
from __future__ import annotations

import json

from ca_es.sources.documents import SourceDocument
from ca_es.sources.parsers import bme_growth, cnmv


def _doc(source_id: str = "CNMV") -> SourceDocument:
    return SourceDocument(
        source_id=source_id,
        official_document_id="TEST-FAMILY",
        content_sha256="0" * 64,
        retrieved_at="2026-09-14",
        media_type="text/html",
    )


def _cnmv_html(text: str) -> bytes:
    return f"<html><body><p>{text}</p></body></html>".encode("utf-8")


def _bmeg_payload(metadata: dict) -> bytes:
    return json.dumps(
        {
            "frame_item_id": "BMEG-TEST",
            "official_category": "NewListings",
            "instrument_isin": metadata.get("isin"),
            "publication_date": "2026-03-06",
            "metadata": metadata,
        }
    ).encode("utf-8")


def test_scrip_gana_al_mecanismo_aumento_liberado():
    """'dividendo flexible' instrumentado via aumento de capital
    liberado -> SCRIP_DIVIDEND, no CAPITAL_INCREASE."""
    parsed = cnmv.parse(
        _cnmv_html(
            "La Sociedad comunica el calendario del aumento de capital "
            "liberado a traves del cual se instrumenta el sistema de "
            "dividendo flexible, que ofrecera a los accionistas la "
            "opcion de recibir el dividendo en efectivo y/o en acciones."
        ),
        _doc(),
        {},
    )
    assert parsed.event_type == "SCRIP_DIVIDEND"


def test_scrip_dividend_lexema_bilingue():
    parsed = cnmv.parse(
        _cnmv_html(
            "Acuerdos respecto a la distribucion de dividendo mediante "
            "un scrip dividend: los accionistas podran optar por "
            "acciones nuevas o por la venta de derechos."
        ),
        _doc(),
        {},
    )
    assert parsed.event_type == "SCRIP_DIVIDEND"


def test_fusion_gana_a_dividendo_incidental():
    """Un documento de fusion que menciona 'dividendo' de pasada no es
    CASH_DIVIDEND."""
    parsed = cnmv.parse(
        _cnmv_html(
            "Se comunica la fusion por absorcion de la sociedad "
            "absorbida por la absorbente. El canje no afecta al "
            "dividendo que cada sociedad hubiera acordado."
        ),
        _doc(),
        {},
    )
    assert parsed.event_type == "MERGER_OR_EXCHANGE"


def test_dividendo_normal_sigue_cash_dividend():
    parsed = cnmv.parse(
        _cnmv_html(
            "La Junta General ha aprobado el pago de un dividendo "
            "complementario de 0,53 euros brutos por accion."
        ),
        _doc(),
        {},
    )
    assert parsed.event_type == "CASH_DIVIDEND"


def test_aumento_sin_scrip_sigue_capital_increase():
    parsed = cnmv.parse(
        _cnmv_html(
            "La sociedad informa del acuerdo de aumento de capital "
            "por compensacion de creditos por importe de 10 millones "
            "de euros."
        ),
        _doc(),
        {},
    )
    assert parsed.event_type == "CAPITAL_INCREASE"


def test_bmeg_newlistings_integration_es_capital_increase():
    """NewListings + Integration + observ de ampliacion -> fase
    ADMISSION de un CAPITAL_INCREASE."""
    parsed = bme_growth.parse(
        _bmeg_payload(
            {
                "admissionType": "Integration",
                "observ": "AMP. CAPITAL NOV 2025",
                "admissionDate": "20260306",
                "isin": "ES0105650008",
                "numShares": 9601365,
            }
        ),
        _doc("BME_GROWTH"),
        {},
    )
    assert parsed.event_type == "CAPITAL_INCREASE"


def test_bmeg_newlistings_inicial_sigue_new_listing():
    """NewListings sin evidencia de ampliacion previa conserva la
    semantica de incorporacion inicial."""
    parsed = bme_growth.parse(
        _bmeg_payload(
            {
                "admissionType": "Incorporation",
                "admissionDate": "20260306",
                "isin": "ES0105650008",
                "numShares": 9601365,
            }
        ),
        _doc("BME_GROWTH"),
        {},
    )
    assert parsed.event_type == "NEW_LISTING"
