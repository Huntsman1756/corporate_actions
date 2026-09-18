"""P10.7/P10.8/P10.9 — dispatcher: derivacion, dispatch, agregado
outbox, retries, clear policy, UNKNOWN_OUTCOME, operator controls."""
from __future__ import annotations

import json

import pytest

from ca_es.ops_alerts import apply_alerts
from ca_es.ops_delivery import (
    AdapterResult, D_ABANDONED, D_DELIVERED, D_FAILED_PERMANENT,
    D_FAILED_RETRYABLE, D_PENDING, D_UNKNOWN, O_FAILED_PERMANENT,
    O_FAILED_RETRYABLE, O_SUCCEEDED, O_UNKNOWN, delivery_abandon,
    delivery_retry, get_delivery, list_attempts, list_deliveries,
    list_transitions, run_alert_deliver)
from ca_es.ops_state import OpsState
from ca_es.semantic_hash import semantic_sha256

NOW = "2026-09-18T10:00:00Z"


def _candidate(alert_key="DEADLINE_OVERDUE|dk1",
               category="DEADLINE_OVERDUE", payload=None):
    payload = payload or {
        "canonical_event_id": "EV-1", "deadline_type": "RESPONSE_DEADLINE",
        "deadline_date": "2026-09-20", "action_status": "OVERDUE",
        "days_until": -2}
    return {
        "alert_key": alert_key,
        "category": category,
        "subject_type": "deadline",
        "subject_key": alert_key.split("|", 1)[1],
        "payload": payload,
        "evidence_refs": ["sha:ref1"],
        "semantic_sha256": semantic_sha256(payload),
    }


def _seed(state, candidates, run_id="r1", evaluated=None):
    with state.open() as conn:
        return apply_alerts(
            conn, candidates, run_id, evaluated or set(), now=NOW)


def _deliver_pass(state, cfg, *, now=NOW, adapters=None):
    conn = state.acquire_run_lock("deliver-test")
    try:
        doc = run_alert_deliver(
            state, conn, cfg, now_fn=lambda: now,
            adapters=adapters)
        state.checkpoint()
        return doc
    finally:
        state.release_run_lock()


def _file_cfg(tmp_path, **kw):
    cfg = {
        "enabled": True,
        "destinations": [{
            "destination_id": "f1", "adapter": "file",
            "enabled": True, "categories": ["*"],
            "config": {"directory": str(tmp_path / "dlv")}}],
    }
    cfg.update(kw)
    return cfg


def test_derive_and_deliver_file(tmp_path):
    state = OpsState(tmp_path / "st").init()
    _seed(state, [_candidate()])
    doc = _deliver_pass(state, _file_cfg(tmp_path))
    assert doc["status"] == "SUCCESS"
    assert doc["deliveries_created"] == 1
    assert doc["succeeded"] == 1
    with state.open() as conn:
        deliveries = list_deliveries(conn)
        assert len(deliveries) == 1
        d = deliveries[0]
        assert d["status"] == D_DELIVERED
        assert d["generation"] == 1
        assert d["adapter_type"] == "file"
        attempts = list_attempts(conn, d["delivery_key"])
        assert len(attempts) == 1
        assert attempts[0]["status"] == "SUCCEEDED"
        alert = conn.execute(
            "SELECT delivery_state, delivery_attempts FROM outbox"
            " WHERE alert_key=?",
            ("DEADLINE_OVERDUE|dk1",)).fetchone()
        assert alert["delivery_state"] == "DELIVERED"
        assert alert["delivery_attempts"] == 1


def test_second_pass_no_duplicate(tmp_path):
    state = OpsState(tmp_path / "st").init()
    _seed(state, [_candidate()])
    cfg = _file_cfg(tmp_path)
    _deliver_pass(state, cfg)
    doc2 = _deliver_pass(state, cfg)
    assert doc2["attempted"] == 0
    assert doc2["skipped_delivered"] == 1
    with state.open() as conn:
        assert len(list_deliveries(conn)) == 1
        assert len(list_attempts(
            conn, list_deliveries(conn)[0]["delivery_key"])) == 1


def test_changed_payload_new_generation(tmp_path):
    state = OpsState(tmp_path / "st").init()
    cand = _candidate()
    _seed(state, [cand])
    cfg = _file_cfg(tmp_path)
    _deliver_pass(state, cfg)
    # payload cambia -> apply_alerts rearma delivery_state
    cand2 = dict(cand, payload=dict(
        cand["payload"], days_until=-3))
    cand2["semantic_sha256"] = semantic_sha256(cand2["payload"])
    _seed(state, [cand2], run_id="r2")
    doc = _deliver_pass(state, cfg)
    assert doc["deliveries_created"] == 1
    assert doc["succeeded"] == 1
    with state.open() as conn:
        deliveries = list_deliveries(conn)
        assert len(deliveries) == 2
        assert {d["generation"] for d in deliveries} == {1, 2}
        assert deliveries[0]["delivery_key"] != \
            deliveries[1]["delivery_key"]
        alert = conn.execute(
            "SELECT delivery_state FROM outbox"
            " WHERE alert_key=?",
            ("DEADLINE_OVERDUE|dk1",)).fetchone()
        assert alert["delivery_state"] == "DELIVERED"


def test_disabled_delivery_is_noop(tmp_path):
    state = OpsState(tmp_path / "st").init()
    _seed(state, [_candidate()])
    doc = _deliver_pass(state, {"enabled": False})
    assert doc["status"] == "DISABLED"
    with state.open() as conn:
        assert list_deliveries(conn) == []
        alert = conn.execute(
            "SELECT delivery_state FROM outbox").fetchone()
        assert alert["delivery_state"] == "PENDING_DELIVERY"


def test_category_not_routed_no_delivery(tmp_path):
    state = OpsState(tmp_path / "st").init()
    _seed(state, [_candidate()])
    cfg = _file_cfg(tmp_path)
    cfg["destinations"][0]["categories"] = ["SOURCE_*"]
    doc = _deliver_pass(state, cfg)
    assert doc["deliveries_created"] == 0
    with state.open() as conn:
        assert list_deliveries(conn) == []


def test_two_destinations_independent(tmp_path):
    """Destino A (file) OK + destino B (fake) falla permanente:
    estados independientes + agregado FAILED_DELIVERY."""
    state = OpsState(tmp_path / "st").init()
    _seed(state, [_candidate()])
    cfg = _file_cfg(tmp_path)
    cfg["destinations"].append({
        "destination_id": "bad", "adapter": "fakefail",
        "enabled": True, "categories": ["*"], "config": {}})
    adapters = {
        "file": _file_adapter(),
        "fakefail": lambda req, c: AdapterResult(
            O_FAILED_PERMANENT, error_code="BOOM")}
    doc = _deliver_pass(state, cfg, adapters=adapters)
    assert doc["succeeded"] == 1
    assert doc["failed_permanent"] == 1
    with state.open() as conn:
        ds = {d["destination_id"]: d for d in list_deliveries(conn)}
        assert ds["f1"]["status"] == D_DELIVERED
        assert ds["bad"]["status"] == D_FAILED_PERMANENT
        alert = conn.execute(
            "SELECT delivery_state FROM outbox").fetchone()
        assert alert["delivery_state"] == "FAILED_DELIVERY"


def _file_adapter():
    from ca_es.delivery.file_adapter import deliver
    return deliver


def test_retryable_then_success(tmp_path):
    state = OpsState(tmp_path / "st").init()
    _seed(state, [_candidate()])
    calls = []

    def flaky(req, cfg):
        calls.append(1)
        if len(calls) == 1:
            return AdapterResult(
                O_FAILED_RETRYABLE, error_code="HTTP_503")
        return AdapterResult(O_SUCCEEDED)

    cfg = {
        "enabled": True,
        "destinations": [{
            "destination_id": "w", "adapter": "flaky",
            "enabled": True, "categories": ["*"], "config": {}}],
        "retry": {"max_attempts": 5, "base_delay_seconds": 60,
                  "backoff_factor": 1.0}}
    doc1 = _deliver_pass(state, cfg,
                         adapters={"flaky": flaky})
    assert doc1["failed_retryable"] == 1
    with state.open() as conn:
        d = list_deliveries(conn)[0]
        assert d["status"] == D_FAILED_RETRYABLE
        assert d["next_attempt_after"] == "2026-09-18T10:01:00Z"

    # antes del backoff -> no elegible
    doc2 = _deliver_pass(state, cfg, now="2026-09-18T10:00:30Z",
                         adapters={"flaky": flaky})
    assert doc2["attempted"] == 0
    # despues -> reintenta y entrega
    doc3 = _deliver_pass(state, cfg, now="2026-09-18T10:02:00Z",
                         adapters={"flaky": flaky})
    assert doc3["succeeded"] == 1
    with state.open() as conn:
        d = list_deliveries(conn)[0]
        assert d["status"] == D_DELIVERED
        assert len(list_attempts(conn, d["delivery_key"])) == 2


def test_permanent_failure_not_auto_retried(tmp_path):
    state = OpsState(tmp_path / "st").init()
    _seed(state, [_candidate()])
    cfg = {
        "enabled": True,
        "destinations": [{
            "destination_id": "w", "adapter": "permfail",
            "enabled": True, "categories": ["*"], "config": {}}]}
    adapters = {"permfail": lambda r, c: AdapterResult(
        O_FAILED_PERMANENT, error_code="HTTP_404")}
    _deliver_pass(state, cfg, adapters=adapters)
    doc2 = _deliver_pass(state, cfg, now="2026-09-19T10:00:00Z",
                         adapters=adapters)
    assert doc2["attempted"] == 0
    with state.open() as conn:
        assert list_deliveries(conn)[0]["status"] == \
            D_FAILED_PERMANENT


def test_max_attempts_exhausted_goes_permanent(tmp_path):
    state = OpsState(tmp_path / "st").init()
    _seed(state, [_candidate()])
    cfg = {
        "enabled": True,
        "destinations": [{
            "destination_id": "w", "adapter": "alwaysfail",
            "enabled": True, "categories": ["*"], "config": {}}],
        "retry": {"max_attempts": 2, "base_delay_seconds": 0,
                  "backoff_factor": 1.0}}
    fail = {"alwaysfail": lambda r, c: AdapterResult(
        O_FAILED_RETRYABLE, error_code="HTTP_503")}
    _deliver_pass(state, cfg, adapters=fail)
    _deliver_pass(state, cfg, now="2026-09-18T10:00:01Z",
                  adapters=fail)
    with state.open() as conn:
        d = list_deliveries(conn)[0]
        assert d["status"] == D_FAILED_PERMANENT
        assert d["attempt_count"] == 2
        attempts = list_attempts(conn, d["delivery_key"])
        assert attempts[-1]["error_code"] == "RETRY_EXHAUSTED"


def test_orphan_started_attempt_unknown(tmp_path):
    """Crash tras STARTED persistido -> siguiente pasada marca
    UNKNOWN_OUTCOME sin reintentar."""
    state = OpsState(tmp_path / "st").init()
    _seed(state, [_candidate()])
    cfg = _file_cfg(tmp_path)
    # deriva la entrega sin intentar
    conn = state.acquire_run_lock("d1")
    run_alert_deliver(state, conn, cfg, now_fn=lambda: NOW,
                      adapters={"file": lambda r, c: AdapterResult(
                          O_SUCCEEDED)})
    state.checkpoint()
    state.release_run_lock()
    # simula crash: inserta attempt STARTED y vuelve a PENDING
    with state.open() as conn:
        d = list_deliveries(conn)[0]
        conn.execute(
            "UPDATE deliveries SET status=?, attempt_count=1"
            " WHERE delivery_key=?", (D_PENDING, d["delivery_key"]))
        conn.execute(
            "INSERT INTO delivery_attempts"
            " (attempt_id, delivery_key, attempt_number, started_at,"
            "  status) VALUES (?,?,?,?,?)",
            (f"ATT-{d['delivery_key']}-orphan", d["delivery_key"], 1,
             NOW, "STARTED"))
    doc = _deliver_pass(state, cfg)
    assert doc["orphan_attempts_marked_unknown"] == 1
    with state.open() as conn:
        d = list_deliveries(conn)[0]
        assert d["status"] == D_UNKNOWN
        attempt = list_attempts(conn, d["delivery_key"])[-1]
        assert attempt["status"] == "UNKNOWN"
    # y no se reintenta automaticamente
    doc2 = _deliver_pass(state, cfg, now="2026-09-19T00:00:00Z")
    assert doc2["attempted"] == 0


def test_unknown_not_retried_without_force(tmp_path):
    state = OpsState(tmp_path / "st").init()
    _seed(state, [_candidate()])
    cfg = {
        "enabled": True,
        "destinations": [{
            "destination_id": "w", "adapter": "uncertain",
            "enabled": True, "categories": ["*"], "config": {}}]}
    adapters = {"uncertain": lambda r, c: AdapterResult(
        O_UNKNOWN, error_code="POST_SEND_TIMEOUT")}
    _deliver_pass(state, cfg, adapters=adapters)
    with state.open() as conn:
        d = list_deliveries(conn)[0]
        assert d["status"] == D_UNKNOWN
        with pytest.raises(ValueError, match="FORCE"):
            delivery_retry(conn, d["delivery_key"], now=NOW)
        d2 = delivery_retry(
            conn, d["delivery_key"], now=NOW, force_unknown=True)
        assert d2["status"] == D_PENDING
        transitions = list_transitions(conn, d["delivery_key"])
        assert any(t["to_status"] == D_PENDING
                   and "FORCE_UNKNOWN" in (t["note"] or "")
                   for t in transitions)


def test_manual_retry_audit_trail(tmp_path):
    state = OpsState(tmp_path / "st").init()
    _seed(state, [_candidate()])
    cfg = {
        "enabled": True,
        "destinations": [{
            "destination_id": "w", "adapter": "perm",
            "enabled": True, "categories": ["*"], "config": {}}]}
    adapters = {"perm": lambda r, c: AdapterResult(
        O_FAILED_PERMANENT, error_code="HTTP_410")}
    _deliver_pass(state, cfg, adapters=adapters)
    with state.open() as conn:
        d = list_deliveries(conn)[0]
        delivery_retry(conn, d["delivery_key"], now=NOW,
                       actor="op-test")
        transitions = list_transitions(conn, d["delivery_key"])
        manual = [t for t in transitions if t["actor"] == "op-test"]
        assert manual and manual[-1]["to_status"] == D_PENDING


def test_delivered_cannot_retry_or_abandon(tmp_path):
    state = OpsState(tmp_path / "st").init()
    _seed(state, [_candidate()])
    _deliver_pass(state, _file_cfg(tmp_path))
    with state.open() as conn:
        d = list_deliveries(conn)[0]
        with pytest.raises(ValueError, match="DELIVERED"):
            delivery_retry(conn, d["delivery_key"], now=NOW)
        with pytest.raises(ValueError, match="DELIVERED"):
            delivery_abandon(conn, d["delivery_key"], now=NOW)


def test_abandon_terminal_and_audit(tmp_path):
    state = OpsState(tmp_path / "st").init()
    _seed(state, [_candidate()])
    cfg = {
        "enabled": True,
        "destinations": [{
            "destination_id": "w", "adapter": "perm",
            "enabled": True, "categories": ["*"], "config": {}}]}
    adapters = {"perm": lambda r, c: AdapterResult(
        O_FAILED_PERMANENT, error_code="HTTP_410")}
    _deliver_pass(state, cfg, adapters=adapters)
    with state.open() as conn:
        d = list_deliveries(conn)[0]
        d2 = delivery_abandon(conn, d["delivery_key"], now=NOW,
                              actor="op", note="superseded")
        assert d2["status"] == D_ABANDONED
        with pytest.raises(ValueError, match="ABANDONED"):
            delivery_retry(conn, d["delivery_key"], now=NOW)
        # abandon cuenta como fallo permanente en el agregado
        alert = conn.execute(
            "SELECT delivery_state FROM outbox").fetchone()
        assert alert["delivery_state"] == "FAILED_DELIVERY"


def test_cleared_alert_no_clear_message_by_default(tmp_path):
    state = OpsState(tmp_path / "st").init()
    cand = _candidate()
    _seed(state, [cand], evaluated={"DEADLINE_OVERDUE"})
    _deliver_pass(state, _file_cfg(tmp_path))
    # la alerta desaparece de los candidatos -> CLEARED
    _seed(state, [], run_id="r2", evaluated={"DEADLINE_OVERDUE"})
    doc = _deliver_pass(state, _file_cfg(tmp_path))
    assert doc["deliveries_created"] == 0
    assert doc["attempted"] == 0
    with state.open() as conn:
        assert len(list_deliveries(conn)) == 1  # solo la OPEN gen


def test_cleared_alert_notify_on_clear(tmp_path):
    state = OpsState(tmp_path / "st").init()
    cand = _candidate()
    _seed(state, [cand], evaluated={"DEADLINE_OVERDUE"})
    cfg = _file_cfg(tmp_path, payload_policy={
        "notify_on_clear": True})
    _deliver_pass(state, cfg)
    _seed(state, [], run_id="r2", evaluated={"DEADLINE_OVERDUE"})
    doc = _deliver_pass(state, cfg)
    assert doc["deliveries_created"] == 1
    assert doc["succeeded"] == 1
    with state.open() as conn:
        deliveries = list_deliveries(conn)
        assert len(deliveries) == 2
        clear = [d for d in deliveries if d["alert_state"]
                 == "CLEARED"][0]
        assert clear["generation"] == 2
        assert clear["delivery_key"] != deliveries[0]["delivery_key"]
        payload = json.loads(clear["payload_json"])
        assert payload["state"] == "CLEARED"


def test_reopened_alert_changed_semantics_new_delivery(tmp_path):
    """Reopen con payload distinto -> nueva generacion."""
    state = OpsState(tmp_path / "st").init()
    cand = _candidate()
    _seed(state, [cand], evaluated={"DEADLINE_OVERDUE"})
    cfg = _file_cfg(tmp_path)
    _deliver_pass(state, cfg)
    _seed(state, [], run_id="r2", evaluated={"DEADLINE_OVERDUE"})
    cand2 = dict(cand, payload=dict(cand["payload"], days_until=-9))
    cand2["semantic_sha256"] = semantic_sha256(cand2["payload"])
    _seed(state, [cand2], run_id="r3", evaluated={"DEADLINE_OVERDUE"})
    doc = _deliver_pass(state, cfg)
    assert doc["deliveries_created"] == 1
    assert doc["succeeded"] == 1
    with state.open() as conn:
        assert len(list_deliveries(conn)) == 2


def test_reopened_same_payload_dedup(tmp_path):
    """Reopen con MISMO payload -> mismo delivery_key ya DELIVERED
    -> no re-envio."""
    state = OpsState(tmp_path / "st").init()
    cand = _candidate()
    _seed(state, [cand], evaluated={"DEADLINE_OVERDUE"})
    cfg = _file_cfg(tmp_path)
    _deliver_pass(state, cfg)
    _seed(state, [], run_id="r2", evaluated={"DEADLINE_OVERDUE"})
    _seed(state, [cand], run_id="r3", evaluated={"DEADLINE_OVERDUE"})
    doc = _deliver_pass(state, cfg)
    assert doc["deliveries_created"] == 0
    assert doc["attempted"] == 0


def test_notify_on_change_disabled(tmp_path):
    state = OpsState(tmp_path / "st").init()
    cand = _candidate()
    _seed(state, [cand])
    cfg = _file_cfg(tmp_path, payload_policy={
        "notify_on_change": False})
    _deliver_pass(state, cfg)
    cand2 = dict(cand, payload=dict(cand["payload"], days_until=-4))
    cand2["semantic_sha256"] = semantic_sha256(cand2["payload"])
    _seed(state, [cand2], run_id="r2")
    doc = _deliver_pass(state, cfg)
    assert doc["deliveries_created"] == 0
    assert doc["attempted"] == 0


def test_unknown_adapter_type_in_config_skipped(tmp_path):
    """Destino con adapter fuera del registry inyectado: no deriva
    (fail-closed via registry, config validation lo rechazaria)."""
    state = OpsState(tmp_path / "st").init()
    _seed(state, [_candidate()])
    cfg = {"enabled": True, "destinations": [{
        "destination_id": "x", "adapter": "carrier_pigeon",
        "enabled": True, "categories": ["*"], "config": {}}]}
    doc = _deliver_pass(state, cfg)
    assert doc["deliveries_created"] == 0


def test_outbound_payload_minimized(tmp_path):
    """El payload persistido solo lleva campos base + allowlist."""
    state = OpsState(tmp_path / "st").init()
    cand = _candidate(payload={
        "canonical_event_id": "EV-1", "deadline_type": "T",
        "deadline_date": "2026-09-20", "action_status": "OVERDUE",
        "days_until": -2, "account_id": "SECRET-ACC",
        "raw_mt": "{4:...}", "positions": ["x"]})
    _seed(state, [cand])
    _deliver_pass(state, _file_cfg(tmp_path))
    with state.open() as conn:
        d = list_deliveries(conn)[0]
        payload = json.loads(d["payload_json"])
    assert payload["schema"] == "CA_ES_ALERT_DELIVERY_PAYLOAD_V1"
    assert "account_id" not in json.dumps(payload)
    assert "raw_mt" not in json.dumps(payload)
    assert "positions" not in json.dumps(payload)
    assert payload["details"]["canonical_event_id"] == "EV-1"
    assert payload["details"]["days_until"] == -2


def test_unknown_category_minimal_details(tmp_path):
    state = OpsState(tmp_path / "st").init()
    cand = _candidate(alert_key="WEIRD|w1", category="WEIRD_NEW_CAT",
                      payload={"a": 1, "secret_thing": "x"})
    _seed(state, [cand])
    _deliver_pass(state, _file_cfg(tmp_path))
    with state.open() as conn:
        d = list_deliveries(conn)[0]
        payload = json.loads(d["payload_json"])
    assert payload["details"] == {}
    assert payload["category"] == "WEIRD_NEW_CAT"
