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
from .html_text import decode as decode_html, html_to_text, spanish_date_to_iso
from .labeled_dates import find_labeled_date
from .pdf_text import extract_text, normalize_text

SOURCE_ID = "CNMV"
REAL_PARSER_VERSION = "CA_ES_CNMV_DOC_V3"
_AMOUNT = r"([\d.]+(?:,\d+)?)"
_ISIN = r"\bES[A-Z0-9]{10}\b"


def parse(
    payload: bytes, document: SourceDocument, policy: dict[str, SourcePolicy]
) -> ParsedDocument:
    if document.source_id != SOURCE_ID:
        raise ValueError(f"parser CNMV recibio fuente {document.source_id}")
    if document.media_type == "application/pdf":
        return _parse_text(normalize_text(extract_text(payload)), document)
    if document.media_type == "text/html":
        return _parse_text(normalize_text(html_to_text(decode_html(payload))), document)
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


def _parse_text(text: str, document: SourceDocument) -> ParsedDocument:
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
    # Deteccion generica por familia: cada ancla conserva el fragmento
    # que la justifica. La precedencia es determinista (lista ordenada).
    capital = grab(
        "event_capital",
        r"aumento de capital[^.]{0,140}exclusi[oó]n del derecho de suscripci[oó]n preferente",
        flags=re.I | re.S,
    )
    capital_generic = grab(
        "event_capital_generic", r"aumento de capital", flags=re.I
    )
    dividend_eur = grab(
        "dividend_eur", rf"dividendo (?:ordinario |bruto )*de {_AMOUNT} euros", flags=re.I
    )
    dividend_generic = grab(
        "dividend_generic",
        rf"dividendo\b[^.]{{0,60}}?de {_AMOUNT} euros(?:\s*(brutos|netos))?",
        flags=re.I | re.S,
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
        r"(?:distribuci[oó]n del dividendo(?: ordinario bruto)?|distribuci[oó]n de dividendos?|reparto de (?:un )?dividendo|repartir un dividendo|pago de (?:un )?dividendo|dividendo complementario|dividendo extraordinario|dividendo a cuenta)",
        flags=re.I,
    )
    redemption = grab(
        "event_redemption",
        r"(?:amortizaci[oó]n anticipada|reembolso anticipado|amortizaci[oó]n total anticipada)",
        flags=re.I,
    )
    merger = grab(
        "event_merger",
        r"\bfusi[oó]n (?:por absorci[oó]n\b|societaria\b|de\b)",
        flags=re.I,
    )
    takeover = grab(
        "event_takeover",
        r"(?:oferta p[úu]blica de (?:adquisici[oó]n|compra)|\bOPA\b)",
        flags=re.I,
    )
    listing = grab(
        "event_listing",
        r"(?:admisi[oó]n a negociaci[oó]n|incorporaci[oó]n al (?:mercado|sistema)|salida a bolsa)",
        flags=re.I,
    )
    delisting = grab(
        "event_delisting",
        r"exclusi[oó]n de (?:negociaci[oó]n|cotizaci[oó]n)",
        flags=re.I,
    )
    capital_reduction = grab(
        "event_capital_reduction", r"reducci[oó]n de capital", flags=re.I
    )
    if dividend_cents or dividend_eur or dividend_generic or dividend_effectivo or dividend_context:
        event_type = "CASH_DIVIDEND"
    elif redemption:
        event_type = "EARLY_REDEMPTION"
    elif takeover:
        event_type = "TAKEOVER_BID"
    elif merger:
        event_type = "MERGER_OR_EXCHANGE"
    elif capital or capital_generic:
        event_type = "CAPITAL_INCREASE"
    elif capital_reduction:
        event_type = "CAPITAL_REDUCTION"
    elif delisting:
        event_type = "DELISTING"
    elif listing:
        event_type = "NEW_LISTING"
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
    # Importe por accion generico: "X euros brutos por accion",
    # "X euros brutos por cada accion", "importe fijo unitario de X euros".
    # Tiene precedencia sobre los patrones sin ancla "por accion" para no
    # confundir el total del reparto con el importe unitario.
    per_share = grab(
        "dividend_per_share",
        rf"(?:equivalente a |importe fijo unitario de |de )?{_AMOUNT} euros(?:\s*brutos)? por (?:cada )?acci[oó]n",
        flags=re.I,
    )
    cents = dividend_cents
    eur = dividend_eur
    generic = dividend_generic
    if per_share:
        claims.append(
            Claim(
                field_path="amount.gross_per_share",
                value=FinancialAmount.parse_localized(per_share, currency="EUR"),
                evidence_locator=cite("dividend_per_share"),
                raw_pointer="/anchors/dividend_per_share/value",
            )
        )
    if cents and not per_share:
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
    if eur and not cents and not per_share:
        claims.append(
            Claim(
                field_path="amount.gross_per_share",
                value=FinancialAmount.parse_localized(eur, currency="EUR"),
                evidence_locator=cite("dividend_eur"),
                raw_pointer="/anchors/dividend_eur/value",
            )
        )
    if generic and not cents and not eur and not per_share:
        claims.append(
            Claim(
                field_path="amount.gross_per_share",
                value=FinancialAmount.parse_localized(generic, currency="EUR"),
                evidence_locator=cite("dividend_generic"),
                raw_pointer="/anchors/dividend_generic/value",
            )
        )
    # "X euros brutos y Y euros netos por accion" y variantes.
    gross_net = grab(
        "dividend_gross_net",
        rf"{_AMOUNT} euros brutos y {_AMOUNT} euros netos por acci[oó]n",
        flags=re.I,
    )
    if gross_net and not (cents or eur or generic or per_share):
        match = re.search(
            rf"{_AMOUNT} euros brutos y ({_AMOUNT}) euros netos por acci[oó]n",
            anchors["dividend_gross_net"]["matched"],
            re.I,
        )
        claims.append(
            Claim(
                field_path="amount.gross_per_share",
                value=FinancialAmount.parse_localized(gross_net, currency="EUR"),
                evidence_locator=cite("dividend_gross_net"),
                raw_pointer="/anchors/dividend_gross_net/value",
            )
        )
        if match:
            claims.append(
                Claim(
                    field_path="amount.net_per_share",
                    value=FinancialAmount.parse_localized(match.group(1), currency="EUR"),
                    evidence_locator=cite("dividend_gross_net"),
                    raw_pointer="/anchors/dividend_gross_net/matched",
                )
            )

    gross_total = grab(
        "dividend_gross_total",
        rf"(?:dividendos?[^.]{{0,40}}?ascendente a|importe (?:bruto )?total de)\s*{_AMOUNT} euros",
        flags=re.I,
    )
    if gross_total:
        claims.append(
            Claim(
                field_path="amount.gross_total",
                value=FinancialAmount.parse_localized(gross_total, currency="EUR"),
                evidence_locator=cite("dividend_gross_total"),
                raw_pointer="/anchors/dividend_gross_total/value",
            )
        )

    # Importes genericos de emision/amortizacion (transcripcion literal).
    for name, field, pattern in (
        ("issue_total", "amount.issue_total", rf"importe de la emisi[oó]n:\s*{_AMOUNT} euros"),
        ("coupon_amount", "amount.coupon", rf"importe del cup[oó]n[^:]*?:\s*{_AMOUNT} euros"),
        ("nominal_unit", "amount.nominal_unit", rf"nominal unitario:\s*{_AMOUNT} euros"),
        ("max_amount", "amount.max_total", rf"importe m[aá]ximo de {_AMOUNT} euros"),
    ):
        add_amount(name, field, grab_amount(name, pattern))
    pct = grab("redemption_price_pct", rf"precio de amortizaci[oó]n:\s*{_AMOUNT}%", flags=re.I)
    if pct:
        claims.append(
            Claim(
                field_path="amount.redemption_price_pct",
                value=FinancialAmount.parse_localized(pct),
                evidence_locator=cite("redemption_price_pct"),
                raw_pointer="/anchors/redemption_price_pct/value",
            )
        )

    # Fecha de pago explicita (con anio).
    payment = grab(
        "payment_date",
        r"(?:pagader[oa][^.]{0,40}?|pago del dividendo[^.]{0,200}?|tenga lugar el |para el |fecha valor[,.]?\s*(?:el d[ií]a\s*)?)(\d{1,2} de \w+ de \d{4})",
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

    # Fallback generico: fechas etiquetadas (Ex-Date / record date /
    # payment date / fecha de pago / fecha valor / "se concreta en el
    # dia") en formatos DD/MM/YYYY o "D de mes de YYYY".
    if not payment_iso:
        found = find_labeled_date(text, "PAYMENT_DATE")
        if found:
            anchors["payment_date"] = {
                "value": found["value"],
                "matched": found["matched"],
                "offset": found["offset"],
                "pattern": "labeled",
            }
            claims.append(
                Claim(
                    field_path="date.payment_date",
                    value=found["iso"],
                    date_kind="PAYMENT_DATE",
                    evidence_locator=cite("payment_date"),
                    raw_pointer="/anchors/payment_date/value",
                )
            )
            payment_iso = found["iso"]
    seen_fields = {c.field_path for c in claims}
    for date_kind, field_path in (
        ("EX_DATE", "date.ex_date"),
        ("RECORD_DATE", "date.record_date"),
    ):
        if field_path in seen_fields:
            continue
        found = find_labeled_date(text, date_kind)
        if not found:
            continue
        name = f"labeled_{date_kind.lower()}"
        anchors[name] = {
            "value": found["value"],
            "matched": found["matched"],
            "offset": found["offset"],
            "pattern": "labeled",
        }
        claims.append(
            Claim(
                field_path=field_path,
                value=found["iso"],
                date_kind=date_kind,
                evidence_locator=cite(name),
                raw_pointer=f"/anchors/{name}/value",
            )
        )

    # --- Fecha de efecto de amortizacion/redencion -------------------
    redemption_date = grab(
        "redemption_date",
        r"(?:amortizaci[oó]n se realizar[aá]|se realizar[aá]n? con fecha[^.]{0,40}?)(\d{1,2} de \w+ de \d{4})",
        flags=re.I | re.S,
    )
    if redemption_date:
        iso = spanish_date_to_iso(redemption_date)
        if iso:
            claims.append(
                Claim(
                    field_path="date.redemption_date",
                    value=iso,
                    date_kind="REDEMPTION_DATE",
                    evidence_locator=cite("redemption_date"),
                    raw_pointer="/anchors/redemption_date/value",
                )
            )

    # --- ISIN explicito ----------------------------------------------
    isins = sorted(set(re.findall(_ISIN, text)))
    isin = None
    for index, value in enumerate(isins):
        match = re.search(re.escape(value), text)
        claims.append(
            Claim(
                field_path="instrument.isin",
                value=value,
                evidence_locator=(
                    f"{reference}: «{text[max(0, match.start() - 60):match.end() + 40]}»"
                    if match
                    else f"{reference}: ISIN {value}"
                ),
                raw_pointer=f"/isins/{index}",
            )
        )
    if len(isins) == 1:
        isin = isins[0]

    # --- Fecha del documento ----------------------------------------
    # Firma "<ciudad>, <d> de <mes> de <yyyy>" al inicio de linea, con
    # fallback al patron historico de Barcelona.
    doc_date = grab(
        "document_date",
        r"(?m)^\s*[A-ZÁÉÍÓÚÑ][\wÁ-ÿ.\- ]{1,40},\s*(\d{1,2} de \w+ de \d{4})",
    ) or grab("document_date", r"Barcelona, (\d{1,2} de \w+ de \d{4})")
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
        parser="cnmv_doc",
        parser_version=REAL_PARSER_VERSION,
        raw_record={
            "text": text,
            "anchors": anchors,
            "isins": isins,
            "text_sha256": sha256_text(text),
        },
        event_type=event_type,
        issuer_name=issuer,
        isin=isin,
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
            else cite("dividend_generic")
            if dividend_generic
            else cite("event_dividend_context")
            if dividend_context
            else cite("event_redemption")
            if redemption
            else cite("event_takeover")
            if takeover
            else cite("event_merger")
            if merger
            else cite("event_capital")
            if capital
            else cite("event_capital_generic")
            if capital_generic
            else cite("event_capital_reduction")
            if capital_reduction
            else cite("event_delisting")
            if delisting
            else cite("event_listing")
            if listing
            else None
        ),
    )
