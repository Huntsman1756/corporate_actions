# -*- coding: utf-8 -*-
"""Evalua el parser actual contra el DEV oracle firmado
(g1r/adjudication/dev-missingness-review.jsonl, 150 campos criticos).

Por cada fila compara tres claim-sets del campo:
    expected  = expected_claims adjudicados (oracle firmado)
    baseline  = pipeline.emitted_claims de c431830 (congelado en la fila)
    current   = claims emitidos por el parser actual

Estados por campo:
    UNCHANGED_CORRECT   baseline correcto, sin cambio
    CORRECTED           era MISSING/incorrecto, ahora emite expected
    P0_RESOLVED         el claim P0 del baseline ya no se emite
    UNCHANGED           sin cambio respecto al baseline
    REGRESSED           era CORRECT y el claim actual difiere de expected
    EMITTED_OTHER       emite algo distinto de expected y de baseline

Uso:
    PYTHONPATH=src python scripts/_eval_dev_oracle.py --out <json>
"""
import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ca_es.pipeline import run_pipeline  # noqa: E402
from ca_es.reference.esma_firds import load_firds_listings  # noqa: E402

REVIEW = REPO / "g1r/adjudication/dev-missingness-review.jsonl"


def _fin(v):
    if isinstance(v, dict) and v.get("__financial__"):
        return {"normalized": v["normalized"], "currency": v["currency"]}
    return v


def claims_for(field, f):
    if field == "amount_or_ratio":
        return {k: _fin(v) for k, v in f.items()
                if k.startswith(("amount.", "ratio."))}
    if field == "currency":
        out = {}
        if "instrument.currency" in f:
            out["instrument.currency"] = f["instrument.currency"]
        for k, v in f.items():
            if (k.startswith(("amount.", "ratio."))
                    and isinstance(v, dict) and v.get("__financial__")):
                out[k + ".currency"] = v["currency"]
        return out
    key = {"event_type": "event_type", "ex_date": "date.ex_date",
           "record_date": "date.record_date",
           "payment_date": "date.payment_date",
           "announcement_date": "date.announcement_date",
           "instrument": "instrument.isin"}.get(field, field)
    return {key: f[key]} if key in f else {}


def _eq(a, b):
    if isinstance(b, dict) and "normalized" in b:
        return (isinstance(a, dict) and "normalized" in a
                and Decimal(str(a["normalized"])) == Decimal(str(b["normalized"]))
                and a.get("currency") == b.get("currency"))
    return a == b


def claimset_eq(a, b):
    if a is None or b is None:
        return a == b
    if set(a) != set(b):
        return False
    return all(_eq(a[k], b[k]) for k in a)


def current_facts():
    resolver = load_firds_listings(
        REPO / "g0/corpus/reference/esma-firds-listings.json")
    out = {}
    for mp in sorted((REPO / "g1r/manifests/dev").glob("*.json")):
        rel = str(mp.relative_to(REPO)).replace("\\", "/")
        run = run_pipeline(
            REPO, manifest_relpath=rel, resolver=resolver,
            instrument_bindings_relpath=(
                "g0/corpus/reference/portfolio-instruments.json"),
            run_id="DEV-ORACLE-EVAL", executed_at="2026-09-14T00:00:00Z")
        out[mp.stem] = {
            f["field_path"]: f["value"] for f in run["body"]["facts"]
            if f["value"] not in (None, "UNKNOWN")}
    return out


def classify(row, baseline, current):
    expected = row["expected_claims"]
    classification = row["classification"]
    if current and expected and claimset_eq(current, expected):
        return "UNCHANGED_CORRECT" if classification == "CORRECT" else "CORRECTED"
    if claimset_eq(current, baseline):
        return "UNCHANGED_" + classification
    if row.get("p0_error") and not current:
        return "P0_RESOLVED"
    if not current:
        return "NOW_ABSENT" if classification == "CORRECT" else "UNCHANGED_" + classification
    if classification == "CORRECT":
        return "REGRESSED"
    return "EMITTED_OTHER"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--phase", default="dev-iter-1")
    args = ap.parse_args()

    rows = [json.loads(l) for l in REVIEW.read_text(
        encoding="utf-8").splitlines() if l.strip()]
    facts = current_facts()

    report_rows = []
    counts = {}
    for row in rows:
        fid = row["frame_item_id"]
        baseline = row["pipeline"]["emitted_claims"] or {}
        current = claims_for(row["field"], facts.get(fid, {}))
        status = classify(row, baseline, current)
        counts[status] = counts.get(status, 0) + 1
        entry = {
            "frame_item_id": fid,
            "field": row["field"],
            "classification": row["classification"],
            "p0_error": row.get("p0_error"),
            "expected": row["expected_claims"],
            "baseline": baseline or "ABSENT",
            "current": current or "ABSENT",
            "status": status,
        }
        report_rows.append(entry)

    report = {
        "phase": args.phase,
        "oracle": "g1r/adjudication/dev-missingness-review.jsonl (signed)",
        "rows": len(report_rows),
        "status_counts": counts,
        "results": report_rows,
    }
    args.out.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(json.dumps(counts, indent=0))
    bad = [r for r in report_rows
           if r["status"] in ("REGRESSED", "EMITTED_OTHER")]
    for r in bad:
        print("REVIEW", r["frame_item_id"], r["field"], r["status"],
              "->", json.dumps(r["current"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
