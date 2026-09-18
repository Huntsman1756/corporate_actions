"""CLI de ca-es (interfaz minima G0)."""
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from .canonical import canonical_json, load_strict_json_object
from .gates import evaluate_gates
from .pipeline import run_pipeline
from .reference.esma_firds import load_firds_listings
from .source_policy import load_source_policy
from .surface import Surface

DEFAULT_RESULTS = Path("g0/results")
DEFAULT_POLICY = Path("docs/sources/source-policy.json")


class _InputError(Exception):
    pass


def _read_json(path: str | Path, label: str) -> dict:
    try:
        return load_strict_json_object(path)
    except (OSError, ValueError) as exc:
        raise _InputError(f"{label}: {exc}") from exc


def _input_error(exc: _InputError) -> int:
    print(json.dumps({"status": "INVALID_INPUT", "detail": str(exc)}))
    return 2


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
    return Surface(
        _read_json(args.canon, "canon"), _read_json(policy, "policy")
    )


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
    return Surface(
        _read_json(args.previous_canon, "previous-canon"),
        _read_json(policy, "policy"),
    )


def cmd_brief(args: argparse.Namespace) -> int:
    from .surface import render_brief

    surface = _surface(args)
    if args.queue:
        queue, code = _load_json(args.queue, "queue")
        if queue is None:
            return code
        try:
            brief = surface.brief_v2(
                args.as_of, queue, previous=_load_previous(args))
        except ValueError as exc:
            print(json.dumps({"status": str(exc)}))
            return 2
    else:
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
    if getattr(args, "latest", False):
        return _cmd_desk_latest(args, OpsDesk, build_desk_model)
    if not args.canon or not args.as_of:
        print(json.dumps({
            "status": "INVALID_INPUT",
            "detail": "--canon y --as-of requeridos "
                      "(o usa --latest --state)",
        }))
        return 2
    surface = _surface(args)
    previous = _load_previous(args)
    if args.queue:
        queue, code = _load_json(args.queue, "queue")
        if queue is None:
            return code
        try:
            brief = surface.brief_v2(
                args.as_of, queue, previous=previous)
        except ValueError as exc:
            print(json.dumps({"status": str(exc)}))
            return 2
    else:
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


def _cmd_desk_latest(args, OpsDesk, build_desk_model) -> int:
    """desk sobre el ultimo run SUCCEEDED: consume artefactos
    persistidos, nunca recalcula."""
    from .surface import Surface

    if not args.state:
        print(json.dumps({
            "status": "INVALID_INPUT",
            "detail": "--latest requiere --state",
        }))
        return 2
    state, code = _open_state(args)
    if state is None:
        return code
    try:
        with state.open() as conn:
            run = state.latest_successful_run(conn)
            if run is None:
                print(json.dumps({"status": "NO_SUCCESSFUL_RUN"}))
                return 1
            steps = {s["step_id"]: s
                     for s in state.get_steps(conn, run["run_id"])}
            brief_sha = (steps.get("morning_brief_v2") or {}
                         ).get("output_sha256")
            inputs_sha = (steps.get("validate_inputs") or {}
                          ).get("output_sha256")
            if not brief_sha or not inputs_sha:
                print(json.dumps({
                    "status": "LATEST_RUN_INCOMPLETE"}))
                return 2
            brief = state.get_artifact(brief_sha)
            inputs_doc = state.get_artifact(inputs_sha)
            canon_ref = (inputs_doc.get("inputs") or {}
                         ).get("canon")
            policy_ref = (inputs_doc.get("inputs") or {}
                          ).get("source_policy")
            canon = state.get_artifact(canon_ref["sha256"])
            policy = (state.get_artifact(policy_ref["sha256"])
                      if policy_ref else {})
            surface = Surface(canon, policy)
    except Exception as exc:
        print(json.dumps({
            "status": "DESK_LATEST_ERROR",
            "detail": str(exc)[:200],
        }))
        return 2
    OpsDesk(build_desk_model(brief), surface).run()
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
        return _load_json(args.recon, "recon")
    if args.entitlements:
        entitlement_doc, code = _load_json(args.entitlements, "entitlements")
        if entitlement_doc is None:
            return None, code
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
    expected_cash = None
    if getattr(args, "expected_cash", None):
        expected_cash, code = _load_json(
            args.expected_cash, "expected-cash")
        if expected_cash is None:
            return None, code
    try:
        doc = reconcile(entitlement_doc, movements,
                        expected_cash_doc=expected_cash)
    except ValueError as exc:
        print(json.dumps({"status": "INVALID_INPUT", "detail": str(exc)}))
        return None, 2
    return doc, 0


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
            store = load_cases(Path(args.cases))
            event_id = store.get("canonical_event_id")
            if not isinstance(event_id, str) or not event_id.strip():
                raise ValueError("INVALID_CASES_EVENT_ID")
            if event_id != recon_doc.get("canonical_event_id"):
                raise ValueError("CASES_EVENT_MISMATCH")
            previous = store["cases"]
        except (ValueError, OSError) as exc:
            print(
                json.dumps(
                    {"status": "INVALID_CASES", "detail": str(exc)}
                )
            )
            return 2
    try:
        doc = build_cases_doc(recon_doc, previous, now=args.now)
    except ValueError as exc:
        print(json.dumps({"status": "INVALID_INPUT", "detail": str(exc)}))
        return 2
    return _emit(doc)


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


def cmd_mx_facts(args: argparse.Namespace) -> int:
    from .mx_facts import parse_mx
    from .swift_mt import AdapterUnavailable

    try:
        xml = Path(args.mx).read_bytes()
    except OSError as exc:
        print(json.dumps({"status": "INVALID_INPUT", "detail": str(exc)}))
        return 2
    try:
        doc, code = parse_mx(xml)
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
        return _load_json(args.facts, "facts")
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


def _mx_facts_doc(args: argparse.Namespace):
    """CA_ES_SWIFT_MX_FACTS_V1 desde --facts o via adapter (--mx)."""
    from .mx_facts import parse_mx
    from .swift_mt import AdapterUnavailable

    if getattr(args, "facts", None):
        return _load_json(args.facts, "facts")
    try:
        xml = Path(args.mx).read_bytes()
    except OSError as exc:
        print(json.dumps({"status": "INVALID_INPUT", "detail": str(exc)}))
        return None, 2
    try:
        return parse_mx(xml)
    except AdapterUnavailable as exc:
        print(json.dumps({"status": "ADAPTER_UNAVAILABLE",
                          "detail": str(exc)}))
        return None, 2


def cmd_mx_project(args: argparse.Namespace) -> int:
    from .mx_ca import project_mx_message

    facts_doc, code = _mx_facts_doc(args)
    if facts_doc is None:
        return code
    try:
        doc = project_mx_message(facts_doc, now=args.now)
    except ValueError as exc:
        print(json.dumps({"status": "INVALID_FACTS", "detail": str(exc)}))
        return 2
    return _emit(doc)


def cmd_mx_bind(args: argparse.Namespace) -> int:
    from .mx_ca import project_mx_message
    from .swift_ca import bind_event

    facts_doc, code = _mx_facts_doc(args)
    if facts_doc is None:
        return code
    try:
        msg = project_mx_message(facts_doc, now=args.now)
    except ValueError as exc:
        print(json.dumps({"status": "INVALID_FACTS", "detail": str(exc)}))
        return 2
    canon, code = _load_json(args.canon, "canon")
    if canon is None:
        return code
    doc = bind_event(msg, canon, now=args.now)
    doc["ca_message"] = msg
    return _emit(doc)


def cmd_mx_election(args: argparse.Namespace) -> int:
    from .mx_ca import project_mx_election

    facts_doc, code = _mx_facts_doc(args)
    if facts_doc is None:
        return code
    canon, code = _load_json(args.canon, "canon")
    if canon is None:
        return code
    queue = None
    if args.queue:
        queue, code = _load_json(args.queue, "queue")
        if queue is None:
            return code
        if not args.deadline_type:
            print(json.dumps({"status": "MISSING_DEADLINE_TYPE_CONFIG"}))
            return 2
    try:
        doc = project_mx_election(
            facts_doc, canon, queue_doc=queue,
            deadline_types=tuple(args.deadline_type or ()),
            now=args.now)
    except ValueError as exc:
        print(json.dumps({"status": str(exc)}))
        return 2
    return _emit(doc)


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
    canon, code = _load_json(args.canon, "canon")
    if canon is None:
        return code
    doc = bind_event(msg, canon, now=args.now)
    doc["ca_message"] = msg
    return _emit(doc)


def cmd_swift_cash_candidate(args: argparse.Namespace) -> int:
    from .swift_cash import cash_candidate

    facts_doc, code = _facts_doc(args)
    if facts_doc is None:
        return code
    canon, code = _load_json(args.canon, "canon")
    if canon is None:
        return code
    try:
        doc = cash_candidate(facts_doc, canon, now=args.now)
    except ValueError as exc:
        print(json.dumps({"status": "INVALID_FACTS", "detail": str(exc)}))
        return 2
    return _emit(doc)


def _load_json(path: str, label: str):
    try:
        return _read_json(path, label), 0
    except _InputError as exc:
        return None, _input_error(exc)


def cmd_deadlines(args: argparse.Namespace) -> int:
    from .deadlines import compute_deadlines

    canon, code = _load_json(args.canon, "canon")
    if canon is None:
        return code
    rules, code = _load_json(args.rules, "rules")
    if rules is None:
        return code
    calendars, code = _load_json(args.calendars, "calendars")
    if calendars is None:
        return code
    try:
        doc = compute_deadlines(
            canon, rules, calendars, event_id=args.event, now=args.now)
    except ValueError as exc:
        print(json.dumps({"status": "INVALID_INPUT", "detail": str(exc)}))
        return 2
    return _emit(doc)


def cmd_action_queue(args: argparse.Namespace) -> int:
    from .action_queue import build_action_queue

    deadlines, code = _load_json(args.deadlines, "deadlines")
    if deadlines is None:
        return code
    try:
        doc = build_action_queue(
            deadlines, args.as_of,
            window_days=args.window_days,
            due_soon_days=args.due_soon_days,
            now=args.now)
    except ValueError as exc:
        print(json.dumps({"status": "INVALID_INPUT",
                          "detail": str(exc)}))
        return 2
    return _emit(doc)


def cmd_swift_election(args: argparse.Namespace) -> int:
    from .election import project_election

    facts_doc, code = _facts_doc(args)
    if facts_doc is None:
        return code
    canon, code = _load_json(args.canon, "canon")
    if canon is None:
        return code
    queue = None
    if args.queue:
        queue, code = _load_json(args.queue, "queue")
        if queue is None:
            return code
        if not args.deadline_type:
            print(json.dumps({"status": "MISSING_DEADLINE_TYPE_CONFIG"}))
            return 2
    try:
        doc = project_election(
            facts_doc, canon, queue_doc=queue,
            deadline_types=tuple(args.deadline_type or ()),
            now=args.now)
    except ValueError as exc:
        print(json.dumps({"status": str(exc)}))
        return 2
    return _emit(doc)


def cmd_election_eligibility(args: argparse.Namespace) -> int:
    from .election_eligibility import compute_election_eligibility
    from .entitlement_engine import load_positions

    opportunity, code = _load_json(args.opportunity, "opportunity")
    if opportunity is None:
        return code
    canon, code = _load_json(args.canon, "canon")
    if canon is None:
        return code
    try:
        positions = load_positions(Path(args.positions))
    except (ValueError, OSError) as exc:
        print(
            json.dumps(
                {"status": "INVALID_POSITIONS", "detail": str(exc)}
            )
        )
        return 2
    rules, code = _load_json(args.rules, "rules")
    if rules is None:
        return code
    try:
        doc = compute_election_eligibility(
            opportunity, canon, positions, rules, now=args.now
        )
    except ValueError as exc:
        print(json.dumps({"status": str(exc)}))
        return 2
    return _emit(doc)


def cmd_election_instruction(args: argparse.Namespace) -> int:
    from .election_instruction import build_instruction

    eligibility, code = _load_json(args.eligibility, "eligibility")
    if eligibility is None:
        return code
    opportunity, code = _load_json(args.opportunity, "opportunity")
    if opportunity is None:
        return code
    request, code = _load_json(args.request, "request")
    if request is None:
        return code
    try:
        doc = build_instruction(
            eligibility, opportunity, request, now=args.now
        )
    except ValueError as exc:
        print(json.dumps({"status": str(exc)}))
        return 2
    return _emit(doc)


def cmd_mt565_project(args: argparse.Namespace) -> int:
    from .mt565 import mt565_project

    instruction, code = _load_json(args.instruction, "instruction")
    if instruction is None:
        return code
    facts_doc, code = _facts_doc(args)
    if facts_doc is None:
        return code
    envelope, code = _load_json(args.envelope, "envelope")
    if envelope is None:
        return code
    try:
        doc = mt565_project(
            instruction, facts_doc, envelope, now=args.now
        )
    except ValueError as exc:
        print(json.dumps({"status": str(exc)}))
        return 2
    return _emit(doc)


def cmd_mt565_write(args: argparse.Namespace) -> int:
    from .mt565 import write_mt565
    from .swift_mt import AdapterUnavailable

    projection, code = _load_json(args.projection, "projection")
    if projection is None:
        return code
    try:
        doc, write_code = write_mt565(projection)
    except AdapterUnavailable as exc:
        print(json.dumps({"status": "ADAPTER_UNAVAILABLE",
                          "detail": str(exc)}))
        return 2
    _emit(doc)
    return write_code


def _source_facts_doc(args: argparse.Namespace):
    """Facts de la notificacion fuente: MX (--mx) o MT (--fin/--facts)."""
    if getattr(args, "mx", None):
        return _mx_facts_doc(args)
    return _facts_doc(args)


def cmd_seev033_project(args: argparse.Namespace) -> int:
    from .seev033 import seev033_project

    instruction, code = _load_json(args.instruction, "instruction")
    if instruction is None:
        return code
    facts_doc, code = _source_facts_doc(args)
    if facts_doc is None:
        return code
    envelope, code = _load_json(args.envelope, "envelope")
    if envelope is None:
        return code
    try:
        doc = seev033_project(
            instruction, facts_doc, envelope, now=args.now
        )
    except ValueError as exc:
        print(json.dumps({"status": str(exc)}))
        return 2
    return _emit(doc)


def cmd_seev033_write(args: argparse.Namespace) -> int:
    from .seev033 import write_seev033
    from .swift_mt import AdapterUnavailable

    projection, code = _load_json(args.projection, "projection")
    if projection is None:
        return code
    try:
        doc, write_code = write_seev033(projection)
    except AdapterUnavailable as exc:
        print(json.dumps({"status": "ADAPTER_UNAVAILABLE",
                          "detail": str(exc)}))
        return 2
    _emit(doc)
    return write_code


def cmd_position_impact(args: argparse.Namespace) -> int:
    from .entitlement_engine import load_positions
    from .position_impact import compute_position_impact

    canon, code = _load_json(args.canon, "canon")
    if canon is None:
        return code
    try:
        positions = load_positions(Path(args.positions))
    except (ValueError, OSError) as exc:
        print(
            json.dumps(
                {"status": "INVALID_POSITIONS", "detail": str(exc)}
            )
        )
        return 2
    rules, code = _load_json(args.rules, "impact rules")
    if rules is None:
        return code
    entitlements = None
    if args.entitlements:
        entitlements, code = _load_json(args.entitlements, "entitlements")
        if entitlements is None:
            return code
    try:
        doc = compute_position_impact(
            canon, args.event, positions, rules,
            entitlements_doc=entitlements, now=args.now)
    except ValueError as exc:
        print(json.dumps({"status": str(exc)}))
        return 2
    return _emit(doc)


def cmd_project_positions(args: argparse.Namespace) -> int:
    from .projected_positions import project_positions

    positions, code = _load_json(args.positions, "positions")
    if positions is None:
        return code
    impact, code = _load_json(args.impact, "impact")
    if impact is None:
        return code
    try:
        doc = project_positions(positions, impact, now=args.now)
    except ValueError as exc:
        print(json.dumps({"status": str(exc)}))
        return 2
    return _emit(doc)


def cmd_swift_security_candidate(args: argparse.Namespace) -> int:
    from .swift_securities import security_movement_candidate

    facts_doc, code = _facts_doc(args)
    if facts_doc is None:
        return code
    canon, code = _load_json(args.canon, "canon")
    if canon is None:
        return code
    try:
        doc = security_movement_candidate(facts_doc, canon, now=args.now)
    except ValueError as exc:
        print(json.dumps({"status": str(exc)}))
        return 2
    return _emit(doc)


def cmd_mx_cash_candidate(args: argparse.Namespace) -> int:
    from .mx_movement import mx_cash_candidate

    facts_doc, code = _mx_facts_doc(args)
    if facts_doc is None:
        return code
    canon, code = _load_json(args.canon, "canon")
    if canon is None:
        return code
    try:
        doc = mx_cash_candidate(facts_doc, canon, now=args.now)
    except ValueError as exc:
        print(json.dumps({"status": "INVALID_FACTS", "detail": str(exc)}))
        return 2
    return _emit(doc)


def cmd_mx_security_candidate(args: argparse.Namespace) -> int:
    from .mx_movement import mx_security_movement_candidate

    facts_doc, code = _mx_facts_doc(args)
    if facts_doc is None:
        return code
    canon, code = _load_json(args.canon, "canon")
    if canon is None:
        return code
    try:
        doc = mx_security_movement_candidate(
            facts_doc, canon, now=args.now)
    except ValueError as exc:
        print(json.dumps({"status": str(exc)}))
        return 2
    return _emit(doc)


def cmd_security_reconcile(args: argparse.Namespace) -> int:
    from .security_recon import reconcile_security_movements

    impact, code = _load_json(args.impact, "impact")
    if impact is None:
        return code
    candidates = []
    for path in args.candidates or []:
        doc, code = _load_json(path, "security candidate")
        if doc is None:
            return code
        candidates.append(doc)
    try:
        doc = reconcile_security_movements(impact, candidates,
                                           now=args.now)
    except ValueError as exc:
        print(json.dumps({"status": str(exc)}))
        return 2
    return _emit(doc)


def cmd_portfolio_impact(args: argparse.Namespace) -> int:
    from .portfolio_impact import aggregate_portfolio_impact

    impact, code = _load_json(args.impact, "impact")
    if impact is None:
        return code
    try:
        doc = aggregate_portfolio_impact(impact, now=args.now)
    except ValueError as exc:
        print(json.dumps({"status": str(exc)}))
        return 2
    return _emit(doc)


def cmd_instruction_status(args: argparse.Namespace) -> int:
    from .instruction_status import bind_instruction_status

    facts_doc, code = _facts_doc(args)
    if facts_doc is None:
        return code
    instruction, code = _load_json(args.instruction, "instruction")
    if instruction is None:
        return code
    try:
        doc = bind_instruction_status(
            facts_doc, instruction, now=args.now
        )
    except ValueError as exc:
        print(json.dumps({"status": str(exc)}))
        return 2
    return _emit(doc)


def cmd_mx_instruction_status(args: argparse.Namespace) -> int:
    from .mx_status import bind_mx_instruction_status

    facts_doc, code = _mx_facts_doc(args)
    if facts_doc is None:
        return code
    instruction, code = _load_json(args.instruction, "instruction")
    if instruction is None:
        return code
    try:
        doc = bind_mx_instruction_status(
            facts_doc, instruction, now=args.now
        )
    except ValueError as exc:
        print(json.dumps({"status": str(exc)}))
        return 2
    return _emit(doc)


# ------------------------------------------------------------------
# P7 — runtime operativo
# ------------------------------------------------------------------

def _open_state(args) -> tuple:
    """Abre el state store; exige ops-init previo."""
    from .ops_state import OpsState

    state = OpsState(args.state)
    if not state.db_path.is_file():
        print(json.dumps({
            "status": "OPS_STATE_NOT_INITIALIZED",
            "detail": f"{state.db_path} — ejecuta ops-init primero",
        }))
        return None, 2
    return state, 0


def cmd_ops_init(args: argparse.Namespace) -> int:
    from .ops_state import OPS_STATE_SCHEMA_VERSION, OpsState

    OpsState(args.state).init()
    return _emit({
        "status": "INITIALIZED",
        "state": str(args.state),
        "ops_state_schema_version": OPS_STATE_SCHEMA_VERSION,
    })


def cmd_ops_run(args: argparse.Namespace) -> int:
    from .ops_dag import run_ops
    from .ops_state import OpsRunAlreadyActive, OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    config, code = _load_json(args.config, "config")
    if config is None:
        return code
    try:
        manifest = run_ops(
            config, state, as_of=args.as_of,
            resume_run_id=args.resume)
    except OpsRunAlreadyActive:
        print(json.dumps({"status": "OPS_RUN_ALREADY_ACTIVE"}))
        return 3
    except (OpsStateError, ValueError) as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    _emit(manifest)
    # exit code refleja el resultado del run, no solo "ejecuto"
    return 0 if manifest["run_status"] in ("SUCCEEDED", "PARTIAL") \
        else 2


def cmd_ops_inbox(args: argparse.Namespace) -> int:
    import uuid

    from .ops_inbox import process_inbox
    from .ops_state import OpsRunAlreadyActive, OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    inbox_dir = Path(args.path) if args.path else \
        state.root / "inbox"
    run_id = f"inbox-{uuid.uuid4().hex[:8]}"
    try:
        conn = state.acquire_run_lock(run_id)
    except OpsRunAlreadyActive:
        print(json.dumps({"status": "OPS_RUN_ALREADY_ACTIVE"}))
        return 3
    try:
        doc = process_inbox(state, conn, inbox_dir, run_id=run_id)
        state.checkpoint()
    except OpsStateError as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    finally:
        state.release_run_lock()
    return _emit(doc)


def cmd_ops_status(args: argparse.Namespace) -> int:
    from .ops_read import ops_status_doc
    from .ops_state import OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    try:
        with state.open() as conn:
            doc = ops_status_doc(state, conn)
    except OpsStateError as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    return _emit(doc)


def cmd_ops_latest(args: argparse.Namespace) -> int:
    from .ops_read import ops_latest_doc
    from .ops_state import OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    try:
        with state.open() as conn:
            doc = ops_latest_doc(state, conn)
    except OpsStateError as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    return _emit(doc)


def cmd_ops_export_run(args: argparse.Namespace) -> int:
    from .ops_read import export_run
    from .ops_state import OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    try:
        with state.open() as conn:
            doc = export_run(
                state, conn, args.run_id, Path(args.output),
                include_inputs=args.include_inputs)
    except (OpsStateError, ValueError) as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    return _emit(doc)


def _policy_path(config: dict) -> Path:
    spec = (config.get("inputs") or {}).get("source_policy") or {}
    path = spec.get("path")
    if not path:
        raise _InputError("INPUT_MISSING:source_policy")
    return Path(path)


def cmd_ops_source_refresh(args: argparse.Namespace) -> int:
    """P9.8 — refresh live de fuentes (unica superficie de red)."""
    from .ops_sources import run_source_refresh
    from .ops_state import OpsRunAlreadyActive, OpsStateError
    from .source_policy import load_source_policy

    state, code = _open_state(args)
    if state is None:
        return code
    config, code = _load_json(args.config, "config")
    if config is None:
        return code
    try:
        policy = load_source_policy(_policy_path(config))
    except (_InputError, ValueError) as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    run_id = f"source-refresh-{uuid.uuid4().hex[:8]}"
    try:
        conn = state.acquire_run_lock(run_id)
    except OpsRunAlreadyActive:
        print(json.dumps({"status": "OPS_RUN_ALREADY_ACTIVE"}))
        return 3
    try:
        doc = run_source_refresh(
            state, conn, config.get("sources") or {},
            policy=policy)
        state.checkpoint()
    except OpsStateError as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    finally:
        state.release_run_lock()
    _emit(doc)
    return 0 if doc["status"] in ("SUCCESS", "UNCHANGED", "PARTIAL") \
        else 2


def cmd_ops_canon_refresh(args: argparse.Namespace) -> int:
    """P9.8 — rebuild del canon sobre evidencia acumulada."""
    from .ops_canon import run_canon_refresh
    from .ops_state import OpsRunAlreadyActive, OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    config, code = _load_json(args.config, "config")
    if config is None:
        return code
    try:
        policy_path = _policy_path(config)
    except _InputError as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    run_id = f"canon-refresh-{uuid.uuid4().hex[:8]}"
    try:
        conn = state.acquire_run_lock(run_id)
    except OpsRunAlreadyActive:
        print(json.dumps({"status": "OPS_RUN_ALREADY_ACTIVE"}))
        return 3
    try:
        doc = run_canon_refresh(
            state, conn, policy_path=policy_path)
        state.checkpoint()
    except (OpsStateError, ValueError) as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    finally:
        state.release_run_lock()
    _emit(doc)
    return 0 if doc["refresh_status"] in ("SUCCESS", "UNCHANGED") \
        else 2


def cmd_ops_source_status(args: argparse.Namespace) -> int:
    from .ops_read import ops_source_status_doc
    from .ops_state import OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    try:
        with state.open() as conn:
            doc = ops_source_status_doc(state, conn)
    except OpsStateError as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    return _emit(doc)


def cmd_ops_source_replay(args: argparse.Namespace) -> int:
    """P9.8 — replay determinista: sin red, sin mutacion."""
    from .ops_canon import replay_canon
    from .ops_state import OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    config, code = _load_json(args.config, "config")
    if config is None:
        return code
    try:
        policy_path = _policy_path(config)
        with state.open() as conn:
            doc = replay_canon(
                state, conn, policy_path=policy_path,
                source_id=args.source,
                from_date=args.from_date, to_date=args.to_date)
    except (_InputError, OpsStateError, ValueError) as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    if args.out:
        Path(args.out).write_text(
            json.dumps(doc["canon"], indent=2, sort_keys=True,
                       ensure_ascii=True) + "\n", encoding="utf-8")
    return _emit({
        "schema": doc["schema"],
        "generated_at": doc["generated_at"],
        "source_id": doc["source_id"],
        "from_date": doc["from_date"],
        "to_date": doc["to_date"],
        "documents": doc["documents"],
        "canon_logical_sha256": doc["canon"].get("logical_sha256"),
        "canon_events": len(doc["canon"].get("events") or []),
        "out": args.out,
    })


# ------------------------------------------------------------------
# P10 — alert delivery boundary
# ------------------------------------------------------------------

def cmd_alert_deliver(args: argparse.Namespace) -> int:
    """P10.7 — una pasada del dispatcher; unica superficie de red
    de entrega (webhook/smtp)."""
    from .ops_config import validate_delivery_config
    from .ops_delivery import run_alert_deliver
    from .ops_state import OpsRunAlreadyActive, OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    config, code = _load_json(args.config, "config")
    if config is None:
        return code
    try:
        validate_delivery_config(config.get("delivery"))
    except ValueError as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    try:
        run_id = f"alert-deliver-{uuid.uuid4().hex[:8]}"
        conn = state.acquire_run_lock(run_id)
    except OpsRunAlreadyActive:
        print(json.dumps({"status": "OPS_RUN_ALREADY_ACTIVE"}))
        return 3
    try:
        doc = run_alert_deliver(
            state, conn, config.get("delivery") or {},
            only_delivery_key=args.delivery_key)
        state.checkpoint()
    except (OpsStateError, ValueError) as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    finally:
        state.release_run_lock()
    _emit(doc)
    return 0 if doc["status"] in (
        "SUCCESS", "UNCHANGED", "DISABLED") else 2


def cmd_delivery_status(args: argparse.Namespace) -> int:
    from .ops_delivery import delivery_status_doc
    from .ops_state import OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    delivery_cfg = {}
    if args.config:
        config, code = _load_json(args.config, "config")
        if config is None:
            return code
        delivery_cfg = config.get("delivery") or {}
    try:
        with state.open() as conn:
            doc = delivery_status_doc(state, conn, delivery_cfg)
    except OpsStateError as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    return _emit(doc)


def cmd_delivery_show(args: argparse.Namespace) -> int:
    from .ops_delivery import (
        get_delivery, list_attempts, list_transitions)
    from .ops_state import OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    try:
        with state.open() as conn:
            delivery = get_delivery(conn, args.delivery_key)
            if delivery is None:
                print(json.dumps({
                    "status": "DELIVERY_NOT_FOUND",
                    "delivery_key": args.delivery_key}))
                return 2
            attempts = list_attempts(conn, args.delivery_key)
            transitions = list_transitions(conn, args.delivery_key)
    except OpsStateError as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    return _emit({
        "schema": "CA_ES_DELIVERY_SHOW_V1",
        "delivery": delivery,
        "attempts": attempts,
        "transitions": transitions,
    })


def cmd_delivery_retry(args: argparse.Namespace) -> int:
    from .ops_delivery import delivery_retry
    from .ops_state import OpsRunAlreadyActive, OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    try:
        conn = state.acquire_run_lock(
            f"delivery-retry-{uuid.uuid4().hex[:8]}")
    except OpsRunAlreadyActive:
        print(json.dumps({"status": "OPS_RUN_ALREADY_ACTIVE"}))
        return 3
    try:
        delivery = delivery_retry(
            conn, args.delivery_key, now=_utcnow_iso(),
            actor=args.actor or "operator",
            force_unknown=args.force_unknown)
        state.checkpoint()
    except (OpsStateError, ValueError) as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    finally:
        state.release_run_lock()
    return _emit({"status": "REQUEUED", "delivery": delivery})


def cmd_delivery_abandon(args: argparse.Namespace) -> int:
    from .ops_delivery import delivery_abandon
    from .ops_state import OpsRunAlreadyActive, OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    try:
        conn = state.acquire_run_lock(
            f"delivery-abandon-{uuid.uuid4().hex[:8]}")
    except OpsRunAlreadyActive:
        print(json.dumps({"status": "OPS_RUN_ALREADY_ACTIVE"}))
        return 3
    try:
        delivery = delivery_abandon(
            conn, args.delivery_key, now=_utcnow_iso(),
            actor=args.actor or "operator", note=args.note)
        state.checkpoint()
    except (OpsStateError, ValueError) as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    finally:
        state.release_run_lock()
    return _emit({"status": "ABANDONED", "delivery": delivery})


# ------------------------------------------------------------------
# P11 — instruction send boundary (FileSpoolTransport)
# ------------------------------------------------------------------

def cmd_send_prepare(args: argparse.Namespace) -> int:
    """P11 — deriva sends PREPARED desde un doc de mensaje
    serializado (CA_ES_MT565_FIN_V1 / CA_ES_SEEV033_XML_V1)."""
    from .ops_config import validate_send_config
    from .ops_send import prepare_sends
    from .ops_state import OpsRunAlreadyActive, OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    config, code = _load_json(args.config, "config")
    if config is None:
        return code
    message_doc, code = _load_json(args.message, "message")
    if message_doc is None:
        return code
    try:
        validate_send_config(config.get("send"))
    except ValueError as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    try:
        conn = state.acquire_run_lock(
            f"send-prepare-{uuid.uuid4().hex[:8]}")
    except OpsRunAlreadyActive:
        print(json.dumps({"status": "OPS_RUN_ALREADY_ACTIVE"}))
        return 3
    try:
        doc = prepare_sends(
            conn, message_doc, args.instruction_id,
            config.get("send") or {})
        state.checkpoint()
    except (OpsStateError, ValueError) as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    finally:
        state.release_run_lock()
    return _emit(doc)


def cmd_send_dispatch(args: argparse.Namespace) -> int:
    """P11 — una pasada del send dispatcher: orphan recovery +
    receipt ingestion + dispatch de elegibles."""
    from .ops_config import validate_send_config
    from .ops_send import run_send_dispatch
    from .ops_state import OpsRunAlreadyActive, OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    config, code = _load_json(args.config, "config")
    if config is None:
        return code
    try:
        validate_send_config(config.get("send"))
    except ValueError as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    try:
        run_id = f"send-dispatch-{uuid.uuid4().hex[:8]}"
        conn = state.acquire_run_lock(run_id)
    except OpsRunAlreadyActive:
        print(json.dumps({"status": "OPS_RUN_ALREADY_ACTIVE"}))
        return 3
    try:
        doc = run_send_dispatch(
            state, conn, config.get("send") or {},
            only_delivery_id=args.delivery_id)
        state.checkpoint()
    except (OpsStateError, ValueError) as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    finally:
        state.release_run_lock()
    _emit(doc)
    return 0 if doc["status"] in (
        "SUCCESS", "UNCHANGED", "DISABLED") else 2


def cmd_send_status(args: argparse.Namespace) -> int:
    from .ops_send import send_status_doc
    from .ops_state import OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    send_cfg = {}
    if args.config:
        config, code = _load_json(args.config, "config")
        if config is None:
            return code
        send_cfg = config.get("send") or {}
    try:
        with state.open() as conn:
            doc = send_status_doc(state, conn, send_cfg)
    except OpsStateError as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    return _emit(doc)


def cmd_send_show(args: argparse.Namespace) -> int:
    from .ops_send import (
        get_send, list_send_attempts, list_send_receipts,
        list_send_transitions)
    from .ops_state import OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    try:
        with state.open() as conn:
            send = get_send(conn, args.delivery_id)
            if send is None:
                print(json.dumps({
                    "status": "SEND_NOT_FOUND",
                    "delivery_id": args.delivery_id}))
                return 2
            doc = {
                "schema": "CA_ES_SEND_SHOW_V1",
                "send": send,
                "attempts": list_send_attempts(
                    conn, args.delivery_id),
                "transitions": list_send_transitions(
                    conn, args.delivery_id),
                "receipts": list_send_receipts(
                    conn, args.delivery_id),
            }
    except OpsStateError as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    return _emit(doc)


def cmd_send_retry(args: argparse.Namespace) -> int:
    from .ops_send import send_retry
    from .ops_state import OpsRunAlreadyActive, OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    try:
        conn = state.acquire_run_lock(
            f"send-retry-{uuid.uuid4().hex[:8]}")
    except OpsRunAlreadyActive:
        print(json.dumps({"status": "OPS_RUN_ALREADY_ACTIVE"}))
        return 3
    try:
        send = send_retry(
            conn, args.delivery_id, now=_utcnow_iso(),
            actor=args.actor or "operator",
            force_unknown=args.force_unknown)
        state.checkpoint()
    except (OpsStateError, ValueError) as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    finally:
        state.release_run_lock()
    return _emit({"status": "REQUEUED", "send": send})


def cmd_send_abandon(args: argparse.Namespace) -> int:
    from .ops_send import send_abandon
    from .ops_state import OpsRunAlreadyActive, OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    try:
        conn = state.acquire_run_lock(
            f"send-abandon-{uuid.uuid4().hex[:8]}")
    except OpsRunAlreadyActive:
        print(json.dumps({"status": "OPS_RUN_ALREADY_ACTIVE"}))
        return 3
    try:
        send = send_abandon(
            conn, args.delivery_id, now=_utcnow_iso(),
            actor=args.actor or "operator", note=args.note)
        state.checkpoint()
    except (OpsStateError, ValueError) as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    finally:
        state.release_run_lock()
    return _emit({"status": "ABANDONED", "send": send})


def cmd_send_ingest_fin(args: argparse.Namespace) -> int:
    """P12.5 — ingiere un service message FIN (ACK/NAK service id 21)
    via el adapter JVM/Prowide y lo correlaciona contra el send
    ledger. Un fichero depositado por el operador registra
    source=FILE_INGEST — evidencia de state machine, no de red."""
    from .ops_fin import ingest_fin_service_file
    from .ops_state import OpsRunAlreadyActive, OpsStateError
    from .swift_mt import AdapterUnavailable

    state, code = _open_state(args)
    if state is None:
        return code
    fin_path = Path(args.fin)
    if not fin_path.is_file():
        print(json.dumps({"status": "FIN_FILE_NOT_FOUND",
                          "path": args.fin}))
        return 2
    try:
        conn = state.acquire_run_lock(
            f"send-ingest-fin-{uuid.uuid4().hex[:8]}")
    except OpsRunAlreadyActive:
        print(json.dumps({"status": "OPS_RUN_ALREADY_ACTIVE"}))
        return 3
    try:
        doc = ingest_fin_service_file(conn, fin_path)
        state.checkpoint()
    except AdapterUnavailable as exc:
        print(json.dumps({"status": f"ADAPTER_UNAVAILABLE:{exc}"}))
        return 4
    except (OpsStateError, ValueError) as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    finally:
        state.release_run_lock()
    _emit(doc)
    return 0 if str(doc.get("result") or "").startswith(
        ("SWIFT_", "DUPLICATE:", "RECONFIRMED:")) else 2


def cmd_send_poll(args: argparse.Namespace) -> int:
    """P12.13 — una pasada de polling de evidencia entrante:
    receipts filespool locales + receipts remotos SFTP. No es un
    daemon; el scheduler externo lo encadena. Idempotente."""
    from .ops_config import validate_send_config
    from .ops_send import run_send_poll
    from .ops_state import OpsRunAlreadyActive, OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    config, code = _load_json(args.config, "config")
    if config is None:
        return code
    try:
        validate_send_config(config.get("send"))
    except ValueError as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    try:
        run_id = f"send-poll-{uuid.uuid4().hex[:8]}"
        conn = state.acquire_run_lock(run_id)
    except OpsRunAlreadyActive:
        print(json.dumps({"status": "OPS_RUN_ALREADY_ACTIVE"}))
        return 3
    try:
        doc = run_send_poll(state, conn, config.get("send") or {})
        state.checkpoint()
    except (OpsStateError, ValueError) as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    finally:
        state.release_run_lock()
    _emit(doc)
    return 0 if doc["status"] in (
        "SUCCESS", "UNCHANGED", "DISABLED") else 2


def _utcnow_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).replace(microsecond=0).isoformat(
    ).replace("+00:00", "Z")


# ------------------------------------------------------------------
# P13 — custody feeds

def _custody_facts(args):
    """facts doc desde --fin/--mx via adapter, o --facts directo."""
    if getattr(args, "facts", None):
        return _load_json(args.facts, "facts")
    if getattr(args, "mx", None):
        return _mx_facts_doc(args)
    return _facts_doc(args)


def cmd_custody_observe(args: argparse.Namespace) -> int:
    from .custody_cash import cash_observation
    from .custody_position import position_observation
    from .ops_custody import CASH_TYPES, POSITION_TYPES

    facts, code = _custody_facts(args)
    if facts is None:
        return code
    mid = facts.get("message_identifier")
    if mid in POSITION_TYPES:
        return _emit(position_observation(facts))
    if mid in CASH_TYPES:
        return _emit(cash_observation(facts))
    print(json.dumps({
        "status": "UNSUPPORTED_MESSAGE_TYPE",
        "message_identifier": mid,
        "detail": "no es un tipo custody (MT535/semt.002/"
                  "MT940/MT950/camt.053/camt.054)",
    }))
    return 3


def cmd_custody_snapshot(args: argparse.Namespace) -> int:
    from .custody_profile import load_profile
    from .custody_profile import account_map as _amap
    from .custody_snapshot import build_snapshots, positions_doc

    observations = []
    for path in args.obs:
        doc, code = _load_json(path, "obs")
        if doc is None:
            return code
        if doc.get("schema") != "CA_ES_POSITION_OBSERVATION_V1":
            print(json.dumps({
                "status": "INVALID_INPUT",
                "detail": f"{path} no es CA_ES_POSITION_OBSERVATION_V1",
            }))
            return 2
        observations.append(doc)

    profile = None
    if args.profile:
        try:
            profile = load_profile(Path(args.profile))
        except (ValueError, OSError) as exc:
            print(json.dumps({"status": str(exc)[:200]}))
            return 2
    index = build_snapshots(observations, now=args.now)
    amap = _amap(profile)
    out = dict(index)
    out["positions_docs"] = [
        positions_doc(s, amap, now=args.now)
        for s in index["snapshots"] if s["completeness"] == "COMPLETE"]
    return _emit(out)


def cmd_custody_bind(args: argparse.Namespace) -> int:
    from .custody_bind import bind_cash, movements_doc
    from .custody_profile import load_profile
    from .custody_profile import account_map as _amap
    from .custody_profile import reference_map as _rmap

    obs, code = _load_json(args.obs, "obs")
    if obs is None:
        return code
    if obs.get("schema") != "CA_ES_CASH_ACCOUNT_OBSERVATION_V1":
        print(json.dumps({
            "status": "INVALID_INPUT",
            "detail": "obs debe ser CA_ES_CASH_ACCOUNT_OBSERVATION_V1",
        }))
        return 2

    rmap, amap = {}, {}
    if args.refs:
        refs, code = _load_json(args.refs, "refs")
        if refs is None:
            return code
        rmap = refs.get("reference_map", refs)
    if args.profile:
        try:
            profile = load_profile(Path(args.profile))
        except (ValueError, OSError) as exc:
            print(json.dumps({"status": str(exc)[:200]}))
            return 2
        rmap = {**rmap, **_rmap(profile)}
        amap = _amap(profile)

    binding = bind_cash(obs, rmap, amap, now=args.now)
    out = dict(binding)
    out["movements_doc"] = movements_doc(binding, now=args.now)
    return _emit(out)


def cmd_custody_recon(args: argparse.Namespace) -> int:
    from .custody_recon import cash_feed_recon, position_recon

    if args.cash:
        movements, code = _load_json(args.movements, "movements")
        if movements is None:
            return code
        obs, code = _load_json(args.obs, "obs")
        if obs is None:
            return code
        return _emit(cash_feed_recon(movements, obs, now=args.now))
    expected, code = _load_json(args.expected, "expected")
    if expected is None:
        return code
    snap, code = _load_json(args.snapshot, "snapshot")
    if snap is None:
        return code
    return _emit(position_recon(expected, snap, now=args.now))


def cmd_custody_inbox(args: argparse.Namespace) -> int:
    import uuid

    from .ops_custody import process_custody_inbox
    from .ops_state import OpsRunAlreadyActive, OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    inbox_dir = Path(args.path) if args.path else \
        state.root / "custody_inbox"
    run_id = f"custody-inbox-{uuid.uuid4().hex[:8]}"
    try:
        conn = state.acquire_run_lock(run_id)
    except OpsRunAlreadyActive:
        print(json.dumps({"status": "OPS_RUN_ALREADY_ACTIVE"}))
        return 3
    try:
        doc = process_custody_inbox(
            state, conn, inbox_dir, run_id=run_id)
        state.checkpoint()
    except OpsStateError as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    finally:
        state.release_run_lock()
    return _emit(doc)


def cmd_custody_build(args: argparse.Namespace) -> int:
    import uuid

    from .custody_profile import load_profile
    from .ops_custody import build_custody_index
    from .ops_state import OpsRunAlreadyActive, OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    profile = None
    if args.profile:
        try:
            profile = load_profile(Path(args.profile))
        except (ValueError, OSError) as exc:
            print(json.dumps({"status": str(exc)[:200]}))
            return 2
    run_id = f"custody-build-{uuid.uuid4().hex[:8]}"
    try:
        conn = state.acquire_run_lock(run_id)
    except OpsRunAlreadyActive:
        print(json.dumps({"status": "OPS_RUN_ALREADY_ACTIVE"}))
        return 3
    try:
        doc = build_custody_index(state, conn, profile=profile)
        state.checkpoint()
    except OpsStateError as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    finally:
        state.release_run_lock()
    return _emit(doc)


def cmd_custody_health(args: argparse.Namespace) -> int:
    from .custody_health import feed_health
    from .ops_custody import latest_index
    from .ops_state import OpsStateError

    state, code = _open_state(args)
    if state is None:
        return code
    try:
        conn = state.open().__enter__()
        index = latest_index(state, conn)
        conn.close()
    except OpsStateError as exc:
        print(json.dumps({"status": str(exc)[:200]}))
        return 2
    doc = feed_health(
        index, now=args.now or _utcnow_iso(),
        required_accounts=args.required_account,
        max_position_age_days=args.max_age_days)
    return _emit(doc)


def _tax_facts_doc(args: argparse.Namespace):
    """facts doc desde --facts, --fin (MT) o --mx (ISO 20022)."""
    if getattr(args, "facts", None):
        return _load_json(args.facts, "facts")
    if getattr(args, "mx", None):
        return _mx_facts_doc(args)
    return _facts_doc(args)


def cmd_tax_evidence(args: argparse.Namespace) -> int:
    from .tax_evidence import tax_evidence

    facts_doc, code = _tax_facts_doc(args)
    if facts_doc is None:
        return code
    return _emit(tax_evidence(
        facts_doc, canonical_event_id=args.event, now=args.now))


def _multi_load(paths, label):
    docs = []
    for path in paths or []:
        doc, code = _load_json(path, label)
        if doc is None:
            return None, code
        docs.append(doc)
    return docs, 0


def cmd_tax_entitlement(args: argparse.Namespace) -> int:
    from .tax_entitlement import tax_entitlement

    entitlement, code = _load_json(args.entitlement, "entitlement")
    if entitlement is None:
        return code
    evidence, code = _multi_load(args.evidence, "evidence")
    if evidence is None:
        return code
    profile = None
    if args.profile:
        profile, code = _load_json(args.profile, "tax-profile")
        if profile is None:
            return code
    rules = None
    if args.rules:
        rules, code = _load_json(args.rules, "tax-rules")
        if rules is None:
            return code
    option_scope = None
    if args.option_number or args.option_type:
        option_scope = {
            "option_number": args.option_number,
            "option_type": args.option_type,
        }
    doc = tax_entitlement(
        entitlement, evidence, profile, rules,
        jurisdiction=args.jurisdiction,
        income_type=args.income_type,
        calculation_date=args.calculation_date,
        option_scope=option_scope,
        requires_election=args.requires_election,
        now=args.now)
    return _emit(doc)


def cmd_tax_expected_cash(args: argparse.Namespace) -> int:
    from .tax_entitlement import expected_cash

    doc, code = _load_json(args.tax_entitlement, "tax-entitlement")
    if doc is None:
        return code
    return _emit(expected_cash(doc))


def cmd_tax_recon(args: argparse.Namespace) -> int:
    from .tax_recon import tax_recon

    ent, code = _load_json(args.tax_entitlement, "tax-entitlement")
    if ent is None:
        return code
    evidence, code = _multi_load(args.evidence, "evidence")
    if evidence is None:
        return code
    return _emit(tax_recon(ent, evidence, now=args.now))


def cmd_tax_rules_validate(args: argparse.Namespace) -> int:
    from .tax_rules import validate_ruleset

    doc, code = _load_json(args.rules, "tax-rules")
    if doc is None:
        return code
    errors = validate_ruleset(doc)
    return _emit({"schema": "CA_ES_TAX_RULES_VALIDATION_V1",
                  "valid": not errors, "errors": errors})


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
    brief.add_argument("--queue", default=None,
                       help="doc CA_ES_ACTION_QUEUE_V1 -> brief V2")
    brief.add_argument("--format", choices=["json", "text"], default="text")
    brief.set_defaults(func=cmd_brief)

    desk = sub.add_parser("desk")
    desk.add_argument("--canon", default=None,
                      help="obligatorio salvo --latest")
    desk.add_argument("--policy", default=None)
    desk.add_argument("--as-of", default=None)
    desk.add_argument("--previous-canon", default=None)
    desk.add_argument("--window", type=int, default=7)
    desk.add_argument("--queue", default=None,
                      help="doc CA_ES_ACTION_QUEUE_V1 -> brief V2")
    desk.add_argument("--state", default=None,
                      help="state store operativo (P7)")
    desk.add_argument("--latest", action="store_true",
                      help="consume el ultimo run SUCCEEDED")
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
    reconcile.add_argument(
        "--expected-cash", default=None,
        help="doc CA_ES_EXPECTED_CASH_V1 (P14): habilita recon NET")
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

    mx_facts = sub.add_parser("mx-facts")
    mx_facts.add_argument("--mx", required=True,
                          help="fichero con el mensaje XML ISO 20022 "
                               "(seev.031/033/034/036); viaja al adapter "
                               "JVM solo por stdin")
    mx_facts.set_defaults(func=cmd_mx_facts)

    mx_project = sub.add_parser("mx-project")
    mx_project.add_argument("--mx", default=None)
    mx_project.add_argument("--facts", default=None,
                            help="doc CA_ES_SWIFT_MX_FACTS_V1 ya "
                                 "calculado")
    mx_project.add_argument("--now", default=None)
    mx_project.set_defaults(func=cmd_mx_project)

    mx_bind = sub.add_parser("mx-bind")
    mx_bind.add_argument("--mx", default=None)
    mx_bind.add_argument("--facts", default=None)
    mx_bind.add_argument("--canon", required=True)
    mx_bind.add_argument("--now", default=None)
    mx_bind.set_defaults(func=cmd_mx_bind)

    mx_election = sub.add_parser("mx-election")
    mx_election.add_argument("--mx", default=None)
    mx_election.add_argument("--facts", default=None)
    mx_election.add_argument("--canon", required=True)
    mx_election.add_argument("--queue", default=None)
    mx_election.add_argument("--deadline-type", action="append",
                             default=None)
    mx_election.add_argument("--now", default=None)
    mx_election.set_defaults(func=cmd_mx_election)

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

    candidate = sub.add_parser("swift-cash-candidate")
    candidate.add_argument("--fin", default=None)
    candidate.add_argument("--facts", default=None)
    candidate.add_argument("--canon", required=True)
    candidate.add_argument("--now", default=None)
    candidate.set_defaults(func=cmd_swift_cash_candidate)

    dl = sub.add_parser("deadlines")
    dl.add_argument("--canon", required=True)
    dl.add_argument("--rules", required=True)
    dl.add_argument("--calendars", required=True)
    dl.add_argument("--event", default=None)
    dl.add_argument("--now", default=None)
    dl.set_defaults(func=cmd_deadlines)

    aq = sub.add_parser("action-queue")
    aq.add_argument("--deadlines", required=True,
                    help="doc CA_ES_OPERATIONAL_DEADLINE_V1")
    aq.add_argument("--as-of", required=True)
    aq.add_argument("--window-days", type=int, required=True)
    aq.add_argument("--due-soon-days", type=int, required=True)
    aq.add_argument("--now", default=None)
    aq.set_defaults(func=cmd_action_queue)

    election = sub.add_parser("swift-election")
    election.add_argument("--fin", default=None)
    election.add_argument("--facts", default=None)
    election.add_argument("--canon", required=True)
    election.add_argument("--queue", default=None,
                          help="doc CA_ES_ACTION_QUEUE_V1")
    election.add_argument("--deadline-type", action="append",
                          default=None,
                          help="deadline_type aplicable; requerido "
                               "con --queue")
    election.add_argument("--now", default=None)
    election.set_defaults(func=cmd_swift_election)

    elig = sub.add_parser("election-eligibility")
    elig.add_argument("--opportunity", required=True,
                      help="doc CA_ES_ELECTION_OPPORTUNITY_V1")
    elig.add_argument("--canon", required=True)
    elig.add_argument("--positions", required=True,
                      help="doc CA_ES_POSITIONS_V1")
    elig.add_argument("--rules", required=True,
                      help="doc CA_ES_ELECTION_ELIGIBILITY_RULES_V1")
    elig.add_argument("--now", default=None)
    elig.set_defaults(func=cmd_election_eligibility)

    instr = sub.add_parser("election-instruction")
    instr.add_argument("--eligibility", required=True,
                       help="doc CA_ES_ELECTION_ELIGIBILITY_V1")
    instr.add_argument("--opportunity", required=True,
                       help="doc CA_ES_ELECTION_OPPORTUNITY_V1")
    instr.add_argument("--request", required=True,
                       help="request JSON: instruction_id, account_id, "
                            "option_key, requested_quantity, actor, "
                            "instructed_at")
    instr.add_argument("--now", default=None)
    instr.set_defaults(func=cmd_election_instruction)

    proj565 = sub.add_parser("mt565-project")
    proj565.add_argument("--instruction", required=True,
                         help="doc CA_ES_ELECTION_INSTRUCTION_V1")
    proj565.add_argument("--fin", default=None,
                         help="FIN MT564 fuente (via adapter)")
    proj565.add_argument("--facts", default=None,
                         help="doc CA_ES_SWIFT_MT_FACTS_V1 ya calculado")
    proj565.add_argument("--envelope", required=True,
                         help="doc CA_ES_SWIFT_MT565_ENVELOPE_V1")
    proj565.add_argument("--now", default=None)
    proj565.set_defaults(func=cmd_mt565_project)

    write565 = sub.add_parser("mt565-write")
    write565.add_argument("--projection", required=True,
                          help="doc CA_ES_MT565_PROJECTION_V1")
    write565.set_defaults(func=cmd_mt565_write)

    proj033 = sub.add_parser("seev033-project")
    proj033.add_argument("--instruction", required=True,
                         help="doc CA_ES_ELECTION_INSTRUCTION_V1")
    proj033.add_argument("--mx", default=None,
                         help="XML seev.031 fuente (via adapter)")
    proj033.add_argument("--fin", default=None,
                         help="FIN MT564 fuente (via adapter)")
    proj033.add_argument("--facts", default=None,
                         help="doc facts (MX o MT) ya calculado")
    proj033.add_argument("--envelope", required=True,
                         help="doc CA_ES_SWIFT_MX_ENVELOPE_V1")
    proj033.add_argument("--now", default=None)
    proj033.set_defaults(func=cmd_seev033_project)

    write033 = sub.add_parser("seev033-write")
    write033.add_argument("--projection", required=True,
                          help="doc CA_ES_SEEV033_PROJECTION_V1")
    write033.set_defaults(func=cmd_seev033_write)

    istat = sub.add_parser("instruction-status")
    istat.add_argument("--fin", default=None,
                       help="FIN MT567 (via adapter)")
    istat.add_argument("--facts", default=None,
                       help="doc CA_ES_SWIFT_MT_FACTS_V1 (MT567)")
    istat.add_argument("--instruction", required=True,
                       help="doc CA_ES_ELECTION_INSTRUCTION_V1")
    istat.add_argument("--now", default=None)
    istat.set_defaults(func=cmd_instruction_status)

    mistat = sub.add_parser("mx-status")
    mistat.add_argument("--mx", default=None,
                        help="XML seev.034 (via adapter)")
    mistat.add_argument("--facts", default=None,
                        help="doc CA_ES_SWIFT_MX_FACTS_V1 (seev.034)")
    mistat.add_argument("--instruction", required=True,
                        help="doc CA_ES_ELECTION_INSTRUCTION_V1")
    mistat.add_argument("--now", default=None)
    mistat.set_defaults(func=cmd_mx_instruction_status)

    mcash = sub.add_parser("mx-cash-candidate")
    mcash.add_argument("--mx", default=None,
                       help="XML seev.036 (via adapter)")
    mcash.add_argument("--facts", default=None,
                       help="doc CA_ES_SWIFT_MX_FACTS_V1 (seev.036)")
    mcash.add_argument("--canon", required=True)
    mcash.add_argument("--now", default=None)
    mcash.set_defaults(func=cmd_mx_cash_candidate)

    msec = sub.add_parser("mx-security-candidate")
    msec.add_argument("--mx", default=None,
                      help="XML seev.036 (via adapter)")
    msec.add_argument("--facts", default=None,
                      help="doc CA_ES_SWIFT_MX_FACTS_V1 (seev.036)")
    msec.add_argument("--canon", required=True)
    msec.add_argument("--now", default=None)
    msec.set_defaults(func=cmd_mx_security_candidate)

    impact = sub.add_parser("position-impact")
    impact.add_argument("--canon", required=True)
    impact.add_argument("--event", required=True)
    impact.add_argument("--positions", required=True,
                        help="doc CA_ES_POSITIONS_V1")
    impact.add_argument("--rules", required=True,
                        help="doc CA_ES_IMPACT_RULES_V1")
    impact.add_argument("--entitlements", default=None,
                        help="doc CA_ES_ENTITLEMENT_V1 (requerido por "
                             "reglas CASH_RECEIVABLE)")
    impact.add_argument("--now", default=None)
    impact.set_defaults(func=cmd_position_impact)

    seccand = sub.add_parser("swift-security-candidate")
    seccand.add_argument("--fin", default=None,
                         help="FIN MT566 (via adapter)")
    seccand.add_argument("--facts", default=None,
                         help="doc CA_ES_SWIFT_MT_FACTS_V1 (MT566)")
    seccand.add_argument("--canon", required=True)
    seccand.add_argument("--now", default=None)
    seccand.set_defaults(func=cmd_swift_security_candidate)

    proj = sub.add_parser("project-positions")
    proj.add_argument("--positions", required=True,
                      help="doc CA_ES_POSITIONS_V1")
    proj.add_argument("--impact", required=True,
                      help="doc CA_ES_POSITION_IMPACT_V1")
    proj.add_argument("--now", default=None)
    proj.set_defaults(func=cmd_project_positions)

    srecon = sub.add_parser("security-reconcile")
    srecon.add_argument("--impact", required=True,
                        help="doc CA_ES_POSITION_IMPACT_V1")
    srecon.add_argument("--candidates", nargs="*", default=[],
                        help="docs "
                        "CA_ES_SWIFT_SECURITY_MOVEMENT_CANDIDATE_V1")
    srecon.add_argument("--now", default=None)
    srecon.set_defaults(func=cmd_security_reconcile)

    portfolio = sub.add_parser("portfolio-impact")
    portfolio.add_argument("--impact", required=True,
                           help="doc CA_ES_POSITION_IMPACT_V1")
    portfolio.add_argument("--now", default=None)
    portfolio.set_defaults(func=cmd_portfolio_impact)

    # ---------------- P7 runtime operativo ----------------

    oinit = sub.add_parser("ops-init")
    oinit.add_argument("--state", required=True,
                       help="directorio del state store operativo")
    oinit.set_defaults(func=cmd_ops_init)

    orun = sub.add_parser("ops-run")
    orun.add_argument("--state", required=True)
    orun.add_argument("--config", required=True,
                    help="doc CA_ES_OPS_CONFIG_V1")
    orun.add_argument("--as-of", default=None,
                    help="YYYY-MM-DD (obligatorio en run nuevo)")
    orun.add_argument("--resume", default=None, metavar="RUN_ID")
    orun.set_defaults(func=cmd_ops_run)

    oinbox = sub.add_parser("ops-inbox")
    oinbox.add_argument("--state", required=True)
    oinbox.add_argument("--path", default=None,
                      help="directorio inbox (default <state>/inbox)")
    oinbox.set_defaults(func=cmd_ops_inbox)

    ostatus = sub.add_parser("ops-status")
    ostatus.add_argument("--state", required=True)
    ostatus.set_defaults(func=cmd_ops_status)

    olatest = sub.add_parser("ops-latest")
    olatest.add_argument("--state", required=True)
    olatest.set_defaults(func=cmd_ops_latest)

    oexport = sub.add_parser("ops-export-run")
    oexport.add_argument("--state", required=True)
    oexport.add_argument("--run-id", required=True)
    oexport.add_argument("--output", required=True)
    oexport.add_argument("--include-inputs", action="store_true")
    oexport.set_defaults(func=cmd_ops_export_run)

    # ---------------- P9.8 sources / replay ----------------

    osrf = sub.add_parser("ops-source-refresh")
    osrf.add_argument("--state", required=True)
    osrf.add_argument("--config", required=True,
                      help="doc CA_ES_OPS_CONFIG_V1")
    osrf.set_defaults(func=cmd_ops_source_refresh)

    ocrf = sub.add_parser("ops-canon-refresh")
    ocrf.add_argument("--state", required=True)
    ocrf.add_argument("--config", required=True)
    ocrf.set_defaults(func=cmd_ops_canon_refresh)

    osstat = sub.add_parser("ops-source-status")
    osstat.add_argument("--state", required=True)
    osstat.set_defaults(func=cmd_ops_source_status)

    osrep = sub.add_parser("ops-source-replay")
    osrep.add_argument("--state", required=True)
    osrep.add_argument("--config", required=True)
    osrep.add_argument("--source", default=None,
                     help="filtra por source_id")
    osrep.add_argument("--from", dest="from_date", default=None,
                       help="publication_date >= (inclusivo)")
    osrep.add_argument("--to", dest="to_date", default=None,
                       help="publication_date <= (inclusivo)")
    osrep.add_argument("--out", default=None,
                       help="escribe el canon resultante a JSON")
    osrep.set_defaults(func=cmd_ops_source_replay)

    # ---------------- P10 alert delivery ----------------

    adel = sub.add_parser("alert-deliver")
    adel.add_argument("--state", required=True)
    adel.add_argument("--config", required=True,
                      help="doc CA_ES_OPS_CONFIG_V1 con seccion delivery")
    adel.add_argument("--delivery-key", default=None,
                      help="limita la pasada a una entrega")
    adel.set_defaults(func=cmd_alert_deliver)

    dstat = sub.add_parser("delivery-status")
    dstat.add_argument("--state", required=True)
    dstat.add_argument("--config", default=None,
                       help="opcional: para reflejar config enabled")
    dstat.set_defaults(func=cmd_delivery_status)

    dshow = sub.add_parser("delivery-show")
    dshow.add_argument("--state", required=True)
    dshow.add_argument("--delivery-key", required=True)
    dshow.set_defaults(func=cmd_delivery_show)

    dretry = sub.add_parser("delivery-retry")
    dretry.add_argument("--state", required=True)
    dretry.add_argument("--delivery-key", required=True)
    dretry.add_argument("--force-unknown", action="store_true",
                        help="permite reencolar UNKNOWN_OUTCOME")
    dretry.add_argument("--actor", default=None)
    dretry.set_defaults(func=cmd_delivery_retry)

    daband = sub.add_parser("delivery-abandon")
    daband.add_argument("--state", required=True)
    daband.add_argument("--delivery-key", required=True)
    daband.add_argument("--actor", default=None)
    daband.add_argument("--note", default=None)
    daband.set_defaults(func=cmd_delivery_abandon)

    # ---------------- P11 instruction send ----------------

    sprep = sub.add_parser("send-prepare")
    sprep.add_argument("--state", required=True)
    sprep.add_argument("--config", required=True,
                       help="doc CA_ES_OPS_CONFIG_V1 con seccion send")
    sprep.add_argument("--message", required=True,
                       help="doc CA_ES_MT565_FIN_V1 o "
                            "CA_ES_SEEV033_XML_V1")
    sprep.add_argument("--instruction-id", required=True,
                       help="instruction_id / SEME / BizMsgIdr")
    sprep.set_defaults(func=cmd_send_prepare)

    sdisp = sub.add_parser("send-dispatch")
    sdisp.add_argument("--state", required=True)
    sdisp.add_argument("--config", required=True)
    sdisp.add_argument("--delivery-id", default=None,
                       help="limita la pasada a un send")
    sdisp.set_defaults(func=cmd_send_dispatch)

    sstat = sub.add_parser("send-status")
    sstat.add_argument("--state", required=True)
    sstat.add_argument("--config", default=None,
                       help="opcional: para reflejar config enabled")
    sstat.set_defaults(func=cmd_send_status)

    sshow = sub.add_parser("send-show")
    sshow.add_argument("--state", required=True)
    sshow.add_argument("--delivery-id", required=True)
    sshow.set_defaults(func=cmd_send_show)

    sretry = sub.add_parser("send-retry")
    sretry.add_argument("--state", required=True)
    sretry.add_argument("--delivery-id", required=True)
    sretry.add_argument("--force-unknown", action="store_true",
                        help="permite reencolar UNKNOWN_OUTCOME")
    sretry.add_argument("--actor", default=None)
    sretry.set_defaults(func=cmd_send_retry)

    saband = sub.add_parser("send-abandon")
    saband.add_argument("--state", required=True)
    saband.add_argument("--delivery-id", required=True)
    saband.add_argument("--actor", default=None)
    saband.add_argument("--note", default=None)
    saband.set_defaults(func=cmd_send_abandon)

    sfin = sub.add_parser("send-ingest-fin")
    sfin.add_argument("--state", required=True)
    sfin.add_argument("--fin", required=True,
                      help="fichero con un service message FIN "
                           "(ACK/NAK service id 21)")
    sfin.set_defaults(func=cmd_send_ingest_fin)

    spoll = sub.add_parser("send-poll")
    spoll.add_argument("--state", required=True)
    spoll.add_argument("--config", required=True)
    spoll.set_defaults(func=cmd_send_poll)

    # P13 — custody feeds
    cobs = sub.add_parser(
        "custody-observe",
        help="MT535/semt.002 -> CA_ES_POSITION_OBSERVATION_V1; "
             "MT940/950/camt.053/054 -> CA_ES_CASH_ACCOUNT_OBSERVATION_V1")
    cobs_src = cobs.add_mutually_exclusive_group(required=True)
    cobs_src.add_argument("--fin", default=None)
    cobs_src.add_argument("--mx", default=None)
    cobs_src.add_argument("--facts", default=None,
                          help="doc de facts ya generado")
    cobs.set_defaults(func=cmd_custody_observe)

    csnap = sub.add_parser(
        "custody-snapshot",
        help="observaciones -> CA_ES_POSITION_SNAPSHOT_V1 + "
             "CA_ES_POSITIONS_V1 (solo COMPLETE)")
    csnap.add_argument("--obs", required=True, nargs="+",
                       help="uno o mas CA_ES_POSITION_OBSERVATION_V1")
    csnap.add_argument("--profile", default=None,
                       help="CA_ES_CUSTODY_PROFILE_V1 (account_map)")
    csnap.add_argument("--now", default=None)
    csnap.set_defaults(func=cmd_custody_snapshot)

    cbind = sub.add_parser(
        "custody-bind",
        help="cash observation -> binding explicito -> "
             "CA_ES_CASH_MOVEMENTS_V2 (solo BOUND)")
    cbind.add_argument("--obs", required=True,
                       help="CA_ES_CASH_ACCOUNT_OBSERVATION_V1")
    cbind.add_argument("--refs", default=None,
                       help="reference_map json {ref: {event_id,...}}")
    cbind.add_argument("--profile", default=None,
                       help="CA_ES_CUSTODY_PROFILE_V1")
    cbind.add_argument("--now", default=None)
    cbind.set_defaults(func=cmd_custody_bind)

    crec = sub.add_parser(
        "custody-recon",
        help="reconciliacion custody: positions vs snapshot o "
             "movements vs cash observation")
    crec.add_argument("--expected", default=None,
                      help="CA_ES_POSITIONS_V1 esperado")
    crec.add_argument("--snapshot", default=None,
                      help="CA_ES_POSITION_SNAPSHOT_V1")
    crec.add_argument("--cash", action="store_true",
                      help="modo cash feed recon")
    crec.add_argument("--movements", default=None,
                      help="CA_ES_CASH_MOVEMENTS_V2")
    crec.add_argument("--obs", default=None,
                      help="CA_ES_CASH_ACCOUNT_OBSERVATION_V1")
    crec.add_argument("--now", default=None)
    crec.set_defaults(func=cmd_custody_recon)

    cinbox = sub.add_parser(
        "custody-inbox",
        help="procesa custody_inbox/ (dedup + facts JVM)")
    cinbox.add_argument("--state", required=True)
    cinbox.add_argument("--path", default=None,
                        help="default <state>/custody_inbox")
    cinbox.set_defaults(func=cmd_custody_inbox)

    cbld = sub.add_parser(
        "custody-build",
        help="facts custody -> observations/snapshots/bindings "
             "-> CA_ES_CUSTODY_FEED_STATE_V1")
    cbld.add_argument("--state", required=True)
    cbld.add_argument("--profile", default=None,
                      help="CA_ES_CUSTODY_PROFILE_V1")
    cbld.set_defaults(func=cmd_custody_build)

    chlth = sub.add_parser(
        "custody-health",
        help="CA_ES_CUSTODY_FEED_HEALTH_V1")
    chlth.add_argument("--state", required=True)
    chlth.add_argument("--required-account", action="append",
                       default=[],
                       help="account_id_raw que debe tener snapshot "
                            "COMPLETE (repetible)")
    chlth.add_argument("--max-age-days", type=int, default=7)
    chlth.add_argument("--now", default=None)
    chlth.set_defaults(func=cmd_custody_health)

    # P14 — tax / withholding / net entitlement
    tev = sub.add_parser(
        "tax-evidence",
        help="facts MT564/566 o seev.031/036 -> CA_ES_TAX_EVIDENCE_V1")
    tev.add_argument("--fin", default=None)
    tev.add_argument("--mx", default=None)
    tev.add_argument("--facts", default=None)
    tev.add_argument("--event", default=None,
                   help="canonical_event_id ya adjudicado")
    tev.add_argument("--now", default=None)
    tev.set_defaults(func=cmd_tax_evidence)

    tent = sub.add_parser(
        "tax-entitlement",
        help="entitlement+evidence+profile+rules -> "
             "CA_ES_TAX_ENTITLEMENT_V1")
    tent.add_argument("--entitlement", required=True)
    tent.add_argument("--evidence", action="append", default=[],
                      help="doc CA_ES_TAX_EVIDENCE_V1 (repetible)")
    tent.add_argument("--profile", default=None,
                      help="doc CA_ES_TAX_PROFILE_V1")
    tent.add_argument("--rules", default=None,
                      help="doc CA_ES_TAX_RULES_V1")
    tent.add_argument("--jurisdiction", required=True)
    tent.add_argument("--income-type", required=True)
    tent.add_argument("--calculation-date", required=True,
                      help="fecha fiscal (payment date) ISO")
    tent.add_argument("--option-number", default=None)
    tent.add_argument("--option-type", default=None)
    tent.add_argument("--requires-election", action="store_true")
    tent.add_argument("--now", default=None)
    tent.set_defaults(func=cmd_tax_entitlement)

    tec = sub.add_parser(
        "tax-expected-cash",
        help="CA_ES_TAX_ENTITLEMENT_V1 -> CA_ES_EXPECTED_CASH_V1")
    tec.add_argument("--tax-entitlement", required=True)
    tec.set_defaults(func=cmd_tax_expected_cash)

    trc = sub.add_parser(
        "tax-recon",
        help="expected vs actual tax -> CA_ES_TAX_RECON_V1")
    trc.add_argument("--tax-entitlement", required=True)
    trc.add_argument("--evidence", action="append", default=[],
                     help="CA_ES_TAX_EVIDENCE_V1 role=ACTUAL "
                          "(repetible)")
    trc.add_argument("--now", default=None)
    trc.set_defaults(func=cmd_tax_recon)

    trv = sub.add_parser(
        "tax-rules-validate",
        help="validacion estatica de CA_ES_TAX_RULES_V1")
    trv.add_argument("--rules", required=True)
    trv.set_defaults(func=cmd_tax_rules_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except _InputError as exc:
        return _input_error(exc)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
