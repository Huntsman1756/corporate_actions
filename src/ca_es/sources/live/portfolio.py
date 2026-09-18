"""Adapter Portfolio Stock Exchange (P9).

Enumeracion probada en G1/G1-R2: index de productos -> pagina de
producto -> documentos ``/poex/document/{id}``. Cobertura
ENUMERABLE_WITH_LIMITATIONS: solo productos visibles en el index.
La ausencia de un item en un snapshot no implica desaparicion (sin
politica de desaparicion prerregistrada).
"""
from __future__ import annotations

import html as html_mod
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

INDEX_URL = "https://www.portfolio.exchange/markets/portfolio-market"
DOC_API = "https://api.portfolio.exchange/poex/document/{doc_id}"

_PRODUCT_RE = re.compile(
    r'href="(/markets/portfolio-market/[^"]+)"', re.I)
_DOC_RE = re.compile(
    r'(?:api\.portfolio\.exchange)?/poex/document/(\d+)', re.I)


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


class PortfolioAdapter:
    source_id = "PORTFOLIO_STOCK_EXCHANGE"
    surface_id = "PORTFOLIO_MARKET"

    def discover(self, fetch, *, index_url: str = INDEX_URL,
                 checkpoint: dict | None = None,
                 **_kw) -> DiscoveryResult:
        result = DiscoveryResult()
        seen: set[str] = set()
        try:
            index = fetch(index_url)
            result.pages_fetched += 1
            products = sorted(set(
                html_mod.unescape(u) for u in
                _PRODUCT_RE.findall(
                    index.content.decode("utf-8", "replace"))))
            for product_path in products:
                product_url = (
                    product_path if product_path.startswith("http")
                    else f"https://www.portfolio.exchange{product_path}")
                page = fetch(product_url)
                result.pages_fetched += 1
                html = page.content.decode("utf-8", "replace")
                for doc_id in sorted(set(_DOC_RE.findall(html))):
                    sid = f"POEX-DOC-{doc_id}"
                    if sid in seen:
                        continue
                    seen.add(sid)
                    result.documents.append(DiscoveredDoc(
                        source_document_id=sid,
                        locator=DOC_API.format(doc_id=doc_id),
                        publication_date=None,
                        metadata={
                            "product_path": product_path,
                            "product_url": product_url,
                            "api_document_id": doc_id,
                        }))
        except Exception as exc:  # noqa: BLE001 — aislado por fuente
            result.error = f"{exc.__class__.__name__}:{exc}"[:300]
            result.complete = False
        result.cursor = {
            "last_refresh_at": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"),
            "documents_seen": len(seen),
        }
        return result


def live_fetcher(**kw):
    from .http import make_fetcher

    return make_fetcher(None, **kw)
