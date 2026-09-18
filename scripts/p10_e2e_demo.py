"""P10 — demo e2e de aceptacion (ad-hoc, no en CI).

Leg 1: P7 ops-run -> alerta -> alert-deliver (file) -> SUCCEEDED.
Leg 2: mismo run otra vez -> mismo sem-sha -> sin segundo envio.
Leg 3: alert materialmente cambiada (as_of nuevo -> days_until
       cambia) -> misma alert_key, nueva generacion -> +1 entrega.
Leg 4: fallo transitorio -> FAILED_RETRYABLE -> reintento ->
       DELIVERED.
Leg 5: UNKNOWN_OUTCOME -> sin auto-retry -> operator-visible.
Leg 6: dos destinos, A ok B falla -> estados independientes +
       agregado correcto.

Uso: PYTHONPATH=src python scripts/p10_e2e_demo.py <work_dir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ca_es.ops_dag import run_ops  # noqa: E402
from ca_es.ops_delivery import (  # noqa: E402
    AdapterResult, O_FAILED_PERMANENT, O_FAILED_RETRYABLE,
    O_SUCCEEDED, O_UNKNOWN, list_attempts, list_deliveries,
    list_transitions, run_alert_deliver)
from ca_es.ops_state import OpsState  # noqa: E402

AS_OF = "2026-09-18"
RULES = {"schema": "CA_ES_DEADLINE_RULES_V1", "rules": [{
    "rule_id": "R1", "deadline_type": "RESPONSE_DEADLINE",
    "source_field": "date.payment_date", "business_days_offset": -1,
    "calendar_id": "TARGET2"}]}
CALS = {"schema": "CA_ES_CALENDARS_V1", "calendars": [{
    "calendar_id": "TARGET2", "business_week": [0, 1, 2, 3, 4],
    "holidays": []}]}
POSITIONS = {"schema": "CA_ES_POSITIONS_V1", "as_of": "2026-05-04",
             "positions": [{"account_id": "A001",
                            "isin": "ES0105561007",
                            "quantity": "100",
                            "as_of": "2026-05-04"}]}
MOVS = {"schema": "CA_ES_CASH_MOVEMENTS_V2", "movements": []}


def _deliver(state, cfg, adapters=None):
    conn = state.acquire_run_lock("demo-deliver")
    try:
        doc = run_alert_deliver(
            state, conn, cfg, adapters=adapters)
        state.checkpoint()
        return doc
    finally:
        state.release_run_lock()


def _file_dest(dest_id, directory):
    return {"destination_id": dest_id, "adapter": "file",
            "enabled": True, "categories": ["*"],
            "config": {"directory": str(directory)}}


def _alert_counts(state):
    with state.open() as conn:
        return conn.execute(
            "SELECT COUNT(*) c FROM outbox").fetchone()["c"]


def _deliveries(state):
    with state.open() as conn:
        return list_deliveries(conn)


def main(work_dir: str) -> int:
    root = Path(work_dir)
    inputs = root / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    for name, doc in [("rules.json", RULES), ("cals.json", CALS),
                      ("pos.json", POSITIONS), ("movs.json", MOVS)]:
        (inputs / name).write_text(json.dumps(doc), encoding="utf-8")
    base_inputs = {
        "canon": {"path": str(REPO / "g3/input/canon.json"),
                  "required": True},
        "source_policy": {
            "path": str(REPO / "docs/sources/source-policy.json"),
            "required": True},
        "deadline_rules": {"path": str(inputs / "rules.json"),
                           "required": True},
        "calendars": {"path": str(inputs / "cals.json"),
                      "required": True},
        "positions": {"path": str(inputs / "pos.json")},
        "cash_movements": {"path": str(inputs / "movs.json")},
    }
    cfg = {
        "schema": "CA_ES_OPS_CONFIG_V1",
        "inputs": base_inputs,
        "action_queue": {"window_days": 30, "due_soon_days": 7},
        "delivery": {"enabled": True, "destinations": [
            _file_dest("file-a", root / "delivery" / "file-a")]},
    }
    state = OpsState(root / "state").init()

    print("=== LEG 1: ops-run -> alerta -> entrega file =========")
    m1 = run_ops(cfg, state, AS_OF)
    print("run_status:", m1["run_status"],
          "| alerts outbox:", _alert_counts(state))
    d1 = _deliver(state, cfg["delivery"])
    print("deliver:", d1["status"], "created:",
          d1["deliveries_created"], "succeeded:", d1["succeeded"])
    files = sorted((root / "delivery" / "file-a").glob("*.json"))
    print("ficheros escritos:", len(files))
    assert m1["run_status"] == "SUCCEEDED" and d1["succeeded"] >= 1

    print("=== LEG 2: mismo run -> sin segundo envio ============")
    m2 = run_ops(cfg, state, AS_OF)
    d2 = _deliver(state, cfg["delivery"])
    n_files2 = len(list((root / "delivery" / "file-a").glob(
        "*.json")))
    print("run_status:", m2["run_status"], "| deliver:",
          d2["status"], "created:", d2["deliveries_created"],
          "attempted:", d2["attempted"],
          "skipped_delivered:", d2["skipped_delivered"],
          "| ficheros:", n_files2)
    assert d2["attempted"] == 0 and n_files2 == len(files)

    print("=== LEG 3: alerta cambiada -> nueva generacion =======")
    m3 = run_ops(cfg, state, "2026-10-05")  # days_until cambia
    d3 = _deliver(state, cfg["delivery"])
    gens = sorted({d["generation"] for d in _deliveries(state)})
    print("run_status:", m3["run_status"], "| deliver:",
          d3["status"], "created:", d3["deliveries_created"],
          "succeeded:", d3["succeeded"], "| generaciones:", gens)
    assert d3["succeeded"] >= 1

    print("=== LEG 4: fallo transitorio -> retry -> DELIVERED ===")
    flaky_calls = []

    def flaky(request, dcfg):
        flaky_calls.append(1)
        if len(flaky_calls) == 1:
            return AdapterResult(
                O_FAILED_RETRYABLE, error_code="HTTP_503")
        return AdapterResult(O_SUCCEEDED)

    cfg4 = {"enabled": True,
            "retry": {"max_attempts": 5, "base_delay_seconds": 0,
                      "backoff_factor": 1.0},
            "destinations": [{
                "destination_id": "flaky", "adapter": "flaky",
                "enabled": True, "categories": ["*"], "config": {}}]}
    d4a = _deliver(state, cfg4, adapters={"flaky": flaky})
    d4b = _deliver(state, cfg4, adapters={"flaky": flaky})
    fl = [d for d in _deliveries(state)
          if d["destination_id"] == "flaky"]
    retried = [d for d in fl if d["attempt_count"] > 1]
    print("pass1:", d4a["status"], "retryable:",
          d4a["failed_retryable"], "| pass2:", d4b["status"],
          "succeeded:", d4b["succeeded"], "| deliveries:",
          len(fl), "reintentadas:", len(retried),
          "| todas:", {d["status"] for d in fl})
    assert all(d["status"] == "DELIVERED" for d in fl)
    assert len(retried) == 1 and retried[0]["attempt_count"] == 2

    print("=== LEG 5: UNKNOWN_OUTCOME -> sin auto-retry ==========")
    cfg5 = {"enabled": True, "destinations": [{
        "destination_id": "uncertain", "adapter": "uncertain",
        "enabled": True, "categories": ["*"], "config": {}}]}
    adapters5 = {"uncertain": lambda r, c: AdapterResult(
        O_UNKNOWN, error_code="POST_SEND_TIMEOUT")}
    d5a = _deliver(state, cfg5, adapters=adapters5)
    d5b = _deliver(state, cfg5, adapters=adapters5)
    du = [d for d in _deliveries(state)
          if d["destination_id"] == "uncertain"]
    print("pass1:", d5a["status"], "unknown:", d5a["unknown"],
          "| pass2 attempted:", d5b["attempted"],
          "| estados:", {d["status"] for d in du})
    assert all(d["status"] == "UNKNOWN_OUTCOME" for d in du)
    assert d5b["attempted"] == 0

    print("=== LEG 6: dos destinos -> estados independientes ====")
    cfg6 = {"enabled": True, "destinations": [
        _file_dest("file-ok", root / "delivery" / "file-ok"),
        {"destination_id": "bad", "adapter": "bad",
         "enabled": True, "categories": ["*"], "config": {}}]}
    adapters6 = {
        "file": _file_adapter(),
        "bad": lambda r, c: AdapterResult(
            O_FAILED_PERMANENT, error_code="HTTP_410")}
    d6 = _deliver(state, cfg6, adapters=adapters6)
    ok = [d for d in _deliveries(state)
          if d["destination_id"] == "file-ok"]
    bad = [d for d in _deliveries(state)
           if d["destination_id"] == "bad"]
    with state.open() as conn:
        agg = {r["alert_key"]: r["delivery_state"] for r in
               conn.execute(
                   "SELECT alert_key, delivery_state FROM outbox"
                   ).fetchall()}
    print("deliver:", d6["status"],
          "| file-ok:", {d["status"] for d in ok},
          "| bad:", {d["status"] for d in bad})
    print("agregado outbox:", set(agg.values()))
    assert all(d["status"] == "DELIVERED" for d in ok)
    assert all(d["status"] == "FAILED_PERMANENT" for d in bad)
    assert set(agg.values()) == {"FAILED_DELIVERY"}

    print("=== audit trail (muestra) ===========================")
    with state.open() as conn:
        dk = bad[0]["delivery_key"]
        for t in list_transitions(conn, dk):
            print(" ", t["from_status"], "->", t["to_status"],
                  t["actor"], t["note"] or "")
        att = list_attempts(conn, dk)[-1]
        print("  attempt:", att["status"], att["error_code"],
              "retryable:", att["retryable"])
    print("=== P10 e2e demo OK ===")
    return 0


def _file_adapter():
    from ca_es.delivery.file_adapter import deliver
    return deliver


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1
                          else "p10-demo"))
