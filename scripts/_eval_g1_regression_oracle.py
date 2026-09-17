# -*- coding: utf-8 -*-
"""Evalua el parser actual contra g1r/manifests/g1-regression-oracle.json.

Re-ejecuta run_pipeline sobre los manifests sellados holdout/adversarial
(mismos raw bytes) y aplica las evaluation_rule del oracle:

  REMAIN_CORRECT:      todos los expected_claims emitidos e iguales.
  CORRECT_OR_ABSTAIN:  ningun forbidden_claim emitido y el claim-set del
                       campo es vacio o igual a un allowed_outcome.

Uso:
    PYTHONPATH=src python scripts/_eval_g1_regression_oracle.py [--json out]
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

ORACLE = REPO / "g1r/manifests/g1-regression-oracle.json"


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
           "payment_date": "date.payment_date"}[field]
    return {key: f[key]} if key in f else {}


def _fin(v):
    if isinstance(v, dict) and v.get("__financial__"):
        return {"normalized": v["normalized"], "currency": v["currency"]}
    return v


def _eq(a, b):
    """Igualdad semantica: financiero {normalized,currency}; escalar exacto."""
    if isinstance(b, dict) and "normalized" in b:
        return (isinstance(a, dict) and "normalized" in a
                and Decimal(a["normalized"]) == Decimal(b["normalized"])
                and a.get("currency") == b.get("currency"))
    return a == b


def _claimset_eq(emitted, allowed):
    if set(emitted) != set(allowed):
        return False
    return all(_eq(emitted[k], allowed[k]) for k in allowed)


def sealed_facts():
    resolver = load_firds_listings(
        REPO / "g0/corpus/reference/esma-firds-listings.json")
    out = {}
    for setname in ("holdout", "adversarial"):
        for mpath in sorted((REPO / "g1/manifests" / setname).glob("*.json")):
            rel = str(mpath.relative_to(REPO)).replace("\\", "/")
            run = run_pipeline(
                REPO, manifest_relpath=rel, resolver=resolver,
                instrument_bindings_relpath=(
                    "g0/corpus/reference/portfolio-instruments.json"),
                run_id="ORACLE-EVAL", executed_at="2026-09-14T00:00:00Z")
            out.setdefault(setname, {})[mpath.stem] = {
                f["field_path"]: f["value"] for f in run["body"]["facts"]
                if f["value"] not in (None, "UNKNOWN")}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    oracle = json.loads(ORACLE.read_text(encoding="utf-8"))
    facts = sealed_facts()
    report = {"correct": [], "incorrect": []}
    fails = 0

    for e in oracle["known_correct_critical_fields"]:
        emitted = claims_for(e["field"], facts[e["set"]][e["frame_item_id"]])
        missing = [k for k, v in e["expected_claims"].items()
                   if not _eq(emitted.get(k), v)]
        ok = not missing
        fails += not ok
        report["correct"].append({
            "id": e["frame_item_id"], "field": e["field"], "ok": ok,
            **({"missing": missing} if missing else {}),
            **({"emitted": emitted} if not ok else {})})

    for e in oracle["known_p0_incorrect_fields"]:
        emitted = claims_for(e["field"], facts[e["set"]][e["frame_item_id"]])
        forbidden_hit = [k for k, v in e["forbidden_claims"].items()
                         if _eq(emitted.get(k), v)]
        allowed_ok = any(
            (not emitted) if a == "ABSENT" else _claimset_eq(emitted, a)
            for a in e["allowed_outcomes"])
        ok = not forbidden_hit and allowed_ok
        fails += not ok
        report["incorrect"].append({
            "id": e["frame_item_id"], "field": e["field"], "ok": ok,
            "emitted": emitted,
            "note": e.get("note", "")})

    n_ok = sum(1 for r in report["correct"] + report["incorrect"] if r["ok"])
    n = len(report["correct"]) + len(report["incorrect"])
    print(f"oracle: {n_ok}/{n} checks OK, {fails} FAIL")
    for r in report["correct"] + report["incorrect"]:
        mark = "OK  " if r["ok"] else "FAIL"
        print(f"  {mark} {r['id']} :: {r['field']}"
              + ("" if r["ok"] else f" -> {json.dumps(r.get('emitted'), ensure_ascii=False)}"))
    if args.json:
        args.json.write_text(json.dumps(report, indent=1, ensure_ascii=False),
                             encoding="utf-8")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
