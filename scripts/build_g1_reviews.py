"""Genera g1/adjudication/missingness-review.jsonl desde un results file.

Entradas mecanicas: por cada seed parseado, los campos criticos de la
matriz de aplicabilidad que el pipeline no poblo quedan en revision.
La matriz se congelo en metric-applicability.json; las familias se
mapean desde event_type (nombres del parser -> nombres de la matriz).
La clasificacion MISSING/UNKNOWN la decide el revisor, no este script.

Uso:
    python scripts/build_g1_reviews.py g1/results/final-run-results.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = REPO_ROOT / "g1" / "manifests" / "metric-applicability.json"
VERDICTS_PATH = REPO_ROOT / "g1" / "adjudication" / "seed-verdicts.jsonl"
OUT_PATH = REPO_ROOT / "g1" / "adjudication" / "missingness-review.jsonl"

# event_type del parser -> familia de la matriz congelada
FAMILY = {
    "CASH_DIVIDEND": "CASH_DIVIDEND",
    "SCRIP_DIVIDEND": "SCRIP_DIVIDEND",
    "RIGHTS_ISSUE": "RIGHTS_ISSUE",
    "CAPITAL_INCREASE": "CAPITAL_INCREASE",
    "CAPITAL_REDUCTION": "CAPITAL_REDUCTION",
    "SPLIT": "SPLIT",
    "MERGER_OR_EXCHANGE": "MERGER",
    "TAKEOVER_BID": "TENDER",
    "EARLY_REDEMPTION": "REDEMPTION",
}


def _populated(entry: dict, field: str) -> bool:
    fields = entry["facts"]["populated_fields"]
    if field == "event_type":
        return "event_type" in fields
    if field == "amount_or_ratio":
        return any(
            f.startswith("amount.") or f.startswith("ratio.") for f in fields
        )
    if field == "currency":
        # moneda poblada si hay importe financiero o divisa explicita
        return any(f.startswith("amount.") for f in fields) or (
            "instrument.currency" in fields
        )
    return f"date.{field}" in fields


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("results", type=Path)
    args = ap.parse_args()

    matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    verdicts = {
        v["frame_item_id"]: v
        for v in (
            json.loads(line)
            for line in VERDICTS_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    results = json.loads(args.results.read_text(encoding="utf-8"))

    lines = []
    for entry in results["results"]:
        fid = entry["frame_item_id"]
        verdict = verdicts.get(fid, {}).get("seed_verdict")
        if entry["parse_status"] != "OK":
            continue
        event_types = [
            f["value"]
            for f in _all_facts(args.results, fid)
            if f["field_path"] == "event_type"
        ]
        event_type = event_types[0] if event_types else "UNKNOWN"
        family = FAMILY.get(event_type)
        row = matrix["matrix"].get(family) if family else None
        for field in matrix["fields"]:
            if _populated(entry, field):
                continue
            applicability = row[field] if row else "UNDETERMINED"
            if applicability == "NOT_APPLICABLE":
                continue
            if applicability == "CONDITIONAL":
                applicability = "UNDETERMINED"
            lines.append(
                {
                    "frame_item_id": fid,
                    "seed_verdict": verdict,
                    "event_type_observed": event_type,
                    "family": family,
                    "field": field,
                    "applicability": applicability,
                    "pipeline": {"populated": False},
                    "source_review": {
                        "published_status": None,
                        "source_document_id": fid,
                        "evidence_locator": None,
                        "reviewer": None,
                        "reviewed_at": None,
                    },
                    "classification": None,
                }
            )

    OUT_PATH.write_text(
        "".join(
            json.dumps(
                line, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            + "\n"
            for line in lines
        ),
        encoding="utf-8",
    )
    print(f"{len(lines)} entradas en {OUT_PATH}")
    return 0


def _all_facts(results_path: Path, frame_item_id: str) -> list[dict]:
    """Reejecuta el manifest del seed para obtener facts completos."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "src"))
    from ca_es.pipeline import run_pipeline

    manifest = f"g1/manifests/dev/{frame_item_id}.json"
    try:
        run = run_pipeline(REPO_ROOT, manifest_relpath=manifest)
    except Exception:
        return []
    return run["body"]["facts"]


if __name__ == "__main__":
    raise SystemExit(main())
