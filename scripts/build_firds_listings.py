"""Genera ESMA_FIRDS_LISTINGS_V1 desde evidencia FIRDS real.

Este generador pertenece a la capa ESMA externa (ADR-006). ca-es NO
reconstruye FIRDS; consume el artefacto resultante.

- Consulta el core Solr `esma_registers_firds` por ISIN.
- Conserva la respuesta cruda en g0/corpus/raw/esma/ (LOCAL_ONLY) con
  SHA-256 en g0/manifests/firds-acquisition.json.
- Emite g0/corpus/reference/esma-firds-listings-real.json (derivado,
  redistribuible con atribucion).

    python scripts/build_firds_listings.py --generated-at 2026-09-13T00:00:00Z
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ca_es.canonical import sha256_bytes  # noqa: E402

SOLR = "https://registers.esma.europa.eu/solr/esma_registers_firds/select"
FIELDS = (
    "isin,mic,rca_mic,lei,gnr_full_name,gnr_cfi_code,mrkt_trdng_start_date,"
    "mrkt_trdng_trmination_date,status,latest_received_flag,never_published_flag,"
    "valid_from_date,published_from_date"
)
ARTIFACT_VERSION = "ESMA_FIRDS_LISTINGS_V1"
OPEN_ENDED_SENTINEL = "9999-12-31"


def _get(isin: str) -> dict:
    params = urllib.parse.urlencode(
        {"q": f"isin:{isin}", "rows": "400", "wt": "json", "fl": FIELDS}
    )
    request = urllib.request.Request(
        f"{SOLR}?{params}", headers={"User-Agent": "ca-es/0.1 (G0-R)"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def _date(value: str | None) -> str | None:
    if not value:
        return None
    day = value[:10]
    return None if day == OPEN_ENDED_SENTINEL else day


def _listings_from_docs(docs: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    listings: list[dict] = []
    for doc in docs:
        if str(doc.get("latest_received_flag")) != "1":
            continue
        if str(doc.get("never_published_flag")) == "1":
            continue
        admission = _date(doc.get("mrkt_trdng_start_date")) or _date(
            doc.get("valid_from_date")
        )
        segment_mic = doc.get("mic")
        if not admission or not segment_mic:
            continue
        termination = _date(doc.get("mrkt_trdng_trmination_date"))
        key = (doc["isin"], segment_mic, admission, termination)
        if key in seen:
            continue
        seen.add(key)
        listings.append(
            {
                "isin": doc["isin"],
                "lei": doc.get("lei"),
                "segment_mic": segment_mic,
                "operating_mic": doc.get("rca_mic"),
                "venue_name": None,
                "admission_date": admission,
                "termination_date": termination,
                "regulatory_lei_role": None,
                "firds_status": doc.get("status"),
                "cfi_code": doc.get("gnr_cfi_code"),
            }
        )
    return sorted(listings, key=lambda item: (item["isin"], item["segment_mic"], item["admission_date"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument(
        "--queries", type=Path, default=Path("g0/manifests/firds-queries.json")
    )
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    queries = json.loads((root / args.queries).read_text(encoding="utf-8"))

    raw_dir = root / "g0/corpus/raw/esma"
    raw_dir.mkdir(parents=True, exist_ok=True)
    acquisition: list[dict] = []
    all_listings: list[dict] = []
    for entry in queries["queries"]:
        isin = entry["isin"]
        payload = _get(isin)
        raw_path = raw_dir / f"{isin}.json"
        raw_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        raw_path.write_bytes(raw_bytes)
        docs = payload.get("response", {}).get("docs", [])
        acquisition.append(
            {
                "isin": isin,
                "label": entry.get("label"),
                "solr_core": queries["solr_core"],
                "raw_relpath": f"g0/corpus/raw/esma/{isin}.json",
                "sha256": sha256_bytes(raw_bytes),
                "num_found": payload.get("response", {}).get("numFound"),
                "docs_returned": len(docs),
            }
        )
        all_listings.extend(_listings_from_docs(docs))

    artifact = {
        "artifact_version": ARTIFACT_VERSION,
        "source": "ESMA_FIRDS",
        "generated_at": args.generated_at,
        "extraction": {
            "solr_core": queries["solr_core"],
            "query_template": "isin:{isin}",
            "fields": FIELDS.split(","),
            "filter": "latest_received_flag==1 and never_published_flag!=1",
            "open_ended_sentinel": OPEN_ENDED_SENTINEL,
        },
        "listings": all_listings,
    }
    out = root / "g0/corpus/reference/esma-firds-listings-real.json"
    out.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "g0/manifests/firds-acquisition.json").write_text(
        json.dumps(
            {
                "manifest_version": "CA_ES_FIRDS_ACQUISITION_V1",
                "generated_at": args.generated_at,
                "records": acquisition,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"listings": len(all_listings), "out": str(out)}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
