"""Parser BME Growth (rows JSON oficiales de la API de corporate actions).

La fuente es la tabla oficial "Operaciones financieras" de BME Growth
(fuente declarada: emisora). Cada raw document es una fila canonizada de
la API: ``{frame_item_id, official_category, issuer_raw,
instrument_isin, publication_date, metadata{...}}``.

Regla: transcribir, nunca promocionar. Cada claim conserva el lexema
exacto del campo y un ``raw_pointer`` verificable a ``/metadata/*``.
Las fechas ``YYYYMMDD`` se serializan ISO (conversion explicita, no
inferencia). Una fila no implica una unica CA canonica: la identidad la
resuelve el pipeline.
"""
from __future__ import annotations

from ...canonical import strict_json_loads
from ...numeric import FinancialAmount
from ...source_policy import SourcePolicy
from ..documents import SourceDocument
from .base import Claim, ParsedDocument

SOURCE_ID = "BME_GROWTH"
PARSER_NAME = "bme_growth_row"
PARSER_VERSION = "CA_ES_BME_GROWTH_ROW_V1"

_EVENT_TYPE = {
    "Dividends": "CASH_DIVIDEND",
    "CapitalIncreases": "CAPITAL_INCREASE",
    "Splits": "SPLIT",
    # BME "Mergers" publica factores de canje + splitDate: es la tabla de
    # contrasplits/agrupaciones. La categoria cruda se preserva en
    # source.official_category.
    "Mergers": "SPLIT",
    "NewListings": "NEW_LISTING",
    "Delistings": "DELISTING",
    "OtherPayments": "OTHER_PAYMENT",
    "TakeoverBids": "TAKEOVER_BID",
    "PublicOfferings": "PUBLIC_OFFERING",
}

_DATE_FIELDS = {
    "exDate": "date.ex_date",
    "paymentDate": "date.payment_date",
    "dividendDate": "date.dividend_date",
    "admissionDate": "date.admission_date",
    "splitDate": "date.split_effective_date",
    "startingDate": "date.period_start",
    "finishDate": "date.period_end",
    "acquiredDate": "date.offer_result_date",
    "cancellationDate": "date.cancellation_date",
    "profitDate": "date.profit_date",
}

_DATE_KIND = {
    "date.ex_date": "EX_DATE",
    "date.payment_date": "PAYMENT_DATE",
    "date.admission_date": "ADMISSION_DATE",
}

_AMOUNT_FIELDS = {
    "grossAmount": "amount.gross_per_share",
    "netAmount": "amount.net_per_share",
    "effectiveAmount": "amount.effective_total",
    "price": "amount.price",
    "disbursement": "amount.disbursement_per_share",
    "nominalAmount": "amount.nominal_total",
    "nominal": "amount.nominal",
    "turnover": "amount.turnover",
    "liberatedPercentage": "amount.liberated_percentage",
    "rightsPrice": "amount.rights_price",
}

_INT_FIELDS = {
    "shares": "shares.total",
    "newShares": "shares.new_shares",
    "oldShares": "shares.old_shares",
    "numShares": "shares.num_shares",
    "acquiredShares": "shares.acquired",
    "tradingUnit": "shares.trading_unit",
    "multiplyingFactor": "ratio.multiplying_factor",
    "dividingFactor": "ratio.dividing_factor",
    "numSeq": "source.num_seq",
}

_TEXT_FIELDS = {
    "observations": "source.observations",
    "observ": "source.observations",
    "typeDescription": "source.type_description",
    "conceptText": "dividend.concept",
    "typeText": "dividend.type",
    "year": "dividend.year",
    "naturDescription": "source.nature",
    "admissionType": "source.admission_type",
    "priceText": "takeover.price_text",
    "result": "takeover.result",
    "offeringCompanyName": "takeover.offering_company",
    "companyName": "takeover.target_company",
    "lastISIN": "instrument.last_isin",
    "currency": "instrument.currency",
    "relevantFactCode": "source.relevant_fact_code",
    "origin": "source.origin",
    "marketCode": "source.market_code",
    "concept": "source.concept_code",
    "type": "source.type_code",
    "class": "source.class_code",
    "rightsIndicator": "source.rights_indicator",
    "typeIndicator": "source.type_indicator",
    "subgroupIndicator": "source.subgroup_indicator",
    "naturIndicator": "source.nature_indicator",
    "cancellationText": "takeover.cancellation_text",
    "companyShortName": "source.company_short_name",
    "companyTradingSystem": "source.company_trading_system",
    "companyKey": "source.company_key",
}


def _yyyymmdd(value: str) -> str | None:
    """'20250701' -> '2025-07-01'. Conversion explicita, sin inferencia."""
    if len(value) != 8 or not value.isdigit():
        return None
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def parse(
    payload: bytes, document: SourceDocument, policy: dict[str, SourcePolicy]
) -> ParsedDocument:
    if document.source_id != SOURCE_ID:
        raise ValueError(f"parser BME_GROWTH recibio fuente {document.source_id}")
    raw = strict_json_loads(payload.decode("utf-8"))
    metadata = raw.get("metadata") or {}
    category = raw.get("official_category") or metadata.get("category") or "UNKNOWN"

    claims: list[Claim] = [
        Claim(
            field_path="source.official_category",
            value=category,
            evidence_locator=f"{document.official_document_id}: official_category={category}",
            raw_pointer="/official_category",
        )
    ]

    for field, field_path in sorted(_TEXT_FIELDS.items()):
        value = metadata.get(field)
        if isinstance(value, str) and value.strip():
            claims.append(
                Claim(
                    field_path=field_path,
                    value=value.strip(),
                    evidence_locator=(
                        f"{document.official_document_id}: {field}={value.strip()[:120]}"
                    ),
                    raw_pointer=f"/metadata/{field}",
                )
            )

    for field, field_path in sorted(_DATE_FIELDS.items()):
        value = metadata.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        iso = _yyyymmdd(value.strip())
        if iso is None:
            continue
        claims.append(
            Claim(
                field_path=field_path,
                value=iso,
                date_kind=_DATE_KIND.get(field_path),
                evidence_locator=(
                    f"{document.official_document_id}: {field}={value.strip()}"
                ),
                raw_pointer=f"/metadata/{field}",
            )
        )

    currency = metadata.get("currency") or None
    for field, field_path in sorted(_AMOUNT_FIELDS.items()):
        value = metadata.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            amount = FinancialAmount.parse(value.strip(), currency=currency)
        except ValueError:
            # Importes no parseables (p.ej. priceText compuesto) quedan
            # como claim textual, nunca reinterpretados.
            claims.append(
                Claim(
                    field_path=f"{field_path}.raw",
                    value=value.strip(),
                    evidence_locator=(
                        f"{document.official_document_id}: {field}={value.strip()[:120]}"
                    ),
                    raw_pointer=f"/metadata/{field}",
                )
            )
            continue
        claims.append(
            Claim(
                field_path=field_path,
                value=amount,
                currency=currency,
                evidence_locator=(
                    f"{document.official_document_id}: {field}={value.strip()}"
                ),
                raw_pointer=f"/metadata/{field}",
            )
        )

    for field, field_path in sorted(_INT_FIELDS.items()):
        value = metadata.get(field)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, int):
            number = value
        elif isinstance(value, str) and value.strip().isdigit():
            number = int(value.strip())
        else:
            continue
        claims.append(
            Claim(
                field_path=field_path,
                value=number,
                evidence_locator=(
                    f"{document.official_document_id}: {field}={value}"
                ),
                raw_pointer=f"/metadata/{field}",
            )
        )

    if category == "CapitalIncreases" and metadata.get("rightsIndicator") == "S":
        event_type = "RIGHTS_ISSUE"
    else:
        event_type = _EVENT_TYPE.get(category, "UNKNOWN")

    isin = metadata.get("isin") or raw.get("instrument_isin")
    if isinstance(isin, str) and isin.strip():
        claims.append(
            Claim(
                field_path="instrument.isin",
                value=isin.strip(),
                evidence_locator=f"{document.official_document_id}: isin={isin.strip()}",
                raw_pointer="/metadata/isin",
            )
        )
        isin = isin.strip()
    else:
        isin = None

    issuer = (
        metadata.get("issuerName")
        or metadata.get("company")
        or metadata.get("companyName")
        or metadata.get("share")
        or raw.get("issuer_raw")
    )

    return ParsedDocument(
        document=document,
        parser=PARSER_NAME,
        parser_version=PARSER_VERSION,
        raw_record=raw,
        event_type=event_type,
        issuer_name=issuer.strip() if isinstance(issuer, str) and issuer.strip() else None,
        isin=isin,
        lei=None,
        claims=tuple(claims),
        references=(),
        infrastructure_roles=(),
        entitlement_basis=None,
        event_type_evidence_locator=(
            f"{document.official_document_id}: official_category={category}"
            if event_type != "UNKNOWN"
            else None
        ),
    )
