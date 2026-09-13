"""Genera PORTFOLIO_INSTRUMENTS_V1 desde la ficha oficial de Portfolio.

Relacion exacta documento -> instrumento usando la propia estructura de
la fuente (ruta canonica + JSON-LD FinancialProduct + lista de documentos
del producto). No usa nombre para enlazar.

    python scripts/build_portfolio_instruments.py --generated-at 2026-09-13T00:00:00Z
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ca_es.canonical import sha256_bytes  # noqa: E402

ARTIFACT_VERSION = "PORTFOLIO_INSTRUMENTS_V1"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9",
}
PRODUCTS = (
    {
        "url": "https://portfolio.exchange/es/portfolio-market/p3-spain-logistic-parks-socimi-PSLP-ES0105282000-5",
        "instrument": "ES0105282000",
    },
)


def _jsonld(ficha: str) -> dict:
    marker = 'data-hid="structured-data-market-product"'
    end = ficha.find(marker)
    start = ficha.rfind("<script", 0, end)
    tag = ficha[start:end]
    children = re.search(r'children="([^"]*)"', tag, re.S)
    if not children:
        return {}
    return json.loads(html_mod.unescape(children.group(1)))


def _financial_product(data: dict) -> dict:
    for node in data.get("@graph", []):
        if node.get("@type") == "FinancialProduct":
            identifiers = {
                item.get("propertyID"): item.get("value")
                for item in node.get("identifier", [])
            }
            return {"name": node.get("name"), "category": node.get("category"), **identifiers}
    return {}


def _issuer(data: dict) -> dict:
    for node in data.get("@graph", []):
        if node.get("@type") == "Organization" and node.get("@id", "").endswith("#issuer"):
            return {
                item.get("propertyID"): item.get("value")
                for item in node.get("identifier", [])
            }
    return {}


def build(product: dict) -> tuple[dict, bytes]:
    request = urllib.request.Request(
        product["url"], headers={**HEADERS, "Referer": "https://portfolio.exchange/"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = response.read()
    ficha = payload.decode("utf-8", "replace")
    # La lista de documentos de la app Nuxt viene con separadores escapados.
    flat = ficha.replace("\\u002F", "/").replace("\\u002f", "/")
    data = _jsonld(ficha)
    fp = _financial_product(data)
    issuer = _issuer(data)
    product_ids = sorted(set(re.findall(r'"product-(\d+)-', ficha)))
    document_ids = sorted(
        {int(doc) for doc in re.findall(r"poex/document/(\d+)", flat)}
    )
    instrument = {
        "isin": fp.get("ISIN"),
        "ticker": fp.get("Ticker"),
        "name": fp.get("name"),
        "category": fp.get("category"),
        "nif": issuer.get("NIF"),
        "lei": issuer.get("LEI"),
        "product_id": product_ids[0] if product_ids else None,
        "canonical_url": product["url"],
        "document_ids": document_ids,
    }
    return instrument, payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--generated-at", required=True)
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()

    raw_dir = root / "g0/corpus/raw/portfolio"
    raw_dir.mkdir(parents=True, exist_ok=True)
    instruments: list[dict] = []
    document_bindings: dict[str, str] = {}
    acquisition: list[dict] = []
    for product in PRODUCTS:
        instrument, payload = build(product)
        raw_path = raw_dir / "p3-product.html"
        raw_path.write_bytes(payload)
        instrument["snapshot_sha256"] = sha256_bytes(payload)
        instruments.append(instrument)
        for document_id in instrument["document_ids"]:
            document_bindings[f"PORTFOLIO-{document_id}"] = instrument["isin"]
        acquisition.append(
            {
                "url": product["url"],
                "raw_relpath": "g0/corpus/raw/portfolio/p3-product.html",
                "sha256": instrument["snapshot_sha256"],
            }
        )

    artifact = {
        "artifact_version": ARTIFACT_VERSION,
        "source": "PORTFOLIO_STOCK_EXCHANGE",
        "generated_at": args.generated_at,
        "extraction": {
            "structured_data": "application/ld+json FinancialProduct + document list",
            "document_binding": "PORTFOLIO-<document_id> -> isin",
        },
        "instruments": instruments,
        "document_bindings": document_bindings,
    }
    out = root / "g0/corpus/reference/portfolio-instruments.json"
    out.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "g0/manifests/portfolio-acquisition.json").write_text(
        json.dumps(
            {"manifest_version": "CA_ES_PORTFOLIO_ACQUISITION_V1", "records": acquisition},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"instruments": len(instruments), "documents": len(document_bindings)}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
