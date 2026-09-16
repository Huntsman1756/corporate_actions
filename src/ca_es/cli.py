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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
