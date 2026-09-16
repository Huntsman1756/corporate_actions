"""CLI de ca-es (interfaz minima G0)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .canonical import canonical_json
from .gates import evaluate_gates
from .pipeline import run_pipeline
from .reference.esma_firds import load_firds_listings
from .source_policy import load_source_policy
from .surface import load_surface

DEFAULT_RESULTS = Path("g0/results")
DEFAULT_POLICY = Path("docs/sources/source-policy.json")


def _repo_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    candidate = Path.cwd()
    for parent in [candidate, *candidate.parents]:
        if (parent / "pyproject.toml").exists() and (parent / "src" / "ca_es").exists():
            return parent
    return candidate.resolve()


def _resolver(repo_root: Path, relpath: str | None):
    if not relpath:
        return None
    path = repo_root / relpath
    if not path.exists():
        return None
    return load_firds_listings(path)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(payload) + "\n", encoding="utf-8")


def _load_policy(repo_root: Path):
    return load_source_policy(repo_root / "docs/sources/source-policy.json")


def cmd_run(args: argparse.Namespace) -> int:
    repo_root = _repo_root(args.repo_root)
    resolver = _resolver(repo_root, args.firds_listings)
    result = run_pipeline(
        repo_root,
        identity_ledger_relpath=args.identity_ledger,
        adjudications_relpath=args.adjudications,
        instrument_bindings_relpath=args.instrument_bindings,
        resolver=resolver,
        run_id=args.run_id,
        executed_at=args.executed_at,
    )
    out = Path(args.out) if args.out else repo_root / DEFAULT_RESULTS / "run.json"
    _write(out, result)
    print(
        json.dumps(
            {
                "run_id": result["run"]["run_id"],
                "events": result["metrics"]["events_detected"],
                "documents": result["metrics"]["documents_total"],
                "result_sha": result["result_sha"],
                "out": str(out),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def cmd_second_run(args: argparse.Namespace) -> int:
    repo_root = _repo_root(args.repo_root)
    resolver = _resolver(repo_root, args.firds_listings)
    first = run_pipeline(
        repo_root,
        identity_ledger_relpath=args.identity_ledger,
        adjudications_relpath=args.adjudications,
        instrument_bindings_relpath=args.instrument_bindings,
        resolver=resolver,
        run_id="run-001",
        executed_at="2026-09-13T00:00:00Z",
    )
    second = run_pipeline(
        repo_root,
        identity_ledger_relpath=args.identity_ledger,
        adjudications_relpath=args.adjudications,
        instrument_bindings_relpath=args.instrument_bindings,
        resolver=resolver,
        run_id="run-002",
        executed_at="2026-09-14T00:00:00Z",
    )
    deterministic = first["result_sha"] == second["result_sha"]
    _write(
        repo_root / DEFAULT_RESULTS / "second-run.json",
        {
            "run_1_sha": first["result_sha"],
            "run_2_sha": second["result_sha"],
            "deterministic": deterministic,
        },
    )
    print(json.dumps({"deterministic": deterministic}, sort_keys=True))
    return 0 if deterministic else 1


def cmd_gates(args: argparse.Namespace) -> int:
    repo_root = _repo_root(args.repo_root)
    resolver = _resolver(repo_root, args.firds_listings)
    result = run_pipeline(
        repo_root,
        identity_ledger_relpath=args.identity_ledger,
        adjudications_relpath=args.adjudications,
        instrument_bindings_relpath=args.instrument_bindings,
        resolver=resolver,
        run_id=args.run_id,
        executed_at=args.executed_at,
    )
    second = None
    if args.second_run:
        second = run_pipeline(
            repo_root,
            identity_ledger_relpath=args.identity_ledger,
            adjudications_relpath=args.adjudications,
        instrument_bindings_relpath=args.instrument_bindings,
            resolver=resolver,
            run_id="run-002",
            executed_at="2026-09-14T00:00:00Z",
        )
    policy = _load_policy(repo_root)
    report = evaluate_gates(result, policy=policy, second_run=second)
    out = Path(args.out) if args.out else repo_root / DEFAULT_RESULTS / "gate-report.json"
    _write(out, report)
    print(json.dumps({"overall": report["overall"], "counts": report["counts"]}, sort_keys=True))
    return 0 if report["overall"] == "PASS" else 1


def cmd_metrics(args: argparse.Namespace) -> int:
    repo_root = _repo_root(args.repo_root)
    resolver = _resolver(repo_root, args.firds_listings)
    result = run_pipeline(
        repo_root,
        identity_ledger_relpath=args.identity_ledger,
        adjudications_relpath=args.adjudications,
        instrument_bindings_relpath=args.instrument_bindings,
        resolver=resolver,
        run_id=args.run_id,
        executed_at=args.executed_at,
    )
    print(json.dumps(result["metrics"], ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def cmd_event(args: argparse.Namespace) -> int:
    repo_root = _repo_root(args.repo_root)
    resolver = _resolver(repo_root, args.firds_listings)
    result = run_pipeline(
        repo_root,
        identity_ledger_relpath=args.identity_ledger,
        adjudications_relpath=args.adjudications,
        instrument_bindings_relpath=args.instrument_bindings,
        resolver=resolver,
        run_id="lookup",
        executed_at="1970-01-01T00:00:00Z",
    )
    target = args.event_id
    match = None
    for event in result["body"]["events"]:
        if event["canonical_event_id"] == target or target in event["candidate_ids"]:
            match = event
            break
    if match is None:
        print(json.dumps({"status": "NOT_FOUND", "event_id": target}, sort_keys=True))
        return 1
    print(json.dumps(match, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def cmd_isin(args: argparse.Namespace) -> int:
    repo_root = _repo_root(args.repo_root)
    resolver = _resolver(repo_root, args.firds_listings)
    result = run_pipeline(
        repo_root,
        identity_ledger_relpath=args.identity_ledger,
        adjudications_relpath=args.adjudications,
        instrument_bindings_relpath=args.instrument_bindings,
        resolver=resolver,
        run_id="lookup",
        executed_at="1970-01-01T00:00:00Z",
    )
    events = [
        event for event in result["body"]["events"] if event.get("isin") == args.isin
    ]
    print(json.dumps({"isin": args.isin, "events": events}, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if events else 1


# --------------------------------------------------------------------- G3
# Subcomandos de superficie operacional (G3): consumen un artefacto
# CA_ES_OPERATIONAL_CANON_V1 ya generado (--canon) + source-policy.json
# READ_ONLY. Thin adapter: la semantica vive en ca_es.surface.


def _surface(args: argparse.Namespace):
    repo_root = _repo_root(args.repo_root)
    policy = Path(args.policy) if args.policy else repo_root / DEFAULT_POLICY
    return load_surface(Path(args.canon), policy)


def _emit(payload: object) -> int:
    if payload is None:
        print(json.dumps({"status": "NOT_FOUND"}, sort_keys=True))
        return 1
    print(canonical_json(payload))
    return 0


def cmd_events(args: argparse.Namespace) -> int:
    surface = _surface(args)
    return _emit(
        {
            "events": surface.search(
                isin=args.isin, event_type=args.type, issuer=args.issuer
            )
        }
    )


def cmd_show(args: argparse.Namespace) -> int:
    return _emit(_surface(args).show(args.canonical_event_id))


def cmd_timeline(args: argparse.Namespace) -> int:
    return _emit(_surface(args).timeline(args.canonical_event_id))


def cmd_conflicts(args: argparse.Namespace) -> int:
    return _emit(_surface(args).conflicts(args.canonical_event_id))


def cmd_evidence(args: argparse.Namespace) -> int:
    return _emit(_surface(args).evidence(args.assertion_id))


def cmd_export_event(args: argparse.Namespace) -> int:
    if args.format != "json":
        print(json.dumps({"status": "UNSUPPORTED_FORMAT", "format": args.format}))
        return 2
    return _emit(_surface(args).export_event(args.canonical_event_id))


def _load_previous(args: argparse.Namespace):
    if not args.previous_canon:
        return None
    repo_root = _repo_root(args.repo_root)
    policy = Path(args.policy) if args.policy else repo_root / DEFAULT_POLICY
    return load_surface(Path(args.previous_canon), policy)


def cmd_brief(args: argparse.Namespace) -> int:
    from .surface import render_brief

    surface = _surface(args)
    brief = surface.brief(
        args.as_of,
        window_days=args.window,
        previous=_load_previous(args),
    )
    if args.format == "text":
        print(render_brief(brief), end="")
        return 0
    return _emit(brief)


def cmd_desk(args: argparse.Namespace) -> int:
    try:
        from .desk import build_desk_model
        from .desk_tui import OpsDesk
    except ImportError:
        print(
            json.dumps(
                {
                    "status": "DESK_UNAVAILABLE",
                    "hint": "pip install 'ca-es[desk]'",
                },
                sort_keys=True,
            )
        )
        return 2
    surface = _surface(args)
    previous = _load_previous(args)
    brief = surface.brief(
        args.as_of,
        window_days=args.window,
        previous=previous,
    )
    OpsDesk(
        build_desk_model(brief),
        surface,
        previous_surface=previous,
    ).run()
    return 0


def cmd_entitlement(args: argparse.Namespace) -> int:
    from .entitlement_engine import compute_entitlements, load_positions

    surface = _surface(args)
    try:
        positions = load_positions(Path(args.positions))
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "INVALID_POSITIONS", "detail": str(exc)}))
        return 2
    return _emit(
        compute_entitlements(surface, args.event, positions)
    )


def _recon_doc(args: argparse.Namespace):
    """recon doc desde --recon, o calculado (--entitlements+--cash o
    --canon+--event+--positions+--cash). Devuelve (doc, exit_code)."""
    from .entitlement_engine import compute_entitlements, load_positions
    from .reconciliation import load_movements, reconcile

    if getattr(args, "recon", None):
        return (
            json.loads(Path(args.recon).read_text(encoding="utf-8")),
            0,
        )
    if args.entitlements:
        entitlement_doc = json.loads(
            Path(args.entitlements).read_text(encoding="utf-8")
        )
    elif args.canon and args.event and args.positions:
        surface = _surface(args)
        try:
            positions = load_positions(Path(args.positions))
        except (ValueError, OSError) as exc:
            print(
                json.dumps(
                    {"status": "INVALID_POSITIONS", "detail": str(exc)}
                )
            )
            return None, 2
        entitlement_doc = compute_entitlements(
            surface, args.event, positions
        )
        if entitlement_doc is None:
            print(json.dumps({"status": "NOT_FOUND"}, sort_keys=True))
            return None, 1
    else:
        print(
            json.dumps(
                {
                    "status": "MISSING_INPUT",
                    "detail": (
                        "--recon, --entitlements+--cash o "
                        "--canon+--event+--positions+--cash"
                    ),
                },
                sort_keys=True,
            )
        )
        return None, 2
    if not args.cash:
        print(
            json.dumps(
                {"status": "MISSING_INPUT", "detail": "--cash requerido"},
                sort_keys=True,
            )
        )
        return None, 2
    try:
        movements = load_movements(Path(args.cash))
    except (ValueError, OSError) as exc:
        print(
            json.dumps({"status": "INVALID_MOVEMENTS", "detail": str(exc)})
        )
        return None, 2
    return reconcile(entitlement_doc, movements), 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    doc, code = _recon_doc(args)
    if doc is None:
        return code
    return _emit(doc)


def cmd_exceptions(args: argparse.Namespace) -> int:
    from .exceptions import build_cases_doc, load_cases

    recon_doc, code = _recon_doc(args)
    if recon_doc is None:
        return code
    previous = None
    if args.cases:
        try:
            previous = load_cases(Path(args.cases))["cases"]
        except (ValueError, OSError, KeyError) as exc:
            print(
                json.dumps(
                    {"status": "INVALID_CASES", "detail": str(exc)}
                )
            )
            return 2
    return _emit(build_cases_doc(recon_doc, previous, now=args.now))


def cmd_case_transition(args: argparse.Namespace) -> int:
    from .exceptions import apply_transition, load_cases, queue

    try:
        doc = load_cases(Path(args.cases))
    except (ValueError, OSError) as exc:
        print(
            json.dumps({"status": "INVALID_CASES", "detail": str(exc)})
        )
        return 2
    case = next(
        (c for c in doc["cases"] if c["case_key"] == args.case_key),
        None,
    )
    if case is None:
        print(
            json.dumps(
                {"status": "CASE_NOT_FOUND", "case_key": args.case_key},
                sort_keys=True,
            )
        )
        return 1
    try:
        apply_transition(
            case,
            args.to,
            actor=args.actor,
            at=args.now,
            note=args.note or "",
            resolution_code=args.resolution_code,
            assigned_to=args.assign_to,
        )
    except ValueError as exc:
        print(
            json.dumps({"status": "INVALID_TRANSITION", "detail": str(exc)})
        )
        return 2
    doc["generated_at"] = args.now
    doc["queue"] = queue(doc["cases"])
    by_workflow: dict = {}
    for c in doc["cases"]:
        by_workflow[c["workflow_status"]] = (
            by_workflow.get(c["workflow_status"], 0) + 1
        )
    doc["summary"]["by_workflow"] = by_workflow
    doc["summary"]["observed"] = sum(
        1 for c in doc["cases"] if c.get("observed")
    )
    if args.out:
        Path(args.out).write_text(
            json.dumps(doc, indent=1, ensure_ascii=False, default=str)
            + "\n",
            encoding="utf-8",
        )
        return 0
    return _emit(doc)


def cmd_swift_facts(args: argparse.Namespace) -> int:
    from .swift_mt import AdapterUnavailable, parse_mt

    try:
        fin = Path(args.fin).read_bytes().decode("utf-8")
    except OSError as exc:
        print(json.dumps({"status": "INVALID_INPUT", "detail": str(exc)}))
        return 2
    try:
        doc, code = parse_mt(fin)
    except AdapterUnavailable as exc:
        print(json.dumps({"status": "ADAPTER_UNAVAILABLE",
                          "detail": str(exc)}))
        return 2
    _emit(doc)
    return code


def _facts_doc(args: argparse.Namespace):
    """CA_ES_SWIFT_MT_FACTS_V1 desde --facts o via adapter (--fin).
    Devuelve (doc, exit_code)."""
    from .swift_mt import AdapterUnavailable, parse_mt

    if getattr(args, "facts", None):
        return json.loads(Path(args.facts).read_text(encoding="utf-8")), 0
    try:
        fin = Path(args.fin).read_bytes().decode("utf-8")
    except OSError as exc:
        print(json.dumps({"status": "INVALID_INPUT", "detail": str(exc)}))
        return None, 2
    try:
        doc, _ = parse_mt(fin)
    except AdapterUnavailable as exc:
        print(json.dumps({"status": "ADAPTER_UNAVAILABLE",
                          "detail": str(exc)}))
        return None, 2
    return doc, 0


def cmd_swift_project(args: argparse.Namespace) -> int:
    from .swift_ca import project_ca_message

    facts_doc, code = _facts_doc(args)
    if facts_doc is None:
        return code
    try:
        doc = project_ca_message(facts_doc, now=args.now)
    except ValueError as exc:
        print(json.dumps({"status": "INVALID_FACTS", "detail": str(exc)}))
        return 2
    return _emit(doc)


def cmd_swift_bind(args: argparse.Namespace) -> int:
    from .swift_ca import bind_event, project_ca_message

    facts_doc, code = _facts_doc(args)
    if facts_doc is None:
        return code
    try:
        msg = project_ca_message(facts_doc, now=args.now)
    except ValueError as exc:
        print(json.dumps({"status": "INVALID_FACTS", "detail": str(exc)}))
        return 2
    try:
        canon = json.loads(Path(args.canon).read_text(encoding="utf-8"))
    except OSError as exc:
        print(json.dumps({"status": "INVALID_INPUT", "detail": str(exc)}))
        return 2
    doc = bind_event(msg, canon, now=args.now)
    doc["ca_message"] = msg
    return _emit(doc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ca-es", description=__doc__)
    parser.add_argument("--repo-root", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--identity-ledger", default=None)
    common.add_argument("--adjudications", default=None)
    common.add_argument("--instrument-bindings", default=None)
    common.add_argument("--firds-listings", default=None)

    run = sub.add_parser("run", parents=[common])
    run.add_argument("--run-id", default="run-001")
    run.add_argument("--executed-at", default="2026-09-13T00:00:00Z")
    run.add_argument("--out", default=None)
    run.set_defaults(func=cmd_run)

    second = sub.add_parser("second-run", parents=[common])
    second.set_defaults(func=cmd_second_run)

    gates = sub.add_parser("gates", parents=[common])
    gates.add_argument("--run-id", default="run-001")
    gates.add_argument("--executed-at", default="2026-09-13T00:00:00Z")
    gates.add_argument("--second-run", action="store_true")
    gates.add_argument("--out", default=None)
    gates.set_defaults(func=cmd_gates)

    metrics = sub.add_parser("metrics", parents=[common])
    metrics.add_argument("--run-id", default="run-001")
    metrics.add_argument("--executed-at", default="2026-09-13T00:00:00Z")
    metrics.set_defaults(func=cmd_metrics)

    event = sub.add_parser("event", parents=[common])
    event.add_argument("event_id")
    event.set_defaults(func=cmd_event)

    isin = sub.add_parser("isin", parents=[common])
    isin.add_argument("isin")
    isin.set_defaults(func=cmd_isin)

    surface_common = argparse.ArgumentParser(add_help=False)
    surface_common.add_argument("--canon", required=True)
    surface_common.add_argument("--policy", default=None)

    events = sub.add_parser("events", parents=[surface_common])
    events.add_argument("--isin", default=None)
    events.add_argument("--type", dest="type", default=None)
    events.add_argument("--issuer", default=None)
    events.set_defaults(func=cmd_events)

    show = sub.add_parser("show", parents=[surface_common])
    show.add_argument("canonical_event_id")
    show.set_defaults(func=cmd_show)

    timeline = sub.add_parser("timeline", parents=[surface_common])
    timeline.add_argument("canonical_event_id")
    timeline.set_defaults(func=cmd_timeline)

    conflicts = sub.add_parser("conflicts", parents=[surface_common])
    conflicts.add_argument("canonical_event_id")
    conflicts.set_defaults(func=cmd_conflicts)

    evidence = sub.add_parser("evidence", parents=[surface_common])
    evidence.add_argument("assertion_id")
    evidence.set_defaults(func=cmd_evidence)

    export = sub.add_parser("export", parents=[surface_common])
    export.add_argument("canonical_event_id")
    export.add_argument("--format", default="json")
    export.set_defaults(func=cmd_export_event)

    brief = sub.add_parser("brief", parents=[surface_common])
    brief.add_argument("--as-of", required=True)
    brief.add_argument("--previous-canon", default=None)
    brief.add_argument("--window", type=int, default=7)
    brief.add_argument("--format", choices=["json", "text"], default="text")
    brief.set_defaults(func=cmd_brief)

    desk = sub.add_parser("desk", parents=[surface_common])
    desk.add_argument("--as-of", required=True)
    desk.add_argument("--previous-canon", default=None)
    desk.add_argument("--window", type=int, default=7)
    desk.set_defaults(func=cmd_desk)

    entitlement = sub.add_parser("entitlement", parents=[surface_common])
    entitlement.add_argument("--event", required=True)
    entitlement.add_argument("--positions", required=True)
    entitlement.set_defaults(func=cmd_entitlement)

    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("--canon", default=None)
    reconcile.add_argument("--policy", default=None)
    reconcile.add_argument("--event", default=None)
    reconcile.add_argument("--positions", default=None)
    reconcile.add_argument("--entitlements", default=None)
    reconcile.add_argument("--cash", required=True)
    reconcile.set_defaults(func=cmd_reconcile)

    exceptions = sub.add_parser("exceptions")
    exceptions.add_argument("--recon", default=None,
                            help="doc CA_ES_CASH_RECON_V1 ya calculado")
    exceptions.add_argument("--canon", default=None)
    exceptions.add_argument("--policy", default=None)
    exceptions.add_argument("--event", default=None)
    exceptions.add_argument("--positions", default=None)
    exceptions.add_argument("--entitlements", default=None)
    exceptions.add_argument("--cash", default=None)
    exceptions.add_argument("--cases", default=None,
                            help="doc CA_ES_EXCEPTION_CASES_V1 previo")
    exceptions.add_argument("--now", required=True,
                            help="timestamp ISO de esta ejecucion")
    exceptions.set_defaults(func=cmd_exceptions)

    transition = sub.add_parser("case-transition")
    transition.add_argument("--cases", required=True)
    transition.add_argument("--case-key", required=True)
    transition.add_argument("--to", required=True)
    transition.add_argument("--actor", required=True)
    transition.add_argument("--note", default=None)
    transition.add_argument("--resolution-code", default=None)
    transition.add_argument("--assign-to", default=None)
    transition.add_argument("--now", required=True)
    transition.add_argument("--out", default=None)
    transition.set_defaults(func=cmd_case_transition)

    swift_facts = sub.add_parser("swift-facts")
    swift_facts.add_argument("--fin", required=True,
                             help="fichero con el mensaje FIN raw "
                                  "(MT564/MT566); viaja al adapter JVM "
                                  "solo por stdin")
    swift_facts.set_defaults(func=cmd_swift_facts)

    project = sub.add_parser("swift-project")
    project.add_argument("--fin", default=None)
    project.add_argument("--facts", default=None,
                         help="doc CA_ES_SWIFT_MT_FACTS_V1 ya calculado")
    project.add_argument("--now", default=None)
    project.set_defaults(func=cmd_swift_project)

    bind = sub.add_parser("swift-bind")
    bind.add_argument("--fin", default=None)
    bind.add_argument("--facts", default=None)
    bind.add_argument("--canon", required=True)
    bind.add_argument("--now", default=None)
    bind.set_defaults(func=cmd_swift_bind)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
