"""P7.5 — operational health: checks deterministas, umbrales de
config, negocio != runtime."""
import json

import pytest

from ca_es.ops_health import (
    DEGRADED,
    FAILED,
    HEALTHY,
    compute_health,
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

NOW = "2026-09-16T08:00:00Z"
AS_OF = "2026-09-16"


def _cfg(inputs, **health):
    cfg = {
        "schema": "CA_ES_OPS_CONFIG_V1",
        "inputs": inputs,
        "action_queue": {"window_days": 30, "due_soon_days": 7},
    }
    if health:
        cfg["health"] = health
    return cfg


@pytest.fixture()
def state(tmp_path):
    return OpsState(tmp_path / "state").init()


def _health(state, cfg, **kw):
    conn = state._connect()
    try:
        doc = compute_health(state, conn, cfg, now=NOW, **kw)
        conn.commit()
        return doc
    finally:
        conn.close()


def _by_name(doc):
    return {c["name"]: c for c in doc["checks"]}


def test_empty_state_degraded(state):
    doc = _health(state, _cfg({}))
    assert doc["schema"] == "CA_ES_OPERATIONAL_HEALTH_V1"
    assert doc["status"] == DEGRADED
    assert _by_name(doc)["last_successful_run"]["status"] == \
        DEGRADED


def test_missing_required_inputs_failed(state):
    cfg = _cfg({"canon": {"path": "x", "required": True}})
    doc = _health(state, cfg, input_docs={})
    assert doc["status"] == FAILED
    chk = _by_name(doc)["required_inputs"]
    assert chk["status"] == FAILED
    assert chk["detail"]["missing"] == ["canon"]


def test_positions_missing_degrades(state):
    cfg = _cfg({"positions": {"path": "x"}})
    doc = _health(state, cfg, input_docs={})
    assert _by_name(doc)["positions_available"]["status"] == \
        DEGRADED


def test_positions_stale_degrades(state):
    cfg = _cfg({"positions": {"path": "x"}},
               positions_max_age_days=5)
    pos = {"schema": "CA_ES_POSITIONS_V1", "as_of": "2026-05-04",
           "positions": []}
    doc = _health(state, cfg, input_docs={"positions": pos},
                  as_of=AS_OF)
    chk = _by_name(doc)["positions_freshness"]
    assert chk["status"] == DEGRADED
    assert chk["detail"]["age_days"] > 5


def test_positions_fresh_ok(state):
    cfg = _cfg({"positions": {"path": "x"}},
               positions_max_age_days=200)
    pos = {"schema": "CA_ES_POSITIONS_V1", "as_of": "2026-09-10",
           "positions": []}
    doc = _health(state, cfg, input_docs={"positions": pos},
                  as_of=AS_OF)
    assert _by_name(doc)["positions_freshness"]["status"] == "OK"


def test_no_threshold_is_info_not_degraded(state):
    cfg = _cfg({"positions": {"path": "x"}})
    pos = {"schema": "CA_ES_POSITIONS_V1", "as_of": "2020-01-01",
           "positions": []}
    doc = _health(state, cfg, input_docs={"positions": pos},
                  as_of=AS_OF)
    # sin umbral configurado nunca se inventa uno
    assert _by_name(doc)["positions_freshness"]["status"] == "INFO"


def test_inbox_failures_degrade(state):
    inbox = {"messages": [
        {"processing_status": "FAILED"},
        {"processing_status": "PROCESSED"},
        {"processing_status": "FAILED"},
    ]}
    doc = _health(state, _cfg({}), inbox_index=inbox)
    chk = _by_name(doc)["inbox_failures"]
    assert chk["status"] == DEGRADED
    assert chk["detail"]["failed"] == 2


def test_stale_running_step_degrades(state):
    with state.open() as conn:
        state.insert_run(conn, {
            "run_id": "old", "as_of": "2026-09-01",
            "started_at": "2026-09-01T00:00:00Z",
            "run_status": "RUNNING", "manifest": {}})
        state.upsert_step(conn, "old", {
            "step_id": "compute_deadlines", "status": "RUNNING"})
    doc = _health(state, _cfg({}), current_run_id="new-run")
    chk = _by_name(doc)["stale_running_steps"]
    assert chk["status"] == DEGRADED
    assert chk["detail"]["steps"][0]["step_id"] == \
        "compute_deadlines"


def test_current_run_running_step_not_stale(state):
    with state.open() as conn:
        state.insert_run(conn, {
            "run_id": "me", "as_of": "x",
            "started_at": "x", "run_status": "RUNNING",
            "manifest": {}})
        state.upsert_step(conn, "me", {
            "step_id": "health_report", "status": "RUNNING"})
    doc = _health(state, _cfg({}), current_run_id="me")
    assert _by_name(doc)["stale_running_steps"]["status"] == "OK"


def test_corrupted_artifact_fails(state):
    with state.open() as conn:
        state.insert_run(conn, {
            "run_id": "r1", "as_of": "x", "started_at": "x",
            "run_status": "SUCCEEDED", "manifest": {}})
        ref = state.store_artifact(conn, {"a": 1}, "S", "V1",
                                   run_id="r1")
        state.upsert_step(conn, "r1", {
            "step_id": "s1", "status": "SUCCEEDED",
            "output_sha256": ref["sha256"],
            "output_ref": ref["ref"]})
    # corrompe el artefacto referenciado
    sha = ref["sha256"]
    (state.artifacts_dir / f"{sha[:2]}/{sha}.json").write_bytes(
        b"corrupto")
    doc = _health(state, _cfg({}))
    chk = _by_name(doc)["artifact_integrity"]
    assert chk["status"] == FAILED
    assert doc["status"] == FAILED


def test_indeterminate_deadlines_info_only(state):
    deadlines = {"deadlines": [
        {"derivation_status": "INDETERMINATE"},
        {"derivation_status": "INDETERMINATE"},
        {"derivation_status": "DERIVED"},
    ]}
    doc = _health(state, _cfg({}), deadlines_doc=deadlines)
    chk = _by_name(doc)["indeterminate_deadlines"]
    assert chk["status"] == "INFO"
    assert chk["detail"]["count"] == 2
    # INFO nunca degrada por si solo: el overall depende de otros
    assert doc["status"] != FAILED


# ---------------- nivel DAG ----------------

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
    return cfg, OpsState(tmp_path / "state").init()


def _health_doc(state, manifest):
    steps = {s["step_id"]: s for s in manifest["steps"]}
    sha = steps["health_report"]["output_sha256"]
    return state.get_artifact(sha)


def test_dag_health_first_run_degraded_second_healthy(env):
    from ca_es.ops_dag import run_ops
    cfg, state = env
    m1 = run_ops(cfg, state, AS_OF)
    assert m1["run_status"] == "SUCCEEDED"
    h1 = _health_doc(state, m1)
    # primer run: aun no hay run SUCCEEDED previo -> DEGRADED
    assert h1["status"] == DEGRADED
    m2 = run_ops(cfg, state, AS_OF)
    h2 = _health_doc(state, m2)
    assert h2["status"] == HEALTHY
    names = _by_name(h2)
    assert names["last_successful_run"]["status"] == "OK"
    assert names["artifact_integrity"]["status"] == "OK"
    assert names["stale_running_steps"]["status"] == "OK"


def test_business_mismatch_keeps_runtime_healthy(env):
    """Recon MISMATCH (excepcion de negocio) con runtime HEALTHY."""
    from ca_es.ops_dag import run_ops
    cfg, state = env
    inputs_dir = __import__("pathlib").Path(
        cfg["inputs"]["positions"]["path"]).parent
    movs = json.loads(json.dumps(MOVEMENTS))
    movs["movements"][0]["amount"] = "999.99"  # mismatch real
    _w(inputs_dir, "movs.json", movs)
    run_ops(cfg, state, AS_OF)
    m2 = run_ops(cfg, state, AS_OF)
    h = _health_doc(state, m2)
    assert h["status"] == HEALTHY
    # y la excepcion de negocio sigue existiendo como tal
    steps = {s["step_id"]: s for s in m2["steps"]}
    idx = state.get_artifact(
        steps["exception_cases"]["output_sha256"])
    assert idx.get("items")
