# -*- coding: utf-8 -*-
"""Runner G1-R: adquisicion de seeds + ejecucion por fase.

--set holdout --acquire-only : sella los 15 HOLDOUT (raw + manifest +
    content_sha256) SIN parsear ni inspeccionar el contenido.
--set development            : baseline c431830 sobre los 25 DEV
    -> g1r/results/baseline-c431830-results.json

Uso:
    python scripts/run_g1r.py --set holdout --acquire-only
    python scripts/run_g1r.py --set development --phase baseline
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from ca_es.canonical import canonical_bytes, sha256_hex  # noqa: E402
from ca_es.pipeline import run_pipeline  # noqa: E402
from ca_es.reference.esma_firds import load_firds_listings  # noqa: E402
from ca_es.sources.locators import resolve_locator  # noqa: E402
from fetch_cnmv import build_opener, fetch_document  # noqa: E402

SPLIT_PATH = REPO_ROOT / "g1r" / "manifests" / "dev-holdout.json"
FRAME = REPO_ROOT / "g1" / "manifests" / "sampling-frame.json"
_SET_DIRNAME = {"development": "dev", "holdout": "holdout", "adversarial": "adversarial"}
RESULTS_DIR = REPO_ROOT / "g1r" / "results"
INSTRUMENT_BINDINGS = "g0/corpus/reference/portfolio-instruments.json"
FIRDS_LISTINGS = REPO_ROOT / "g0" / "corpus" / "reference" / "esma-firds-listings.json"
EXECUTED_AT = "2026-09-14T00:00:00Z"

SOURCE_ID = {"CNMV": "CNMV", "POEX": "PORTFOLIO_STOCK_EXCHANGE", "BMEG": "BME_GROWTH"}
MEDIA_TYPE = {"pdf": "application/pdf", "json": "application/json", "html": "text/html"}


def git_commit() -> tuple[str, bool]:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain", "--", "src/", "scripts/", "docs/"],
            capture_output=True, text=True, check=True,
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


def acquire(item: dict, opener, raw_dir: Path) -> dict:
    frame_item_id = item["frame_item_id"]
    name = _safe_name(frame_item_id)
    raw_dir.mkdir(parents=True, exist_ok=True)

    if frame_item_id.startswith("BMEG-"):
        payload = _bmeg_raw(item)
        path = raw_dir / f"{name}.json"
        path.write_bytes(payload)
        return {
            "raw_relpath": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
            "content_sha256": hashlib.sha256(payload).hexdigest(),
            "media_type": "application/json",
            "retrieval_status": "OK",
            "url": item.get("source_locator"),
            "retrieval_method": "BME_API_ROW_SNAPSHOT",
        }

    url = resolve_locator(item["source"], item.get("source_locator"))
    if not url:
        return {
            "raw_relpath": None, "content_sha256": None, "media_type": None,
            "retrieval_status": "NO_URL", "url": item.get("source_locator"),
            "retrieval_method": None,
        }
    try:
        fetched = fetch_document(opener, url, raw_dir, name)
    except Exception as exc:  # noqa: BLE001 - el fallo es el resultado del seed
        return {
            "raw_relpath": None, "content_sha256": None, "media_type": None,
            "retrieval_status": f"FETCH_FAILED:{type(exc).__name__}",
            "url": url, "retrieval_method": "HTTP_GET",
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


def write_manifest(item: dict, acq: dict, manifest_dir: Path, corpus_id_prefix: str) -> str:
    frame_item_id = item["frame_item_id"]
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "manifest_version": "CA_ES_SOURCE_MANIFEST_V1",
        "corpus_id": f"{corpus_id_prefix}_{frame_item_id}",
        "retrieved_at": EXECUTED_AT[:10],
        "documents": [
            {
                "source_id": SOURCE_ID[frame_item_id.split("-")[0]],
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
    path = manifest_dir / f"{_safe_name(frame_item_id)}.json"
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return str(path.relative_to(REPO_ROOT)).replace("\\", "/")


_CRITICAL_FIELDS = (
    "date.ex_date", "date.record_date", "date.payment_date", "date.redemption_date",
)


def _layers(entry: dict) -> dict:
    parsed = entry["parse_status"]
    populated = entry["facts"]["populated_fields"]
    return {
        "seed_retrieved": entry["retrieval_status"] == "OK",
        "document_resolved": entry["retrieval_status"] == "OK",
        "parser_available": (
            parsed is not None and not str(parsed).startswith("NO_PARSER")
        ),
        "document_parsed": parsed == "OK",
        "event_detected": entry["event_detected"],
        "critical_facts_extracted": bool(
            set(populated) & set(_CRITICAL_FIELDS)
            or any(f.startswith("amount.") for f in populated)
        ),
        "instrument_resolved": entry["instrument_resolved"],
    }


def seed_result(item: dict, acq: dict, run: dict | None, exc: str | None) -> dict:
    entry = {
        "frame_item_id": item["frame_item_id"],
        "stratum": item["stratum"],
        "retrieval_status": acq["retrieval_status"],
        "parse_status": None,
        "event_detected": False,
        "instrument_resolved": False,
        "facts": {"total": 0, "populated_fields": []},
        "missing": [],
        "unknown": [],
        "conflicts": 0,
        "identity_status": "NONE",
        "exception": exc,
        "result_sha": None,
    }
    if run is None:
        entry["layers"] = _layers(entry)
        return entry
    body = run["body"]
    entry["result_sha"] = run["result_sha"]
    document = body["documents"][0]
    entry["retrieval_status"] = document["retrieval_status"]
    parse_errors = body.get("parse_errors") or {}
    if document["document_id"] in parse_errors:
        entry["parse_status"] = parse_errors[document["document_id"]]
    elif document["retrieval_status"] != "OK":
        entry["parse_status"] = "SKIPPED:NO_RAW"
    else:
        entry["parse_status"] = "OK"
    events = body["events"]
    entry["event_detected"] = bool(events)
    facts = body["facts"]
    entry["facts"] = {
        "total": len(facts),
        "populated_fields": sorted(
            {f["field_path"] for f in facts if f["value"] not in (None, "UNKNOWN")}
        ),
    }
    entry["unknown"] = sorted(
        {f["field_path"] for f in facts if f["value"] == "UNKNOWN"}
    )
    entry["conflicts"] = len(body["conflicts"])
    resolutions = body["identity"]["resolutions"]
    if resolutions:
        entry["identity_status"] = resolutions[0]["state"]
    entry["instrument_resolved"] = any(e.get("isin") for e in events)
    entry["layers"] = _layers(entry)
    return entry


def funnel(entries: list[dict]) -> dict:
    layers = [
        "seed_retrieved", "document_resolved", "parser_available",
        "document_parsed", "event_detected", "critical_facts_extracted",
        "instrument_resolved",
    ]
    out = {"seeds": len(entries)}
    for layer in layers:
        out[layer] = sum(1 for e in entries if e.get("layers", {}).get(layer))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", dest="seed_set",
                        choices=["development", "holdout", "adversarial"],
                        default="development")
    parser.add_argument("--phase", default="baseline",
                        help="etiqueta de fase (baseline, dev-iter-N, ...)")
    parser.add_argument("--acquire-only", action="store_true",
                        help="sellado: raw+manifest+sha256 sin parsear (HOLDOUT)")
    parser.add_argument("--only", nargs="*", default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    frame = json.loads(FRAME.read_text(encoding="utf-8"))
    items = {i["frame_item_id"]: i for i in frame["items"]}
    seed_ids = sorted(split["holdout"] if args.seed_set == "holdout"
                      else split["development"])
    if args.only:
        wanted = set(args.only)
        missing = wanted - set(seed_ids)
        if missing:
            print(f"ERROR: ids fuera del set: {sorted(missing)}", file=sys.stderr)
            return 2
        seed_ids = [s for s in seed_ids if s in wanted]

    commit, dirty = git_commit()
    if dirty and not args.only:
        print("ERROR: arbol sucio en src/ scripts/ docs/ — la corrida exige commit limpio",
              file=sys.stderr)
        return 2

    manifest_dir = REPO_ROOT / "g1r" / "manifests" / _SET_DIRNAME[args.seed_set]
    raw_dir = REPO_ROOT / "g1r" / "corpus" / "raw" / _SET_DIRNAME[args.seed_set]
    corpus_prefix = f"G1R_{args.seed_set.upper()}"

    resolver = (
        load_firds_listings(FIRDS_LISTINGS) if FIRDS_LISTINGS.exists() else None
    )
    opener = build_opener()
    results = []
    for index, frame_item_id in enumerate(seed_ids, 1):
        item = items[frame_item_id]
        acq = acquire(item, opener, raw_dir)
        manifest_rel = write_manifest(item, acq, manifest_dir, corpus_prefix)
        run, exc = None, None
        if not args.acquire_only:
            try:
                run = run_pipeline(
                    REPO_ROOT,
                    manifest_relpath=manifest_rel,
                    resolver=resolver,
                    instrument_bindings_relpath=INSTRUMENT_BINDINGS,
                    run_id=f"G1R-{args.seed_set.upper()}-{index:02d}-{args.phase}",
                    executed_at=EXECUTED_AT,
                )
            except Exception as error:  # noqa: BLE001 - el fallo es el resultado
                exc = f"{type(error).__name__}: {error}"
        entry = seed_result(item, acq, run, exc)
        entry["parser_commit"] = commit
        if args.acquire_only:
            entry["sealed"] = True
        results.append(entry)
        status = ("SEALED" if args.acquire_only
                  else "EXC" if exc
                  else ("OK" if run and run["body"]["events"] else "EMPTY"))
        print(f"  [{index:02d}/{len(seed_ids)}] {frame_item_id} -> {status}")

    if args.acquire_only:
        print(f"{args.seed_set}: {len(results)} seeds adquiridos y sellados "
              f"(sin parseo)")
        return 0

    body = {
        "results_version": "CA_ES_G1R_RESULTS_V1",
        "phase": args.phase,
        "seed_set": args.seed_set,
        "parser_commit": commit,
        "parser_commit_dirty": dirty,
        "executed_at": EXECUTED_AT,
        "seeds": len(results),
        "seed_verdicts": {
            k: sum(1 for e in results
                   if (e.get("seed_verdict") or "UNADJUDICATED") == k)
            for k in ("ACTUAL_CA", "NOT_CA", "AMBIGUOUS", "UNADJUDICATED")
        },
        "funnel": funnel(results),
        "results": results,
    }
    batch_sha = sha256_hex(body)
    body["batch_sha256"] = batch_sha

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = args.out or RESULTS_DIR / f"{args.phase}-{commit[:7]}-results.json"
    out.write_text(
        json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    out.with_suffix(".sha256").write_text(
        f"{batch_sha}  {out.name}\n", encoding="utf-8")
    detected = sum(1 for e in results if e["event_detected"])
    exceptions = sum(1 for e in results if e["exception"])
    print(f"{args.phase}: {detected}/{len(results)} event_detected, {exceptions} exceptions")
    print(f"funnel={body['funnel']}")
    print(f"batch_sha256={batch_sha}")
    print(f"out={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
