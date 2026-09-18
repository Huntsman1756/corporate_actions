"""P8.1 — SPLIT/REVERSE_SPLIT: proyeccion de operandos, event_terms,
securities entitlement, impacto y proyeccion de posiciones.

Cubre: SPLF/SPLR->SPLIT (+mechanism), ratio NEWO new/old, target_isin
desde SECMOVE, DISF, PROVEN/INCOMPLETE/UNSUPPORTED en terms, math
Decimal por politica de fraccion, propagation verbatim de estados,
impact items SECURITY_DELIVERY/SECURITY_RECEIPT/CASH_IN_LIEU, y la
cadena e2e terms->entitlement->impact->projected_positions.
"""
import json
from pathlib import Path

import pytest

from ca_es import swift_mt
from ca_es.event_terms import (
    TERMS_SCHEMA,
    build_event_terms,
)
from ca_es.exceptions import build_cases_doc
from ca_es.projected_positions import project_positions
from ca_es.security_recon import reconcile_security_movements
from ca_es.swift_ca import bind_event
from ca_es.swift_securities import security_movement_candidate
from ca_es.securities_entitlement import (
    SEC_ENT_SCHEMA,
    compute_securities_entitlements,
)
from ca_es.security_impact import (
    IMPACT_SCHEMA,
    compute_security_impact,
)
from ca_es.swift_ca import project_ca_message

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "adapters" / "iso-adapter-jvm" / "src" / "test" / "resources"
JAR = swift_mt.default_adapter_jar()

requires_jar = pytest.mark.skipif(
    not JAR.is_file(), reason="iso-adapter.jar no construido")

NOW = "2026-09-16T00:00:00Z"
SHA = "ab" * 32
SRC_ISIN = "ES0105857009"
DST_ISIN = "ES0105857033"


# ---------------------------------------------------------- helpers

def _fact(seq, tag, qual, label, value, occ=0, mid="MT564"):
    return {
        "message_identifier": mid,
        "field_path": f"{mid}.{seq.replace('/', '.')}.{tag}"
                      + (f":{qual}" if qual else "")
                      + f".{label}",
        "value": value,
        "source_tag": tag,
        "source_qualifier": qual,
        "sequence": seq,
        "occurrence": occ,
        "evidence_locator": "block4.tag[0].component[1]",
        "input_sha256": SHA,
    }


def _facts_doc(*facts, mid="MT564", parse_status="OK"):
    return {
        "schema_version": "CA_ES_SWIFT_MT_FACTS_V1",
        "generated_at": NOW,
        "message_identifier": mid,
        "input_sha256": SHA,
        "parse_status": parse_status,
        "facts": list(facts),
    }


def _splf_facts(caev="SPLF", camv="MAND", rdte="20260609",
                xdte="20260609", disf="STAN", new="10", old="1",
                payd="20260610", src=SRC_ISIN, dst=DST_ISIN):
    facts = [
        _fact("GENL", "20C", "SEME", "reference", "SPLIT-1"),
        _fact("GENL", "23G", None, "function", "NEWM"),
        _fact("GENL", "22F", "CAEV", "indicator", caev),
        _fact("GENL", "25D", "PROC", "status code", "COMP"),
        _fact("USECU", "35B", "ISIN", "isin", src),
        _fact("USECU/CADETL", "98A", "RDTE", "date", rdte),
        _fact("USECU/CADETL", "98A", "XDTE", "date", xdte),
    ]
    if camv is not None:
        facts.append(
            _fact("GENL", "22F", "CAMV", "indicator", camv))
    if disf is not None:
        facts.append(
            _fact("USECU/CAOPTN", "22F", "DISF", "indicator", disf))
    if new is not None:
        facts.append(_fact(
            "USECU/CAOPTN/SECMOVE", "92D", "NEWO", "quantity1", new))
    if old is not None:
        facts.append(_fact(
            "USECU/CAOPTN/SECMOVE", "92D", "NEWO", "quantity2", old))
    if dst is not None:
        facts.append(_fact(
            "USECU/CAOPTN/SECMOVE", "35B", "ISIN", "isin", dst, occ=1))
    if payd is not None:
        facts.append(_fact(
            "USECU/CAOPTN/SECMOVE", "98A", "PAYD", "date", payd))
    return _facts_doc(*facts)


def _positions_doc(*positions, as_of="2026-06-09"):
    return {
        "schema": "CA_ES_POSITIONS_V1",
        "as_of": as_of,
        "positions": list(positions),
    }


def _pos(qty, isin=SRC_ISIN, account="ACC-1", as_of=None):
    p = {"account_id": account, "isin": isin, "quantity": qty}
    if as_of is not None:
        p["as_of"] = as_of
    return p


def _proven_terms(**overrides):
    msg = project_ca_message(_splf_facts(**overrides), now=NOW)
    return build_event_terms(msg, now=NOW)


# ---------------------------------------------------- proyeccion

def test_splf_maps_to_split():
    msg = project_ca_message(_splf_facts(), now=NOW)
    assert msg["status"] == "OK"
    assert msg["event_type"] == "SPLIT"
    assert msg["caev"] == "SPLF"
    assert msg["mechanism"] is None


def test_splr_maps_to_reverse_split():
    msg = project_ca_message(_splf_facts(caev="SPLR"), now=NOW)
    assert msg["event_type"] == "SPLIT"
    assert msg["mechanism"] == "REVERSE_SPLIT"


def test_spli_is_not_caev_split():
    msg = project_ca_message(_splf_facts(caev="SPLI"), now=NOW)
    assert msg["status"] == "UNSUPPORTED_CA_EVENT"
    assert msg["event_type"] is None


def test_newo_pairs_new_over_old():
    msg = project_ca_message(_splf_facts(new="10", old="1"), now=NOW)
    ratio = msg["fields"]["new_for_old_ratio"]
    assert ratio["status"] == "PRESENT"
    assert ratio["value"] == {"new": "10", "old": "1"}
    assert len(ratio["provenance"]) == 2


def test_newo_conflicting_not_collapsed():
    facts = _splf_facts()
    facts["facts"].append(_fact(
        "USECU/CAOPTN/SECMOVE", "92D", "NEWO", "quantity1",
        "5", occ=1))
    facts["facts"].append(_fact(
        "USECU/CAOPTN/SECMOVE", "92D", "NEWO", "quantity2",
        "1", occ=1))
    msg = project_ca_message(facts, now=NOW)
    ratio = msg["fields"]["new_for_old_ratio"]
    assert ratio["status"] == "CONFLICTING"
    assert ratio["value"] is None


def test_target_isin_from_secmove():
    msg = project_ca_message(_splf_facts(), now=NOW)
    f = msg["fields"]["target_isin"]
    assert f["status"] == "PRESENT"
    assert f["value"] == DST_ISIN


def test_target_isin_same_isin_split():
    msg = project_ca_message(_splf_facts(dst=SRC_ISIN), now=NOW)
    assert msg["fields"]["target_isin"]["value"] == SRC_ISIN


def test_disf_and_camv_projected():
    msg = project_ca_message(_splf_facts(), now=NOW)
    assert msg["fields"]["camv"]["value"] == "MAND"
    assert msg["fields"]["fraction_disposition"]["value"] == "STAN"
    assert msg["fields"]["effective_date"]["value"] == "2026-06-10"


# ---------------------------------------------------- event_terms

def test_terms_proven_full_splf():
    t = _proven_terms()
    assert t["schema"] == TERMS_SCHEMA
    assert t["terms_status"] == "PROVEN"
    assert t["reasons"] == []
    assert t["event_basis"] == "SWIFT_NOTIFICATION"
    assert t["basis_date"]["kind"] == "RECORD_DATE"
    assert t["basis_date"]["value"] == "2026-06-09"
    assert t["ratio"] == {"new": "10", "old": "1"}
    assert t["source_isin"] == SRC_ISIN
    assert t["target_isin"] == DST_ISIN
    assert t["fraction_disposition"] == "STAN"
    assert t["effective_date"] == "2026-06-10"


def test_terms_incomplete_without_basis_date():
    facts = _splf_facts()
    facts["facts"] = [f for f in facts["facts"]
                      if f["source_qualifier"] != "RDTE"]
    t = build_event_terms(project_ca_message(facts, now=NOW), now=NOW)
    assert t["terms_status"] == "INCOMPLETE"
    assert "MISSING_BASIS_DATE" in t["reasons"]


def test_terms_incomplete_without_ratio():
    facts = _splf_facts(new=None)
    t = build_event_terms(project_ca_message(facts, now=NOW), now=NOW)
    assert t["terms_status"] == "INCOMPLETE"
    assert "MISSING_RATIO" in t["reasons"]


def test_terms_unsupported_non_mand():
    t = _proven_terms(camv="VOLU")
    assert t["terms_status"] == "UNSUPPORTED"
    assert any(r.startswith("NON_MANDATORY_EVENT") for r in t["reasons"])


def test_terms_unsupported_event_type():
    facts = _facts_doc(
        _fact("GENL", "22F", "CAEV", "indicator", "DVCA"),
        _fact("GENL", "22F", "CAMV", "indicator", "MAND"),
        _fact("USEQ", "35B", "ISIN", "isin", SRC_ISIN),
    )
    t = build_event_terms(project_ca_message(facts, now=NOW), now=NOW)
    assert t["terms_status"] == "UNSUPPORTED"
    assert "UNSUPPORTED_EVENT_TYPE" in t["reasons"]


def test_terms_canon_bound_basis():
    msg = project_ca_message(_splf_facts(), now=NOW)
    binding = {"schema": "CA_ES_SWIFT_EVENT_BINDING_V1",
               "binding_status": "BOUND",
               "canonical_event_id": "EV-1"}
    t = build_event_terms(msg, binding, now=NOW)
    assert t["event_basis"] == "CANON_BOUND"
    assert t["canonical_event_id"] == "EV-1"


# ------------------------------------------------ entitlement math

def _ent(qty="12500", **terms_kw):
    terms = _proven_terms(**terms_kw)
    return compute_securities_entitlements(
        terms, _positions_doc(_pos(qty)), now=NOW)


def test_forward_split_10_for_1():
    doc = _ent("12500")
    assert doc["schema"] == SEC_ENT_SCHEMA
    e = doc["entitlements"][0]
    assert e["status"] == "ENTITLED"
    assert e["delivered"] == {"isin": SRC_ISIN, "quantity": "12500"}
    assert e["receivable"] == {"isin": DST_ISIN, "quantity": "125000"}
    assert e["raw_quantity"] == "125000"
    assert e["fraction"]["disposition"] == "STAN"
    assert e["fraction"]["amount"] == "0"
    assert e["fraction"]["cash_in_lieu"] is None
    assert e["basis"]["position_eligibility"] == \
        "POSITION_AT_RECORD_DATE"


def test_reverse_split_1_for_10():
    doc = _ent("12500", caev="SPLR", new="1", old="10")
    e = doc["entitlements"][0]
    assert e["status"] == "ENTITLED"
    assert e["receivable"]["quantity"] == "1250"


def test_fraction_rddn_floors():
    doc = _ent("12505", disf="RDDN")          # 125050 exacto -> no frac
    assert doc["entitlements"][0]["status"] == "ENTITLED"
    doc = _ent("1250.5", disf="RDDN")         # 12505 exacto
    assert doc["entitlements"][0]["status"] == "ENTITLED"
    doc = _ent("125", disf="RDDN", new="1", old="10")   # 12.5 -> 12
    e = doc["entitlements"][0]
    assert e["status"] == "ENTITLED"
    assert e["receivable"]["quantity"] == "12"
    assert e["fraction"]["amount"] == "0.5"


def test_fraction_rdup_ceils():
    doc = _ent("125", disf="RDUP", new="1", old="10")
    assert doc["entitlements"][0]["receivable"]["quantity"] == "13"


def test_fraction_stan_rounds():
    doc = _ent("125", disf="STAN", new="1", old="10")
    assert doc["entitlements"][0]["receivable"]["quantity"] == "13"
    doc = _ent("124", disf="STAN", new="1", old="10")
    assert doc["entitlements"][0]["receivable"]["quantity"] == "12"


def test_fraction_unknown_disf_with_real_fraction():
    doc = _ent("125", disf="UKNW", new="1", old="10")
    e = doc["entitlements"][0]
    assert e["status"] == "INDETERMINATE"
    assert "FRACTION_DISPOSITION_UNKNOWN" in e["reasons"]
    doc = _ent("125", disf=None, new="1", old="10")
    assert doc["entitlements"][0]["status"] == "INDETERMINATE"


def test_integral_result_ignores_missing_disf():
    doc = _ent("12500", disf=None)
    e = doc["entitlements"][0]
    assert e["status"] == "ENTITLED"
    assert e["receivable"]["quantity"] == "125000"


def test_disf_secu_exact_fraction():
    doc = _ent("125", disf="SECU", new="1", old="10")
    e = doc["entitlements"][0]
    assert e["status"] == "ENTITLED"
    assert e["receivable"]["quantity"] == "12.5"
    assert e["fraction"]["amount"] == "0.5"


def test_cinl_requires_price():
    doc = _ent("125", disf="CINL", new="1", old="10")
    e = doc["entitlements"][0]
    assert e["status"] == "INDETERMINATE"
    assert "CASH_IN_LIEU_PRICE_MISSING" in e["reasons"]


def test_cinl_with_price_emits_cash_leg():
    terms = _proven_terms(disf="CINL", new="1", old="10")
    terms["cash_in_lieu_price"] = {"normalized": "1.5",
                                   "currency": "EUR"}
    doc = compute_securities_entitlements(
        terms, _positions_doc(_pos("125")), now=NOW)
    e = doc["entitlements"][0]
    assert e["status"] == "ENTITLED"
    assert e["receivable"]["quantity"] == "12"
    assert e["fraction"]["cash_in_lieu"]["normalized"] == "0.75"
    assert e["fraction"]["cash_in_lieu"]["currency"] == "EUR"


def test_snapshot_not_at_record_is_indeterminate():
    terms = _proven_terms()
    doc = compute_securities_entitlements(
        terms, _positions_doc(_pos("12500"), as_of="2026-06-08"),
        now=NOW)
    e = doc["entitlements"][0]
    assert e["status"] == "INDETERMINATE"
    assert "POSITION_SNAPSHOT_BEFORE_RECORD" in e["reasons"]
    doc = compute_securities_entitlements(
        terms, _positions_doc(_pos("12500"), as_of="2026-06-10"),
        now=NOW)
    assert "POSITION_SNAPSHOT_AFTER_RECORD" in \
        doc["entitlements"][0]["reasons"]


def test_zero_and_foreign_positions():
    doc = compute_securities_entitlements(
        _proven_terms(),
        _positions_doc(_pos("0"), _pos("10", isin="ES9999999999")),
        now=NOW)
    assert doc["entitlements"][0]["status"] == "NOT_ENTITLED"
    e1 = doc["entitlements"][1]
    assert e1["status"] == "INDETERMINATE"
    assert "NO_POSITION_FOR_INSTRUMENT" in e1["reasons"]


def test_terms_not_proven_is_unsupported_verbatim():
    facts = _splf_facts()
    facts["facts"] = [f for f in facts["facts"]
                      if f["source_qualifier"] != "RDTE"]
    terms = build_event_terms(project_ca_message(facts, now=NOW),
                              now=NOW)
    doc = compute_securities_entitlements(
        terms, _positions_doc(_pos("12500")), now=NOW)
    e = doc["entitlements"][0]
    assert e["status"] == "UNSUPPORTED"
    assert "TERMS_INCOMPLETE" in e["reasons"]


def test_no_floats_anywhere():
    doc = _ent("12500")
    def _walk(o):
        if isinstance(o, float):
            return True
        if isinstance(o, dict):
            return any(_walk(v) for v in o.values())
        if isinstance(o, list):
            return any(_walk(v) for v in o)
        return False
    assert not _walk(doc)


# ----------------------------------------------------------- impact

def test_impact_delivery_and_receipt():
    terms = _proven_terms()
    positions = _positions_doc(_pos("12500"))
    ent = compute_securities_entitlements(terms, positions, now=NOW)
    doc = compute_security_impact(ent, positions, now=NOW)
    assert doc["schema"] == IMPACT_SCHEMA
    types = {i["impact_type"]: i for i in doc["impacts"]}
    delivery = types["SECURITY_DELIVERY"]
    assert delivery["status"] == "PROJECTED"
    assert delivery["quantity_delta"] == "-12500"
    receipt = types["SECURITY_RECEIPT"]
    assert receipt["target_isin"] == DST_ISIN
    assert receipt["quantity_delta"] == "125000"
    assert doc["source_positions_logical_sha256"]


def test_impact_missing_cell_indeterminate():
    terms = _proven_terms()
    positions = _positions_doc(_pos("12500"))
    ent = compute_securities_entitlements(terms, positions, now=NOW)
    ent["entitlements"] = []
    doc = compute_security_impact(ent, positions, now=NOW)
    assert doc["impacts"][0]["status"] == "INDETERMINATE"
    assert "ENTITLEMENT_CELL_MISSING" in doc["impacts"][0]["reasons"]


def test_impact_propagates_unsupported_verbatim():
    facts = _splf_facts(camv="VOLU")
    terms = build_event_terms(project_ca_message(facts, now=NOW),
                              now=NOW)
    positions = _positions_doc(_pos("12500"))
    ent = compute_securities_entitlements(terms, positions, now=NOW)
    doc = compute_security_impact(ent, positions, now=NOW)
    assert doc["impacts"][0]["status"] == "UNSUPPORTED"


# --------------------------------------------------- e2e projection

def test_e2e_split_projects_positions():
    terms = _proven_terms()
    positions = _positions_doc(_pos("12500"))
    ent = compute_securities_entitlements(terms, positions, now=NOW)
    impact = compute_security_impact(ent, positions, now=NOW)
    proj = project_positions(positions, impact, now=NOW)
    by_isin = {l["isin"]: l for l in proj["lines"]}
    old_line = by_isin[SRC_ISIN]
    assert old_line["status"] == "PROJECTED"
    assert old_line["projected_quantity"] == "0"
    assert old_line["delta_quantity"] == "-12500"
    new_line = by_isin[DST_ISIN]
    assert new_line["status"] == "PROJECTED"
    assert new_line["pre_quantity"] == "0"
    assert new_line["projected_quantity"] == "125000"
    assert "NEW_INSTRUMENT_RECEIPT" in new_line["reasons"]


# ------------------------------------------------------------ jvm e2e

@requires_jar
def test_e2e_real_mt564_splf_adapter():
    fin = (RES / "mt564-splf.fin").read_text(encoding="utf-8")
    facts_doc, code = swift_mt.parse_mt(fin)
    assert code == 0
    msg = project_ca_message(facts_doc, now=NOW)
    assert msg["status"] == "OK"
    assert msg["event_type"] == "SPLIT"
    terms = build_event_terms(msg, now=NOW)
    assert terms["terms_status"] == "PROVEN", terms["reasons"]
    assert terms["ratio"] == {"new": "10", "old": "1"}
    assert terms["source_isin"] == SRC_ISIN
    assert terms["target_isin"] == DST_ISIN
    positions = _positions_doc(_pos("12500"))
    ent = compute_securities_entitlements(terms, positions, now=NOW)
    assert ent["entitlements"][0]["status"] == "ENTITLED"
    assert ent["entitlements"][0]["receivable"]["quantity"] == "125000"
    impact = compute_security_impact(ent, positions, now=NOW)
    proj = project_positions(positions, impact, now=NOW)
    by_isin = {l["isin"]: l for l in proj["lines"]}
    assert by_isin[DST_ISIN]["projected_quantity"] == "125000"


@requires_jar
def test_e2e_real_mt566_secmove_matches_expected():
    """El MT566 real de split debe confirmar lo proyectado por el
    MT564: DEBT viejo 12500 + CRED nuevo 125000."""
    facts_564, code = swift_mt.parse_mt(
        (RES / "mt564-splf.fin").read_text(encoding="utf-8"))
    assert code == 0
    facts_566, code = swift_mt.parse_mt(
        (RES / "mt566-secmove.fin").read_text(encoding="utf-8"))
    assert code == 0
    moves = [f for f in facts_566["facts"]
             if f.get("sequence") and "SECMOVE" in f["sequence"]]
    labels = {(f.get("source_tag"), f.get("source_qualifier"),
               (f.get("field_path") or "").rsplit(".", 1)[-1])
              for f in moves}
    isins = {f["value"] for f in facts_566["facts"]
             if f.get("source_tag") == "35B"
             and (f.get("field_path") or "").endswith(".isin")}
    assert SRC_ISIN in isins and DST_ISIN in isins
    crdb = {f["value"] for f in facts_566["facts"]
            if f.get("source_qualifier") == "CRDB"}
    assert {"DEBT", "CRED"} <= crdb
    psta = {(f["value"] or "").rstrip(",")
            for f in facts_566["facts"]
            if f.get("source_qualifier") == "PSTA"}
    assert "12500" in psta and "125000" in psta
    json.dumps(moves)  # facts serializables


# ----------------------------------------- e2e canon-bound -> recon

def _split_canon():
    return {
        "canon_version": "CA_ES_OPERATIONAL_CANON_V1",
        "events": [{
            "canonical_event_id": "EV-SPLIT-1",
            "event_type": "SPLIT",
            "affected_instrument": {"isin": SRC_ISIN},
            "facts": [{
                "field_path": "date.record_date",
                "value": "2026-06-09",
                "revision_id": "r1",
                "assertion_id": "as-1",
                "evidence_locator": "doc:rdte",
            }],
            "conflicts": [],
        }],
    }


def _candidate_566():
    facts_566, code = swift_mt.parse_mt(
        (RES / "mt566-secmove.fin").read_text(encoding="utf-8"))
    assert code == 0
    return security_movement_candidate(
        facts_566, _split_canon(), now=NOW)


@requires_jar
def test_e2e_canon_bound_split_reconciles_match():
    """Cadena completa: MT564 SPLF -> terms CANON_BOUND -> entitlement
    -> impact -> candidates MT566 -> recon MATCH + sin casos."""
    facts_564, code = swift_mt.parse_mt(
        (RES / "mt564-splf.fin").read_text(encoding="utf-8"))
    assert code == 0
    msg = project_ca_message(facts_564, now=NOW)
    binding = bind_event(msg, _split_canon(), now=NOW)
    assert binding["binding_status"] == "BOUND"
    assert binding["canonical_event_id"] == "EV-SPLIT-1"

    terms = build_event_terms(msg, binding, now=NOW)
    assert terms["terms_status"] == "PROVEN"
    assert terms["event_basis"] == "CANON_BOUND"
    assert terms["canonical_event_id"] == "EV-SPLIT-1"

    positions = _positions_doc(_pos("12500", account="A001"))
    ent = compute_securities_entitlements(terms, positions, now=NOW)
    assert ent["entitlements"][0]["status"] == "ENTITLED"

    impact = compute_security_impact(ent, positions, now=NOW)
    candidate = _candidate_566()
    assert candidate["binding_status"] == "BOUND"
    assert candidate["canonical_event_id"] == "EV-SPLIT-1"
    assert candidate["status"] == "PROJECTABLE"
    moves = {(m["direction"], m["isin"], m["quantity"])
             for m in candidate["movements"]}
    assert ("DELIVERY", SRC_ISIN, "12500") in moves
    assert ("RECEIPT", DST_ISIN, "125000") in moves

    recon = reconcile_security_movements(
        impact, [candidate], now=NOW)
    assert recon["expected_set_authoritative"] is True
    assert recon["summary"]["match"] == 2
    by_dir = {(i["direction"], i["isin"]): i
              for i in recon["items"]}
    assert by_dir[("DELIVERY", SRC_ISIN)]["status"] == "MATCH"
    assert by_dir[("RECEIPT", DST_ISIN)]["status"] == "MATCH"

    cases = build_cases_doc(recon, now=NOW)
    assert cases["cases"] == []


@requires_jar
def test_e2e_quantity_mismatch_opens_case():
    facts_564, _ = swift_mt.parse_mt(
        (RES / "mt564-splf.fin").read_text(encoding="utf-8"))
    msg = project_ca_message(facts_564, now=NOW)
    binding = bind_event(msg, _split_canon(), now=NOW)
    terms = build_event_terms(msg, binding, now=NOW)
    positions = _positions_doc(_pos("12500", account="A001"))
    ent = compute_securities_entitlements(terms, positions, now=NOW)
    impact = compute_security_impact(ent, positions, now=NOW)
    candidate = _candidate_566()
    # actual distinto del esperado -> QUANTITY_MISMATCH + caso
    for m in candidate["movements"]:
        if m["direction"] == "RECEIPT":
            m["quantity"] = "124000"
    recon = reconcile_security_movements(impact, [candidate], now=NOW)
    by_dir = {(i["direction"], i["isin"]): i
              for i in recon["items"]}
    mism = by_dir[("RECEIPT", DST_ISIN)]
    assert mism["status"] == "QUANTITY_MISMATCH"
    assert mism["delta"] == "-1000"
    cases = build_cases_doc(recon, now=NOW)
    assert len(cases["cases"]) == 1
    case = cases["cases"][0]
    assert case["factual_status"] == "QUANTITY_MISMATCH"
    assert case["expected_quantity"] == "125000"
    assert case["actual_quantity"] == "124000"
    assert case["delta"] == "-1000"
    assert case["direction"] == "RECEIPT"
