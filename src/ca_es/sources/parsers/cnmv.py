"""Parser CNMV (documentos reales PDF / fixtures estructurados).

Los documentos reales de CNMV se publican como PDF. Se extrae texto
(dependencia opcional pypdf) y se localizan anclas exactas. No se
inventan campos: lo no demostrado queda ausente.

El servicio de registro usa el numero de comunicacion (p.ej. 1885) como
identificador oficial; el manifiesto fija official_document_id =
CNMV-IP-<numero> o CNMV-OIR-<numero>.
"""
from __future__ import annotations

import re

from ...canonical import sha256_text, strict_json_loads
from ...numeric import FinancialAmount
from ...source_policy import SourcePolicy
from ..documents import SourceDocument
from .base import (
    Claim,
    DocumentReference,
    ParsedDocument,
    parse_structured,
)
from .html_text import spanish_date_to_iso
from .pdf_text import extract_text, normalize_text

SOURCE_ID = "CNMV"
REAL_PARSER_VERSION = "CA_ES_CNMV_PDF_V1"
_AMOUNT = r"([\d.]+(?:,\d+)?)"


def parse(
    payload: bytes, document: SourceDocument, policy: dict[str, SourcePolicy]
) -> ParsedDocument:
    if document.source_id != SOURCE_ID:
        raise ValueError(f"parser CNMV recibio fuente {document.source_id}")
    if document.media_type == "application/pdf":
        return _parse_pdf(payload, document)
    raw = strict_json_loads(payload.decode("utf-8"))
    return parse_structured(raw, document, policy, parser_name="cnmv")


def _parse_pdf(payload: bytes, document: SourceDocument) -> ParsedDocument:
    text = normalize_text(extract_text(payload))
    anchors: dict[str, dict] = {}

    def grab(name: str, pattern: str, *, group: int = 1, flags: int = 0) -> str | None:
        match = re.search(pattern, text, flags)
        if match is None:
            return None
        try:
            value = match.group(group)
        except IndexError:
            value = match.group(0)
        anchors[name] = {
            "value": value,
            "matched": match.group(0),
            "offset": match.start(),
            "pattern": pattern,
        }
        return value

    reference = document.official_document_id

    def cite(name: str) -> str:
        return f"{reference}: «{anchors[name]['matched'][:200]}»"

    claims: list[Claim] = []

    # Tipo de evento: aumento de capital sin derecho de suscripcion preferente.
    grab("event", r"aumento de capital[^.]{0,120}exclusi[oó]n del derecho de suscripci[oó]n preferente", flags=re.I)
    event_type = "CAPITAL_INCREASE" if "event" in anchors else "UNKNOWN"

    def add_amount(name: str, field_path: str, pattern: str) -> None:
        value = grab(name, pattern, flags=re.I)
        if value is None:
            return
        claims.append(
            Claim(
                field_path=field_path,
                value=FinancialAmount.parse_localized(value, currency="EUR"),
                evidence_locator=cite(name),
                raw_pointer=f"/anchors/{name}/value",
            )
        )

    add_amount(
        "issue_price",
        "amount.issue_price_per_share",
        rf"se fija en {_AMOUNT} euros",
    )
    add_amount("gross_proceeds", "amount.gross_proceeds", rf"fondos brutos[^.]*?ser[aá]n de {_AMOUNT}")
    add_amount("nominal_amount", "amount.nominal_amount", rf"importe nominal de {_AMOUNT} euros")

    new_shares = grab("new_shares", r"emisi[oó]n de ([\d.]+) Acciones Nuevas", flags=re.I)
    if new_shares:
        claims.append(
            Claim(
                field_path="shares.new_shares",
                value=int(new_shares.replace(".", "")),
                evidence_locator=cite("new_shares"),
                raw_pointer="/anchors/new_shares/value",
            )
        )

    subscribed = grab("subscribed", r"suscrito ([\d.]+) Acciones Nuevas", flags=re.I)
    if subscribed:
        claims.append(
            Claim(
                field_path="shares.subscribed_by_reference_holder",
                value=int(subscribed.replace(".", "")),
                evidence_locator=cite("subscribed"),
                raw_pointer="/anchors/subscribed/value",
            )
        )

    date_value = grab("document_date", r"Barcelona, (\d{1,2} de \w+ de \d{4})")
    if date_value:
        iso = spanish_date_to_iso(date_value)
        if iso:
            claims.append(
                Claim(
                    field_path="date.announcement_date",
                    value=iso,
                    date_kind="ANNOUNCEMENT_DATE",
                    evidence_locator=cite("document_date"),
                    raw_pointer="/anchors/document_date/value",
                )
            )

    # Referencia explicita a una comunicacion previa (clustering, no revision).
    references: list[DocumentReference] = []
    predecessor = grab(
        "predecessor",
        r"comunicaci[oó]n de informaci[oó]n privilegiada n[.º°]?\.?\s*([\d.]+)",
        flags=re.I,
    )
    if predecessor:
        number = predecessor.replace(".", "")
        references.append(
            DocumentReference(
                relation="EXACT_OFFICIAL_CROSS_REFERENCE",
                target_source_id="CNMV",
                target_official_document_id=f"CNMV-IP-{number}",
                evidence_locator=cite("predecessor"),
            )
        )

    issuer = None
    issuer_match = re.search(r"([A-Z][A-Za-zÀ-ÿ&.\- ]{2,60}), S\.A\.", text)
    if issuer_match:
        issuer = issuer_match.group(1).strip()

    return ParsedDocument(
        document=document,
        parser="cnmv_pdf",
        parser_version=REAL_PARSER_VERSION,
        raw_record={
            "text": text,
            "anchors": anchors,
            "text_sha256": sha256_text(text),
        },
        event_type=event_type,
        issuer_name=issuer,
        isin=None,
        lei=None,
        claims=tuple(claims),
        references=tuple(references),
        infrastructure_roles=(),
        entitlement_basis=None,
        event_type_evidence_locator=(cite("event") if "event" in anchors else None),
    )
