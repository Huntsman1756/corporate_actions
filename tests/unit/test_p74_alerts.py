"""P7.4 — alert outbox: identidad estable, dedup, lifecycles
state/delivery independientes."""
import json

import pytest

from ca_es.ops_alerts import (
    CLEARED,
    DELIVERED,
    OPEN,
    PENDING_DELIVERY,
    apply_alerts,
    derive_deadline_alerts,
    derive_exception_alerts,
    derive_inbox_alerts,
    outbox_all,
    run_failed_candidate,
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


@pytest.fixture()
def conn(tmp_path):
    state = OpsState(tmp_path / "state").init()
    c = state._connect()
    yield state, c
    c.close()


def _alert(category="DEADLINE_OVERDUE", key="DL-1",
           payload=None, stype="deadline"):
    return {
        "alert_key": f"{category}|{key}",
        "category": category,
        "subject_type": stype,
        "subject_key": key,
        "payload": payload or {"x": 1},
        "evidence_refs": [],
        "semantic_sha256": __import__(
            "ca_es.semantic_hash", fromlist=["x"]).semantic_sha256(
            payload or {"x": 1}),
    }


def _cand(category, key, payload, stype="deadline"):
    from ca_es.semantic_hash import semantic_sha256
    return {
        "alert_key": f"{category}|{key}",
        "category": category,
        "subject_type": stype,
        "subject_key": key,
        "payload": payload,
        "evidence_refs": [],
        "semantic_sha256": semantic_sha256(payload),
    }


def test_new_alert_open_pending(conn):
    state, c = conn
    stats = apply_alerts(c, [_cand("DEADLINE_OVERDUE", "DL-1",
                                 {"d": "2026-09-10"})],
                         "run1", {"DEADLINE_OVERDUE"}, now=NOW)
    assert stats["new"] == 1
    row = outbox_all(c)[0]
    assert row["state"] == OPEN
    assert row["delivery_state"] == PENDING_DELIVERY
    assert row["first_observed_run_id"] == "run1"
    assert row["last_observed_run_id"] == "run1"


def test_identical_run_no_new_notification(conn):
    state, c = conn
    cand = _cand("DEADLINE_OVERDUE", "DL-1", {"d": "2026-09-10"})
    apply_alerts(c, [cand], "run1", {"DEADLINE_OVERDUE"}, now=NOW)
    # simula entrega previa
    c.execute("UPDATE outbox SET delivery_state=?",
              (DELIVERED,))
    stats = apply_alerts(c, [cand], "run2",
                         {"DEADLINE_OVERDUE"}, now=NOW)
    assert stats["unchanged"] == 1
    row = outbox_all(c)[0]
    assert row["delivery_state"] == DELIVERED  # no rearma
    assert row["last_observed_run_id"] == "run2"
    assert len(outbox_all(c)) == 1


def test_changed_facts_same_identity_rearms(conn):
    state, c = conn
    apply_alerts(c, [_cand("DEADLINE_OVERDUE", "DL-1",
                           {"d": "2026-09-10"})],
                 "run1", {"DEADLINE_OVERDUE"}, now=NOW)
    c.execute("UPDATE outbox SET delivery_state=?", (DELIVERED,))
    stats = apply_alerts(
        c, [_cand("DEADLINE_OVERDUE", "DL-1",
                  {"d": "2026-09-08"})],
        "run2", {"DEADLINE_OVERDUE"}, now=NOW)
    assert stats["updated"] == 1
    row = outbox_all(c)[0]
    assert row["delivery_state"] == PENDING_DELIVERY  # rearma
    assert row["state"] == OPEN
    assert len(outbox_all(c)) == 1


def test_condition_gone_clears(conn):
    state, c = conn
    apply_alerts(c, [_cand("DEADLINE_DUE_SOON", "DL-1", {"d": 1})],
                 "run1", {"DEADLINE_DUE_SOON"}, now=NOW)
    stats = apply_alerts(c, [], "run2", {"DEADLINE_DUE_SOON"},
                         now=NOW)
    assert stats["cleared"] == 1
    row = outbox_all(c)[0]
    assert row["state"] == CLEARED
    assert row["delivery_state"] == PENDING_DELIVERY


def test_unevaluated_category_not_cleared(conn):
    state, c = conn
    apply_alerts(c, [_cand("DEADLINE_OVERDUE", "DL-1", {"d": 1})],
                 "run1", {"DEADLINE_OVERDUE"}, now=NOW)
    # run2 evalua solo EXCEPTION_CASE (queue sin output)
    stats = apply_alerts(c, [], "run2", {"EXCEPTION_CASE"},
                         now=NOW)
    assert stats["cleared"] == 0
    assert outbox_all(c)[0]["state"] == OPEN


def test_cleared_reopens_on_recurrence(conn):
    state, c = conn
    cand = _cand("EXCEPTION_CASE", "CASE-1", {"f": "MISMATCH"},
                 stype="exception_case")
    apply_alerts(c, [cand], "run1", {"EXCEPTION_CASE"}, now=NOW)
    apply_alerts(c, [], "run2", {"EXCEPTION_CASE"}, now=NOW)
    assert outbox_all(c)[0]["state"] == CLEARED
    stats = apply_alerts(c, [cand], "run3", {"EXCEPTION_CASE"},
                         now=NOW)
    assert stats["reopened"] == 1
    row = outbox_all(c)[0]
    assert row["state"] == OPEN
    assert row["delivery_state"] == PENDING_DELIVERY
    assert row["first_observed_run_id"] == "run1"


def test_derive_deadline_alerts_maps_status():
    queue = {"items": [
        {"deadline_key": "K1", "canonical_event_id": "E1",
         "deadline_type": "RESPONSE_DEADLINE",
         "deadline_date": "2026-09-10", "action_status": "OVERDUE",
         "days_until": -6},
        {"deadline_key": "K2", "canonical_event_id": "E1",
         "deadline_type": "X", "deadline_date": "2026-09-16",
         "action_status": "DUE_TODAY", "days_until": 0},
        {"deadline_key": "K3", "canonical_event_id": "E1",
         "deadline_type": "X", "deadline_date": "2026-09-30",
         "action_status": "UPCOMING", "days_until": 14},
    ]}
    alerts = derive_deadline_alerts(queue, None)
    cats = {a["category"] for a in alerts}
    assert cats == {"DEADLINE_OVERDUE", "DEADLINE_DUE_TODAY"}
    assert alerts[0]["alert_key"] == "DEADLINE_OVERDUE|K1"


def test_derive_exception_alerts_open_cases():
    cases = {"cases": [
        {"case_key": "C1", "canonical_event_id": "E1",
         "workflow_status": "OPEN", "factual_status": "MISMATCH",
         "reason_codes": ["AMOUNT_MISMATCH"],
         "history": [{"type": "CREATED"}]},
        {"case_key": "C2", "canonical_event_id": "E1",
         "workflow_status": "RESOLVED",
         "factual_status": "MISMATCH", "history": []},
    ]}
    alerts = derive_exception_alerts(cases, None)
    assert len(alerts) == 1
    assert alerts[0]["alert_key"] == "EXCEPTION_CASE|C1"
    assert alerts[0]["payload"]["last_action"] == "CREATED"


def test_derive_inbox_alerts_failed_only():
    inbox = {"messages": [
        {"input_sha256": "a1", "processing_status": "FAILED",
         "message_identifier": "MT564"},
        {"input_sha256": "b2", "processing_status": "PROCESSED"},
    ]}
    alerts = derive_inbox_alerts(inbox, None)
    assert len(alerts) == 1
    assert alerts[0]["alert_key"] == "PROCESSING_FAILURE|a1"


def test_run_failed_candidate():
    c = run_failed_candidate("run9", ["step_x"])
    assert c["alert_key"] == "RUN_FAILED|run9"
    assert c["payload"]["error_summary"] == ["step_x"]


# ---------------- nivel DAG ----------------

@pytest.fixture()
def env(tmp_path):
    from ca_es.ops_state import OpsState as _S
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
    return cfg, _S(tmp_path / "state").init()


def test_dag_alert_step_and_dedup(env):
    from ca_es.ops_dag import run_ops
    cfg, state = env
    run_ops(cfg, state, "2026-09-16")
    with state.open() as conn:
        n1 = conn.execute("SELECT COUNT(*) FROM outbox"
                          ).fetchone()[0]
    m2 = run_ops(cfg, state, "2026-09-16")
    with state.open() as conn:
        rows = outbox_all(conn)
        n2 = len(rows)
    assert n2 == n1  # segundo run identico: cero alertas nuevas
    step = [s for s in m2["steps"]
            if s["step_id"] == "alert_outbox"][0]
    assert step["status"] == "SUCCEEDED"
    # dedup real: ningun delivery re-armado en run2 (nada DELIVERED
    # -> PENDING sigue, pero no hay filas nuevas ni updated)
    assert all(r["last_observed_run_id"] == m2["run_id"]
               for r in rows)


def test_failed_run_emits_run_failed_alert(env):
    from ca_es.ops_dag import run_ops
    cfg, state = env
    cfg2 = json.loads(json.dumps(cfg))
    del cfg2["inputs"]["canon"]
    m = run_ops(cfg2, state, "2026-09-16")
    assert m["run_status"] == "FAILED"
    with state.open() as conn:
        rows = outbox_all(conn)
    assert any(r["category"] == "RUN_FAILED"
               and r["subject_key"] == m["run_id"]
               for r in rows)
