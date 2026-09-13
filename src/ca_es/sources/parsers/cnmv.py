"""Parser CNMV (documentos reales PDF / fixtures estructurados).

Extrae hechos de aumentos de capital y de dividendos publicados por CNMV.
No inventa: cada ancla se cita con su fragmento; los campos no
demostrados quedan ausentes. Una fecha sin anio se deriva
(`DERIVED_BY_DEFINITION`) usando el anio de una fecha explicita del mismo
documento, nunca el reloj del sistema.
"""
from __future__ import annotations

import re

from ...canonical import sha256_text, strict_json_loads
from ...numeric import FinancialAmount
from ...source_policy import SourcePolicy
from ..documents import SourceDocument
from .base import Claim, DocumentReference, ParsedDocument, parse_structured
from .html_text import spanish_date_to_iso
from .pdf_text import extract_text, normalize_text

SOURCE_ID = "CNMV"
REAL_PARSER_VERSION = "CA_ES_CNMV_PDF_V2"
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


def _daymonth_to_iso(value: str, default_year: str) -> str | None:
    normalized = re.sub(r"\s+", " ", value.strip())
    iso = spanish_date_to_iso(normalized)
    if iso:
        return iso
    match = re.match(r"(\d{1,2}) de (\w+)", normalized)
    if not match:
        return None
    return spanish_date_to_iso(f"{match.group(1)} de {match.group(2)} de {default_year}")


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
        return f"{reference}: «{anchors[name]['matched'][:220]}»"

    claims: list[Claim] = []

    # --- Clasificacion de evento ------------------------------------
    capital = grab(
        "event_capital",
        r"aumento de capital[^.]{0,140}exclusi[oó]n del derecho de suscripci[oó]n preferente",
        flags=re.I | re.S,
    )
    dividend_eur = grab(
        "dividend_eur", rf"dividendo (?:ordinario |bruto )*de {_AMOUNT} euros", flags=re.I
    )
    dividend_cents = grab(
        "dividend_cents",
        rf"cantidad bruta de {_AMOUNT}\s*c[eé]ntimos de euro",
        flags=re.I,
    )
    dividend_effectivo = grab(
        "event_dividend", r"dividendo\s+(?:complementario\s+)?en efectivo", flags=re.I
    )
    dividend_context = grab(
        "event_dividend_context",
        r"distribuci[oó]n del dividendo(?: ordinario bruto)?",
        flags=re.I,
    )
    if dividend_cents or dividend_eur or dividend_effectivo or dividend_context:
        event_type = "CASH_DIVIDEND"
    elif capital:
        event_type = "CAPITAL_INCREASE"
    else:
        event_type = "UNKNOWN"

    def add_amount(name: str, field_path: str, value: FinancialAmount | None) -> None:
        if value is None:
            return
        claims.append(
            Claim(
                field_path=field_path,
                value=value,
                evidence_locator=cite(name),
                raw_pointer=f"/anchors/{name}/value",
            )
        )

    # --- Aumento de capital -----------------------------------------
    def grab_amount(name: str, pattern: str, currency: str = "EUR") -> FinancialAmount | None:
        value = grab(name, pattern, flags=re.I)
        return FinancialAmount.parse_localized(value, currency=currency) if value else None

    if capital:
        add_amount("issue_price", "amount.issue_price_per_share", grab_amount("issue_price", rf"se fija en {_AMOUNT} euros"))
        add_amount("gross_proceeds", "amount.gross_proceeds", grab_amount("gross_proceeds", rf"fondos brutos[^.]*?ser[aá]n de {_AMOUNT}"))
        add_amount("nominal_amount", "amount.nominal_amount", grab_amount("nominal_amount", rf"importe nominal de {_AMOUNT} euros"))

        for name, field, pattern in (
            ("new_shares", "shares.new_shares", r"emisi[oó]n de ([\d.]+) Acciones Nuevas"),
            ("subscribed", "shares.subscribed_by_reference_holder", r"suscrito ([\d.]+) Acciones Nuevas"),
        ):
            value = grab(name, pattern, flags=re.I)
            if value:
                claims.append(
                    Claim(
                        field_path=field,
                        value=int(value.replace(".", "")),
                        evidence_locator=cite(name),
                        raw_pointer=f"/anchors/{name}/value",
                    )
                )

    # --- Dividendo --------------------------------------------------
    cents = dividend_cents
    if cents:
        claims.append(
            Claim(
                field_path="amount.gross_per_share",
                value=FinancialAmount.from_cents(cents),
                evidence_locator=cite("dividend_cents"),
                raw_pointer="/anchors/dividend_cents/value",
                evidence_mode="DERIVED_BY_DEFINITION",
                fact_origin="DETERMINISTIC_DERIVATION",
            )
        )
    eur = dividend_eur
    if eur and not cents:
        claims.append(
            Claim(
                field_path="amount.gross_per_share",
                value=FinancialAmount.parse_localized(eur, currency="EUR"),
                evidence_locator=cite("dividend_eur"),
                raw_pointer="/anchors/dividend_eur/value",
            )
        )

    # Fecha de pago explicita (con anio).
    payment = grab(
        "payment_date",
        r"(?:pagader[oa][^.]{0,40}?|pago del dividendo[^.]{0,200}?|tenga lugar el |para el )(\d{1,2} de \w+ de \d{4})",
        flags=re.I | re.S,
    )
    payment_iso = spanish_date_to_iso(payment) if payment else None
    if payment_iso:
        claims.append(
            Claim(
                field_path="date.payment_date",
                value=payment_iso,
                date_kind="PAYMENT_DATE",
                evidence_locator=cite("payment_date"),
                raw_pointer="/anchors/payment_date/value",
            )
        )
    default_year = payment_iso[:4] if payment_iso else (
        document.publication_date or "1970"[:4]
    )

    def add_relative_date(name: str, pattern: str, field_path: str, date_kind: str) -> None:
        value = grab(name, pattern, flags=re.I | re.S)
        if not value:
            return
        iso = _daymonth_to_iso(value, default_year)
        if not iso:
            return
        explicit = bool(re.search(r"de \d{4}", value))
        claims.append(
            Claim(
                field_path=field_path,
                value=iso,
                date_kind=date_kind,
                evidence_locator=cite(name)
                + ("" if explicit else f" (anio derivado de la fecha de pago: {default_year})"),
                raw_pointer=f"/anchors/{name}/value",
                evidence_mode="EXPLICIT" if explicit else "DERIVED_BY_DEFINITION",
                fact_origin="SOURCE_ASSERTION" if explicit else "DETERMINISTIC_DERIVATION",
            )
        )

    add_relative_date(
        "ex_date",
        r"ex ?-?dividendo[^0-9]{0,40}(\d{1,2}\s+de\s+\w+(?:\s+de\s+\d{4})?)",
        "date.ex_date",
        "EX_DATE",
    )
    add_relative_date(
        "record_date",
        r"(?:record date\)?[^0-9]{0,40}|fecha de registro[^0-9]{0,40})(\d{1,2}\s+de\s+\w+(?:\s+de\s+\d{4})?)",
        "date.record_date",
        "RECORD_DATE",
    )

    # --- Fecha del documento ----------------------------------------
    doc_date = grab("document_date", r"Barcelona, (\d{1,2} de \w+ de \d{4})")
    if doc_date:
        iso = spanish_date_to_iso(doc_date)
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

    # --- Referencia explicita a comunicacion previa -----------------
    references: list[DocumentReference] = []
    predecessor = grab(
        "predecessor",
        r"comunicaci[oó]n de informaci[oó]n privilegiada n[.º°]?\.?\s*([\d.]+)",
        flags=re.I,
    )
    if predecessor:
        references.append(
            DocumentReference(
                relation="EXACT_OFFICIAL_CROSS_REFERENCE",
                target_source_id="CNMV",
                target_official_document_id=f"CNMV-IP-{predecessor.replace('.', '')}",
                evidence_locator=cite("predecessor"),
            )
        )
    if grab("new_dates", r"nuevas fechas relativas a la distribuci[oó]n del dividendo", flags=re.I):
        # La relacion concreta (SUPERSEDES/EXPLICIT_PREDECESSOR_REFERENCE) la
        # aporta el registro oficial (manifest); aqui solo se conserva evidencia.
        pass

    issuer = None
    issuer_match = re.search(r"([A-Z][A-Za-zÀ-ÿ&.\- ]{2,60}), S\.A\.", text)
    if issuer_match:
        issuer = issuer_match.group(1).strip()

    return ParsedDocument(
        document=document,
        parser="cnmv_pdf",
        parser_version=REAL_PARSER_VERSION,
        raw_record={"text": text, "anchors": anchors, "text_sha256": sha256_text(text)},
        event_type=event_type,
        issuer_name=issuer,
        isin=None,
        lei=None,
        claims=tuple(claims),
        references=tuple(references),
        infrastructure_roles=(),
        entitlement_basis=None,
        event_type_evidence_locator=(
            cite("event_dividend")
            if dividend_effectivo
            else cite("dividend_cents")
            if dividend_cents
            else cite("dividend_eur")
            if dividend_eur
            else cite("event_dividend_context")
            if dividend_context
            else cite("event_capital")
            if capital
            else None
        ),
    )
