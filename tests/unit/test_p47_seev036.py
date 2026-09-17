"""P4.7 — seev.036 -> cash/security candidates (docs/p4/p47)."""
from __future__ import annotations

from pathlib import Path

import pytest

from ca_es.mx_facts import FACTS_SCHEMA, parse_mx
from ca_es.mx_movement import (
    CASH_CANDIDATE_SCHEMA,
    SEC_CANDIDATE_SCHEMA,
    mx_cash_candidate,
    mx_security_movement_candidate,
)
from ca_es.swift_mt import default_adapter_jar

REPO = Path(__file__).resolve().parents[2]
RES = (REPO / "adapters" / "iso-adapter-jvm" / "src" / "test"
       / "resources")
FIXTURE_SEC = RES / "seev036-002.xml"
FIXTURE_CASH = RES / "seev036-cash.xml"
MID = "seev.036.002.16"
SHA = "7" * 64
NOW = "2026-09-18T00:00:00Z"
DOC = "/Document/CorpActnMvmntConf"
CONF = f"{DOC}/CorpActnConfDtls"
OLD_ISIN = "ES0105857009"
NEW_ISIN = "ES0105857033"
EID = "evt-split-1"


def _fact(path, value, sec=None, csh=None):
    loc = path
    if sec is not None:
        loc = loc.replace("/SctiesMvmntDtls/",
                          f"/SctiesMvmntDtls[{sec}]/")
    if csh is not None:
        loc = loc.replace("/CshMvmntDtls/", f"/CshMvmntDtls[{csh}]/")
    return {
        "message_identifier": MID,
        "model_path": path,
        "value": value,
        "occurrence": 0,
        "evidence_locator": f"element:{loc}",
        "input_sha256": SHA,
    }


def _facts_doc(*facts, mid=MID, parse_status="PARSE_OK"):
    return {
        "schema_version": FACTS_SCHEMA,
        "generated_at": NOW,
        "message_identifier": mid,
        "input_sha256": SHA,
        "parse_status": parse_status,
        "facts": list(facts),
    }


def _gnl(evt="RDG-SPLIT-2026", caev="SPLF", isin=OLD_ISIN,
         acct="A001"):
    return [
        _fact(f"{DOC}/CorpActnGnlInf/CorpActnEvtId", evt),
        _fact(f"{DOC}/CorpActnGnlInf/EvtTp/Cd", caev),
        _fact(f"{DOC}/CorpActnGnlInf/FinInstrmId/ISIN", isin),
        _fact(f"{DOC}/AcctDtls/SfkpgAcct", acct),
    ]


def _sec_move(idx, dbt, isin, qty="12500",
              qty_leaf="PstngQty/Qty/Unit", dt="2026-06-09"):
    facts = [
        _fact(f"{CONF}/SctiesMvmntDtls/FinInstrmId/ISIN", isin, sec=idx),
        _fact(f"{CONF}/SctiesMvmntDtls/CdtDbtInd", dbt, sec=idx),
    ]
    if qty_leaf:
        facts.append(_fact(
            f"{CONF}/SctiesMvmntDtls/{qty_leaf}", qty, sec=idx))
    if dt:
        facts.append(_fact(
            f"{CONF}/SctiesMvmntDtls/DtDtls/PstngDt/Dt", dt, sec=idx))
    return facts


def _csh_move(idx, amt_elem="PstngAmt", amt="125.00", ccy="EUR",
              dbt="CRDT", dt_leaf="DtDtls/PstngDt/Dt", dt="2026-07-20"):
    facts = [
        _fact(f"{CONF}/CshMvmntDtls/CdtDbtInd", dbt, csh=idx),
        _fact(f"{CONF}/CshMvmntDtls/AmtDtls/{amt_elem}", amt, csh=idx),
        _fact(f"{CONF}/CshMvmntDtls/AmtDtls/{amt_elem}/@Ccy", ccy,
              csh=idx),
        _fact(f"{CONF}/CshMvmntDtls/{dt_leaf}", dt, csh=idx),
    ]
    return facts


def _canon(event_type="SPLIT", isin=OLD_ISIN, eid=EID):
    return {
        "canon_version": "CA_ES_OPERATIONAL_CANON_V1",
        "logical_sha256": SHA,
        "events": [
            {
                "canonical_event_id": eid,
                "event_type": event_type,
                "affected_instrument": {"isin": isin},
                "facts": [
                    {"field_path": "instrument.isin", "value": isin,
                     "revision_id": "r1", "assertion_id": "a1"},
                ],
                "conflicts": [],
            }
        ],
    }


# --- security ---------------------------------------------------------

def test_sec_two_movements():
    doc = mx_security_movement_candidate(
        _facts_doc(*_gnl(),
                   *_sec_move(0, "DBIT", OLD_ISIN),
                   *_sec_move(1, "CRDT", NEW_ISIN, "125000")),
        _canon(), now=NOW)
    assert doc["schema"] == SEC_CANDIDATE_SCHEMA
    assert doc["status"] == "PROJECTABLE"
    assert doc["binding_status"] == "BOUND"
    assert doc["canonical_event_id"] == EID
    m0, m1 = doc["movements"]
    assert m0["direction"] == "DELIVERY"
    assert m0["isin"] == OLD_ISIN
    assert m0["quantity"] == "12500"
    assert m0["quantity_type"] == "UNIT"
    assert m0["posting_date"] == "2026-06-09"
    assert m0["account_id"] == "A001"
    assert m1["direction"] == "RECEIPT"
    assert m1["isin"] == NEW_ISIN
    assert m1["quantity"] == "125000"


def test_sec_direction_never_inferred():
    doc = mx_security_movement_candidate(
        _facts_doc(*_gnl(),
                   *_sec_move(0, "XXXX", OLD_ISIN)),
        _canon(), now=NOW)
    m = doc["movements"][0]
    assert m["status"] == "UNSUPPORTED"
    assert "UNSUPPORTED_DIRECTION_CODE" in m["reasons"]


def test_sec_missing_direction():
    facts = [f for f in _sec_move(0, "CRDT", OLD_ISIN)
             if not f["model_path"].endswith("/CdtDbtInd")]
    doc = mx_security_movement_candidate(
        _facts_doc(*_gnl(), *facts), _canon(), now=NOW)
    assert "MISSING_DIRECTION" in doc["movements"][0]["reasons"]


def test_sec_unsupported_qty_type():
    doc = mx_security_movement_candidate(
        _facts_doc(*_gnl(),
                   *_sec_move(0, "CRDT", OLD_ISIN,
                              qty_leaf="PstngQty/Qty/FceAmt")),
        _canon(), now=NOW)
    m = doc["movements"][0]
    assert m["status"] == "UNSUPPORTED"
    assert "UNSUPPORTED_QUANTITY_TYPE" in m["reasons"]


def test_sec_not_bound():
    doc = mx_security_movement_candidate(
        _facts_doc(*_gnl(isin="ES0000000000"),
                   *_sec_move(0, "CRDT", OLD_ISIN)),
        _canon(), now=NOW)
    assert doc["binding_status"] != "BOUND"
    assert "EVENT_NOT_BOUND" in doc["movements"][0]["reasons"]


def test_sec_wrong_message():
    doc = mx_security_movement_candidate(
        _facts_doc(*_gnl(), mid="seev.034.002.15"), _canon(), now=NOW)
    assert doc["status"] == "UNSUPPORTED"
    assert "UNSUPPORTED_MESSAGE_TYPE" in doc["reasons"]


# --- cash --------------------------------------------------------------

def test_cash_basis_priority():
    """PstngAmt > NetAmt > GrssAmt, espejo de POSTING_PRIORITY P4.2."""
    for elem, basis in [("PstngAmt", "UNKNOWN"), ("NetAmt", "NET"),
                        ("GrssAmt", "GROSS")]:
        doc = mx_cash_candidate(
            _facts_doc(*_gnl(evt="BME-DVCA-0001", caev="DVCA",
                             isin="ES0113900J37"),
                       *_csh_move(0, amt_elem=elem)),
            _canon(event_type="CASH_DIVIDEND", isin="ES0113900J37",
                   eid="evt-dv-1"),
            now=NOW)
        assert doc["schema"] == CASH_CANDIDATE_SCHEMA
        assert doc["status"] == "PROJECTABLE", doc["reasons"]
        mv = doc["movement"]
        assert mv["amount_basis"] == basis
        assert mv["amount"] == "125.00"
        assert mv["currency"] == "EUR"
        assert mv["direction"] == "CRDT"
        assert mv["event_id"] == "evt-dv-1"


def test_cash_multiple_movements():
    doc = mx_cash_candidate(
        _facts_doc(*_gnl(evt="BME-DVCA-0001", caev="DVCA",
                         isin="ES0113900J37"),
                   *_csh_move(0), *_csh_move(1, amt="200.00")),
        _canon(event_type="CASH_DIVIDEND", isin="ES0113900J37",
               eid="evt-dv-1"),
        now=NOW)
    assert doc["status"] == "INDETERMINATE"
    assert "MULTIPLE_CASH_MOVEMENTS" in doc["reasons"]
    assert doc["movement"] is None


def test_cash_missing_amount():
    doc = mx_cash_candidate(
        _facts_doc(*_gnl(evt="BME-DVCA-0001", caev="DVCA",
                         isin="ES0113900J37"),
                   _fact(f"{CONF}/CshMvmntDtls/CdtDbtInd", "CRDT",
                         csh=0)),
        _canon(event_type="CASH_DIVIDEND", isin="ES0113900J37",
               eid="evt-dv-1"),
        now=NOW)
    assert doc["status"] == "INDETERMINATE"
    assert "MISSING_AMOUNT" in doc["reasons"]


def test_cash_unknown_basis_projectable():
    doc = mx_cash_candidate(
        _facts_doc(*_gnl(evt="BME-DVCA-0001", caev="DVCA",
                         isin="ES0113900J37"),
                   *_csh_move(0)),
        _canon(event_type="CASH_DIVIDEND", isin="ES0113900J37",
               eid="evt-dv-1"),
        now=NOW)
    assert doc["amount_basis"] == "UNKNOWN"
    assert doc["basis_reason"] == "UNKNOWN_AMOUNT_BASIS"
    assert doc["movement"]["amount_basis"] == "UNKNOWN"


# --- e2e real adapter ----------------------------------------------------

def test_e2e_seev036_security():
    jar = default_adapter_jar()
    if not jar.is_file():
        pytest.skip("adapter jar no construido")
    facts_doc, rc = parse_mx(FIXTURE_SEC.read_bytes())
    assert rc == 0
    assert facts_doc["message_identifier"] == MID
    doc = mx_security_movement_candidate(facts_doc, _canon(), now=NOW)
    assert doc["status"] == "PROJECTABLE"
    assert len(doc["movements"]) == 2
    assert doc["movements"][0]["direction"] == "DELIVERY"
    assert doc["movements"][1]["direction"] == "RECEIPT"


def test_e2e_seev036_cash():
    jar = default_adapter_jar()
    if not jar.is_file():
        pytest.skip("adapter jar no construido")
    facts_doc, rc = parse_mx(FIXTURE_CASH.read_bytes())
    assert rc == 0
    doc = mx_cash_candidate(
        facts_doc,
        _canon(event_type="CASH_DIVIDEND", isin="ES0113900J37",
               eid="evt-dv-1"),
        now=NOW)
    assert doc["status"] == "PROJECTABLE", doc["reasons"]
    assert doc["movement"]["amount_basis"] == "GROSS"
    assert doc["movement"]["amount"] == "125.00"


def test_e2e_mt566_vs_seev036_parity():
    """Mismo escenario split en MT566 y seev.036 -> mismos outcomes."""
    jar = default_adapter_jar()
    if not jar.is_file():
        pytest.skip("adapter jar no construido")
    from ca_es.swift_mt import parse_mt
    from ca_es.swift_securities import security_movement_candidate

    fin = (RES / "mt566-secmove.fin").read_text(encoding="utf-8")
    mt_doc, rc = parse_mt(fin)
    assert rc == 0
    mt_cand = security_movement_candidate(mt_doc, _canon(), now=NOW)
    mx_doc, _ = parse_mx(FIXTURE_SEC.read_bytes())
    mx_cand = mx_security_movement_candidate(mx_doc, _canon(), now=NOW)

    assert mt_cand["status"] == mx_cand["status"] == "PROJECTABLE"
    assert len(mt_cand["movements"]) == len(mx_cand["movements"]) == 2
    for mt_m, mx_m in zip(mt_cand["movements"], mx_cand["movements"]):
        assert mt_m["direction"] == mx_m["direction"]
        assert mt_m["isin"] == mx_m["isin"]
        assert mt_m["quantity"] == mx_m["quantity"]
        assert mt_m["quantity_type"] == mx_m["quantity_type"]
        assert mt_m["posting_date"] == mx_m["posting_date"]
        assert mt_m["account_id"] == mx_m["account_id"]
