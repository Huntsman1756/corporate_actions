"""P7.7 — OpenLineage export: determinista, datasets
content-addressed, fallo opcional no invalida el run."""
import json
from pathlib import Path

import pytest

from ca_es.ops_lineage import (
    build_lineage_events,
    export_lineage,
)
from ca_es.ops_state import OpsState
from tests.unit.test_p72_ops_dag import (
    CALS,
    MOVEMENTS,
    POSITIONS,
    RULES,
    CANON,
    POLICY,
    _w,
)

AS_OF = "2026-09-16"


@pytest.fixture()
def env(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    cfg = {
        "schema": "CA_ES_OPS_CONFIG_V1",
        "inputs": {
            "canon": {"path": str(CANON), "required": True},
            "source_policy": {"path": str(POLICY), "required": True},
            "deadline_rules": {"path": _w(inputs, "rules.json",
                                          RULES),
                               "required": True},
            "calendars": {"path": _w(inputs, "cals.json", CALS),
                          "required": True},
            "positions": {"path": _w(inputs, "pos.json",
                                     POSITIONS)},
            "cash_movements": {"path": _w(inputs, "movs.json",
                                          MOVEMENTS)},
        },
        "action_queue": {"window_days": 30, "due_soon_days": 7},
    }
    return cfg, OpsState(tmp_path / "state").init(), tmp_path


def _run(env, extra=None):
    from ca_es.ops_dag import run_ops
    cfg, state, _ = env
    cfg = json.loads(json.dumps(cfg))
    if extra:
        cfg.update(extra)
    return run_ops(cfg, state, AS_OF), state


def test_events_cover_run_and_steps(env):
    m, state = _run(env)
    with state.open() as conn:
        events = build_lineage_events(state, conn, m["run_id"])
    types = [e["eventType"] for e in events]
    assert types[0] == "START"
    assert types[-1] == "COMPLETE"
    jobs = [e["job"]["name"] for e in events]
    assert jobs[0] == "ops-run" and jobs[-1] == "ops-run"
    step_events = [e for e in events
                   if e["job"]["name"].startswith("ops-run.")]
    assert len(step_events) == len(m["steps"])
    for e in step_events:
        assert e["run"]["runId"].startswith(m["run_id"])
        assert e["job"]["namespace"] == "ca-es"
        facet = e["job"]["facets"]["caEs"]
        assert "step_version" in facet
        assert "expected_output_schema" in facet


def test_datasets_are_content_addressed(env):
    m, state = _run(env)
    with state.open() as conn:
        events = build_lineage_events(state, conn, m["run_id"])
    outs = [o for e in events for o in e["outputs"]]
    assert outs
    assert all(o["namespace"] == "ca-es-artifacts" for o in outs)
    assert all(o["name"].startswith("artifact:") for o in outs)
    # nunca contenido de negocio en el evento
    blob = json.dumps(events)
    assert "ESTIMACIONES" not in blob
    assert "A001" not in blob


def test_export_deterministic(env):
    m, state = _run(env)
    with state.open() as conn:
        p1 = state.root / "l1.jsonl"
        p2 = state.root / "l2.jsonl"
        export_lineage(state, conn, m["run_id"], p1)
        export_lineage(state, conn, m["run_id"], p2)
    assert p1.read_bytes() == p2.read_bytes()


def test_cache_reuse_facet(env):
    m1, state = _run(env)
    m2, _ = _run(env)
    with state.open() as conn:
        events = build_lineage_events(state, conn, m2["run_id"])
    cached = [e for e in events
              if e["run"]["facets"]["caEs"].get(
                  "cache_source_run_id")]
    assert cached
    assert all(e["run"]["facets"]["caEs"]["cache_source_run_id"]
               == m1["run_id"] for e in cached)


def test_step_disabled_by_default(env):
    m, state = _run(env)
    step = [s for s in m["steps"]
            if s["step_id"] == "lineage_export"][0]
    assert step["status"] == "SUCCEEDED"
    doc = state.get_artifact(step["output_sha256"])
    assert doc["enabled"] is False


def test_enabled_writes_file(env):
    m, state = _run(env, {"lineage": {"enabled": True}})
    step = [s for s in m["steps"]
            if s["step_id"] == "lineage_export"][0]
    assert step["status"] == "SUCCEEDED"
    doc = state.get_artifact(step["output_sha256"])
    assert doc["enabled"] is True
    assert Path(doc["path"]).is_file()
    assert doc["events"] == len(m["steps"]) + 2


def test_optional_failure_does_not_fail_run(env, tmp_path):
    # path dentro de un fichero regular -> mkdir/open falla
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    m, state = _run(env, {
        "lineage": {"enabled": True, "required": False,
                    "path": str(blocker / "sub" / "l.jsonl")}})
    assert m["run_status"] == "SUCCEEDED"
    step = [s for s in m["steps"]
            if s["step_id"] == "lineage_export"][0]
    assert step["status"] == "SUCCEEDED"
    doc = state.get_artifact(step["output_sha256"])
    assert "error" in doc


def test_required_failure_fails_step(env, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    m, state = _run(env, {
        "lineage": {"enabled": True, "required": True,
                    "path": str(blocker / "sub" / "l.jsonl")}})
    step = [s for s in m["steps"]
            if s["step_id"] == "lineage_export"][0]
    assert step["status"] == "FAILED"
    assert m["run_status"] == "PARTIAL"  # opcional -> no FAILED
