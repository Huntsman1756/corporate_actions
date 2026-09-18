"""Adapter CNMV OIR/IP (P9).

Mecanica probada en G1 (build_g1_frame.enumerate_cnmv_portal) y en
scripts/fetch_cnmv.py: listados ``resultado-{portal}.aspx`` GET por
ventana de fechas + paginacion page=N; identidad = numero de registro
oficial; retrieval del documento por su locator. Una sola
implementacion: ``scripts/fetch_cnmv.py`` reexporta este modulo.
"""
from __future__ import annotations

import html as html_mod
import re
import urllib.request
from dataclasses import dataclass, field
from datetime import date, timedelta

from .http import build_opener, make_fetcher

HOME = "https://www.cnmv.es/portal/home.aspx"

PORTALS = {
    "oir": {
        "surface_id": "OIR",
        "page": "https://www.cnmv.es/portal/Otra-Informacion-Relevante/"
                "Consulta-OIR.aspx",
        "resultado": "https://www.cnmv.es/portal/"
                     "otra-informacion-relevante/resultado-oir.aspx"
                     "?fechaDesde={desde}&fechaHasta={hasta}&page={page}",
        "doc_prefix": "CNMV-OIR",
    },
    "ip": {
        "surface_id": "IP",
        "page": "https://www.cnmv.es/portal/Informacion-Privilegiada/"
                "Consulta-IP.aspx",
        "resultado": "https://www.cnmv.es/portal/"
                     "informacion-privilegiada/resultado-ip.aspx"
                     "?fechaDesde={desde}&fechaHasta={hasta}&page={page}",
        "doc_prefix": "CNMV-IP",
    },
}

_ROW_SPLIT = re.compile(
    r'id="[^"]*repListaPrincipal_(ctl\d+)_elementoPrimerNivel"')


def _clean(fragment: str) -> str:
    return re.sub(
        r"\s+", " ",
        html_mod.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def extract_results(html: str) -> list[dict]:
    """Filas del listado resultado-*: registro, fecha, emisor,
    categoria, titulo, document_url, relaciones oficiales."""
    text = re.sub(r"(?is)<script.*?</script>", " ", html)
    parts = _ROW_SPLIT.split(text)
    results: list[dict] = []
    for index in range(1, len(parts), 2):
        control, body = parts[index], parts[index + 1]
        record: dict = {"control": control}

        def grab(pattern: str, group: int = 1) -> str | None:
            match = re.search(pattern, body, re.I | re.S)
            return match.group(group) if match else None

        record["date"] = grab(
            r"liFechaRegistro[^>]*>\s*([0-9]{2}/[0-9]{2}/[0-9]{4})")
        record["time"] = grab(r"liHora[^>]*>\s*([0-9]{2}:[0-9]{2})")
        record["issuer"] = grab(
            r"spanTituloCabecera[^>]*>([^<]+)</span>")
        record["category"] = grab(
            r"descripcionSubtituloCabecera[^>]*>([^<]+)</span>")
        title = re.search(
            r"subtituloRegistroEnlace\"[^>]*href=\"([^\"]+)\"[^>]*>"
            r"\s*<span[^>]*>(.*?)</span>",
            body, re.I | re.S)
        if title:
            record["document_url"] = html_mod.unescape(title.group(1))
            record["title"] = _clean(title.group(2))
        else:
            link = re.search(
                r"subtituloRegistroEnlace\"[^>]*href=\"([^\"]+)\"[^>]*>"
                r"(.*?)</a>",
                body, re.I | re.S)
            if link:
                record["document_url"] = html_mod.unescape(link.group(1))
                record["title"] = _clean(link.group(2))
        record["registration_number"] = grab(
            r"N[uú]mero de registro:\s*([0-9]+)")
        record["related"] = [
            {"url": href, "text": _clean(text)}
            for href, text in re.findall(
                r'href="([^"]+)"[^>]*>'
                r'([^<]*Relacionado con la comunicaci[^<]*)</a>',
                body, re.I)
        ]
        if record.get("title") or record.get("date"):
            results.append(record)
    return results


def paginate_links(html: str) -> list[str]:
    return sorted(set(
        html_mod.unescape(link)
        for link in re.findall(
            r'href="([^"]*resultado-[a-z]+\.aspx\?[^"]*page=[0-9]+[^"]*)"',
            html, re.I)))


def max_page(html: str) -> int:
    out = 0
    for link in paginate_links(html):
        match = re.search(r"page=(\d+)", link)
        if match:
            out = max(out, int(match.group(1)))
    return out


def dmy(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y}"


def iso_from_dmy(value: str | None) -> str | None:
    if not value:
        return None
    d, m, y = value.split("/")
    return f"{y}-{m}-{d}"


def month_chunks(dfrom: date, dto: date) -> list[tuple[date, date]]:
    chunks = []
    year, month = dfrom.year, dfrom.month
    while True:
        start = date(year, month, 1)
        nxt = date(year + 1, 1, 1) if month == 12 else date(
            year, month + 1, 1)
        end = date.fromordinal(nxt.toordinal() - 1)
        chunk = (max(start, dfrom), min(end, dto))
        if chunk[0] > chunk[1]:
            break
        chunks.append(chunk)
        if end >= dto:
            break
        year, month = nxt.year, nxt.month
    return chunks


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


class CnmvAdapter:
    """Enumeracion de un portal CNMV (OIR o IP) por ventana mensual."""

    source_id = "CNMV"

    def __init__(self, portal: str):
        if portal not in PORTALS:
            raise ValueError(f"portal CNMV desconocido: {portal}")
        self.portal = portal
        self.cfg = PORTALS[portal]

    @property
    def surface_id(self) -> str:
        return self.cfg["surface_id"]

    def discover(self, fetch, *, desde: str, hasta: str,
                 overlap_days: int = 0,
                 checkpoint: dict | None = None) -> DiscoveryResult:
        """Enumera el registro completo del portal en [desde, hasta].

        ``checkpoint.last_publication_date`` + ``overlap_days`` permite
        ventanas solapadas: nunca ``last+1s``."""
        result = DiscoveryResult()
        cursor = (checkpoint or {}).get("cursor") or {}
        last_pub = cursor.get("last_publication_date")
        dfrom = date.fromisoformat(desde)
        if last_pub:
            overlap = date.fromisoformat(last_pub) - timedelta(
                days=overlap_days)
            dfrom = max(dfrom, overlap)
        dto = date.fromisoformat(hasta)
        if dfrom > dto:
            result.cursor = dict(cursor)
            return result

        seen: set[str] = set()
        latest_pub: str | None = last_pub
        try:
            for start, end in month_chunks(dfrom, dto):
                template = self.cfg["resultado"]
                page0 = fetch(
                    template.format(
                        desde=dmy(start.isoformat()),
                        hasta=dmy(end.isoformat()), page=0),
                    referer=self.cfg["page"])
                html = page0.content.decode("utf-8", "replace")
                rows = extract_results(html)
                result.pages_fetched += 1
                chunk_max = max_page(html)
                result.max_page += chunk_max
                for page in range(1, chunk_max + 1):
                    page_result = fetch(
                        template.format(
                            desde=dmy(start.isoformat()),
                            hasta=dmy(end.isoformat()), page=page),
                        referer=self.cfg["page"])
                    page_rows = extract_results(
                        page_result.content.decode("utf-8", "replace"))
                    result.pages_fetched += 1
                    if not page_rows:
                        break
                    rows.extend(page_rows)
                for row in rows:
                    reg = row.get("registration_number")
                    if not reg:
                        result.dropped_no_identity += 1
                        continue
                    doc_id = f"{self.cfg['doc_prefix']}-{reg}"
                    if doc_id in seen:
                        continue
                    seen.add(doc_id)
                    pub = iso_from_dmy(row.get("date"))
                    if pub and (latest_pub is None or pub > latest_pub):
                        latest_pub = pub
                    result.documents.append(DiscoveredDoc(
                        source_document_id=doc_id,
                        locator=row.get("document_url"),
                        publication_date=pub,
                        metadata={
                            "registration_number": reg,
                            "portal": self.portal,
                            "issuer": row.get("issuer"),
                            "category": row.get("category"),
                            "title": row.get("title"),
                            "time": row.get("time"),
                            "related": row.get("related") or [],
                        }))
        except Exception as exc:  # noqa: BLE001 — aislado por fuente
            result.error = f"{exc.__class__.__name__}:{exc}"[:300]
            result.complete = False
        result.cursor = {
            "last_publication_date": latest_pub,
            "window_days": overlap_days,
            "documents_seen": len(seen),
        }
        return result


def live_fetcher(portal: str, *, timeout: int = 90, retries: int = 3,
                 politeness: float = 0.35,
                 max_bytes: int | None = None):
    """Fetcher urllib con sesion CNMV caliente (cookiejar del home)."""
    opener = build_opener(HOME)
    kwargs = {"timeout": timeout, "retries": retries,
              "politeness": politeness}
    if max_bytes is not None:
        kwargs["max_bytes"] = max_bytes
    return make_fetcher(opener, **kwargs)


# --- compat: la superficie historica de scripts/fetch_cnmv.py ------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,"
              "application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


def fetch_document(opener, url: str, out_dir, name: str) -> dict:
    """Compat historica con scripts/fetch_cnmv.py (mismo contrato)."""
    import hashlib
    from pathlib import Path

    request = urllib.request.Request(
        url, headers={**HEADERS, "Referer": PORTALS["ip"]["page"]})
    with opener.open(request, timeout=90) as response:
        payload = response.read()
        content_type = response.headers.get("Content-Type", "")
    extension = "pdf" if "pdf" in content_type else "html"
    path = Path(out_dir) / f"{name}.{extension}"
    path.write_bytes(payload)
    return {
        "path": str(path),
        "content_type": content_type,
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
