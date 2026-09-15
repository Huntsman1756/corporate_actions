# -*- coding: utf-8 -*-
"""Runner G1-R2: ejecuta el HOLDOUT virgen sellado (8 CA-groups, 11 docs).

Los manifests y raws ya estan sellados por build_g1r2_corpus.py; este
runner NO adquiere nada: verifica la integridad sha256 de cada raw
sellado antes de parsear (HOLDOUT sealed: cualquier divergencia aborta).

    PYTHONPATH=src python scripts/run_g1r2.py --run 1
    PYTHONPATH=src python scripts/run_g1r2.py --run 2

Escribe g1r2/results/holdout-run-<N>-<shortsha>-results.json (+ .sha256).
La determinism check (run1 == run2) se evalua en adjudicacion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from ca_es.pipeline import run_pipeline  # noqa: E402
from ca_es.reference.esma_firds import load_firds_listings  # noqa: E402
from run_g1r import funnel, git_commit, seed_result  # noqa: E402

MANIFEST_DIR = REPO_ROOT / "g1r2" / "manifests" / "holdout"
RESULTS_DIR = REPO_ROOT / "g1r2" / "results"
INSTRUMENT_BINDINGS = "g0/corpus/reference/portfolio-instruments.json"
FIRDS_LISTINGS = REPO_ROOT / "g0" / "corpus" / "reference" / "esma-firds-listings.json"
EXECUTED_AT = "2026-09-15T00:00:00Z"


def verify_seal(manifest: dict) -> str | None:
    """None si el raw sellado coincide con content_sha256 del manifest."""
    doc = manifest["documents"][0]
    expected = doc["content_sha256"]
    raw = REPO_ROOT / doc["raw_relpath"]
    if not raw.exists():
        return f"MISSING_RAW:{doc['raw_relpath']}"
    actual = hashlib.sha256(raw.read_bytes()).hexdigest()
    if actual != expected:
        return f"SEAL_BROKEN:{doc['official_document_id']}"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=int, required=True, choices=[1, 2])
    args = parser.parse_args(argv)

    commit, dirty = git_commit()
    if dirty:
        print(
            "ERROR: arbol sucio en src/ scripts/ docs/ — la corrida exige commit limpio",
            file=sys.stderr,
        )
        return 2

    manifests = sorted(MANIFEST_DIR.glob("*.json"))
    if not manifests:
        print("ERROR: no hay manifests sellados en g1r2/manifests/holdout",
              file=sys.stderr)
        return 2

    seal_errors = []
    for mp in manifests:
        manifest = json.loads(mp.read_text(encoding="utf-8"))
        error = verify_seal(manifest)
        if error:
            seal_errors.append(error)
    if seal_errors:
        print(f"ERROR: sello roto: {seal_errors}", file=sys.stderr)
        return 2

    resolver = (
        load_firds_listings(FIRDS_LISTINGS) if FIRDS_LISTINGS.exists() else None
    )
    results = []
    for index, mp in enumerate(manifests, 1):
        manifest = json.loads(mp.read_text(encoding="utf-8"))
        document = manifest["documents"][0]
        doc_id = document["official_document_id"]
        item = {"frame_item_id": doc_id, "stratum": "PORTFOLIO"}
        acq = {
            "retrieval_status": document["retrieval_status"],
        }
        run, exc = None, None
        try:
            run = run_pipeline(
                REPO_ROOT,
                manifest_relpath=str(mp.relative_to(REPO_ROOT)).replace("\\", "/"),
                resolver=resolver,
                instrument_bindings_relpath=INSTRUMENT_BINDINGS,
                run_id=f"G1R2-HOLDOUT-{index:02d}-RUN{args.run}",
                executed_at=EXECUTED_AT,
            )
        except Exception as error:  # noqa: BLE001 - el fallo es el resultado
            exc = f"{type(error).__name__}: {error}"
        entry = seed_result(item, acq, run, exc)
        entry["ca_group_sealed"] = True
        entry["parser_commit"] = commit
        results.append(entry)
        print(f"  [{index:02d}/{len(manifests)}] {doc_id} -> {entry['parse_status']}")

    report = {
        "results_version": "CA_ES_G1R2_RESULTS_V1",
        "phase": "holdout",
        "seed_set": "holdout",
        "run": args.run,
        "parser_commit": commit,
        "parser_commit_dirty": False,
        "executed_at": EXECUTED_AT,
        "seeds": len(results),
        "funnel": funnel(results),
        "results": results,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"holdout-run-{args.run}-{commit[:7]}-results.json"
    payload = json.dumps(report, indent=1, ensure_ascii=False) + "\n"
    out.write_text(payload, encoding="utf-8")
    out.with_suffix(".sha256").write_text(
        hashlib.sha256(payload.encode("utf-8")).hexdigest() + "\n",
        encoding="utf-8",
    )
    print(
        f"run{args.run}: {report['funnel']['document_parsed']}/{len(results)} parsed, "
        f"batch_sha256={hashlib.sha256(payload.encode('utf-8')).hexdigest()}"
    )
    print(f"out={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
