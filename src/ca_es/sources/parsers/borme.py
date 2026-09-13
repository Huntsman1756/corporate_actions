"""Parser BOE / BORME.

Dos modos:
  - `text/html`: documento real del BORME (extraccion por anclas).
  - JSON estructurado: fixture (parser generico).
"""
from __future__ import annotations

import re

from ...canonical import sha256_text, strict_json_loads
from ...numeric import FinancialAmount
from ...source_policy import SourcePolicy
from ..documents import SourceDocument
from .base import (
    Claim,
    EntitlementBasis,
    InfrastructureClaim,
    ParsedDocument,
    parse_structured,
)
from .html_text import anchor, decode, html_to_text, spanish_date_to_iso

SOURCE_ID = "BOE_BORME"
REAL_PARSER_VERSION = "CA_ES_BORME_HTML_V1"

_AMOUNT = r"([\d.]+(?:,\d+)?)"


def parse(
    payload: bytes, document: SourceDocument, policy: dict[str, SourcePolicy]
) -> ParsedDocument:
    if document.source_id != SOURCE_ID:
        raise ValueError(f"parser BORME recibio fuente {document.source_id}")
    if document.media_type.startswith("text/html"):
        return _parse_html(payload, document)
    raw = strict_json_loads(payload.decode("utf-8"))
    return parse_structured(raw, document, policy, parser_name="borme")


def _parse_html(payload: bytes, document: SourceDocument) -> ParsedDocument:
    text = html_to_text(decode(payload))
    anchors: dict[str, dict] = {}

    def grab(name: str, pattern: str, *, group: int = 1, flags: int = 0) -> str | None:
        found = anchor(text, pattern, group=group, flags=flags)
        if found is not None:
            anchors[name] = found
            return found["value"]
        return None

    reference = document.official_document_id

    def cite(name: str) -> str:
        matched = anchors[name]["matched"]
        return f"{reference}: «{matched[:200]}»"

    claims: list[Claim] = []

    grab("event", r"reconocimiento del derecho de suscripción preferente", flags=0)
    event_type = "RIGHTS_ISSUE" if "event" in anchors else "UNKNOWN"

    def add_amount(name: str, field_path: str, pattern: str) -> None:
        value = grab(name, pattern)
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

    add_amount("nominal_max", "amount.nominal_issue_max", rf"importe nominal máximo del Aumento de Capital es de {_AMOUNT} euros")
    add_amount("nominal_per_share", "amount.nominal_per_share", rf"de {_AMOUNT} euros de valor nominal cada una")
    add_amount("premium_total_max", "amount.issue_premium_total_max", rf"prima de emisión ascendente, en su globalidad, a un máximo de {_AMOUNT} euros")
    add_amount("premium_per_share", "amount.issue_premium_per_share", rf"a razón de {_AMOUNT} euros por cada nueva acción")
    add_amount("issue_price", "amount.issue_price_per_share", rf"tipo unitario de emisión es de {_AMOUNT} euros por acción")

    # Ratio publicado como relacion entera exacta (sin inventar decimales).
    ratio_matched = grab(
        "ratio_new",
        r"proporción de (\d+) Nuevas Acciones por cada (\d+) acciones",
        group=0,
    )
    if ratio_matched:
        match = re.match(
            r"proporción de (\d+) Nuevas Acciones por cada (\d+) acciones", ratio_matched
        )
        claims.append(
            Claim(
                field_path="ratio.terms",
                value={
                    "new_shares": int(match.group(1)),
                    "old_shares": int(match.group(2)),
                },
                evidence_locator=cite("ratio_new"),
                raw_pointer="/anchors/ratio_new/matched",
            )
        )

    new_shares_max = grab("new_shares_max", r"hasta ([\d.]+) nuevas acciones ordinarias")
    if new_shares_max:
        claims.append(
            Claim(
                field_path="shares.new_shares_max",
                value=int(new_shares_max.replace(".", "")),
                evidence_locator=cite("new_shares_max"),
                raw_pointer="/anchors/new_shares_max/value",
            )
        )

    announcement = grab("announcement_date", r"Barcelona, (\d{1,2} de \w+ de \d{4})")
    if announcement:
        iso = spanish_date_to_iso(announcement)
        if iso:
            claims.append(
                Claim(
                    field_path="date.announcement_date",
                    value=iso,
                    date_kind="ANNOUNCEMENT_DATE",
                    evidence_locator=cite("announcement_date"),
                    raw_pointer="/anchors/announcement_date/value",
                )
            )

    # Entitlement basis: assertion temporal, nunca atributo estatico.
    eligible = grab("eligible", r"acciones con derecho de suscripción preferente serán ([\d.]+)")
    registered = grab("registered", r"número de acciones inscritas en Iberclear asciende a ([\d.]+)")
    treasury = grab("treasury", r"de las cuales ([\d.]+) se encuentran en autocartera")
    waived = grab("waived", r"correspondientes a ([\d.]+) acciones de su titularidad")
    board_date = grab("board_date", r"reunión celebrada el (\d{1,2} de \w+ de \d{4})")
    basis = None
    if eligible:
        components: dict[str, int] = {}
        if registered:
            components["registered_shares"] = int(registered.replace(".", ""))
        if treasury:
            components["treasury_shares"] = int(treasury.replace(".", ""))
        if waived:
            components["waived_rights_basis_shares"] = int(waived.replace(".", ""))
        asserted_as_of = spanish_date_to_iso(board_date) if board_date else "UNKNOWN"
        basis = EntitlementBasis(
            eligible_shares=int(eligible.replace(".", "")),
            asserted_as_of=asserted_as_of,
            status="SUBJECT_TO_ADJUSTMENT",
            components=components,
            adjustment_rule_present=True,
            evidence_locator=cite("eligible"),
            raw_pointer="/anchors/eligible/value",
        )

    roles: list[InfrastructureClaim] = []
    if grab(
        "iberclear",
        r"registro contable estará atribuido a la Sociedad de Gestión.*?\(\"Iberclear\"\)",
        flags=re.S,
    ):
        roles.append(
            InfrastructureClaim(
                role="ISSUER_CSD",
                entity="IBERCLEAR",
                evidence_locator=cite("iberclear"),
            )
        )
    if grab("bme_growth", r"segmento de negociación BME Growth de BME MTF Equity \(\"BME Growth\"\)"):
        roles.append(
            InfrastructureClaim(
                role="TRADING_VENUE",
                entity="BME Growth",
                evidence_locator=cite("bme_growth") + " (venue name; segment MIC via ESMA/FIRDS)",
            )
        )

    issuer = None
    title = anchor(text, r"BORME-[A-Z]-\d{4}-\d+\s+([^\n]+)", group=1)
    if title:
        issuer = title["value"].strip()

    return ParsedDocument(
        document=document,
        parser="borme_html",
        parser_version=REAL_PARSER_VERSION,
        raw_record={"text": text, "anchors": anchors, "text_sha256": sha256_text(text)},
        event_type=event_type,
        issuer_name=issuer,
        isin=None,
        lei=None,
        claims=tuple(claims),
        references=(),
        infrastructure_roles=tuple(roles),
        entitlement_basis=basis,
        event_type_evidence_locator=(cite("event") if "event" in anchors else None),
    )
