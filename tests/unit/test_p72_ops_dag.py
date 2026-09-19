"""P7.2 — DAG operativo: orden determinista, checkpoints, cache,
invalidacion selectiva, resume y single-writer."""
import json
import sqlite3
from pathlib import Path

import pytest

from ca_es.ops_dag import (
    OperationalStep,
    run_ops,
)
from ca_es.ops_state import (
    OpsRunAlreadyActive,
    OpsState,
)

REPO = Path(__file__).resolve().parents[2]
CANON = REPO / "g3/input/canon.json"
POLICY = REPO / "docs/sources/source-policy.json"
SAN = "6443e2be-b70d-50c7-88d1-4a62f43789e9"
AS_OF = "2026-09-16"

RULES = {"schema": "CA_ES_DEADLINE_RULES_V1", "rules": [{
    "rule_id": "R1", "deadline_type": "RESPONSE_DEADLINE",
    "source_field": "date.payment_date", "business_days_offset": -1,
    "calendar_id": "TARGET2"}]}
CALS = {"schema": "CA_ES_CALENDARS_V1", "calendars": [{
    "calendar_id": "TARGET2", "business_week": [0, 1, 2, 3, 4],
    "holidays": []}]}
POSITIONS = {"schema": "CA_ES_POSITIONS_V1", "as_of": "2026-05-04",
             "positions": [{"account_id": "A001",
                            "isin": "ESTIMACIONES",
                            "quantity": "12500",
                            "as_of": "2026-05-04"}]}
MOVEMENTS = {"schema": "CA_ES_CASH_MOVEMENTS_V2", "movements": [{
    "movement_id": "MOV-1", "account_id": "A001", "amount": "1562.50",
    "currency": "EUR", "value_date": "2026-05-06", "event_id": SAN,
    "amount_basis": "GROSS"}]}

NOWS = iter(lambda t=f"2026-09-16T08:{m:02d}:00Z": t
            for m in range(10000))


def _w(root: Path, name: str, doc: dict) -> str:
    p = root / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return str(p)


@pytest.fixture()
def env(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    cfg = {
        "schema": "CA_ES_OPS_CONFIG_V1",
        "inputs": {
            "canon": {"path": str(CANON), "required": True},
            "source_policy": {"path": str(POLICY), "required": True},
            "deadline_rules": {"path": _w(inputs, "rules.json", RULES),
                               "required": True},
            "calendars": {"path": _w(inputs, "cals.json", CALS),
                          "required": True},
            "positions": {"path": _w(inputs, "pos.json", POSITIONS)},
            "cash_movements": {"path": _w(inputs, "movs.json",
                                          MOVEMENTS)},
        },
        "action_queue": {"window_days": 30, "due_soon_days": 7},
    }
    state = OpsState(tmp_path / "state").init()
    return {"cfg": cfg, "state": state, "inputs": inputs}


def _steps(manifest):
    return {s["step_id"]: s for s in manifest["steps"]}


def test_clean_first_run_all_steps_succeed(env):
    m = run_ops(env["cfg"], env["state"], AS_OF)
    assert m["schema"] == "CA_ES_OPERATIONAL_RUN_V1"
    assert m["run_status"] == "SUCCEEDED"
    steps = _steps(m)
    expected = ["validate_inputs", "source_refresh",
                "canon_refresh", "process_inbox",
                "compute_deadlines", "build_action_queue",
                "morning_brief_v2", "entitlements", "tax_events",
                "cash_reconciliation", "tax_recovery",
                "market_claims", "exception_cases",
                "securities_events", "alert_outbox",
                "health_report", "lineage_export"]
    assert [s["step_id"] for s in m["steps"]] == expected
    assert all(s["status"] == "SUCCEEDED" for s in m["steps"])
    assert all(steps[s]["output_sha256"] for s in expected)


def test_second_identical_run_skips_pure_steps(env):
    run_ops(env["cfg"], env["state"], AS_OF)
    m2 = run_ops(env["cfg"], env["state"], AS_OF)
    assert m2["run_status"] == "SUCCEEDED"
    steps = _steps(m2)
    for sid in ("compute_deadlines", "build_action_queue",
                "morning_brief_v2", "entitlements",
                "cash_reconciliation"):
        assert steps[sid]["status"] == "SKIPPED_UNCHANGED"
        assert steps[sid]["cache_source_run_id"]


def test_execution_timestamps_do_not_break_cache(env):
    run_ops(env["cfg"], env["state"], AS_OF,
            now_fn=lambda: "2026-09-16T08:00:00Z")
    m2 = run_ops(env["cfg"], env["state"], AS_OF,
                 now_fn=lambda: "2027-01-01T00:00:00Z")
    assert _steps(m2)["compute_deadlines"]["status"] == \
        "SKIPPED_UNCHANGED"


def test_as_of_change_invalidates_only_as_of_steps(env):
    run_ops(env["cfg"], env["state"], AS_OF)
    m2 = run_ops(env["cfg"], env["state"], "2026-09-20")
    steps = _steps(m2)
    # deadlines son as_of-independientes; queue/brief dependen
    assert steps["compute_deadlines"]["status"] == "SKIPPED_UNCHANGED"
    assert steps["build_action_queue"]["status"] == "SUCCEEDED"
    assert steps["morning_brief_v2"]["status"] == "SUCCEEDED"


def test_changed_input_invalidates_dependents_only(env, tmp_path):
    run_ops(env["cfg"], env["state"], AS_OF)
    changed = json.loads(json.dumps(POSITIONS))
    changed["positions"][0]["quantity"] = "9000"
    _w(env["inputs"], "pos.json", changed)
    m2 = run_ops(env["cfg"], env["state"], AS_OF)
    steps = _steps(m2)
    assert steps["compute_deadlines"]["status"] == "SKIPPED_UNCHANGED"
    assert steps["build_action_queue"]["status"] == "SKIPPED_UNCHANGED"
    assert steps["entitlements"]["status"] == "SUCCEEDED"
    assert steps["cash_reconciliation"]["status"] == "SUCCEEDED"
    assert steps["exception_cases"]["status"] == "SUCCEEDED"


def test_config_change_invalidates_dependent_branch(env):
    run_ops(env["cfg"], env["state"], AS_OF)
    cfg2 = json.loads(json.dumps(env["cfg"]))
    cfg2["action_queue"]["window_days"] = 60
    m2 = run_ops(cfg2, env["state"], AS_OF)
    steps = _steps(m2)
    assert steps["compute_deadlines"]["status"] == "SKIPPED_UNCHANGED"
    assert steps["build_action_queue"]["status"] == "SUCCEEDED"
    assert steps["morning_brief_v2"]["status"] == "SUCCEEDED"
    assert steps["entitlements"]["status"] == "SKIPPED_UNCHANGED"


def test_step_version_change_invalidates_cache(env):
    from ca_es.ops_dag import default_dag
    run_ops(env["cfg"], env["state"], AS_OF)
    dag = default_dag()
    for s in dag:
        if s.step_id == "compute_deadlines":
            s.version = "2"
    m2 = run_ops(env["cfg"], env["state"], AS_OF, dag=dag)
    steps = _steps(m2)
    assert steps["compute_deadlines"]["status"] == "SUCCEEDED"
    # el output recomputado es semanticamente identico -> los
    # dependientes NO invalidan (invalidacion solo si el output
    # cambia de verdad)
    assert steps["build_action_queue"]["status"] == \
        "SKIPPED_UNCHANGED"


def test_cached_schema_mismatch_reruns(env):
    m1 = run_ops(env["cfg"], env["state"], AS_OF)
    # corrompe la version esperada registrada del step
    with env["state"].open() as conn:
        conn.execute(
            "UPDATE run_steps SET expected_output_version='V99'"
            " WHERE step_id='compute_deadlines'")
    m2 = run_ops(env["cfg"], env["state"], AS_OF)
    steps = _steps(m2)
    assert steps["compute_deadlines"]["status"] == "SUCCEEDED"
    assert steps["compute_deadlines"]["output_semantic_sha256"] == \
        _steps(m1)["compute_deadlines"]["output_semantic_sha256"]


def test_corrupted_cached_artifact_reruns(env):
    m1 = run_ops(env["cfg"], env["state"], AS_OF)
    sha = _steps(m1)["compute_deadlines"]["output_sha256"]
    target = (env["state"].artifacts_dir / f"{sha[:2]}/{sha}.json")
    target.unlink()
    m2 = run_ops(env["cfg"], env["state"], AS_OF)
    assert _steps(m2)["compute_deadlines"]["status"] == "SUCCEEDED"


def test_resume_after_failed_step(env):
    calls = {"n": 0}
    from ca_es.ops_dag import default_dag
    dag = default_dag()
    for s in dag:
        if s.step_id == "build_action_queue":
            orig = s.fn

            def flaky(ctx, _orig=orig):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("boom")
                return _orig(ctx)

            s.fn = flaky
    m1 = run_ops(env["cfg"], env["state"], AS_OF, dag=dag)
    assert m1["run_status"] == "FAILED"
    assert _steps(m1)["build_action_queue"]["status"] == "FAILED"
    assert _steps(m1)["morning_brief_v2"]["status"] == "BLOCKED"

    m2 = run_ops(env["cfg"], env["state"], AS_OF,
                 resume_run_id=m1["run_id"])
    assert m2["run_status"] == "SUCCEEDED"
    steps = _steps(m2)
    assert steps["compute_deadlines"]["status"] == "SKIPPED_UNCHANGED"
    assert steps["build_action_queue"]["status"] == "SUCCEEDED"
    assert steps["morning_brief_v2"]["status"] == "SUCCEEDED"


def test_stale_running_step_is_reexecuted(env):
    m1 = run_ops(env["cfg"], env["state"], AS_OF)
    with env["state"].open() as conn:
        conn.execute(
            "UPDATE runs SET run_status='FAILED'"
            " WHERE run_id=?", (m1["run_id"],))
        conn.execute(
            "UPDATE run_steps SET status='RUNNING'"
            " WHERE run_id=? AND step_id='compute_deadlines'",
            (m1["run_id"],))
    m2 = run_ops(env["cfg"], env["state"], AS_OF,
                 resume_run_id=m1["run_id"])
    assert m2["run_status"] == "SUCCEEDED"
    assert _steps(m2)["compute_deadlines"]["status"] == "SUCCEEDED"


def test_failed_run_never_replaces_latest_successful(env):
    m1 = run_ops(env["cfg"], env["state"], AS_OF)
    assert m1["run_status"] == "SUCCEEDED"
    cfg2 = json.loads(json.dumps(env["cfg"]))
    del cfg2["inputs"]["canon"]
    m2 = run_ops(cfg2, env["state"], AS_OF)
    assert m2["run_status"] == "FAILED"
    with env["state"].open() as conn:
        latest = env["state"].latest_successful_run(conn)
    assert latest["run_id"] == m1["run_id"]


def test_missing_required_input_fails_run(env):
    cfg = json.loads(json.dumps(env["cfg"]))
    cfg["inputs"]["deadline_rules"]["path"] = \
        str(env["inputs"] / "no-existe.json")
    m = run_ops(cfg, env["state"], AS_OF)
    assert m["run_status"] == "FAILED"
    assert _steps(m)["validate_inputs"]["status"] == "FAILED"


def test_indeterminate_domain_output_does_not_fail_run(env):
    # el canon real no tiene fact date.payment_date -> deadlines
    # INDETERMINATE; es salida de dominio valida, el runtime sigue
    # sano (SUCCEEDED), nunca re-interpretado ni "resuelto".
    m = run_ops(env["cfg"], env["state"], AS_OF)
    assert m["run_status"] == "SUCCEEDED"
    sha = _steps(m)["compute_deadlines"]["output_sha256"]
    doc = env["state"].get_artifact(sha)
    statuses = {d["derivation_status"] for d in doc["deadlines"]}
    assert "INDETERMINATE" in statuses


def test_missing_optional_inputs_block_branch_not_run(env):
    cfg = json.loads(json.dumps(env["cfg"]))
    del cfg["inputs"]["positions"]
    del cfg["inputs"]["cash_movements"]
    m = run_ops(cfg, env["state"], AS_OF)
    # rama opcional BLOCKED -> PARTIAL, nunca FAILED
    assert m["run_status"] == "PARTIAL"
    steps = _steps(m)
    assert steps["compute_deadlines"]["status"] == "SUCCEEDED"
    assert steps["morning_brief_v2"]["status"] == "SUCCEEDED"
    assert steps["entitlements"]["status"] == "BLOCKED"
    assert steps["exception_cases"]["status"] == "BLOCKED"


def test_second_writer_rejected(env):
    state = env["state"]
    conn = state.acquire_run_lock("runA")
    try:
        with pytest.raises(OpsRunAlreadyActive,
                           match="OPS_RUN_ALREADY_ACTIVE"):
            state.acquire_run_lock("runB")
        # reader sigue pudiendo leer con writer activo
        with state.open() as reader:
            assert reader.execute(
                "SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    finally:
        conn.close()
        state._lock_conn = None
        state._lock_run_id = None


def test_run_resume_rejected_when_unknown_or_succeeded(env):
    m1 = run_ops(env["cfg"], env["state"], AS_OF)
    with pytest.raises(ValueError, match="RUN_IMMUTABLE"):
        run_ops(env["cfg"], env["state"], AS_OF,
                resume_run_id=m1["run_id"])
    with pytest.raises(ValueError, match="RUN_NOT_FOUND"):
        run_ops(env["cfg"], env["state"], AS_OF,
                resume_run_id="no-existe")


def test_resume_does_not_duplicate_artifacts(env):
    m1 = run_ops(env["cfg"], env["state"], AS_OF)
    with env["state"].open() as conn:
        conn.execute(
            "UPDATE runs SET run_status='FAILED' WHERE run_id=?",
            (m1["run_id"],))
    m2 = run_ops(env["cfg"], env["state"], AS_OF,
                 resume_run_id=m1["run_id"])
    assert m2["run_status"] == "SUCCEEDED"
    with env["state"].open() as conn:
        steps = env["state"].get_steps(conn, m2["run_id"])
    impure = {"validate_inputs", "source_refresh", "canon_refresh",
              "process_inbox", "alert_outbox", "health_report",
              "lineage_export", "exception_cases",
              "securities_events", "tax_events", "tax_recovery",
              "market_claims"}
    pure = [s for s in steps if s["step_id"] not in impure]
    # resume reutiliza los pasos puros ya commiteados: ningun
    # side effect de negocio se duplica
    assert all(s["status"] == "SKIPPED_UNCHANGED" for s in pure)


def test_manifest_records_reuse_provenance(env):
    run_ops(env["cfg"], env["state"], AS_OF)
    m2 = run_ops(env["cfg"], env["state"], AS_OF)
    cached = [s for s in m2["steps"]
              if s["status"] == "SKIPPED_UNCHANGED"]
    assert cached
    assert all(s["cache_source_run_id"] for s in cached)
    with env["state"].open() as conn:
        run = env["state"].latest_successful_run(conn)
        manifest = json.loads(run["manifest_json"])
    assert manifest["run_id"] == m2["run_id"]
    assert manifest["run_status"] == "SUCCEEDED"


def test_deterministic_outputs_across_runs(env):
    # byte sha difiere (generated_at); la igualdad material es
    # semantica. Quedan fuera: exception_cases (su input efectivo
    # cambia legitimamente: last_seen_at es timestamp de negocio)
    # y los pasos impuros, cuyo output refleja estado mutable del
    # store (alertas/outbox, health, lineage referencian run_ids).
    impure = {"validate_inputs", "source_refresh", "canon_refresh",
              "process_inbox", "alert_outbox", "health_report",
              "lineage_export", "exception_cases",
              "securities_events", "tax_events", "tax_recovery",
              "market_claims"}
    m1 = run_ops(env["cfg"], env["state"], AS_OF)
    m2 = run_ops(env["cfg"], env["state"], AS_OF)
    s1 = _steps(m1)
    s2 = _steps(m2)
    for sid in s1:
        if sid in impure:
            continue
        assert s1[sid]["output_semantic_sha256"] == \
            s2[sid]["output_semantic_sha256"]


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def _cli_env(tmp_path, env):
    cfg_path = tmp_path / "ops.json"
    cfg_path.write_text(json.dumps(env["cfg"]), encoding="utf-8")
    return cfg_path


def test_cli_ops_init_and_run(tmp_path, env, capsys):
    from ca_es.cli import main
    cfg_path = _cli_env(tmp_path, env)
    state_dir = str(tmp_path / "cli-state")

    assert main(["ops-init", "--state", state_dir]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "INITIALIZED"

    rc = main(["ops-run", "--state", state_dir,
               "--config", str(cfg_path), "--as-of", AS_OF])
    assert rc == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["run_status"] == "SUCCEEDED"


def test_cli_ops_run_requires_init(tmp_path, env, capsys):
    from ca_es.cli import main
    cfg_path = _cli_env(tmp_path, env)
    rc = main(["ops-run", "--state", str(tmp_path / "nope"),
               "--config", str(cfg_path), "--as-of", AS_OF])
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "OPS_STATE_NOT_INITIALIZED"


def test_cli_ops_run_failed_exit_code(tmp_path, env, capsys):
    from ca_es.cli import main
    cfg = json.loads(json.dumps(env["cfg"]))
    del cfg["inputs"]["canon"]
    cfg_path = tmp_path / "bad.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    state_dir = str(tmp_path / "cli-state2")
    main(["ops-init", "--state", state_dir])
    capsys.readouterr()
    rc = main(["ops-run", "--state", state_dir,
               "--config", str(cfg_path), "--as-of", AS_OF])
    assert rc == 2
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["run_status"] == "FAILED"
