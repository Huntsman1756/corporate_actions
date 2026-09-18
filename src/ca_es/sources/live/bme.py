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

KINDS = (
    "CapitalIncreases", "CapitalReductions", "Dividends",
    "DividendOptions", "Distributions", "Exchanges", "Meetings",
    "Splits", "Takeovers",
)

_DATE_KEYS = (
    "FechaPago", "PaymentDate", "ExDate", "FechaEx", "FechaAnuncio",
    "AnnouncementDate", "Fecha", "Date",
)


def bme_item_date(row: dict) -> str | None:
    for key in _DATE_KEYS:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:10]
    return None


def _normalize(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", text.upper()).strip("-")


def canonical_row_bytes(row: dict) -> bytes:
    """JSON determinista del row fuente: orden estable, sin
    normalizacion semantica de valores."""
    return json.dumps(
        row, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")


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
        try:
            for kind in kinds:
                url = f"{API}/{kind}"
                response = fetch(url, referer=API)
                result.pages_fetched += 1
                payload = json.loads(response.content)
                rows = payload if isinstance(payload, list) else (
                    payload.get("results") or payload.get("data") or [])
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    day = bme_item_date(row)
                    isin = (row.get("ISIN") or row.get("Isin")
                            or row.get("isin") or "")
                    if isin:
                        doc_id = f"BMEG-{kind}-{isin}-{day or 'NA'}"
                    else:
                        doc_id = (
                            f"BMEG-{kind}-"
                            f"{_normalize(str(row.get('Emisor') or row.get('Nombre') or 'UNK'))[:24]}"
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
                        inline_content=canonical_row_bytes(row),
                        media_type="application/json"))
        except Exception as exc:  # noqa: BLE001 — aislado por fuente
            result.error = f"{exc.__class__.__name__}:{exc}"[:300]
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
