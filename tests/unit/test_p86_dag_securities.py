"""P8 integracion — step `securities_events` del DAG P7.

Siembra facts MT564/MT566 en inbox_messages (como los dejaria
process_inbox) y verifica: terms -> entitlement -> impact -> recon
-> cases, artefactos persistidos, y comportamiento sin inbox.
"""
import json
from pathlib import Path

import pytest

from ca_es.ops_dag import run_ops
from ca_es.ops_state import OpsState
from tests.unit.test_p81_split import (
    NOW,
    SHA,
    _fact,
    _facts_doc,
    _splf_facts,
)

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "g3" / "input" / "canon.json"
POLICY = ROOT / "docs" / "sources" / "source-policy.json"
AS_OF = "2026-09-16"

RULES = {"schema": "CA_ES_DEADLINE_RULES_V1", "rules": [{
    "rule_id": "R1", "deadline_type": "RESPONSE_DEADLINE",
    "source_field": "date.payment_date", "business_days_offset": -1,
    "calendar_id": "TARGET2"}]}
CALS = {"schema": "CA_ES_CALENDARS_V1", "calendars": [{
    "calendar_id": "TARGET2", "business_week": [0, 1, 2, 3, 4],
    "holidays": []}]}
POSITIONS = {"schema": "CA_ES_POSITIONS_V1", "as_of": "2026-06-09",
             "positions": [{"account_id": "A001",
                            "isin": "ES0105857009",
                            "quantity": "12500",
                            "as_of": "2026-06-09"}]}


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
        },
        "action_queue": {"window_days": 30, "due_soon_days": 7},
    }
    state = OpsState(tmp_path / "state").init()
    return {"cfg": cfg, "state": state, "inputs": inputs}


def _seed_inbox(state: OpsState, facts_doc: dict) -> None:
    """Registra un mensaje PROCESSED con su facts artifact, igual que
    lo dejaria process_inbox."""
    with state.open() as conn:
        ref = state.store_artifact(
            conn, facts_doc, "CA_ES_SWIFT_MT_FACTS_V1", "V1")
        conn.execute(
            "INSERT OR REPLACE INTO inbox_messages"
            "(input_sha256, semantic_fingerprint, standard_family,"
            " message_identifier, received_at, source_path,"
            " processing_status, duplicate_status,"
            " artifact_refs_json)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (facts_doc["input_sha256"], "fp-test",
             "ISO_15022_MT",
             facts_doc.get("message_identifier"),
             NOW, "test.fin", "PROCESSED", "UNIQUE",
             json.dumps([ref])))
        conn.commit()


def _steps(manifest):
    return {s["step_id"]: s for s in manifest["steps"]}


def test_dag_has_securities_step(env):
    m = run_ops(env["cfg"], env["state"], AS_OF)
    assert "securities_events" in _steps(m)
    # sin inbox -> output None pero step OK (opcional)
    assert _steps(m)["securities_events"]["status"] == "SUCCEEDED"


def test_securities_step_processes_splf(env):
    facts = _splf_facts()
    _seed_inbox(env["state"], facts)
    m = run_ops(env["cfg"], env["state"], AS_OF)
    step = _steps(m)["securities_events"]
    assert step["status"] == "SUCCEEDED"
    index = env["state"].get_artifact(step["output_sha256"])
    assert index["kind"] == "CA_ES_SECURITIES_EVENT_V1"
    key = f"unbound:{SHA}"
    assert key in index["items"]
    entry = index["items"][key]

    state = env["state"]
    terms = state.get_artifact(entry["terms"]["sha256"])
    assert terms["schema"] == "CA_ES_EVENT_TERMS_V1"
    assert terms["terms_status"] == "PROVEN"
    assert terms["event_basis"] == "SWIFT_NOTIFICATION"

    ent = state.get_artifact(entry["entitlement"]["sha256"])
    e = ent["entitlements"][0]
    assert e["status"] == "ENTITLED"
    assert e["receivable"]["quantity"] == "125000"

    impact = state.get_artifact(entry["impact"]["sha256"])
    types = {i["impact_type"] for i in impact["impacts"]}
    assert types == {"SECURITY_DELIVERY", "SECURITY_RECEIPT"}

    recon = state.get_artifact(entry["recon"]["sha256"])
    # sin MT566 actual -> expected set completo, movimientos MISSING
    assert recon["expected_set_authoritative"] is True
    assert recon["summary"]["missing_security_movement"] == 2

    cases = state.get_artifact(entry["cases"]["sha256"])
    assert len(cases["cases"]) == 2
    assert {c["factual_status"] for c in cases["cases"]} == \
        {"MISSING_SECURITY_MOVEMENT"}


def _mt566_facts():
    """MT566 sintetico: DEBT viejo + CRED nuevo (sin canon SPLIT ->
    candidate NO_MATCH, no PROJECTABLE como actual)."""
    return _facts_doc(
        _fact("GENL", "20C", "SEME", "reference", "REFSEME005"),
        _fact("GENL", "22F", "CAEV", "indicator", "SPLF"),
        _fact("GENL", "22F", "CAMV", "indicator", "MAND"),
        _fact("USECU", "97A", "SAFE", "account number", "A001"),
        _fact("USECU", "35B", "ISIN", "isin", "ES0105857009"),
        _fact("CACONF/SECMOVE", "22H", "CRDB", "indicator", "DEBT"),
        _fact("CACONF/SECMOVE", "35B", "ISIN", "isin",
              "ES0105857009", occ=0),
        _fact("CACONF/SECMOVE", "36B", "PSTA", "quantity",
              "12500,"),
        _fact("CACONF/SECMOVE", "36B", "PSTA",
              "quantity type code", "UNIT"),
        _fact("CACONF/SECMOVE", "98A", "POST", "date", "20260609"),
        _fact("CACONF/SECMOVE", "22H", "CRDB", "indicator", "CRED",
              occ=1),
        _fact("CACONF/SECMOVE", "35B", "ISIN", "isin",
              "ES0105857033", occ=1),
        _fact("CACONF/SECMOVE", "36B", "PSTA", "quantity",
              "125000,", occ=1),
        _fact("CACONF/SECMOVE", "36B", "PSTA",
              "quantity type code", "UNIT", occ=1),
        _fact("CACONF/SECMOVE", "98A", "POST", "date", "20260609",
              occ=1),
        mid="MT566")


def _mt566_seed_doc() -> dict:
    doc = _mt566_facts()
    doc["input_sha256"] = "cd" * 32
    for f in doc["facts"]:
        f["input_sha256"] = "cd" * 32
    return doc


def test_securities_step_mt566_candidate_not_bound(env):
    """MT564 SPLF + MT566 sin canon SPLIT: el candidate se persiste
    pero binding NO_MATCH -> no entra como actual -> recon MISSING
    sigue fail-closed."""
    facts = _splf_facts()
    m566 = _mt566_seed_doc()
    # locators con indice creciente para el windowing SECMOVE
    for i, f in enumerate(m566["facts"]):
        f["evidence_locator"] = f"block4.tag[{i}]"
    _seed_inbox(env["state"], facts)
    _seed_inbox(env["state"], m566)
    m = run_ops(env["cfg"], env["state"], AS_OF)
    index = env["state"].get_artifact(
        _steps(m)["securities_events"]["output_sha256"])
    assert "_candidates" in index["items"]
    cand_ref = index["items"]["_candidates"]["cd" * 32]
    cand = env["state"].get_artifact(cand_ref["sha256"])
    assert cand["binding_status"] == "NO_MATCH"
    key = f"unbound:{SHA}"
    recon = env["state"].get_artifact(
        index["items"][key]["recon"]["sha256"])
    assert recon["summary"]["missing_security_movement"] == 2


def _outbox_rows(state: OpsState) -> list[dict]:
    with state.open() as conn:
        rows = conn.execute(
            "SELECT alert_key, category, subject_key, state"
            " FROM outbox").fetchall()
    cols = ("alert_key", "category", "subject_key", "state")
    return [dict(zip(cols, r)) for r in rows]


def test_security_cases_raise_alerts(env):
    """Casos P3.5 de valores -> alertas EXCEPTION_CASE en outbox."""
    _seed_inbox(env["state"], _splf_facts())
    run_ops(env["cfg"], env["state"], AS_OF)
    rows = _outbox_rows(env["state"])
    sec = [r for r in rows if r["category"] == "EXCEPTION_CASE"]
    assert len(sec) == 2  # DELIVERY + RECEIPT missing


def test_security_cases_merge_across_runs(env):
    """Segundo run: los casos se mergean por case_key (no duplican,
    conservan first_seen_at del primer run)."""
    _seed_inbox(env["state"], _splf_facts())
    run_ops(env["cfg"], env["state"], AS_OF)
    m2 = run_ops(env["cfg"], env["state"], AS_OF)
    index = env["state"].get_artifact(
        _steps(m2)["securities_events"]["output_sha256"])
    key = f"unbound:{SHA}"
    cases = env["state"].get_artifact(
        index["items"][key]["cases"]["sha256"])
    assert len(cases["cases"]) == 2
    keys = [c["case_key"] for c in cases["cases"]]
    assert len(set(keys)) == 2
    # alertas no duplicadas tras dos runs
    rows = _outbox_rows(env["state"])
    sec = [r for r in rows if r["category"] == "EXCEPTION_CASE"]
    assert len(sec) == 2
