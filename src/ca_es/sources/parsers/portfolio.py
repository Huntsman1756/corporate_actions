"""Parser Portfolio Stock Exchange (PDF real / fixture estructurado).

Documentos de Otra Informacion Relevante de Portfolio (BME Growth/MTF).
Extrae la tabla de dividendo: record/ex/payment date, importe bruto por
accion (hasta 8 decimales) y el canal de pago. No se mapea el nombre del
venue a MIC (eso es de la capa ESMA, ADR-006).
"""
from __future__ import annotations

import re

from ...canonical import sha256_text, strict_json_loads
from ...numeric import FinancialAmount
from ...source_policy import SourcePolicy
from ..documents import SourceDocument
from .base import Claim, InfrastructureClaim, ParsedDocument, parse_structured
from .labeled_dates import find_labeled_date
from .magnitude_amounts import find_magnitude_amounts
from .pdf_text import extract_text, normalize_text

_ISIN = r"\bES[A-Z0-9]{10}\b"

SOURCE_ID = "PORTFOLIO_STOCK_EXCHANGE"
REAL_PARSER_VERSION = "CA_ES_PORTFOLIO_PDF_V1"


def parse(
    payload: bytes, document: SourceDocument, policy: dict[str, SourcePolicy]
) -> ParsedDocument:
    if document.source_id != SOURCE_ID:
        raise ValueError(f"parser Portfolio recibio fuente {document.source_id}")
    if document.media_type == "application/pdf":
        return _parse_pdf(payload, document)
    raw = strict_json_loads(payload.decode("utf-8"))
    return parse_structured(raw, document, policy, parser_name="portfolio")


def _dmy_to_iso(value: str) -> str | None:
    match = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", value.strip())
    if not match:
        return None
    day, month, year = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def _line_with(text: str, needle: str) -> str | None:
    for line in text.splitlines():
        if needle.lower() in line.lower():
            return line
    return None


def _last_amount(line: str) -> str | None:
    matches = re.findall(r"\d[\d.]*(?:,\d+)?", line)
    return matches[-1] if matches else None


def _parse_pdf(payload: bytes, document: SourceDocument) -> ParsedDocument:
    text = normalize_text(extract_text(payload))
    anchors: dict[str, dict] = {}

    def register(name: str, line: str, value: str) -> None:
        anchors[name] = {"value": value, "matched": line.strip(), "pattern": "line"}

    claims: list[Claim] = []
    # Las etiquetas llevan numeros de nota entre la etiqueta y la fecha
    # ("Record Date (2) 23/07/2025"); se permite cualquier caracter de la
    # misma linea antes de la fecha.
    date_patterns = (
        ("date.ex_date", r"Ex[^\n]{0,4}Date[^\n]{0,25}?(\d{1,2}/\d{1,2}/\d{4})", "EX_DATE"),
        ("date.record_date", r"Record Date[^\n]{0,25}?(\d{1,2}/\d{1,2}/\d{4})", "RECORD_DATE"),
        ("date.payment_date", r"[Ff]echa de pago[^\n]{0,40}?(\d{1,2}/\d{1,2}/\d{4})", "PAYMENT_DATE"),
    )
    for field_path, pattern, date_kind in date_patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        iso = _dmy_to_iso(match.group(1))
        if not iso:
            continue
        line = match.group(0)
        register(field_path, line, match.group(1))
        claims.append(
            Claim(
                field_path=field_path,
                value=iso,
                date_kind=date_kind,
                evidence_locator=f"{document.official_document_id}: «{line.strip()[:200]}»",
                raw_pointer=f"/anchors/{field_path}/value",
            )
        )

    # Fallback generico: etiquetas EN/ES con fechas en formato numerico
    # espaciado ("03 / 07 / 2026") o espanol ("22 de julio de 2026").
    seen_fields = {c.field_path for c in claims}
    for date_kind, field_path in (
        ("EX_DATE", "date.ex_date"),
        ("RECORD_DATE", "date.record_date"),
        ("PAYMENT_DATE", "date.payment_date"),
        ("LAST_TRADING_DATE", "date.last_trading_date"),
    ):
        if field_path in seen_fields:
            continue
        found = find_labeled_date(text, date_kind)
        if not found:
            continue
        register(field_path, found["matched"], found["value"])
        claims.append(
            Claim(
                field_path=field_path,
                value=found["iso"],
                date_kind=date_kind,
                evidence_locator=(
                    f"{document.official_document_id}: «{found['matched'].strip()[:200]}»"
                ),
                raw_pointer=f"/anchors/{field_path}/value",
            )
        )

    line = next(
        (
            candidate
            for candidate in text.splitlines()
            if "Importe bruto" in candidate and "acci" in candidate.lower()
        ),
        "",
    )
    if line:
        amount = _last_amount(line)
        if amount:
            register("amount.gross_per_share", line, amount)
            claims.append(
                Claim(
                    field_path="amount.gross_per_share",
                    value=FinancialAmount.parse_localized(amount, currency="EUR"),
                    evidence_locator=f"{document.official_document_id}: «{line.strip()[:200]}»",
                    raw_pointer="/anchors/amount.gross_per_share/value",
                )
            )

    line = _line_with(text, "Dividendo bruto")
    if line:
        amount = _last_amount(line)
        if amount:
            register("amount.gross_total", line, amount)
            claims.append(
                Claim(
                    field_path="amount.gross_total",
                    value=FinancialAmount.parse_localized(amount, currency="EUR"),
                    evidence_locator=f"{document.official_document_id}: «{line.strip()[:200]}»",
                    raw_pointer="/anchors/amount.gross_total/value",
                )
            )

    # Importe por accion generico (dividendos y devoluciones de
    # aportaciones): "importe bruto de X euros por accion",
    # "Importe bruto unitario X", "X euros por accion".
    if not any(c.field_path == "amount.gross_per_share" for c in claims):
        per_share = re.search(
            r"importe bruto[^\n]{0,60}?(\d[\d.,]*)\s*\.?-?\s*(?:€|euros)?[^\n]{0,15}?por acci[oó]n",
            text,
            re.I,
        ) or re.search(
            r"(\d[\d.,]*)\s*\.?-?\s*(?:€|euros)\s+por acci[oó]n", text, re.I
        )
        if per_share:
            register("amount.gross_per_share", per_share.group(0), per_share.group(1))
            claims.append(
                Claim(
                    field_path="amount.gross_per_share",
                    value=FinancialAmount.parse_localized(
                        per_share.group(1), currency="EUR"
                    ),
                    evidence_locator=(
                        f"{document.official_document_id}: «{per_share.group(0).strip()[:200]}»"
                    ),
                    raw_pointer="/anchors/amount.gross_per_share/value",
                )
            )
    if not any(c.field_path == "amount.gross_per_share" for c in claims):
        line = _line_with(text, "bruto unitario") or _line_with(text, "Bruto por acci")
        if line:
            amount = _last_amount(line)
            if amount:
                register("amount.gross_per_share", line, amount)
                claims.append(
                    Claim(
                        field_path="amount.gross_per_share",
                        value=FinancialAmount.parse_localized(amount, currency="EUR"),
                        evidence_locator=(
                            f"{document.official_document_id}: «{line.strip()[:200]}»"
                        ),
                        raw_pointer="/anchors/amount.gross_per_share/value",
                    )
                )
    if not any(c.field_path == "amount.gross_total" for c in claims):
        line = _line_with(text, "bruto a repartir") or _line_with(text, "importe total de")
        if line:
            amount = _last_amount(line)
            if amount:
                register("amount.gross_total", line, amount)
                claims.append(
                    Claim(
                        field_path="amount.gross_total",
                        value=FinancialAmount.parse_localized(amount, currency="EUR"),
                        evidence_locator=(
                            f"{document.official_document_id}: «{line.strip()[:200]}»"
                        ),
                        raw_pointer="/anchors/amount.gross_total/value",
                    )
                )

    # Importe de reduccion de capital: "reduccion de capital por un
    # importe de X" / "disminucion de capital social de X euros".
    reduction_amount = re.search(
        r"(?:reducci[oó]n de capital por un importe de|disminuci[oó]n de capital social de)\s*(\d[\d.,]*)\s*\.?-?\s*(?:€|euros)",
        text,
        re.I,
    )
    if reduction_amount:
        register("amount.reduction_total", reduction_amount.group(0), reduction_amount.group(1))
        claims.append(
            Claim(
                field_path="amount.reduction_total",
                value=FinancialAmount.parse_localized(
                    reduction_amount.group(1), currency="EUR"
                ),
                evidence_locator=(
                    f"{document.official_document_id}: «{reduction_amount.group(0).strip()[:200]}»"
                ),
                raw_pointer="/anchors/amount.reduction_total/value",
            )
        )

    # Magnitudes verbales con ancla semantica ("importe ... de
    # X millones de euros"). Misma regla generica que CNMV.
    for item in find_magnitude_amounts(text):
        if any(c.field_path == item["field_path"] for c in claims):
            continue
        name = f"magnitude_{item['offset']}"
        anchors[name] = {"value": item["amount"].normalized_str(), "matched": item["matched"]}
        claims.append(
            Claim(
                field_path=item["field_path"],
                value=item["amount"],
                evidence_locator=(
                    f"{document.official_document_id}: «{item['matched'].strip()[:200]}»"
                ),
                raw_pointer=f"/anchors/{name}/value",
            )
        )

    # ISIN explicito.
    isins = sorted(set(re.findall(_ISIN, text)))
    for index, value in enumerate(isins):
        match = re.search(re.escape(value), text)
        claims.append(
            Claim(
                field_path="instrument.isin",
                value=value,
                evidence_locator=(
                    f"{document.official_document_id}: «{text[max(0, match.start() - 60):match.end() + 40].strip()[:200]}»"
                    if match
                    else f"{document.official_document_id}: ISIN {value}"
                ),
                raw_pointer=f"/isins/{index}",
            )
        )

    roles: list[InfrastructureClaim] = []
    if "Euroclear France" in text:
        roles.append(
            InfrastructureClaim(
                role="PAYMENT_CHANNEL",
                entity="EUROCLEAR_FRANCE",
                evidence_locator=f"{document.official_document_id}: «El abono ... Euroclear France, S.A.»",
            )
        )

    event_type = (
        "CASH_DIVIDEND"
        if re.search(
            r"reparto de dividendo|distribuci[oó]n de dividendo|Dividendo bruto", text, re.I
        )
        else "CAPITAL_REDUCTION"
        if re.search(r"reducci[oó]n de capital", text, re.I)
        else "UNKNOWN"
    )

    issuer = None
    match = re.search(r"^\s*([A-Z][A-Z0-9 .,À-ÿ&()\-]{3,80}?),\s*S\.A\.", text, re.M)
    if match:
        issuer = match.group(1).strip()

    evidence = None
    ev = (
        _line_with(text, "reparto de un dividendo")
        or _line_with(text, "reparto de dividendo")
        or _line_with(text, "distribuci")
        or _line_with(text, "Dividendo bruto")
        or _line_with(text, "reducci")
    )
    if ev:
        evidence = f"{document.official_document_id}: «{ev.strip()[:200]}»"

    return ParsedDocument(
        document=document,
        parser="portfolio_pdf",
        parser_version=REAL_PARSER_VERSION,
        raw_record={
            "text": text,
            "anchors": anchors,
            "isins": isins,
            "text_sha256": sha256_text(text),
        },
        event_type=event_type,
        issuer_name=issuer,
        isin=isins[0] if len(isins) == 1 else None,
        lei=None,
        claims=tuple(claims),
        references=(),
        infrastructure_roles=tuple(roles),
        entitlement_basis=None,
        event_type_evidence_locator=evidence,
    )
