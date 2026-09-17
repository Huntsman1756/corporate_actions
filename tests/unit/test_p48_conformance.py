"""P4.8 — conformance matrix MT <-> ISO 20022 (docs/p4/seev-conformance.md).

Cada escenario compara outcomes de dominio, nunca bytes ni metadatos
de transporte. Donde los estandares llevan informacion distinta, el
test fija la diferencia legitima explicitamente.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ca_es.instruction_status import bind_instruction_status
from ca_es.mx_facts import parse_mx
from ca_es.mx_movement import (
    mx_cash_candidate,
    mx_security_movement_candidate,
)
from ca_es.mx_status import bind_mx_instruction_status
from ca_es.swift_cash import cash_candidate
from ca_es.swift_mt import default_adapter_jar, parse_mt
from ca_es.swift_securities import security_movement_candidate

REPO = Path(__file__).resolve().parents[2]
RES = (REPO / "adapters" / "iso-adapter-jvm" / "src" / "test"
       / "resources")
NOW = "2026-09-18T00:00:00Z"
SHA = "8" * 64
MID = "seev.036.002.16"
DOC = "/Document/CorpActnMvmntConf"
CONF = f"{DOC}/CorpActnConfDtls"
JAR = default_adapter_jar()


def _jar_or_skip():
    if not JAR.is_file():
        pytest.skip("adapter jar no construido")


# --- MT facts builder -----------------------------------------------------

def _mtf(seq, tag, qual, value, occ=0, idx=0, label="value"):
    return {
        "message_identifier": "MT566",
        "field_path": (
            f"MT566.{seq.replace('/', '.')}.{tag}:{qual}"
            if qual else f"MT566.{seq.replace('/', '.')}.{tag}"
        ) + f"[{occ}].{label}",
        "value": value,
        "source_tag": tag,
        "source_qualifier": qual,
        "sequence": seq,
        "occurrence": occ,
        "evidence_locator": f"block4.tag[{idx}]",
        "input_sha256": SHA,
    }


def _mt_doc(facts, mt="MT566"):
    return {
        "schema_version": "CA_ES_SWIFT_MT_FACTS_V1",
        "generated_at": NOW,
        "message_identifier": mt,
        "input_sha256": SHA,
        "parse_status": "OK",
        "facts": list(facts),
    }


# --- MX facts builder -----------------------------------------------------

def _mxf(path, value, sec=None, csh=None, sts=None, mid=MID):
    loc = path
    for anchor, idx in (("SctiesMvmntDtls", sec), ("CshMvmntDtls", csh),
                        ("InstrPrcgSts", sts)):
        if idx is not None:
            loc = loc.replace(f"/{anchor}/", f"/{anchor}[{idx}]/")
    return {
        "message_identifier": mid,
        "model_path": path,
        "value": value,
        "occurrence": 0,
        "evidence_locator": f"element:{loc}",
        "input_sha256": SHA,
    }


def _mx_doc(facts, mid=MID):
    return {
        "schema_version": "CA_ES_SWIFT_MX_FACTS_V1",
        "generated_at": NOW,
        "message_identifier": mid,
        "input_sha256": SHA,
        "parse_status": "PARSE_OK",
        "facts": list(facts),
    }


def _canon(event_type="CASH_DIVIDEND", isin="ES0113900J37",
           eid="evt-1"):
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


def _instruction(iid="INS-0001"):
    return {
        "schema": "CA_ES_ELECTION_INSTRUCTION_V1",
        "instruction_id": iid,
        "canonical_event_id": "evt-1",
        "source_canon_logical_sha256": "a" * 64,
        "source_positions_logical_sha256": "b" * 64,
        "source_message_input_sha256": "c" * 64,
        "status": "READY",
        "fields": {},
    }


def _mt567(status="PACK", prev="INS-0001", extra_prev=None):
    facts = [
        _mtf("GENL", "20C", "SEME", "STAT-0001", idx=1,
             label="reference"),
        _mtf("GENL", "23G", None, "INST", idx=2, label="function"),
        _mtf("GENL", "20C", "CORP", "CORP-REF-42", idx=3,
             label="reference"),
        _mtf("GENL/LINK", "13A", "LINK", "565", idx=4,
             label="number id"),
        _mtf("GENL/LINK", "20C", "PREV", prev, idx=5,
             label="reference"),
        _mtf("GENL/STAT", "25D", "IPRC", status, idx=8,
             label="status code"),
    ]
    if extra_prev:
        facts.append(_mtf("GENL/LINK", "20C", "PREV", extra_prev, idx=6,
                          label="reference"))
    return _mt_doc(facts, mt="MT567")


def _mx034(choice="AccptdForFrthrPrcg", instr_id="INS-0001",
           extra_id=None):
    sts = "/Document/CorpActnInstrStsAdvc"
    facts = [
        _mxf(f"{sts}/InstrId/Id", instr_id, mid="seev.034.002.15"),
        _mxf(f"{sts}/CorpActnGnlInf/CorpActnEvtId", "CORP-REF-42",
             mid="seev.034.002.15"),
        _mxf(f"{sts}/InstrPrcgSts/{choice}/NoSpcfdRsn", "NORE",
             sts=0, mid="seev.034.002.15"),
    ]
    if extra_id:
        facts.append(_mxf(f"{sts}/InstrId/Id", extra_id,
                          mid="seev.034.002.15"))
    return _mx_doc(facts, mid="seev.034.002.15")


# --- escenario 1: cash dividend notification (e2e real) -------------------

def test_s1_notification_parity_e2e():
    _jar_or_skip()
    from ca_es.mx_ca import project_mx_message
    from ca_es.swift_ca import project_ca_message

    mt_doc, _ = parse_mt(
        (RES / "mt564-valid.fin").read_text(encoding="utf-8"))
    mx_doc, _ = parse_mx((RES / "seev031-parity.xml").read_bytes())
    mt_msg = project_ca_message(mt_doc, now=NOW)
    mx_msg = project_mx_message(mx_doc, now=NOW)
    assert mt_msg["event_type"] == mx_msg["event_type"]
    for k in ("isin", "ex_date", "record_date", "payment_date",
              "gross_per_share", "currency",
              "corporate_action_reference"):
        assert mt_msg["fields"][k]["value"] == mx_msg["fields"][k]["value"], k
    # diferencia legitima: message_function no existe en seev.031 como
    # 23G; NtfctnTp es transporte-specifico -> no se exige igualdad


# --- escenario 4/5: instruction status ------------------------------------

def test_s4_instruction_accepted():
    mt = bind_instruction_status(_mt567("PACK"), _instruction(), now=NOW)
    mx = bind_mx_instruction_status(
        _mx034("AccptdForFrthrPrcg"), _instruction(), now=NOW)
    assert mt["instruction_binding_status"] == mx[
        "instruction_binding_status"] == "BOUND"
    assert mt["statuses"][0]["normalized_status"] == mx[
        "statuses"][0]["normalized_status"] == "ACCEPTED"


def test_s5_instruction_rejected():
    mt = bind_instruction_status(_mt567("REJT"), _instruction(), now=NOW)
    mx = bind_mx_instruction_status(
        _mx034("Rjctd"), _instruction(), now=NOW)
    assert mt["statuses"][0]["normalized_status"] == mx[
        "statuses"][0]["normalized_status"] == "REJECTED"


# --- escenarios 6/7: cash movement ------------------------------------------

def _mt566_cash(qual, amount="125,"):
    facts = [
        _mtf("GENL", "20C", "CORP", "BME-DVCA-0001", idx=1,
             label="reference"),
        _mtf("GENL", "23G", None, "NEWM", idx=2, label="function"),
        _mtf("GENL", "22F", "CAEV", "DVCA", idx=3, label="indicator"),
        _mtf("USECU", "97A", "SAFE", "A001", idx=4,
             label="account number"),
        _mtf("USECU", "35B", None, "ES0113900J37", idx=5,
             label="isin"),
        _mtf("CACONF/CSHMOVE", "19B", qual, amount, idx=8,
             label="amount"),
        _mtf("CACONF/CSHMOVE", "19B", qual, "EUR", idx=8,
             label="currency code"),
        _mtf("CACONF/CSHMOVE", "98A", "PAYD", "20260720", idx=9,
             label="date"),
    ]
    return _mt_doc(facts)


def _mx036_cash(elem, amount="125.00"):
    gnl = [
        _mxf(f"{DOC}/CorpActnGnlInf/CorpActnEvtId", "BME-DVCA-0001"),
        _mxf(f"{DOC}/CorpActnGnlInf/EvtTp/Cd", "DVCA"),
        _mxf(f"{DOC}/CorpActnGnlInf/FinInstrmId/ISIN",
             "ES0113900J37"),
        _mxf(f"{DOC}/AcctDtls/SfkpgAcct", "A001"),
        _mxf(f"{CONF}/CshMvmntDtls/CdtDbtInd", "CRDT", csh=0),
        _mxf(f"{CONF}/CshMvmntDtls/AmtDtls/{elem}", amount, csh=0),
        _mxf(f"{CONF}/CshMvmntDtls/AmtDtls/{elem}/@Ccy", "EUR",
             csh=0),
        _mxf(f"{CONF}/CshMvmntDtls/DtDtls/PmtDt", "2026-07-20", csh=0),
    ]
    return _mx_doc(gnl)


def test_s6_cash_gross_parity():
    canon = _canon()
    mt = cash_candidate(_mt566_cash("GRSS"), canon, now=NOW)
    mx = mx_cash_candidate(_mx036_cash("GrssAmt"), canon, now=NOW)
    assert mt["status"] == mx["status"] == "PROJECTABLE"
    assert mt["movement"]["amount_basis"] == mx[
        "movement"]["amount_basis"] == "GROSS"
    # lexema distinto (MT "125," vs MX "125.00"), mismo valor Decimal
    from decimal import Decimal
    assert Decimal(mt["movement"]["amount"]) == Decimal(
        mx["movement"]["amount"]) == Decimal("125")
    assert mt["movement"]["currency"] == mx["movement"]["currency"]
    # diferencia legitima: seev.036 expone CdtDbtInd; MT candidate no
    assert mx["movement"]["direction"] == "CRDT"
    assert "direction" not in mt["movement"]


def test_s7_cash_unknown_basis_parity():
    canon = _canon()
    mt = cash_candidate(_mt566_cash("PSTA"), canon, now=NOW)
    mx = mx_cash_candidate(_mx036_cash("PstngAmt"), canon, now=NOW)
    assert mt["movement"]["amount_basis"] == mx[
        "movement"]["amount_basis"] == "UNKNOWN"
    assert mt["basis_reason"] == mx["basis_reason"] == \
        "UNKNOWN_AMOUNT_BASIS"


# --- escenarios 8/9: security movement -------------------------------------

def _mt566_sec(code, isin="ES0105857033", qty="125000,"):
    facts = [
        _mtf("GENL", "20C", "CORP", "RDG-SPLIT-2026", idx=1,
             label="reference"),
        _mtf("GENL", "22F", "CAEV", "SPLF", idx=2, label="indicator"),
        _mtf("USECU", "97A", "SAFE", "A001", idx=4,
             label="account number"),
        _mtf("USECU", "35B", None, "ES0105857009", idx=5,
             label="isin"),
        _mtf("CACONF", "13A", "CAON", "001", idx=7,
             label="number id"),
        _mtf("CACONF", "22F", "CAOP", "SECU", idx=8,
             label="indicator"),
        _mtf("CACONF/SECMOVE", "22H", "CRDB", code, idx=10,
             label="indicator"),
        _mtf("CACONF/SECMOVE", "35B", None, isin, idx=11,
             label="isin"),
        _mtf("CACONF/SECMOVE", "36B", "PSTA", qty, idx=12,
             label="quantity"),
        _mtf("CACONF/SECMOVE", "36B", "PSTA", "UNIT", idx=12,
             label="quantity type code"),
        _mtf("CACONF/SECMOVE", "98A", "POST", "20260609", idx=13,
             label="date"),
    ]
    return _mt_doc(facts)


def _mx036_sec(code, isin="ES0105857033", qty="125000"):
    facts = [
        _mxf(f"{DOC}/CorpActnGnlInf/CorpActnEvtId", "RDG-SPLIT-2026"),
        _mxf(f"{DOC}/CorpActnGnlInf/EvtTp/Cd", "SPLF"),
        _mxf(f"{DOC}/CorpActnGnlInf/FinInstrmId/ISIN",
             "ES0105857009"),
        _mxf(f"{DOC}/AcctDtls/SfkpgAcct", "A001"),
        _mxf(f"{CONF}/SctiesMvmntDtls/CdtDbtInd", code, sec=0),
        _mxf(f"{CONF}/SctiesMvmntDtls/FinInstrmId/ISIN", isin, sec=0),
        _mxf(f"{CONF}/SctiesMvmntDtls/PstngQty/Qty/Unit", qty, sec=0),
        _mxf(f"{CONF}/SctiesMvmntDtls/DtDtls/PstngDt/Dt",
             "2026-06-09", sec=0),
    ]
    return _mx_doc(facts)


def _split_canon():
    return _canon(event_type="SPLIT", isin="ES0105857009",
                  eid="evt-split-1")


def test_s8_security_receipt_parity():
    canon = _split_canon()
    mt = security_movement_candidate(_mt566_sec("CRED"), canon, now=NOW)
    mx = mx_security_movement_candidate(
        _mx036_sec("CRDT"), canon, now=NOW)
    for cand in (mt, mx):
        assert cand["status"] == "PROJECTABLE"
        m = cand["movements"][0]
        assert m["direction"] == "RECEIPT"
        assert m["quantity"] == "125000"
        assert m["quantity_type"] == "UNIT"
        assert m["posting_date"] == "2026-06-09"
        assert m["account_id"] == "A001"


def test_s9_security_delivery_parity():
    canon = _split_canon()
    mt = security_movement_candidate(_mt566_sec("DEBT"), canon, now=NOW)
    mx = mx_security_movement_candidate(
        _mx036_sec("DBIT"), canon, now=NOW)
    for cand in (mt, mx):
        m = cand["movements"][0]
        assert m["direction"] == "DELIVERY"


# --- escenario 10: conflicto deliberado --------------------------------------

def test_s10_conflicting_amount_both_transports():
    canon = _canon()
    mt_facts = _mt566_cash("GRSS")["facts"] + [
        _mtf("CACONF/CSHMOVE", "19B", "GRSS", "999,", occ=1, idx=10,
             label="amount"),
    ]
    mt = cash_candidate(_mt_doc(mt_facts), canon, now=NOW)
    mx_facts = _mx036_cash("GrssAmt")["facts"] + [
        _mxf(f"{CONF}/CshMvmntDtls/AmtDtls/GrssAmt", "999.00", csh=0),
    ]
    mx = mx_cash_candidate(_mx_doc(mx_facts), canon, now=NOW)
    assert "CONFLICTING_AMOUNT" in mt["reasons"]
    assert "CONFLICTING_AMOUNT" in mx["reasons"]
    assert mt["status"] == mx["status"] == "INDETERMINATE"


# --- escenario 11: codigo unsupported preservado raw -------------------------

def test_s11_unsupported_status_raw_preserved():
    mt = bind_instruction_status(_mt567("XXYY"), _instruction(), now=NOW)
    mx = bind_mx_instruction_status(
        _mx034("PrtrySts"), _instruction(), now=NOW)
    assert mt["statuses"][0]["normalized_status"] == "UNSUPPORTED"
    assert mt["statuses"][0]["status_code_raw"] == "XXYY"
    assert mx["statuses"][0]["normalized_status"] == "UNSUPPORTED"
    assert mx["statuses"][0]["status_code_raw"] == "PrtrySts"


# --- escenario 12: identidad ambigua sigue ambigua ---------------------------

def test_s12_ambiguous_identity():
    mt = bind_instruction_status(
        _mt567("PACK", extra_prev="INS-9999"), _instruction(), now=NOW)
    mx = bind_mx_instruction_status(
        _mx034(extra_id="INS-9999"), _instruction(), now=NOW)
    assert mt["instruction_binding_status"] == mx[
        "instruction_binding_status"] == "AMBIGUOUS"


# --- escenario 3: instruction -> MT565 + seev.033 (e2e real) -----------------

def test_s3_instruction_parity_e2e():
    _jar_or_skip()
    import json

    from ca_es.seev033 import seev033_project, write_seev033

    instr = {
        "schema": "CA_ES_ELECTION_INSTRUCTION_V1",
        "instruction_id": "INS-0001",
        "instruction_status": "READY",
        "canonical_event_id": "evt-1",
        "account_id": "SAFE-001",
        "isin": "ES0113900J37",
        "option_kind": "CASH",
        "option_identifier": "001",
        "option_code_raw": "CASH",
        "requested_quantity": "1000",
        "source_canon_logical_sha256": "a" * 64,
        "source_message_input_sha256": SHA,
    }
    envelope = {
        "schema": "CA_ES_SWIFT_MX_ENVELOPE_V1",
        "sender_bic": "BANKESMMXXX",
        "receiver_bic": "BANKDEFFXXX",
        "msg_def_idr": "seev.033.002.13",
        "biz_svc": "swift.cbprplus.02",
        "cre_dt": "2026-09-18T12:00:00Z",
    }
    src = _mx_doc([
        _mxf("/Document/CorpActnNtfctn/CorpActnGnlInf/CorpActnEvtId",
             "SAN-DIV-2026", mid="seev.031.002.15"),
        _mxf("/Document/CorpActnNtfctn/CorpActnGnlInf/EvtTp/Cd",
             "DVCA", mid="seev.031.002.15"),
        _mxf("/Document/CorpActnNtfctn/CorpActnGnlInf/UndrlygScty"
             "/FinInstrmId/ISIN", "ES0113900J37",
             mid="seev.031.002.15"),
    ], mid="seev.031.002.15")
    proj = seev033_project(instr, src, envelope, now=NOW)
    out, rc = write_seev033(proj)
    assert rc == 0
    assert out["schema_version"] == "CA_ES_SEEV033_XML_V1"
    assert out["write_status"] == "OK"
    xml = out["xml"]
    for token in ("INS-0001", "SAN-DIV-2026", "DVCA",
                  "ES0113900J37", "SAFE-001", "CASH", "1000"):
        assert token in xml
    # round-trip real: el XML escrito parsea con Prowide
    rt, rc = parse_mx(xml.encode("utf-8"))
    assert rc == 0
    assert rt["message_identifier"] == "seev.033.002.13"
    paths = {f["model_path"]: f["value"] for f in rt["facts"]}
    assert any(v == "INS-0001" for v in paths.values())
    assert any(v == "SAN-DIV-2026" for v in paths.values())
    json.dumps(out)


# --- escenario 2: voluntary option opportunity ------------------------------

def test_s2_voluntary_option_parity():
    """MT564 VOLU y seev.031 con CASH option + RspnDdln ->
    misma opportunidad semantica."""
    _jar_or_skip()
    canon = _canon()
    from ca_es.election import project_election
    from ca_es.mx_ca import project_mx_election

    mt_doc, _ = parse_mt(
        (RES / "mt564-valid.fin").read_text(encoding="utf-8"))
    mx_doc, _ = parse_mx((RES / "seev031-parity.xml").read_bytes())
    mt_opp = project_election(mt_doc, canon, now=NOW)
    mx_opp = project_mx_election(mx_doc, canon, now=NOW)
    assert mt_opp["schema"] == mx_opp["schema"] == \
        "CA_ES_ELECTION_OPPORTUNITY_V1"
    if (mt_opp["options"] and mx_opp["options"]):
        mt_o, mx_o = mt_opp["options"][0], mx_opp["options"][0]
        assert mt_o["option_code_raw"] == mx_o["option_code_raw"]
        assert mt_o["default_status"] == mx_o["default_status"]
        assert mt_o["source_response_deadline"] == mx_o[
            "source_response_deadline"]
