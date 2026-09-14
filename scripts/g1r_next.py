# -*- coding: utf-8 -*-
"""G1-R runbook driver: selecciona la siguiente failure class y ejecuta
los gates del checkpoint. Protocolo: docs/gates/g1r-execution-runbook.md.
Estado: g1r/state.json.

Uso:
    python scripts/g1r_next.py status
    python scripts/g1r_next.py next
    python scripts/g1r_next.py begin --class DECIMAL_SPLIT_PDF
    python scripts/g1r_next.py gates --phase dev-iter-2

El script NO escribe remediacion: decide la clase y aplica los gates.
La aprobacion de un checkpoint es externa (revision humana); el script
nunca mueve una clase de in_review a resolved por si mismo.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATE = REPO / "g1r" / "state.json"
CATALOG = REPO / "g1r" / "results" / "dev-failure-catalog.json"
RESULTS = REPO / "g1r" / "results"


def load_state():
    return json.loads(STATE.read_text(encoding="utf-8"))


def save_state(state):
    STATE.write_text(
        json.dumps(state, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")


def catalog_entry(name):
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    for f in catalog["failures"]:
        if f["failure_class"] == name:
            return f
    return None


def cmd_status(state):
    fc = state["failure_classes"]
    print(f"last_approved: {state['last_approved_checkpoint']['phase']} "
          f"({state['last_approved_checkpoint']['commit']})")
    print(f"resolved:    {fc['resolved']}")
    print(f"in_review:   {fc['in_review']}  <- requiere aprobacion externa")
    print(f"queue:       {fc['queue']}")
    print(f"holdout:     {state['holdout']['status']}")
    if fc["in_review"]:
        print("\nSTOP: hay clase en revision; no abrir otra hasta que el "
              "checkpoint se firme.")
        return
    cmd_next(state)


def cmd_next(state):
    fc = state["failure_classes"]
    if fc["in_review"]:
        print(f"AWAITING_REVIEW: {fc['in_review'][0]}")
        return
    if not fc["queue"]:
        print("QUEUE_EMPTY: parser freeze -> HOLDOUT virgin")
        return
    name = fc["queue"][0]
    entry = catalog_entry(name)
    print(f"NEXT_FAILURE_CLASS: {name}")
    if entry:
        print(f"  safety: {entry['safety']}")
        print(f"  seeds:  {', '.join(entry['seeds'])}")
        print(f"  desc:   {entry['description']}")
    print("\nProtocolo: docs/gates/g1r-execution-runbook.md")


def cmd_begin(state, name):
    fc = state["failure_classes"]
    if fc["in_review"]:
        print(f"STOP: {fc['in_review'][0]} sigue en revision", file=sys.stderr)
        return 2
    if name not in fc["queue"]:
        print(f"STOP: {name} no esta en queue", file=sys.stderr)
        return 2
    fc["queue"].remove(name)
    fc["in_review"].append(name)
    save_state(state)
    print(f"BEGIN {name}: implementa la regla generica, luego "
          f"'gates --phase dev-iter-N'.")
    return 0


def holdout_dirty(state):
    out = subprocess.run(
        ["git", "status", "--porcelain", "--"] + state["holdout"]["paths"],
        cwd=REPO, capture_output=True, text=True)
    return [l for l in out.stdout.splitlines() if l.strip()]


def cmd_gates(state, phase):
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"
    verdict = []

    dirty = holdout_dirty(state)
    verdict.append(("HOLDOUT intacto", not dirty, "; ".join(dirty)))

    test = subprocess.run(
        [sys.executable, "-m", "pytest", "-x", "-q"],
        cwd=REPO, env=env, capture_output=True, text=True)
    verdict.append(("pytest", test.returncode == 0,
                    test.stdout.strip().splitlines()[-1]
                    if test.stdout.strip() else ""))

    g1_json = RESULTS / f"{phase}-g1-oracle-eval.json"
    g1 = subprocess.run(
        [sys.executable, "scripts/_eval_g1_regression_oracle.py",
         "--json", str(g1_json)],
        cwd=REPO, env=env, capture_output=True, text=True)
    print(g1.stdout)
    new_fails = []
    if g1_json.exists():
        report = json.loads(g1_json.read_text(encoding="utf-8"))
        known = set(state["g1_oracle"]["known_open_failures"])
        rows = report.get("correct", []) + report.get("incorrect", [])
        new_fails = [f"{r['id']} :: {r['field']}"
                     for r in rows if not r["ok"]
                     and f"{r['id']} :: {r['field']}" not in known]
    verdict.append(("G1 oracle: sin FAIL nuevo", not new_fails,
                    "; ".join(new_fails)))

    dev_eval = RESULTS / f"{phase}-dev-oracle-eval.json"
    if dev_eval.exists():
        counts = json.loads(
            dev_eval.read_text(encoding="utf-8"))["status_counts"]
        ok = (counts.get("REGRESSED", 0) == 0
              and counts.get("EMITTED_OTHER", 0) == 0)
        verdict.append(("DEV oracle: 0 REGRESSED / 0 EMITTED_OTHER", ok,
                        json.dumps(counts)))
    else:
        verdict.append((f"DEV oracle eval ({dev_eval.name})", False,
                        "artefacto ausente: ejecuta _eval_dev_oracle.py"))

    print("\n== GATES ==")
    stop = False
    for label, ok, detail in verdict:
        print(f"  {'PASS' if ok else 'STOP'}  {label}"
              + ("" if ok or not detail else f"  [{detail}]"))
        stop |= not ok
    print(f"\nVERDICT: {'STOP — no congelar checkpoint' if stop else 'PASS'}")
    return 1 if stop else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status")
    sub.add_parser("next")
    b = sub.add_parser("begin")
    b.add_argument("--class", dest="cls", required=True)
    g = sub.add_parser("gates")
    g.add_argument("--phase", required=True)
    args = ap.parse_args()

    state = load_state()
    if args.cmd == "next":
        return cmd_next(state) or 0
    if args.cmd == "begin":
        return cmd_begin(state, args.cls)
    if args.cmd == "gates":
        return cmd_gates(state, args.phase)
    return cmd_status(state) or 0


if __name__ == "__main__":
    sys.exit(main())
