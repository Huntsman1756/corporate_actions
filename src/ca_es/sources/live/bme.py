"""Adapter BME Growth CorporateActions API (P9).

Superficie probada por los manifests del corpus real
(manifest.securities_sources.urls) y por build_g1_frame.fetch_bme:
endpoint JSON por evento, sin paginacion. Identidad compuesta
``BMEG-{kind}-{isin}-{dia}``. Cada row JSON se conserva como documento
inline byte-exacto (JSON canonizado deterministicamente). Sin cursor
de descubrimiento: re-enumeracion completa.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

API = "https://apiweb.bolsasymercados.es/Market/v1/EQ/CorporateActions"

# Conjunto probado por build_g1_frame.BME_TYPES (corpus G1 real);
# categorias que el endpoint no expone devuelven 404 -> kind_errors,
# nunca abortan el resto.
KINDS = (
    "Dividends", "CapitalIncreases", "Splits", "Mergers",
    "OtherPayments", "NewListings", "Delistings", "PublicOfferings",
    "TakeoverBids",
)

_DATE_KEYS = (
    "exDate", "paymentDate", "dividendDate", "admissionDate",
    "splitDate", "startingDate", "finishDate", "acquiredDate",
    "cancellationDate", "profitDate",
)


def _iso_date(value: str) -> str | None:
    """API devuelve YYYYMMDD; el doc-id usa ISO. Conversion explicita."""
    value = value.strip()
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value[:10] if value else None


def bme_item_date(row: dict) -> str | None:
    for key in _DATE_KEYS:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return _iso_date(value)
    return None


def _normalize(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", text.upper()).strip("-")


def _no_floats(obj: object) -> object:
    """float -> lexema (repr), igual que build_g1_frame.no_floats:
    la API devuelve floats, pero los valores financieros entran al
    canon como raw_lexeme string y ``strict_json_loads`` rechaza
    float en la frontera de parse."""
    if isinstance(obj, float):
        return repr(obj)
    if isinstance(obj, dict):
        return {k: _no_floats(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_no_floats(v) for v in obj]
    return obj


def canonical_row_bytes(row: dict) -> bytes:
    """JSON determinista del row fuente: orden estable; floats se
    serializan como lexema (semantica probada de G1), sin otra
    normalizacion semantica de valores."""
    return json.dumps(
        _no_floats(row), ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")


def frame_row_bytes(doc_id: str, kind: str, row: dict,
                    day: str | None) -> bytes:
    """Documento BME en el formato probado del corpus (el mismo que
    produce G1 y que consume ``sources/parsers/bme_growth.py``):
    ``{frame_item_id, instrument_isin, issuer_raw, metadata,
    official_category, publication_date}``.

    La unidad de evidencia estable para esta fuente es la row
    canonizada (``BME_API_ROW_SNAPSHOT``), no la respuesta entera.
    """
    frame = {
        "frame_item_id": doc_id,
        "instrument_isin": row.get("isin") or row.get("ISIN") or None,
        "issuer_raw": (
            row.get("issuerName") or row.get("Emisor")
            or row.get("issuer") or ""),
        "metadata": row,
        "official_category": kind,
        "publication_date": day,
    }
    return canonical_row_bytes(frame)


@dataclass
class DiscoveredDoc:
    source_document_id: str
    locator: str | None
    publication_date: str | None
    metadata: dict = field(default_factory=dict)
    inline_content: bytes | None = None
    media_type: str | None = None


@dataclass
class DiscoveryResult:
    documents: list[DiscoveredDoc] = field(default_factory=list)
    complete: bool = True
    pages_fetched: int = 0
    max_page: int = 0
    dropped_no_identity: int = 0
    error: str | None = None
    cursor: dict = field(default_factory=dict)


class BmeAdapter:
    source_id = "BME_GROWTH"
    surface_id = "CORPORATE_ACTIONS"

    def discover(self, fetch, *, kinds: tuple[str, ...] = KINDS,
                 checkpoint: dict | None = None,
                 **_kw) -> DiscoveryResult:
        result = DiscoveryResult()
        seen: set[str] = set()
        kind_errors: list[str] = []
        for kind in kinds:
            url = f"{API}/{kind}"
            try:
                response = fetch(url, referer=API)
                result.pages_fetched += 1
                payload = json.loads(response.content)
                rows = payload if isinstance(payload, list) else (
                    payload.get("results") or payload.get("data")
                    or [])
            except Exception as exc:  # noqa: BLE001 — por categoria
                kind_errors.append(
                    f"{kind}:{exc.__class__.__name__}:{exc}"[:200])
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                day = bme_item_date(row)
                isin = (row.get("isin") or row.get("ISIN")
                        or row.get("Isin") or "")
                issuer_raw = (
                    row.get("issuerName") or row.get("Emisor")
                    or row.get("Nombre") or "")
                if isin:
                    doc_id = f"BMEG-{kind}-{isin}-{day or 'NA'}"
                else:
                    doc_id = (
                        f"BMEG-{kind}-"
                        f"{_normalize(str(issuer_raw or 'UNK'))[:24]}"
                        f"-{day or 'NA'}")
                if doc_id in seen:
                    continue
                seen.add(doc_id)
                result.documents.append(DiscoveredDoc(
                    source_document_id=doc_id,
                    locator=url,
                    publication_date=day,
                    metadata={"kind": kind, "isin": isin or None,
                              "api": url},
                    inline_content=frame_row_bytes(
                        doc_id, kind, row, day),
                    media_type="application/json"))
        if kind_errors:
            result.error = "; ".join(kind_errors)[:300]
            result.complete = False
        result.cursor = {
            "last_refresh_at": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"),
            "kinds": list(kinds),
            "documents_seen": len(seen),
        }
        return result


def live_fetcher(**kw):
    from .http import make_fetcher

    return make_fetcher(None, **kw)
