"""P9 — demo e2e de aceptacion (ad-hoc, no en CI).

Leg 1: refresh LIVE real (BME) -> canon acumulado -> DAG P7.
Leg 2: mismo run otra vez -> sin duplicados, UNCHANGED, skips.
Leg 3: observacion nueva/cambiada (fetcher inyectado con doc
       modificado) -> delta de canon -> invalidacion selectiva.

Uso: PYTHONPATH=src python scripts/p9_e2e_demo.py <state_dir>
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ca_es.ops_dag import run_ops  # noqa: E402
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

BME_API = ("https://apiweb.bolsasymercados.es/Market/v1/"
           "EQ/CorporateActions")
# Documento de la "observacion nueva": doc-id BMEG-Dividends no
# observado en legs 1-2 (los 167 docs reales no incluyen este dia).
# El resto de kinds devuelven []: ausencia != desaparicion, los
# docs chosen previos se conservan y el canon los mantiene.
CHANGED_ROW = {
    "isin": "ES0105561007",
    "issuerName": "PARLEM TELECOM COMPANYIA DE TELECOMUNICA",
    "dividendDate": "20261015",
    "disbursement": "0.42",
    "typeDescription": "A CUENTA",
    "currency": "EUR",
}
CHANGED_ROW_V2 = dict(CHANGED_ROW, disbursement="0.50")


@dataclass
class FakeResp:
    content: bytes
    status: int = 200
    media_type: str = "application/json"
    url: str = ""


def fake_fetcher(routes):
    def fetch(url, referer=None):
        value = routes.get(url)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise ConnectionError(f"NO_ROUTE:{url}")
        return FakeResp(content=value, url=url)
    return fetch


def _bme_routes(rows_by_kind):
    from ca_es.sources.live.bme import KINDS
    return {f"{BME_API}/{k}": json.dumps(
        rows_by_kind.get(k, [])).encode() for k in KINDS}


def _steps(m):
    return {s["step_id"]: s for s in m["steps"]}


def _artifact(state, step):
    sha = step.get("output_sha256")
    return state.get_artifact(sha) if sha else None


def main(state_dir: str) -> int:
    root = Path(state_dir)
    inputs = root / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    for name, doc in [("rules.json", RULES), ("cals.json", CALS),
                      ("pos.json", POSITIONS), ("movs.json", MOVS)]:
        (inputs / name).write_text(json.dumps(doc), encoding="utf-8")
    cfg = {
        "schema": "CA_ES_OPS_CONFIG_V1",
        "inputs": {
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
        },
        "action_queue": {"window_days": 30, "due_soon_days": 7},
        "sources": {
            "enabled": True,
            "adapters": {"bme_growth": {
                "adapter": "bme", "source_id": "BME_GROWTH",
                "surface_id": "CORPORATE_ACTIONS",
                "enabled": True, "required": False}}},
    }
    state = OpsState(root / "state").init()

    print("=== LEG 1: LIVE refresh (BME real) ==================")
    m1 = run_ops(cfg, state, AS_OF)  # sin fetchers -> urllib real
    s1 = _steps(m1)
    sr1 = _artifact(state, s1["source_refresh"])
    cr1 = _artifact(state, s1["canon_refresh"])
    print("run_status:", m1["run_status"])
    print("source_refresh:", sr1["status"], "docs:",
          sr1["summary"]["new_documents"], "new")
    print("canon_refresh:", cr1["refresh_status"],
          "events:", len(cr1.get("events_unchanged") or [])
          + len(cr1.get("events_added") or []),
          "canon_sha:", cr1["canon_artifact_sha256"][:16])
    health1 = _artifact(state, s1["health_report"])
    print("health:", health1["status"])

    print("=== LEG 2: identical run ==========================")
    m2 = run_ops(cfg, state, AS_OF)
    s2 = _steps(m2)
    sr2 = _artifact(state, s2["source_refresh"])
    cr2 = _artifact(state, s2["canon_refresh"])
    print("run_status:", m2["run_status"])
    print("source_refresh:", sr2["status"],
          "new_docs:", sr2["summary"]["new_documents"])
    print("canon_refresh:", cr2["refresh_status"],
          "same canon:", cr2["canon_artifact_sha256"]
          == cr1["canon_artifact_sha256"])
    skipped = [k for k, v in s2.items()
               if v["status"] == "SKIPPED_UNCHANGED"]
    print("skipped unchanged:", len(skipped), skipped[:6])
    with state.open() as conn:
        n_obs1 = conn.execute(
            "SELECT COUNT(*) c FROM source_observations"
        ).fetchone()["c"]
        n_docs = conn.execute(
            "SELECT COUNT(*) c FROM source_documents").fetchone()["c"]
        n_alerts = conn.execute(
            "SELECT COUNT(*) c FROM outbox").fetchone()["c"]

    print("=== LEG 3: changed/new observation =================")
    # fetcher inyectado: la enumeracion BME devuelve el doc real
    # del dia + un doc modificado respecto a la observacion previa
    routes = _bme_routes({"Dividends": [CHANGED_ROW_V2]})
    m3 = run_ops(cfg, state, AS_OF,
                 source_fetchers={"bme_growth": fake_fetcher(routes)})
    s3 = _steps(m3)
    sr3 = _artifact(state, s3["source_refresh"])
    cr3 = _artifact(state, s3["canon_refresh"])
    print("run_status:", m3["run_status"])
    print("source_refresh:", sr3["status"], "new:",
          sr3["summary"]["new_documents"], "changed:",
          sr3["summary"]["changed"])
    print("canon_refresh:", cr3["refresh_status"],
          "added:", len(cr3.get("events_added") or []),
          "changed:", len(cr3.get("events_changed") or []))
    reran = [k for k, v in s3.items()
             if v["status"] == "SUCCEEDED" and k in
             ("compute_deadlines", "build_action_queue",
              "morning_brief_v2", "entitlements")]
    print("downstream re-ejecutado:", reran)
    with state.open() as conn:
        n_obs2 = conn.execute(
            "SELECT COUNT(*) c FROM source_observations"
        ).fetchone()["c"]
        n_docs2 = conn.execute(
            "SELECT COUNT(*) c FROM source_documents").fetchone()["c"]
        n_alerts2 = conn.execute(
            "SELECT COUNT(*) c FROM outbox").fetchone()["c"]
        changed = conn.execute(
            "SELECT COUNT(*) c FROM source_observations"
            " WHERE change_status='CONTENT_CHANGED'").fetchone()["c"]
    print(f"observations: {n_obs1} -> {n_obs2} "
          f"(docs: {n_docs} -> {n_docs2}, "
          f"alerts: {n_alerts} -> {n_alerts2}, "
          f"content_changed_obs: {changed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1
                          else "p9-demo-state"))
