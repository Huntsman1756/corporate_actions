"""P4.5 — seev.033 writer: CA_ES_SEEV033_PROJECTION_V1 +
CA_ES_SWIFT_MX_ENVELOPE_V1 + CA_ES_SEEV033_XML_V1.
"""

from pathlib import Path

import pytest

from ca_es import mx_facts, seev033
from ca_es.seev033 import seev033_project, write_seev033
from ca_es.swift_mt import default_adapter_jar

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "adapters" / "iso-adapter-jvm" / "src" / "test" / "resources"
JAR = default_adapter_jar()
requires_jar = pytest.mark.skipif(
    not JAR.is_file(), reason="iso-adapter.jar no construido")

NOW = "2026-09-17T00:00:00Z"
SHA = "ef" * 32


def _mx_facts(corp="SAN-DIV-2026", caev="DVCA", sha=SHA):
    return {
        "schema_version": "CA_ES_SWIFT_MX_FACTS_V1",
        "message_identifier": "seev.031.002.15",
        "input_sha256": sha,
        "parse_status": "PARSE_OK",
        "facts": [
            {"model_path":
                "/Document/CorpActnNtfctn/CorpActnGnlInf/CorpActnEvtId",
             "value": corp,
             "occurrence": 0,
             "evidence_locator": "element:/x",
             "input_sha256": sha},
            {"model_path":
                "/Document/CorpActnNtfctn/CorpActnGnlInf/EvtTp/Cd",
             "value": caev,
             "occurrence": 0,
             "evidence_locator": "element:/y",
             "input_sha256": sha},
        ],
    }


def _mt_facts(corp="SAN-DIV-2026", caev="DVCA", sha=SHA):
    return {
        "schema_version": "CA_ES_SWIFT_MT_FACTS_V1",
        "message_identifier": "MT564",
        "input_sha256": sha,
        "parse_status": "OK",
        "facts": [
            {"message_identifier": "MT564", "field_path": "MT564.GENL",
             "value": corp, "source_tag": "20C",
             "source_qualifier": "CORP", "sequence": "GENL",
             "occurrence": 0,
             "evidence_locator": "block4.tag[1]",
             "input_sha256": sha},
            {"message_identifier": "MT564", "field_path": "MT564.GENL",
             "value": caev, "source_tag": "22F",
             "source_qualifier": "CAEV", "sequence": "GENL",
             "occurrence": 0,
             "evidence_locator": "block4.tag[2]",
             "input_sha256": sha},
        ],
    }


def _instruction(**kw):
    base = {
        "schema": "CA_ES_ELECTION_INSTRUCTION_V1",
        "instruction_id": "INS-0001",
        "instruction_status": "READY",
        "canonical_event_id": "E1",
        "account_id": "ACC-001",
        "isin": "ES0113900J37",
        "option_kind": "SECURITIES",
        "option_identifier": "001",
        "option_code_raw": "SECU",
        "requested_quantity": "12500",
        "source_canon_logical_sha256": "aa" * 32,
        "source_message_input_sha256": SHA,
    }
    base.update(kw)
    return base


def _envelope(**kw):
    base = {
        "schema": "CA_ES_SWIFT_MX_ENVELOPE_V1",
        "sender_bic": "BANKESMMAXX",
        "receiver_bic": "BANKDEFFXXX",
        "msg_def_idr": "seev.033.002.13",
        "biz_svc": "swift.cbprplus.02",
        "cre_dt": "2026-09-17T10:00:00Z",
    }
    base.update(kw)
    return base


# -------------------------------------------------------- projection

def test_serializable_projection_from_mx_facts():
    proj = seev033_project(
        _instruction(), _mx_facts(), _envelope(), now=NOW)
    assert proj["schema"] == "CA_ES_SEEV033_PROJECTION_V1"
    assert proj["projection_status"] == "SERIALIZABLE"
    assert proj["message_identifier"] == "seev.033.002.13"
    paths = {e["model_path"]: e["value"] for e in proj["elements"]}
    assert paths[
        "CorpActnInstr/CorpActnGnlInf/CorpActnEvtId"] == "SAN-DIV-2026"
    assert paths[
        "CorpActnInstr/CorpActnGnlInf/EvtTp/Cd"] == "DVCA"
    assert paths[
        "CorpActnInstr/CorpActnInstr/OptnTp/Cd"] == "SECU"
    assert paths[
        "CorpActnInstr/CorpActnInstr/SctiesQtyOrInstdAmt"
        "/SctiesQty/InstdQty/Qty/Unit"] == "12500"
    # BizMsgIdr = instruction_id (correlacion seev.034)
    assert proj["envelope"]["biz_msg_idr"] == "INS-0001"
    # provenance por elemento
    assert all("source" in e for e in proj["elements"])


def test_serializable_projection_from_mt564_facts():
    """La notificacion fuente puede ser MT564 (mismo instruction doc)."""
    proj = seev033_project(
        _instruction(), _mt_facts(), _envelope(), now=NOW)
    assert proj["projection_status"] == "SERIALIZABLE"


def test_not_ready_and_bad_option_fail_closed():
    proj = seev033_project(
        _instruction(instruction_status="DRAFT"),
        _mx_facts(), _envelope(), now=NOW)
    assert proj["projection_status"] == "NOT_SERIALIZABLE"
    assert "INSTRUCTION_NOT_READY" in proj["reasons"]
    proj = seev033_project(
        _instruction(option_kind="OTHER"), _mx_facts(), _envelope(),
        now=NOW)
    assert "UNSUPPORTED_OPTION_KIND" in proj["reasons"]


def test_facts_mismatch_and_bad_envelope_raise():
    with pytest.raises(ValueError, match="INSTRUCTION_FACTS_MISMATCH"):
        seev033_project(
            _instruction(), _mx_facts(sha="00" * 32),
            _envelope(), now=NOW)
    with pytest.raises(ValueError, match="msg_def_idr"):
        seev033_project(
            _instruction(), _mx_facts(),
            _envelope(msg_def_idr="seev.033.001.13"), now=NOW)
    with pytest.raises(ValueError):
        seev033_project(
            _instruction(), _mx_facts(),
            _envelope(biz_svc=None), now=NOW)


def test_missing_corp_or_bad_quantity():
    facts = _mx_facts()
    facts["facts"] = facts["facts"][1:]
    proj = seev033_project(
        _instruction(), facts, _envelope(), now=NOW)
    assert "MISSING_CORP_REFERENCE" in proj["reasons"]
    assert proj["projection_status"] == "NOT_SERIALIZABLE"
    proj = seev033_project(
        _instruction(requested_quantity="-5"),
        _mx_facts(), _envelope(), now=NOW)
    assert "INVALID_REQUESTED_QUANTITY" in proj["reasons"]


def test_inputs_not_mutated():
    inst, facts, env = _instruction(), _mx_facts(), _envelope()
    snap = (dict(inst), dict(facts), dict(env))
    seev033_project(inst, facts, env, now=NOW)
    assert inst["instruction_id"] == snap[0]["instruction_id"]
    assert facts["facts"] == snap[1]["facts"]
    assert env == snap[2]


# ------------------------------------------------------------ e2e jar

@requires_jar
def test_e2e_project_write_parse_round_trip():
    proj = seev033_project(
        _instruction(), _mx_facts(), _envelope(), now=NOW)
    assert proj["projection_status"] == "SERIALIZABLE"
    out, code = write_seev033(proj)
    assert code == 0
    assert out["schema_version"] == "CA_ES_SEEV033_XML_V1"
    assert out["write_status"] == "OK"
    assert out["xml_sha256"]
    assert out["source_projection_sha256"]

    # round-trip: el XML vuelve por el adapter facts
    facts_doc, code = mx_facts.parse_mx(out["xml"])
    assert code == 0
    assert facts_doc["message_identifier"] == "seev.033.002.13"
    paths = {f["model_path"]: f["value"] for f in facts_doc["facts"]}
    assert paths["/AppHdr/BizMsgIdr"] == "INS-0001"
    assert paths["/AppHdr/Fr/FIId/FinInstnId/BICFI"] == "BANKESMMAXX"
    assert paths[
        "/Document/CorpActnInstr/CorpActnInstr/OptnTp/Cd"] == "SECU"
    assert paths[
        "/Document/CorpActnInstr/CorpActnInstr"
        "/SctiesQtyOrInstdAmt/SctiesQty/InstdQty/Qty/Unit"] == "12500"


@requires_jar
def test_e2e_deterministic_and_not_serializable_rejected():
    proj = seev033_project(
        _instruction(), _mx_facts(), _envelope(), now=NOW)
    a, _ = write_seev033(proj)
    b, _ = write_seev033(proj)
    assert a["xml_sha256"] == b["xml_sha256"]

    bad = dict(proj)
    bad["projection_status"] = "NOT_SERIALIZABLE"
    out, code = write_seev033(bad)
    assert code == 2
    assert out["write_status"] == "NOT_SERIALIZABLE"
    assert out["xml"] is None
