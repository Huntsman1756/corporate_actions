"""P7.8 — superficies read-only: ops-status, ops-latest,
ops-export-run y desk --latest. Nunca recalculan negocio."""
import json
from pathlib import Path

import pytest

from ca_es.ops_dag import run_ops
from ca_es.ops_read import (
    export_run,
    ops_latest_doc,
    ops_status_doc,
)
from ca_es.ops_state import OpsState

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


# ------------------------------------------------------------------
# ops_status_doc
# ------------------------------------------------------------------

def test_status_empty_state(env):
    with env["state"].open() as conn:
        doc = ops_status_doc(env["state"], conn)
    assert doc["schema"] == "CA_ES_OPS_STATUS_V1"
    assert doc["active_run"] is None
    assert doc["latest_run"] is None
    assert doc["latest_successful_run"] is None
    assert doc["health"] == "NO_HEALTH"
    assert doc["pending_alerts"] == 0
    assert doc["inbox_failures"] == 0


def test_status_after_successful_run(env):
    m = run_ops(env["cfg"], env["state"], AS_OF)
    with env["state"].open() as conn:
        doc = ops_status_doc(env["state"], conn)
    assert doc["latest_run"]["run_id"] == m["run_id"]
    assert doc["latest_run"]["run_status"] == "SUCCEEDED"
    assert doc["latest_successful_run"]["run_id"] == m["run_id"]
    assert doc["health"] in ("HEALTHY", "DEGRADED", "FAILED")
    step_ids = {s["step_id"] for s in doc["steps"]}
    assert "compute_deadlines" in step_ids
    assert "exception_cases" in step_ids


def test_status_reports_failed_run(env):
    cfg = json.loads(json.dumps(env["cfg"]))
    del cfg["inputs"]["canon"]
    m = run_ops(cfg, env["state"], AS_OF)
    assert m["run_status"] == "FAILED"
    with env["state"].open() as conn:
        doc = ops_status_doc(env["state"], conn)
    assert doc["latest_run"]["run_status"] == "FAILED"
    assert doc["latest_failed_run"]["run_id"] == m["run_id"]
    assert doc["latest_successful_run"] is None


def test_status_counts_open_exceptions(env):
    # MOV-1 cuadra exacto contra el entitlement de 12500 -> 0 casos.
    # Con un movimiento distinto se abre un caso OPEN.
    movs = json.loads(json.dumps(MOVEMENTS))
    movs["movements"][0]["amount"] = "1.00"
    _w(env["inputs"], "movs.json", movs)
    m = run_ops(env["cfg"], env["state"], AS_OF)
    assert m["run_status"] == "SUCCEEDED"
    with env["state"].open() as conn:
        doc = ops_status_doc(env["state"], conn)
    assert doc["open_exceptions"] >= 1


# ------------------------------------------------------------------
# ops_latest_doc
# ------------------------------------------------------------------

def test_latest_empty_state(env):
    with env["state"].open() as conn:
        doc = ops_latest_doc(env["state"], conn)
    assert doc["status"] == "NO_SUCCESSFUL_RUN"
    assert doc["run"] is None


def test_latest_after_run(env):
    m = run_ops(env["cfg"], env["state"], AS_OF)
    with env["state"].open() as conn:
        doc = ops_latest_doc(env["state"], conn)
    assert doc["run"]["run_id"] == m["run_id"]
    assert doc["run"]["as_of"] == AS_OF
    arts = doc["artifacts"]
    assert arts["compute_deadlines"]["status"] == "SUCCEEDED"
    assert arts["compute_deadlines"]["sha256"]
    assert arts["compute_deadlines"]["semantic_sha256"]


def test_latest_ignores_later_failed_run(env):
    m1 = run_ops(env["cfg"], env["state"], AS_OF)
    cfg2 = json.loads(json.dumps(env["cfg"]))
    del cfg2["inputs"]["canon"]
    run_ops(cfg2, env["state"], AS_OF)
    with env["state"].open() as conn:
        doc = ops_latest_doc(env["state"], conn)
    assert doc["run"]["run_id"] == m1["run_id"]


# ------------------------------------------------------------------
# export_run
# ------------------------------------------------------------------

def test_export_run_writes_manifest_steps_lineage(env, tmp_path):
    m = run_ops(env["cfg"], env["state"], AS_OF)
    out = tmp_path / "export"
    with env["state"].open() as conn:
        res = export_run(env["state"], conn, m["run_id"], out)
    assert res["schema"] == "CA_ES_OPS_EXPORT_V1"
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["run_id"] == m["run_id"]
    steps = json.loads((out / "steps.json").read_text())
    assert {s["step_id"] for s in steps} == \
        {s["step_id"] for s in m["steps"]}
    lineage_lines = (out / "lineage.jsonl").read_text().strip()
    assert lineage_lines
    copied = {c["step_id"] for c in res["artifacts"]}
    assert "compute_deadlines" in copied
    # inputs confidenciales excluidos por defecto
    assert "validate_inputs" not in copied


def test_export_run_include_inputs(env, tmp_path):
    m = run_ops(env["cfg"], env["state"], AS_OF)
    out = tmp_path / "export2"
    with env["state"].open() as conn:
        res = export_run(env["state"], conn, m["run_id"], out,
                         include_inputs=True)
    copied = {c["step_id"] for c in res["artifacts"]}
    assert "validate_inputs" in copied


def test_export_run_unknown_run_fails(env, tmp_path):
    run_ops(env["cfg"], env["state"], AS_OF)
    with env["state"].open() as conn:
        with pytest.raises(ValueError, match="RUN_NOT_FOUND"):
            export_run(env["state"], conn, "no-existe",
                       tmp_path / "x")


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def _cli_env(tmp_path, env):
    cfg_path = tmp_path / "ops.json"
    cfg_path.write_text(json.dumps(env["cfg"]), encoding="utf-8")
    state_dir = str(tmp_path / "cli-state")
    return cfg_path, state_dir


def test_cli_ops_status_and_latest(tmp_path, env, capsys):
    from ca_es.cli import main
    cfg_path, state_dir = _cli_env(tmp_path, env)
    main(["ops-init", "--state", state_dir])
    capsys.readouterr()

    assert main(["ops-status", "--state", state_dir]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["health"] == "NO_HEALTH"

    assert main(["ops-latest", "--state", state_dir]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["status"] == "NO_SUCCESSFUL_RUN"

    assert main(["ops-run", "--state", state_dir,
                 "--config", str(cfg_path), "--as-of", AS_OF]) == 0
    manifest = json.loads(capsys.readouterr().out)

    assert main(["ops-status", "--state", state_dir]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["latest_run"]["run_id"] == manifest["run_id"]

    assert main(["ops-latest", "--state", state_dir]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["run"]["run_id"] == manifest["run_id"]


def test_cli_ops_export_run(tmp_path, env, capsys):
    from ca_es.cli import main
    cfg_path, state_dir = _cli_env(tmp_path, env)
    main(["ops-init", "--state", state_dir])
    capsys.readouterr()
    main(["ops-run", "--state", state_dir,
          "--config", str(cfg_path), "--as-of", AS_OF])
    manifest = json.loads(capsys.readouterr().out)
    out_dir = str(tmp_path / "exp")
    rc = main(["ops-export-run", "--state", state_dir,
               "--run-id", manifest["run_id"],
               "--output", out_dir])
    assert rc == 0
    res = json.loads(capsys.readouterr().out)
    assert res["run_id"] == manifest["run_id"]
    assert (Path(out_dir) / "manifest.json").is_file()


def test_cli_ops_export_unknown_run(tmp_path, env, capsys):
    from ca_es.cli import main
    cfg_path, state_dir = _cli_env(tmp_path, env)
    main(["ops-init", "--state", state_dir])
    capsys.readouterr()
    main(["ops-run", "--state", state_dir,
          "--config", str(cfg_path), "--as-of", AS_OF])
    capsys.readouterr()
    rc = main(["ops-export-run", "--state", state_dir,
               "--run-id", "no-existe",
               "--output", str(tmp_path / "x")])
    assert rc == 2


def test_cli_ops_inbox_empty(tmp_path, env, capsys):
    from ca_es.cli import main
    _, state_dir = _cli_env(tmp_path, env)
    main(["ops-init", "--state", state_dir])
    capsys.readouterr()
    rc = main(["ops-inbox", "--state", state_dir])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["messages"] == []
