"""P17 integracion — step `settlement_feed` del DAG P7.

Siembra facts MT54x/sese en inbox_messages (como los dejaria
process_inbox) y verifica: observations -> ledger -> status ->
recon -> export V1 -> cases, merge entre runs, y comportamiento
sin inbox (indice minimo estable).
"""
import json
from pathlib import Path

import pytest

from ca_es.ops_dag import run_ops
from ca_es.ops_state import OpsState
from tests.unit.test_p81_split import NOW, _fact, _facts_doc

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


def _seed_inbox(state: OpsState, facts_doc: dict,
                family="ISO_15022_MT") -> None:
    """Registra un mensaje PROCESSED con su facts artifact."""
    with state.open() as conn:
        ref = state.store_artifact(
            conn, facts_doc,
            ("CA_ES_SWIFT_MX_FACTS_V1"
             if family == "ISO_20022_MX"
             else "CA_ES_SWIFT_MT_FACTS_V1"), "V1")
        conn.execute(
            "INSERT OR REPLACE INTO inbox_messages"
            "(input_sha256, semantic_fingerprint, standard_family,"
            " message_identifier, received_at, source_path,"
            " processing_status, duplicate_status,"
            " artifact_refs_json)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (facts_doc["input_sha256"], "fp-test",
             family,
             facts_doc.get("message_identifier"),
             NOW, "test.msg", "PROCESSED", "UNIQUE",
             json.dumps([ref])))
        conn.commit()


def _steps(manifest):
    return {s["step_id"]: s for s in manifest["steps"]}


def _mt541(sha="41" * 32):
    return _facts_doc(
        _fact("GENL", "20C", "SEME", "reference", "SI-001",
              mid="MT541"),
        _fact("GENL", "23G", None, "function", "NEWM",
              mid="MT541"),
        _fact("TRADDET", "98A", "TRAD", "date", "20240110",
              mid="MT541"),
        _fact("TRADDET", "98A", "SETT", "date", "20240112",
              mid="MT541"),
        _fact("TRADDET", "35B", None, "isin", "ES0105857009",
              mid="MT541"),
        _fact("FIAC", "97A", "SAFE", "account", "ACC-1",
              mid="MT541"),
        _fact("FIAC", "36B", "SETT", "quantity type code",
              "UNIT", mid="MT541"),
        _fact("FIAC", "36B", "SETT", "quantity", "1000,",
              occ=1, mid="MT541"),
        _fact("SETDET", "22H", "REDE", "indicator", "RECE",
              mid="MT541"),
        _fact("SETDET", "22H", "PAYM", "indicator", "FREE",
              mid="MT541"),
        mid="MT541") | {"input_sha256": sha}


def _mt545(sha="45" * 32):
    return _facts_doc(
        _fact("GENL", "20C", "SEME", "reference", "CF-001",
              mid="MT545"),
        _fact("GENL", "20C", "RELA", "reference", "SI-001",
              mid="MT545"),
        _fact("TRADDET", "98A", "SETT", "date", "20240112",
              mid="MT545"),
        _fact("FIAC", "36B", "ESTT", "quantity type code",
              "UNIT", mid="MT545"),
        _fact("FIAC", "36B", "ESTT", "quantity", "1000,",
              occ=1, mid="MT545"),
        mid="MT545") | {"input_sha256": sha}


def _sese023(sha="23" * 32):
    def mx(path, value):
        return {"model_path": path, "value": value,
                "occurrence": 0, "evidence_locator": "t",
                "input_sha256": sha}
    return {
        "schema_version": "CA_ES_SWIFT_MX_FACTS_V1",
        "generated_at": NOW,
        "message_identifier": "sese.023.001.11",
        "input_sha256": sha,
        "parse_status": "OK",
        "facts": [
            mx("/Document/SctiesSttlmTxInstr/TxId", "SESE-1"),
            mx("/Document/SctiesSttlmTxInstr/SctiesMvmntTp",
               "RECE"),
            mx("/Document/SctiesSttlmTxInstr/QtyAndAcctDtls/"
               "SttlmQty/Qty/Unit", "500"),
            mx("/Document/SctiesSttlmTxInstr/QtyAndAcctDtls/"
               "SfkpgAcct/Id", "ACC-1"),
            mx("/Document/SctiesSttlmTxInstr/FinInstrmId/ISIN",
               "ES0105857009"),
            mx("/Document/SctiesSttlmTxInstr/TradDtls/SttlmDt/"
               "Dt/Dt", "2024-01-12"),
        ],
    }


def _feed_index(state, manifest):
    step = _steps(manifest)["settlement_feed"]
    assert step["status"] == "SUCCEEDED"
    return state.get_artifact(step["output_sha256"])


def test_dag_has_settlement_step(env):
    m = run_ops(env["cfg"], env["state"], AS_OF)
    assert "settlement_feed" in _steps(m)
    index = _feed_index(env["state"], m)
    # sin inbox -> indice minimo estable
    assert index["items"] == {}


def test_settlement_feed_mt_flow(env):
    _seed_inbox(env["state"], _mt541())
    _seed_inbox(env["state"], _mt545())
    m = run_ops(env["cfg"], env["state"], AS_OF)
    index = _feed_index(env["state"], m)
    entry = index["items"]["feed"]

    ledger = env["state"].get_artifact(entry["ledger"]["sha256"])
    assert ledger["schema"] == "CA_ES_SETTLEMENT_TRANSACTION_V1"
    txs = ledger["transactions"]
    assert len(txs) == 1
    tx = txs[0]
    assert tx["status"] == "SETTLED"
    assert tx["instructed_quantity"] == "1000"
    assert tx["settled_quantity"] == "1000"
    assert tx["has_instruction"] and tx["has_confirmation"]

    exported = env["state"].get_artifact(
        entry["transactions"]["sha256"])
    assert exported["schema"] == \
        "CA_ES_SECURITIES_TRANSACTIONS_V1"
    et = exported["transactions"][0]
    assert et["direction"] == "BUY"
    assert et["settlement_status"] == "SETTLED"

    recon = env["state"].get_artifact(entry["recon"]["sha256"])
    assert recon["items"][0]["status"] == "MATCH"

    cases = env["state"].get_artifact(entry["cases"]["sha256"])
    assert cases["schema"] == "CA_ES_EXCEPTION_CASES_V1"


def test_settlement_feed_mx_and_orphan(env):
    _seed_inbox(env["state"], _sese023(), family="ISO_20022_MX")
    # MT541 sin referencias -> huerfano INSUFFICIENT_IDENTITY
    orphan = _facts_doc(
        _fact("GENL", "23G", None, "function", "NEWM",
              mid="MT541"),
        mid="MT541") | {"input_sha256": "aa" * 32}
    _seed_inbox(env["state"], orphan)
    m = run_ops(env["cfg"], env["state"], AS_OF)
    index = _feed_index(env["state"], m)
    ledger = env["state"].get_artifact(
        index["items"]["feed"]["ledger"]["sha256"])
    assert len(ledger["transactions"]) == 1
    assert ledger["transactions"][0]["status"] == "INSTRUCTED"
    assert len(ledger["orphan_observations"]) == 1

    recon = env["state"].get_artifact(
        index["items"]["feed"]["recon"]["sha256"])
    statuses = {i["status"] for i in recon["items"]}
    assert "INSUFFICIENT_IDENTITY" in statuses


def test_settlement_feed_second_run_merges_ledger(env):
    _seed_inbox(env["state"], _mt541())
    m1 = run_ops(env["cfg"], env["state"], AS_OF)
    l1 = env["state"].get_artifact(
        _feed_index(env["state"], m1)["items"]["feed"]
        ["ledger"]["sha256"])
    tx1 = l1["transactions"][0]
    assert tx1["status"] == "INSTRUCTED"

    _seed_inbox(env["state"], _mt545())
    m2 = run_ops(env["cfg"], env["state"], AS_OF)
    l2 = env["state"].get_artifact(
        _feed_index(env["state"], m2)["items"]["feed"]
        ["ledger"]["sha256"])
    tx2 = l2["transactions"][0]
    # S15: el merge conserva el ciclo del ledger previo
    assert tx2["transaction_id"] == tx1["transaction_id"]
    assert tx2["status"] == "SETTLED"
    assert tx2["has_instruction"] and tx2["has_confirmation"]
