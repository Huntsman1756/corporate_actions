"""Runner G1 DEV: adquisicion de seeds + ejecucion por fase.

Fase A (first-run): mismo parser commit para los 25 seeds, sin cambios
de codigo entre ejecuciones -> g1/results/first-run-results.json.
Fase C (final-run): rerun 25/25 tras desarrollo -> final-run-results.json
preservando first_run_result por seed.

Uso:
    python scripts/run_g1_dev.py --phase first-run
    python scripts/run_g1_dev.py --phase final-run
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from ca_es.canonical import canonical_bytes, sha256_hex  # noqa: E402
from ca_es.pipeline import run_pipeline  # noqa: E402
from ca_es.reference.esma_firds import load_firds_listings  # noqa: E402
from fetch_cnmv import build_opener, fetch_document  # noqa: E402

DEV_HOLDOUT = REPO_ROOT / "g1" / "manifests" / "dev-holdout.json"
FRAME = REPO_ROOT / "g1" / "manifests" / "sampling-frame.json"
MANIFEST_DIR = REPO_ROOT / "g1" / "manifests" / "dev"
RAW_DIR = REPO_ROOT / "g1" / "corpus" / "raw" / "dev"
RESULTS_DIR = REPO_ROOT / "g1" / "results"
INSTRUMENT_BINDINGS = "g0/corpus/reference/portfolio-instruments.json"
FIRDS_LISTINGS = REPO_ROOT / "g0" / "corpus" / "reference" / "esma-firds-listings.json"
EXECUTED_AT = "2026-09-14T00:00:00Z"

SOURCE_ID = {
    "CNMV": "CNMV",
    "POEX": "PORTFOLIO_STOCK_EXCHANGE",
    "BMEG": "BME_GROWTH",
}

MEDIA_TYPE = {
    "pdf": "application/pdf",
    "json": "application/json",
    "html": "text/html",
}


def git_commit() -> tuple[str, bool]:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain", "--", "src/", "scripts/", "docs/"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    return head, dirty


def _safe_name(frame_item_id: str) -> str:
    return frame_item_id.replace("/", "_")


def _bmeg_raw(item: dict) -> bytes:
    row = {
        "frame_item_id": item["frame_item_id"],
        "official_category": item["official_category"],
        "issuer_raw": item["issuer_raw"],
        "instrument_isin": item["instrument_isin"],
        "publication_date": item.get("publication_date"),
        "metadata": item["metadata"],
    }
    return canonical_bytes(row)


def acquire(item: dict, opener) -> dict:
    """Devuelve {raw_relpath, content_sha256, media_type, retrieval_status, url}."""
    frame_item_id = item["frame_item_id"]
    name = _safe_name(frame_item_id)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if frame_item_id.startswith("BMEG-"):
        payload = _bmeg_raw(item)
        path = RAW_DIR / f"{name}.json"
        path.write_bytes(payload)
        import hashlib

        return {
            "raw_relpath": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
            "content_sha256": hashlib.sha256(payload).hexdigest(),
            "media_type": "application/json",
            "retrieval_status": "OK",
            "url": item.get("source_locator"),
            "retrieval_method": "BME_API_ROW_SNAPSHOT",
        }

    url = item.get("source_locator")
    if not url:
        return {
            "raw_relpath": None,
            "content_sha256": None,
            "media_type": None,
            "retrieval_status": "NO_URL",
            "url": None,
            "retrieval_method": None,
        }
    try:
        fetched = fetch_document(opener, url, RAW_DIR, name)
    except Exception as exc:  # noqa: BLE001 - el fallo es el resultado del seed
        return {
            "raw_relpath": None,
            "content_sha256": None,
            "media_type": None,
            "retrieval_status": f"FETCH_FAILED:{type(exc).__name__}",
            "url": url,
            "retrieval_method": "HTTP_GET",
        }
    path = Path(fetched["path"])
    return {
        "raw_relpath": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "content_sha256": fetched["sha256"],
        "media_type": MEDIA_TYPE.get(path.suffix.lstrip("."), fetched["content_type"]),
        "retrieval_status": "OK",
        "url": url,
        "retrieval_method": "HTTP_GET",
    }


def write_manifest(item: dict, acq: dict) -> str:
    frame_item_id = item["frame_item_id"]
    prefix = frame_item_id.split("-")[0]
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "manifest_version": "CA_ES_SOURCE_MANIFEST_V1",
        "corpus_id": f"G1_DEV_{frame_item_id}",
        "retrieved_at": EXECUTED_AT[:10],
        "documents": [
            {
                "source_id": SOURCE_ID[prefix],
                "official_document_id": frame_item_id,
                "content_sha256": acq["content_sha256"],
                "retrieved_at": EXECUTED_AT[:10],
                "publication_date": item.get("publication_date"),
                "media_type": acq["media_type"],
                "raw_relpath": acq["raw_relpath"],
                "synthetic": False,
                "retrieval_status": acq["retrieval_status"],
                "acquisition": {
                    "url": acq["url"],
                    "retrieval_method": acq["retrieval_method"],
                },
                "relations": [],
            }
        ],
    }
    path = MANIFEST_DIR / f"{_safe_name(frame_item_id)}.json"
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return str(path.relative_to(REPO_ROOT)).replace("\\", "/")


def seed_result(item: dict, acq: dict, run: dict | None, exc: str | None) -> dict:
    entry = {
        "frame_item_id": item["frame_item_id"],
        "stratum": item["stratum"],
        "retrieval_status": acq["retrieval_status"],
        "parse_status": None,
        "event_detected": False,
        "facts": {"total": 0, "populated_fields": []},
        "missing": [],
        "unknown": [],
        "conflicts": 0,
        "identity_status": "NONE",
        "exception": exc,
        "result_sha": None,
    }
    if run is None:
        return entry
    entry["result_sha"] = run["result_sha"]
    document = run["documents"][0]
    entry["retrieval_status"] = document["retrieval_status"]
    parse_errors = run.get("parse_errors") or {}
    if document["document_id"] in parse_errors:
        entry["parse_status"] = parse_errors[document["document_id"]]
    elif document["retrieval_status"] != "OK":
        entry["parse_status"] = "SKIPPED:NO_RAW"
    else:
        entry["parse_status"] = "OK"
    events = run["events"]
    entry["event_detected"] = bool(events)
    facts = run["facts"]
    entry["facts"] = {
        "total": len(facts),
        "populated_fields": sorted(
            {f["field_path"] for f in facts if f["value"] not in (None, "UNKNOWN")}
        ),
    }
    entry["unknown"] = sorted(
        {f["field_path"] for f in facts if f["value"] == "UNKNOWN"}
    )
    entry["conflicts"] = len(run["conflicts"])
    resolutions = run["identity"]["resolutions"]
    if resolutions:
        entry["identity_status"] = resolutions[0]["state"]
    return entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", choices=["first-run", "final-run"], default="first-run"
    )
    args = parser.parse_args(argv)

    dev_holdout = json.loads(DEV_HOLDOUT.read_text(encoding="utf-8"))
    frame = json.loads(FRAME.read_text(encoding="utf-8"))
    items = {i["frame_item_id"]: i for i in frame["items"]}
    seed_ids = sorted(dev_holdout["development"])

    commit, dirty = git_commit()
    if dirty and args.phase == "first-run":
        print("ERROR: arbol sucio en src/ scripts/ docs/ — baseline exige commit limpio", file=sys.stderr)
        return 2

    resolver = (
        load_firds_listings(FIRDS_LISTINGS) if FIRDS_LISTINGS.exists() else None
    )
    opener = build_opener()
    results = []
    for index, frame_item_id in enumerate(seed_ids, 1):
        item = items[frame_item_id]
        acq = acquire(item, opener)
        manifest_rel = write_manifest(item, acq)
        run, exc = None, None
        try:
            run = run_pipeline(
                REPO_ROOT,
                manifest_relpath=manifest_rel,
                resolver=resolver,
                instrument_bindings_relpath=INSTRUMENT_BINDINGS,
                run_id=f"G1-DEV-{index:02d}-{args.phase}",
                executed_at=EXECUTED_AT,
            )
        except Exception as error:  # noqa: BLE001 - el fallo es el resultado
            exc = f"{type(error).__name__}: {error}"
        results.append(seed_result(item, acq, run, exc))
        status = "EXC" if exc else ("OK" if run and run["events"] else "EMPTY")
        print(f"  [{index:02d}/25] {frame_item_id} -> {status}")

    first_run = None
    if args.phase == "final-run":
        first_path = RESULTS_DIR / "first-run-results.json"
        if first_path.exists():
            first_run = {
                r["frame_item_id"]: r
                for r in json.loads(first_path.read_text(encoding="utf-8"))["results"]
            }

    entries = []
    for result in results:
        record = dict(result)
        record["parser_commit"] = commit
        if first_run is not None:
            record["first_run_result"] = first_run.get(result["frame_item_id"])
            record["final_run_result"] = result
            record["reason_for_change"] = None
        entries.append(record)

    body = {
        "results_version": "CA_ES_G1_DEV_RESULTS_V1",
        "phase": args.phase,
        "parser_commit": commit,
        "parser_commit_dirty": dirty,
        "executed_at": EXECUTED_AT,
        "seeds": len(entries),
        "results": entries,
    }
    batch_sha = sha256_hex(canonical_bytes(body))
    body["batch_sha256"] = batch_sha

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{args.phase}-results.json"
    out.write_text(
        json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (RESULTS_DIR / f"{args.phase}-results.sha256").write_text(
        f"{batch_sha}  {out.name}\n", encoding="utf-8"
    )
    detected = sum(1 for e in entries if e["event_detected"])
    exceptions = sum(1 for e in entries if e["exception"])
    print(f"{args.phase}: {detected}/25 event_detected, {exceptions} exceptions")
    print(f"batch_sha256={batch_sha}")
    print(f"out={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
