"""P4.4 — seev.031 -> dominio existente (CA_ES_SWIFT_CA_MESSAGE_V1,
CA_ES_SWIFT_EVENT_BINDING_V1, CA_ES_ELECTION_OPPORTUNITY_V1).

Los tests e2e usan el adapter JVM real sobre los fixtures
seev031-*.xml de adapters/iso-adapter-jvm/src/test/resources.
"""

from pathlib import Path

import pytest

from ca_es import mx_ca
from ca_es.mx_ca import project_mx_election, project_mx_message
from ca_es.swift_ca import bind_event, project_ca_message
from ca_es.swift_mt import default_adapter_jar

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "adapters" / "iso-adapter-jvm" / "src" / "test" / "resources"
JAR = default_adapter_jar()
requires_jar = pytest.mark.skipif(
    not JAR.is_file(), reason="iso-adapter.jar no construido")

NOW = "2026-09-17T00:00:00Z"
SHA = "cd" * 32
D = "/Document/CorpActnNtfctn"


def _mfact(path, value, optn=0):
    loc = f"element:/Document[0]/CorpActnNtfctn[0]{path}"
    if "/CorpActnOptnDtls" in path:
        loc = loc.replace("CorpActnOptnDtls[",
                          f"CorpActnOptnDtls[{optn}]")
    return {
        "message_identifier": "seev.031.002.15",
        "model_path": "/Document/CorpActnNtfctn" + path,
        "value": value,
        "occurrence": 0,
        "evidence_locator": loc,
        "input_sha256": SHA,
    }


def _opt(optn, nb, code, dflt="true", rddt="2026-07-18", extra=()):
    facts = [
        {
            "message_identifier": "seev.031.002.15",
            "model_path": D + f"/CorpActnOptnDtls/OptnNb",
            "value": nb,
            "occurrence": optn,
            "evidence_locator":
                f"element:/Document[0]/CorpActnNtfctn[0]"
                f"/CorpActnOptnDtls[{optn}]/OptnNb[0]",
            "input_sha256": SHA,
        },
        {
            "message_identifier": "seev.031.002.15",
            "model_path": D + "/CorpActnOptnDtls/OptnTp/Cd",
            "value": code,
            "occurrence": optn,
            "evidence_locator":
                f"element:/Document[0]/CorpActnNtfctn[0]"
                f"/CorpActnOptnDtls[{optn}]/OptnTp[0]/Cd[0]",
            "input_sha256": SHA,
        },
    ]
    if dflt is not None:
        facts.append({
            "message_identifier": "seev.031.002.15",
            "model_path":
                D + "/CorpActnOptnDtls/DfltPrcgOrStgInstr/DfltOptnInd",
            "value": dflt,
            "occurrence": optn,
            "evidence_locator":
                f"element:/Document[0]/CorpActnNtfctn[0]"
                f"/CorpActnOptnDtls[{optn}]"
                f"/DfltPrcgOrStgInstr[0]/DfltOptnInd[0]",
            "input_sha256": SHA,
        })
    if rddt is not None:
        facts.append({
            "message_identifier": "seev.031.002.15",
            "model_path": D + "/CorpActnOptnDtls/DtDtls/RspnDdln/Dt/Dt",
            "value": rddt,
            "occurrence": optn,
            "evidence_locator":
                f"element:/Document[0]/CorpActnNtfctn[0]"
                f"/CorpActnOptnDtls[{optn}]/DtDtls[0]"
                f"/RspnDdln[0]/Dt[0]/Dt[0]",
            "input_sha256": SHA,
        })
    facts.extend(extra)
    return facts


def _facts(*facts, mid="seev.031.002.15", parse_status="PARSE_OK"):
    return {
        "schema_version": "CA_ES_SWIFT_MX_FACTS_V1",
        "generated_at": NOW,
        "message_identifier": mid,
        "input_sha256": SHA,
        "parse_status": parse_status,
        "facts": list(facts),
    }


def _gnl(isin="ES0113900J37", caev="DVCA", mvty="MAND",
         corp="SAN-DIV-2026", xdte="2026-07-16", rdte="2026-07-15",
         payd="2026-07-20", grss="0.125", ccy="EUR", optn=0):
    facts = [
        _mfact("/NtfctnGnlInf[0]/NtfctnTp[0]", "NEWM"),
        _mfact("/CorpActnGnlInf[0]/CorpActnEvtId[0]", corp),
        _mfact("/CorpActnGnlInf[0]/EvtTp[0]/Cd[0]", caev),
        _mfact("/CorpActnGnlInf[0]/MndtryVlntryEvtTp[0]/Cd[0]", mvty),
        _mfact("/CorpActnGnlInf[0]/UndrlygScty[0]"
               "/FinInstrmId[0]/ISIN[0]", isin),
        _mfact("/CorpActnDtls[0]/DtDtls[0]/ExDvddDt[0]/Dt[0]", xdte),
        _mfact("/CorpActnDtls[0]/DtDtls[0]/RcrdDt[0]/Dt[0]", rdte),
        _mfact("/CorpActnDtls[0]/DtDtls[0]/PmtDt[0]/Dt[0]", payd),
    ]
    facts[0]["model_path"] = D + "/NtfctnGnlInf/NtfctnTp"
    facts[1]["model_path"] = D + "/CorpActnGnlInf/CorpActnEvtId"
    facts[2]["model_path"] = D + "/CorpActnGnlInf/EvtTp/Cd"
    facts[3]["model_path"] = (
        D + "/CorpActnGnlInf/MndtryVlntryEvtTp/Cd")
    facts[4]["model_path"] = (
        D + "/CorpActnGnlInf/UndrlygScty/FinInstrmId/ISIN")
    facts[5]["model_path"] = D + "/CorpActnDtls/DtDtls/ExDvddDt/Dt"
    facts[6]["model_path"] = D + "/CorpActnDtls/DtDtls/RcrdDt/Dt"
    facts[7]["model_path"] = D + "/CorpActnDtls/DtDtls/PmtDt/Dt"
    if grss is not None:
        facts.append({
            "message_identifier": "seev.031.002.15",
            "model_path":
                D + "/CorpActnOptnDtls/RateAndAmtDtls"
                    "/GrssDstrbtnRate/Amt",
            "value": grss,
            "occurrence": optn,
            "evidence_locator":
                f"element:/Document[0]/CorpActnNtfctn[0]"
                f"/CorpActnOptnDtls[{optn}]/RateAndAmtDtls[0]"
                f"/GrssDstrbtnRate[0]/Amt[0]",
            "input_sha256": SHA,
        })
        facts.append({
            "message_identifier": "seev.031.002.15",
            "model_path":
                D + "/CorpActnOptnDtls/RateAndAmtDtls"
                    "/GrssDstrbtnRate/Amt/@Ccy",
            "value": ccy,
            "occurrence": 0,
            "evidence_locator":
                f"element:/Document[0]/CorpActnNtfctn[0]"
                f"/CorpActnOptnDtls[{optn}]/RateAndAmtDtls[0]"
                f"/GrssDstrbtnRate[0]/Amt[0]/@Ccy",
            "input_sha256": SHA,
        })
    return facts


def _event(eid, etype="CASH_DIVIDEND", isin=None, dates=None,
           gross=None):
    facts = []
    if isin:
        facts.append({
            "field_path": "instrument.isin", "value": isin,
            "revision_id": "r1", "assertion_id": f"as-{eid}-i",
            "evidence_locator": f"doc-{eid}:isin"})
    for path, val in (dates or {}).items():
        facts.append({
            "field_path": path, "value": val,
            "revision_id": "r1", "assertion_id": f"as-{eid}-{path}",
            "evidence_locator": f"doc-{eid}:{path}"})
    if gross:
        facts.append({
            "field_path": "amount.gross_per_share",
            "value": {"__financial__": True, "normalized": gross,
                      "currency": "EUR", "scale": 3,
                      "raw_lexeme": gross},
            "revision_id": "r1", "assertion_id": f"as-{eid}-g",
            "evidence_locator": f"doc-{eid}:gross"})
    return {"canonical_event_id": eid, "event_type": etype,
            "affected_instrument": {"isin": isin},
            "facts": facts, "conflicts": []}


def _canon(*events):
    return {"canon_version": "CA_ES_OPERATIONAL_CANON_V1",
            "logical_sha256": "aa" * 32,
            "events": list(events)}


CANON = _canon(_event(
    "E-DVCA", isin="ES0113900J37",
    dates={"date.ex_date": "2026-07-16",
           "date.record_date": "2026-07-15",
           "date.payment_date": "2026-07-20"},
    gross="0.125"))


# ---------------------------------------------------------- projection

def test_seev031_projects_to_same_ca_message_contract():
    msg = project_mx_message(_facts(*_gnl()), now=NOW)
    assert msg["schema"] == "CA_ES_SWIFT_CA_MESSAGE_V1"
    assert msg["status"] == "OK"
    assert msg["event_type"] == "CASH_DIVIDEND"
    assert msg["caev"] == "DVCA"
    f = msg["fields"]
    assert f["corporate_action_reference"]["value"] == "SAN-DIV-2026"
    assert f["isin"]["value"] == "ES0113900J37"
    assert f["ex_date"]["value"] == "2026-07-16"
    assert f["record_date"]["value"] == "2026-07-15"
    assert f["payment_date"]["value"] == "2026-07-20"
    assert f["gross_per_share"]["value"] == "0.125"
    assert f["currency"]["value"] == "EUR"
    assert f["message_function"]["value"] == "NEWM"
    # provenance MX: model_path, no source_tag
    prov = f["isin"]["provenance"][0]
    assert prov["model_path"].endswith("FinInstrmId/ISIN")
    assert "source_tag" not in prov


def test_unsupported_mid_and_bad_parse_fail_closed():
    msg = project_mx_message(
        _facts(*_gnl(), mid="seev.033.002.13"), now=NOW)
    assert msg["status"] == "UNSUPPORTED_MESSAGE_TYPE"
    msg = project_mx_message(
        _facts(*_gnl(), parse_status="PARSE_ERROR"), now=NOW)
    assert msg["status"] == "PARSE_NOT_OK"


def test_unknown_caev_unsupported():
    facts = _gnl(caev="WTHD")
    msg = project_mx_message(_facts(*facts), now=NOW)
    assert msg["status"] == "UNSUPPORTED_CA_EVENT"


def test_conflicting_isin_is_conflicting_not_chosen():
    facts = _gnl()
    dup = dict(facts[4])
    dup["value"] = "ES0000000000"
    dup["evidence_locator"] += "b"
    facts.append(dup)
    msg = project_mx_message(_facts(*facts), now=NOW)
    assert msg["fields"]["isin"]["status"] == "CONFLICTING"
    assert msg["fields"]["isin"]["value"] is None


def test_schema_guard():
    with pytest.raises(ValueError):
        project_mx_message({"schema_version": "X"}, now=NOW)


# ------------------------------------------------------------- binding

def test_bind_event_reused_unchanged():
    msg = project_mx_message(_facts(*_gnl()), now=NOW)
    binding = bind_event(msg, CANON, now=NOW)
    assert binding["schema"] == "CA_ES_SWIFT_EVENT_BINDING_V1"
    assert binding["binding_status"] == "BOUND"
    assert binding["canonical_event_id"] == "E-DVCA"
    statuses = {c["field"]: c["status"] for c in binding["comparisons"]}
    assert statuses == {
        "ex_date": "AGREES", "record_date": "AGREES",
        "payment_date": "AGREES", "gross_per_share": "AGREES"}


def test_bind_no_match_when_isin_absent_from_canon():
    canon = _canon(_event("E-OTRO", isin="ES9999999999"))
    msg = project_mx_message(_facts(*_gnl()), now=NOW)
    binding = bind_event(msg, canon, now=NOW)
    assert binding["binding_status"] == "NO_MATCH"


# --------------------------------------------------- election parity

def test_mx_election_two_options():
    facts = _gnl() + _opt(0, "001", "CASH", dflt="true") \
        + _opt(1, "002", "SECU", dflt="false")
    doc = project_mx_election(_facts(*facts), CANON, now=NOW)
    assert doc["schema"] == "CA_ES_ELECTION_OPPORTUNITY_V1"
    assert doc["projection_status"] == "PROJECTED"
    assert doc["canonical_event_id"] == "E-DVCA"
    assert doc["source_message_identifier"] == "seev.031.002.15"
    opts = doc["options"]
    assert len(opts) == 2
    assert opts[0]["option_identifier"] == "001"
    assert opts[0]["option_kind"] == "CASH"
    assert opts[0]["default_status"] == "DEFAULT"
    assert opts[0]["source_response_deadline"] == "2026-07-18"
    assert opts[1]["option_identifier"] == "002"
    assert opts[1]["option_kind"] == "SECURITIES"
    assert opts[1]["default_status"] == "NOT_DEFAULT"
    assert doc["source_response_deadline"] == "2026-07-18"


def test_mx_election_no_options_is_indeterminate():
    facts = [f for f in _gnl() if "CorpActnOptnDtls" not in
             (f["model_path"] or "")]
    doc = project_mx_election(_facts(*facts), CANON, now=NOW)
    assert doc["projection_status"] == "INDETERMINATE"
    assert "NO_OPTION_EVIDENCE" in doc["reasons"]
    assert doc["options"] == []


def test_mx_election_missing_optn_nb():
    facts = _gnl() + _opt(0, "001", "CASH")
    for f in facts:
        if (f["model_path"] or "").endswith("/OptnNb"):
            f["value"] = None
    doc = project_mx_election(_facts(*facts), CANON, now=NOW)
    assert "MISSING_OPTION_IDENTITY" in doc["reasons"]
    assert doc["options"] == []


def test_mx_election_stg_instr_is_not_default():
    facts = _gnl() + _opt(0, "001", "CASH", dflt=None)
    doc = project_mx_election(_facts(*facts), CANON, now=NOW)
    assert doc["options"][0]["default_status"] == "UNKNOWN"


def test_mx_election_unknown_option_code_unsupported():
    facts = _gnl() + _opt(0, "001", "BIDS")
    doc = project_mx_election(_facts(*facts), CANON, now=NOW)
    assert doc["options"][0]["option_kind"] == "UNSUPPORTED"
    assert doc["options"][0]["option_code_raw"] == "BIDS"


def test_mx_election_unsupported_mid():
    doc = project_mx_election(
        _facts(*_gnl(), mid="seev.034.002.15"), CANON, now=NOW)
    assert doc["projection_status"] == "UNSUPPORTED"


def test_mx_election_queue_binding_reused():
    queue = {
        "source_canon_logical_sha256": "aa" * 32,
        "items": [{
            "canonical_event_id": "E-DVCA",
            "deadline_type": "ELECTION_RESPONSE",
            "due_date": "2026-07-17",
        }],
    }
    facts = _gnl() + _opt(0, "001", "CASH")
    doc = project_mx_election(
        _facts(*facts), CANON, queue_doc=queue,
        deadline_types=("ELECTION_RESPONSE",), now=NOW)
    assert doc["deadline_binding_status"] == "BOUND"
    assert doc["operational_deadlines"][0]["deadline_type"] == (
        "ELECTION_RESPONSE")


# ------------------------------------------------------------ e2e jar

@requires_jar
def test_e2e_mt_mx_parity_same_event():
    from ca_es import mx_facts, swift_mt
    mt_doc, code = swift_mt.parse_mt(
        (RES / "mt564-valid.fin").read_text(encoding="utf-8"))
    assert code == 0
    mx_doc, code = mx_facts.parse_mx(
        (RES / "seev031-parity.xml").read_bytes())
    assert code == 0

    mt_msg = project_ca_message(mt_doc, now=NOW)
    mx_msg = project_mx_message(mx_doc, now=NOW)
    assert mt_msg["status"] == mx_msg["status"] == "OK"
    assert mt_msg["event_type"] == mx_msg["event_type"] \
        == "CASH_DIVIDEND"
    assert mt_msg["caev"] == mx_msg["caev"] == "DVCA"
    for name in ("isin", "ex_date", "record_date", "payment_date",
                 "gross_per_share", "currency", "message_function"):
        mt_f, mx_f = mt_msg["fields"][name], mx_msg["fields"][name]
        assert mt_f["status"] == mx_f["status"] == "PRESENT", name
        assert mt_f["value"] == mx_f["value"], name

    binding = bind_event(mx_msg, CANON, now=NOW)
    assert binding["binding_status"] == "BOUND"
