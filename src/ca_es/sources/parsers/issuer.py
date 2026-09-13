"""Parser de investor relations del emisor (HTML real / fixture).

Extrae la remuneracion publicada por el propio emisor. Cuando una fuente
da el importe en centimos, se etiqueta como derivado (1 EUR = 100
centimos) y se conserva el lexema publicado.
"""
from __future__ import annotations

import re

from ...canonical import sha256_text, strict_json_loads
from ...numeric import FinancialAmount
from ...source_policy import SourcePolicy
from ..documents import SourceDocument
from .base import Claim, ParsedDocument, parse_structured
from .html_text import decode, html_to_text

SOURCE_ID = "ISSUER_IR"
REAL_PARSER_VERSION = "CA_ES_ISSUER_HTML_V1"


def parse(
    payload: bytes, document: SourceDocument, policy: dict[str, SourcePolicy]
) -> ParsedDocument:
    if document.source_id != SOURCE_ID:
        raise ValueError(f"parser issuer IR recibio fuente {document.source_id}")
    if document.media_type.startswith("text/html"):
        return _parse_html(payload, document)
    raw = strict_json_loads(payload.decode("utf-8"))
    return parse_structured(raw, document, policy, parser_name="issuer_ir")


def _parse_html(payload: bytes, document: SourceDocument) -> ParsedDocument:
    text = html_to_text(decode(payload))
    anchors: dict[str, dict] = {}
    claims: list[Claim] = []

    def grab(name: str, pattern: str, *, group: int = 1, flags: int = re.I) -> str | None:
        match = re.search(pattern, text, flags)
        if match is None:
            return None
        anchors[name] = {"value": match.group(group), "matched": match.group(0), "pattern": pattern}
        return match.group(group)

    def cite(name: str) -> str:
        return f"{document.official_document_id}: «{anchors[name]['matched'][:220]}»"

    cents = grab("dividend_cents", r"cash dividend of [^0-9]{0,3}([\d.]+) cents per share")
    if cents:
        claims.append(
            Claim(
                field_path="amount.gross_per_share",
                value=FinancialAmount.from_cents(
                    cents, decimal_sep=".", thousands_sep=None
                ),
                evidence_locator=cite("dividend_cents"),
                raw_pointer="/anchors/dividend_cents/value",
                evidence_mode="DERIVED_BY_DEFINITION",
                fact_origin="DETERMINISTIC_DERIVATION",
            )
        )

    eur = grab("dividend_eur", r"cash dividend of [^0-9]{0,3}([\d.,]+) euros? per share")
    if eur and not cents:
        claims.append(
            Claim(
                field_path="amount.gross_per_share",
                value=FinancialAmount.parse_localized(eur, currency="EUR"),
                evidence_locator=cite("dividend_eur"),
                raw_pointer="/anchors/dividend_eur/value",
            )
        )

    event_type = "CASH_DIVIDEND" if cents or eur else "UNKNOWN"
    issuer = grab("issuer", r"^(.{0,60}?)\s+[|–-]\s", group=1)

    return ParsedDocument(
        document=document,
        parser="issuer_html",
        parser_version=REAL_PARSER_VERSION,
        raw_record={"text": text, "anchors": anchors, "text_sha256": sha256_text(text)},
        event_type=event_type,
        issuer_name=issuer,
        isin=None,
        lei=None,
        claims=tuple(claims),
        references=(),
        infrastructure_roles=(),
        entitlement_basis=None,
        event_type_evidence_locator=(cite("dividend_cents") if cents else None),
    )
