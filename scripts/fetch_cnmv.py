"""Cliente de adquisicion CNMV (OIR / Informacion Privilegiada).

Formularios ASP.NET WebForms: se conserva ViewState y cookies, se hace
POST con los campos del buscador y se extraen las filas de resultado.
Adquisicion externa (no es runtime de ca-es).

El parsing de filas/paginacion vive en
``ca_es.sources.live.cnmv`` (P9): este script conserva solo la
mecanica POST de consulta por denominacion/LEI.

    python scripts/fetch_cnmv.py --portal oir --denominacion P3 --out-dir g0/corpus/raw/cnmv/p3
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from ca_es.sources.live.cnmv import (  # noqa: E402
    extract_results, fetch_document, paginate_links)

REPO_ROOT = Path(__file__).resolve().parents[1]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

PORTALS = {
    "oir": {
        "page": "https://www.cnmv.es/portal/Otra-Informacion-Relevante/Consulta-OIR.aspx",
        "post": "https://www.cnmv.es/portal/Otra-Informacion-Relevante/Consulta-OIR",
        "prefix": "ctl00$ContentPrincipal$",
        "denominacion": "wucNombreEntidad$txtDenominacion",
        "lei": "wucCodigoLEI$txtCodigoLEI",
        "desde": "wucFechas$fecha_desde",
        "hasta": "wucFechas$fecha_hasta",
        "dias": "wucFechas$ult_dias",
        "submit": "buttonOk",
    },
    "ip": {
        "page": "https://www.cnmv.es/portal/Informacion-Privilegiada/Consulta-IP.aspx",
        "post": "https://www.cnmv.es/portal/Informacion-Privilegiada/Consulta-IP",
        "prefix": "ctl00$ContentPrincipal$",
        "denominacion": "wucNombreEntidad$txtDenominacion",
        "lei": "wucCodigoLEI$txtCodigoLEI",
        "desde": "wucFechas$fecha_desde",
        "hasta": "wucFechas$fecha_hasta",
        "dias": "wucFechas$ult_dias",
        "submit": "buttonOk",
    },
}


def _hidden_fields(html: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in re.finditer(r"<input[^>]*type=\"hidden\"[^>]*>", html, re.I):
        tag = match.group(0)
        name = re.search(r"name=\"([^\"]+)\"", tag)
        value = re.search(r"value=\"([^\"]*)\"", tag)
        if name:
            fields[name.group(1)] = value.group(1) if value else ""
    return fields


def build_opener() -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = list(HEADERS.items())
    opener.open("https://www.cnmv.es/portal/home.aspx", timeout=30).read()
    return opener


def search(
    portal: str,
    denominacion: str | None = None,
    lei: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    dias: str | None = None,
) -> str:
    cfg = PORTALS[portal]
    opener = build_opener()
    html = opener.open(cfg["page"], timeout=40).read().decode("utf-8", "replace")
    fields = _hidden_fields(html)
    submit = re.search(
        r"<input[^>]*name=\"" + re.escape(cfg["prefix"] + cfg["submit"])
        + r"\"[^>]*value=\"([^\"]*)\"",
        html,
        re.I,
    )
    prefix = cfg["prefix"]
    fields[prefix + cfg["denominacion"]] = denominacion or ""
    fields[prefix + cfg["lei"]] = lei or ""
    fields[prefix + cfg["desde"]] = desde or ""
    fields[prefix + cfg["hasta"]] = hasta or ""
    fields[prefix + cfg["dias"]] = dias or ""
    fields[prefix + cfg["submit"]] = submit.group(1) if submit else "Buscar"
    body = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(
        cfg["post"],
        data=body,
        headers={
            **HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": cfg["page"],
        },
    )
    return opener.open(request, timeout=60).read().decode("utf-8", "replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portal", choices=sorted(PORTALS), required=True)
    parser.add_argument("--denominacion")
    parser.add_argument("--lei")
    parser.add_argument("--desde")
    parser.add_argument("--hasta")
    parser.add_argument("--dias")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--fetch-docs", action="store_true")
    args = parser.parse_args(argv)

    cfg = PORTALS[args.portal]
    opener = build_opener()
    html = search(
        args.portal, args.denominacion, args.lei, args.desde, args.hasta, args.dias
    )
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.save:
        (out_dir / f"{args.portal}-results.html").write_text(html, encoding="utf-8")
    results = extract_results(html)
    if args.pages > 1:
        for link in paginate_links(html)[: args.pages - 1]:
            page_html = opener.open(
                urllib.request.Request(link, headers={**HEADERS, "Referer": cfg["page"]}),
                timeout=60,
            ).read().decode("utf-8", "replace")
            results.extend(extract_results(page_html))
    if args.fetch_docs:
        for result in results:
            url = result.get("document_url")
            if not url:
                continue
            name = f"{args.portal}-{result.get('registration_number') or result.get('date','doc').replace('/','')}".replace(" ", "-")
            result["fetched"] = fetch_document(opener, url, out_dir, name)
    (out_dir / f"{args.portal}-rows.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"portal": args.portal, "results": len(results)}, ensure_ascii=False))
    for result in results[:20]:
        print(
            " ",
            result.get("date"),
            result.get("time"),
            "|reg", result.get("registration_number"),
            "|", (result.get("title") or "")[:80],
            "|related", len(result.get("related", [])),
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
