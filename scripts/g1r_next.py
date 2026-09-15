# -*- coding: utf-8 -*-
"""G1-R runbook driver: selecciona la siguiente failure class y ejecuta
los gates del checkpoint. Protocolo: docs/gates/g1r-execution-runbook.md.
Estado: g1r/state.json.

Uso:
    python scripts/g1r_next.py status
    python scripts/g1r_next.py next
    python scripts/g1r_next.py begin          # abre queue[0], sin seleccion
    python scripts/g1r_next.py gates --phase dev-iter-N

El script NO escribe remediacion: decide la clase y aplica los gates.
begin no acepta eleccion: siempre abre queue[0]. La aprobacion de un
checkpoint es externa (revision humana); el script nunca mueve una
clase de in_review a resolved por si mismo.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATE = REPO / "g1r" / "state.json"
CATALOG = REPO / "g1r" / "results" / "dev-failure-catalog.json"
RESULTS = REPO / "g1r" / "results"

TARGET_OK = {"P0_CORRECTED", "P0_SAFE_ABSTENTION", "CORRECTED",
             "UNCHANGED_CORRECT"}
P0_OPEN = {"P0_UNRESOLVED", "P0_CHANGED_OTHER"}


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


class GateError(RuntimeError):
    """Fallo de infraestructura: el gate no puede decidir -> STOP."""


def _git(*args):
    proc = subprocess.run(["git"] + list(args), cwd=REPO,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise GateError(f"git {' '.join(args)} rc={proc.returncode}: "
                        f"{proc.stderr.strip()}")
    return proc.stdout


def _head():
    return _git("rev-parse", "HEAD").strip()


def _run(cmd, env, allowed=(0,)):
    """Ejecuta un evaluador fail-closed: rc fuera de allowed -> GateError."""
    proc = subprocess.run(cmd, cwd=REPO, env=env,
                          capture_output=True, text=True)
    if proc.returncode not in allowed:
        raise GateError(f"{' '.join(cmd)} rc={proc.returncode}: "
                        f"{(proc.stderr or proc.stdout).strip()[:400]}")
    return proc


def print_class(state, name):
    entry = catalog_entry(name)
    print(f"FAILURE_CLASS: {name}")
    if entry:
        print(f"  safety: {entry['safety']}")
        print(f"  seeds:  {', '.join(entry['seeds'])}")
        print(f"  desc:   {entry['description']}")
    targets = state.get("targets", {}).get(name, {})
    for scope in ("dev", "g1reg"):
        for t in targets.get(scope, []):
            print(f"  target[{scope}]: {t}")


def cmd_status(state):
    fc = state["failure_classes"]
    print(f"last_approved: {state['last_approved_checkpoint']['phase']} "
          f"({state['last_approved_checkpoint']['commit'][:7]})")
    print(f"resolved:    {fc['resolved']}")
    print(f"in_review:   {fc['in_review']}  <- requiere aprobacion externa")
    print(f"queue:       {fc['queue']}")
    print(f"holdout:     {state['holdout']['status']} "
          f"(freeze_ref {state['holdout']['freeze_ref'][:7]})")
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
    print_class(state, fc["queue"][0])
    print("\nProtocolo: docs/gates/g1r-execution-runbook.md")


def cmd_begin(state):
    fc = state["failure_classes"]
    if fc["in_review"]:
        print(f"STOP: {fc['in_review'][0]} sigue en revision", file=sys.stderr)
        return 2
    if not fc["queue"]:
        print("QUEUE_EMPTY: parser freeze -> HOLDOUT virgin")
        return 0
    name = fc["queue"].pop(0)          # siempre queue[0]: sin seleccion
    fc["in_review"].append(name)
    save_state(state)
    print(f"BEGIN {name}")
    print_class(state, name)
    print("\nImplementa la regla generica, luego "
          "'gates --phase dev-iter-N'.")
    return 0


def holdout_problems(state):
    """Cambios en paths sellados: working tree, historia desde
    freeze_ref, y raw ignorados verificados por sha256 vs manifest."""
    h = state["holdout"]
    problems = []
    paths = h["sealed_git_paths"]
    dirty = _git("status", "--porcelain", "--", *paths)
    problems += [f"working tree: {l.strip()}"
                 for l in dirty.splitlines() if l.strip()]
    committed = _git("diff", "--name-only",
                     f"{h['freeze_ref']}..HEAD", "--", *paths)
    problems += [f"committed since freeze: {l.strip()}"
                 for l in committed.splitlines() if l.strip()]
    for mdir in h.get("raw_manifest_dirs", []):
        for mpath in sorted((REPO / mdir).glob("*.json")):
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
            for doc in manifest.get("documents", []):
                rel, sha = doc.get("raw_relpath"), doc.get("content_sha256")
                if not rel or not sha:
                    continue
                raw = REPO / rel
                if not raw.exists():
                    problems.append(f"raw missing: {rel}")
                    continue
                actual = hashlib.sha256(raw.read_bytes()).hexdigest()
                if actual != sha:
                    problems.append(f"raw sha mismatch: {rel}")
    return problems


def _fails_in_eval(path):
    report = json.loads(path.read_text(encoding="utf-8"))
    rows = report.get("correct", []) + report.get("incorrect", [])
    return {f"{r['id']} :: {r['field']}": r for r in rows if not r["ok"]}


# Paths que determinan la salida de una corrida: si cambian entre
# parser_commit y HEAD, el results artifact ya no describe HEAD.
_RUN_INPUTS = ["src", "g1r/manifests", "g1r/corpus",
               "g0/corpus/reference", "scripts/run_g1r.py",
               "scripts/fetch_cnmv.py"]


def results_artifact_problems(phase, head):
    """El results artifact debe estar ligado a HEAD: parser_commit del
    artefacto con src/corpus/manifests identicos a HEAD (diff vacio),
    run no dirty y sha256 valido."""
    problems = []
    matches = sorted(RESULTS.glob(f"{phase}-*-results.json"))
    if not matches:
        return [f"results artifact ausente: {phase}-<commit>-results.json "
                f"(run_g1r --phase {phase})"]
    if len(matches) > 1:
        return [f"results artifact ambiguo: {[m.name for m in matches]}"]
    results = matches[0]
    sha_file = results.with_suffix(".sha256")
    body = json.loads(results.read_text(encoding="utf-8"))
    parser_commit = body.get("parser_commit")
    if body.get("phase") != phase:
        problems.append(f"phase={body.get('phase')} != {phase}")
    if body.get("parser_commit_dirty"):
        problems.append("parser_commit_dirty=true")
    if not parser_commit:
        problems.append("parser_commit ausente")
    else:
        drift = _git("diff", "--name-only",
                     f"{parser_commit}..{head}", "--", *_RUN_INPUTS)
        if drift.strip():
            problems.append(
                f"run inputs cambiados desde parser_commit "
                f"{parser_commit[:7]}: {drift.strip()}")
    batch_sha = body.get("batch_sha256")
    if not sha_file.exists():
        problems.append(f"sha256 ausente: {sha_file.name}")
    elif batch_sha:
        m = re.match(r"([0-9a-f]{64})\s+(\S+)",
                     sha_file.read_text().strip())
        if not m or m.group(1) != batch_sha or m.group(2) != results.name:
            problems.append(f"sha256 invalido: {sha_file.name}")
    return problems


def cmd_gates(state, phase):
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"
    verdict = []
    fc = state["failure_classes"]
    active = fc["in_review"][0] if fc["in_review"] else None
    targets = state.get("targets", {}).get(active, {}) if active else {}
    dev_targets = set(targets.get("dev", []))
    g1_targets = set(targets.get("g1reg", []))

    try:
        head = _head()
        verdict.append(("results artifact ligado a HEAD",
                        not (p := results_artifact_problems(phase, head)),
                        "; ".join(p)))

        problems = holdout_problems(state)
        verdict.append(("HOLDOUT intacto (tree + freeze_ref + raw sha)",
                        not problems, "; ".join(problems)))

        test = _run([sys.executable, "-m", "pytest", "-x", "-q"], env,
                    allowed=(0, 1))
        verdict.append(("pytest", test.returncode == 0,
                        test.stdout.strip().splitlines()[-1]
                        if test.stdout.strip() else ""))

        # freshness: artefacto viejo no puede satisfacer el gate
        g1_json = RESULTS / f"{phase}-g1-oracle-eval.json"
        g1_json.unlink(missing_ok=True)
        g1 = _run([sys.executable, "scripts/_eval_g1_regression_oracle.py",
                   "--json", str(g1_json)], env, allowed=(0, 1))
        print(g1.stdout)
        if not g1_json.exists():
            raise GateError("evaluador G1 no produjo artefacto")
        known = set(state["g1_oracle"]["known_open_failures"]) - g1_targets
        fails = _fails_in_eval(g1_json)
        new_fails = sorted(set(fails) - known)
        all_ids = {_row_id(r) for r in _all_rows(g1_json)}
        unresolved = sorted(g1_targets & set(fails))
        missing = sorted(g1_targets - all_ids)
        verdict.append(("G1 oracle: sin FAIL nuevo", not new_fails,
                        "; ".join(new_fails)))
        if g1_targets:
            ok_targets = not unresolved and not missing
            verdict.append((f"G1 targets {active} resueltos", ok_targets,
                            "; ".join(unresolved
                                      + [f"{t} (target missing)"
                                         for t in missing])))

        dev_eval = RESULTS / f"{phase}-dev-oracle-eval.json"
        dev_eval.unlink(missing_ok=True)
        _run([sys.executable, "scripts/_eval_dev_oracle.py",
              "--phase", phase, "--out", str(dev_eval)], env)
        if not dev_eval.exists():
            raise GateError("evaluador DEV no produjo artefacto")
        report = json.loads(dev_eval.read_text(encoding="utf-8"))
        counts = report["status_counts"]
        clean = (counts.get("REGRESSED", 0) == 0
                 and counts.get("EMITTED_OTHER", 0) == 0
                 and counts.get("NOW_ABSENT", 0) == 0)
        verdict.append(("DEV oracle: 0 REGRESSED/EMITTED_OTHER/NOW_ABSENT",
                        clean, json.dumps(counts)))
        rows = {f"{r['frame_item_id']} :: {r['field']}": r
                for r in report["results"]}
        if dev_targets:
            bad = []
            for t in sorted(dev_targets):
                if t not in rows:
                    bad.append(f"{t} (target missing)")
                elif rows[t]["status"] not in TARGET_OK:
                    bad.append(f"{t} -> {rows[t]['status']}")
            verdict.append((f"DEV targets {active} resueltos",
                            not bad, "; ".join(bad)))
        other_p0 = [f"{k} -> {r['status']}" for k, r in rows.items()
                    if r["status"] == "P0_CHANGED_OTHER"
                    or (r["status"] == "P0_UNRESOLVED" and k in dev_targets)]
        verdict.append(("DEV: sin P0 fuera de eje", not other_p0,
                        "; ".join(other_p0)))
    except GateError as error:
        verdict.append(("INFRASTRUCTURE", False, str(error)))

    print("\n== GATES ==")
    stop = False
    for label, ok, detail in verdict:
        print(f"  {'PASS' if ok else 'STOP'}  {label}"
              + ("" if ok or not detail else f"  [{detail}]"))
        stop |= not ok
    print(f"\nVERDICT: {'STOP — no congelar checkpoint' if stop else 'PASS'}")
    return 1 if stop else 0


def _all_rows(path):
    report = json.loads(path.read_text(encoding="utf-8"))
    return report.get("correct", []) + report.get("incorrect", [])


def _row_id(r):
    return f"{r['id']} :: {r['field']}"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status")
    sub.add_parser("next")
    sub.add_parser("begin")
    g = sub.add_parser("gates")
    g.add_argument("--phase", required=True)
    args = ap.parse_args()

    state = load_state()
    if args.cmd == "next":
        return cmd_next(state) or 0
    if args.cmd == "begin":
        return cmd_begin(state)
    if args.cmd == "gates":
        return cmd_gates(state, args.phase)
    return cmd_status(state) or 0


if __name__ == "__main__":
    sys.exit(main())
