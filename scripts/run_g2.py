# -*- coding: utf-8 -*-
"""Runner G2 Operational Canon.

Ejecuta el qualification corpus sellado (g2/manifests/qualification-corpus.json):

    --run 1|2  corrida principal (con adjudications-real.json)
    --control-e  corrida de control SIN adjudications (caso E)

Cada corrida escribe g2/results/<fase>-<shortsha>-canon.json con el
payload CA_ES_OPERATIONAL_CANON_V1 + logical_sha256. El runner verifica
antes de ejecutar:
  - PARSER_SURFACE_FREEZE: git diff g2-protocol..HEAD y working tree
    vacios sobre los frozen paths
  - sello sha256 de cada raw contra el manifest (aborta si diverge)

    PYTHONPATH=src python scripts/run_g2.py --run 1
    PYTHONPATH=src python scripts/run_g2.py --run 2
    PYTHONPATH=src python scripts/run_g2.py --control-e
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

from ca_es.export import canon_bytes, canon_payload, logical_sha256, operational_canon  # noqa: E402
from ca_es.pipeline import run_pipeline  # noqa: E402
from ca_es.reference.esma_firds import load_firds_listings  # noqa: E402

MANIFEST = "g2/manifests/qualification-corpus.json"
ADJUDICATIONS = "g0/manifests/adjudications-real.json"
INSTRUMENT_BINDINGS = "g0/corpus/reference/portfolio-instruments.json"
FIRDS_LISTINGS = REPO_ROOT / "g0/corpus/reference/esma-firds-listings-real.json"
RESULTS_DIR = REPO_ROOT / "g2" / "results"
FREEZE_TAG = "g2-protocol"
FROZEN_PATHS = [
    "src/ca_es/sources/parsers/",
    "docs/sources/source-policy.json",
]
EXECUTED_AT = "2026-09-16T00:00:00Z"


def check_parser_freeze() -> list[str]:
    errors = []
    diff = subprocess.run(
        ["git", "diff", f"{FREEZE_TAG}..HEAD", "--"] + FROZEN_PATHS,
        capture_output=True, text=True, cwd=REPO_ROOT, check=True,
    ).stdout.strip()
    if diff:
        errors.append("FREEZE_DIFF")
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--"] + FROZEN_PATHS,
        capture_output=True, text=True, cwd=REPO_ROOT, check=True,
    ).stdout.strip()
    if dirty:
        errors.append("FREEZE_DIRTY")
    return errors


def verify_seals(manifest: dict) -> list[str]:
    errors = []
    for doc in manifest["documents"]:
        raw = REPO_ROOT / doc["raw_relpath"]
        if not raw.exists():
            errors.append(f"MISSING_RAW:{doc['official_document_id']}")
            continue
        if hashlib.sha256(raw.read_bytes()).hexdigest() != doc["content_sha256"]:
            errors.append(f"SEAL_BROKEN:{doc['official_document_id']}")
    return errors


def execute(phase: str, adjudications: str | None, run_label: str) -> dict:
    manifest = json.loads(
        (REPO_ROOT / MANIFEST).read_text(encoding="utf-8")
    )
    seal_errors = verify_seals(manifest)
    if seal_errors:
        print(f"ERROR: sello roto: {seal_errors}", file=sys.stderr)
        raise SystemExit(2)

    resolver = (
        load_firds_listings(FIRDS_LISTINGS) if FIRDS_LISTINGS.exists() else None
    )
    run = run_pipeline(
        REPO_ROOT,
        manifest_relpath=MANIFEST,
        adjudications_relpath=adjudications,
        instrument_bindings_relpath=INSTRUMENT_BINDINGS,
        resolver=resolver,
        run_id=run_label,
        executed_at=EXECUTED_AT,
    )
    canon = operational_canon(run["body"], manifest["corpus_id"])
    payload_bytes = canon_bytes(canon_payload(canon))
    sha = logical_sha256(canon)

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
        cwd=REPO_ROOT, check=True,
    ).stdout.strip()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{phase}-{commit[:7]}-canon.json"
    out.write_bytes(payload_bytes + b"\n")
    summary = {
        "phase": phase,
        "parser_commit": commit,
        "manifest_sha256": hashlib.sha256(
            (REPO_ROOT / MANIFEST).read_bytes()
        ).hexdigest(),
        "adjudications": adjudications,
        "events": len(canon["events"]),
        "logical_sha256": sha,
        "canon_artifact": str(out.relative_to(REPO_ROOT)).replace("\\", "/"),
        "result_sha": run["result_sha"],
    }
    print(json.dumps(summary, indent=1))
    return {"canon": canon, "summary": summary, "run": run}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=int, choices=[1, 2])
    parser.add_argument("--control-e", action="store_true")
    args = parser.parse_args(argv)
    if not args.run and not args.control_e:
        parser.error("indicar --run 1|2 o --control-e")

    freeze_errors = check_parser_freeze()
    if freeze_errors:
        print(f"ERROR: parser surface freeze roto: {freeze_errors}",
              file=sys.stderr)
        return 2

    if args.control_e:
        execute("control-e", None, "G2-CONTROL-E")
        return 0
    execute(f"run-{args.run}", ADJUDICATIONS, f"G2-RUN-{args.run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
