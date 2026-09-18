"""P8.5 — SCRIP_DIVIDEND (DVOP CHOS): eleccion CASH|SECU por cuenta.

Cubre: mapping DVOP + mechanism, terms exigiendo AMBAS piernas
demostrables, PENDING_ELECTION/INVALID_ELECTION, pierna SECU
(receipt-only + DISF) y CASH (receivable_cash), impact
CASH_RECEIVABLE, e2e JVM.
"""
from pathlib import Path

import pytest

from ca_es import swift_mt
from ca_es.event_terms import build_event_terms
from ca_es.projected_positions import project_positions
from ca_es.securities_entitlement import (
    compute_securities_entitlements,
)
from ca_es.security_impact import compute_security_impact
from ca_es.swift_ca import project_ca_message
from tests.unit.test_p81_split import (
    NOW,
    _fact,
    _facts_doc,
    _pos,
    _positions_doc,
)
from tests.unit.test_p82_rights import _terms

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "adapters" / "iso-adapter-jvm" / "src" / "test" / "resources"
JAR = swift_mt.default_adapter_jar()

requires_jar = pytest.mark.skipif(
    not JAR.is_file(), reason="iso-adapter.jar no construido")

ISIN = "ES0105857033"


def _dvop_facts(camv="CHOS", gross="0,15", ccy="EUR",
                new="1", old="50", disf="RDDN", dst=ISIN,
                rdte="20260715"):
    facts = [
        _fact("GENL", "20C", "SEME", "reference", "DVOP-1"),
        _fact("GENL", "23G", None, "function", "NEWM"),
        _fact("GENL", "22F", "CAEV", "indicator", "DVOP"),
        _fact("GENL", "25D", "PROC", "status code", "COMP"),
        _fact("USECU", "35B", "ISIN", "isin", ISIN),
        _fact("USECU/CADETL", "98A", "RDTE", "date", rdte),
    ]
    if camv is not None:
        facts.append(_fact("GENL", "22F", "CAMV", "indicator", camv))
    if gross is not None:
        facts += [
            _fact("USECU/CAOPTN/CASHMOVE", "92J", "GRSS",
                  "amount", gross),
            _fact("USECU/CAOPTN/CASHMOVE", "19B", "GRSS",
                  "currency code", ccy),
        ]
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
            "USECU/CAOPTN/SECMOVE", "35B", "ISIN", "isin", dst,
            occ=1))
    return _facts_doc(*facts)


def _setup(election, qty="125000"):
    terms = _terms(_dvop_facts())
    positions = _positions_doc(
        _pos(qty, isin=ISIN, account="A001"), as_of="2026-07-15")
    return compute_securities_entitlements(
        terms, positions, election=election, now=NOW)


def test_dvop_maps_to_scrip():
    msg = project_ca_message(_dvop_facts(), now=NOW)
    assert msg["event_type"] == "SCRIP_DIVIDEND"
    assert msg["mechanism"] == "SCRIP_DIVIDEND"


def test_scrip_terms_require_both_legs():
    t = _terms(_dvop_facts())
    assert t["terms_status"] == "PROVEN"
    assert t["gross_per_share"] == "0.15"
    assert t["currency"] == "EUR"
    assert t["ratio"] == {"new": "1", "old": "50"}

    t = _terms(_dvop_facts(gross=None))
    assert t["terms_status"] == "INCOMPLETE"
    assert "MISSING_GROSS_PER_SHARE" in t["reasons"]
    t = _terms(_dvop_facts(new=None))
    assert t["terms_status"] == "INCOMPLETE"
    assert "MISSING_RATIO" in t["reasons"]


def test_scrip_mand_camv_unsupported():
    t = _terms(_dvop_facts(camv="MAND"))
    assert t["terms_status"] == "UNSUPPORTED"
    assert "NON_ADMISSIBLE_CAMV:MAND" in t["reasons"]


def test_scrip_pending_and_invalid_election():
    e = _setup(None)["entitlements"][0]
    assert e["status"] == "INDETERMINATE"
    assert "PENDING_ELECTION" in e["reasons"]
    e = _setup({"A001": "OVER"})["entitlements"][0]
    assert e["status"] == "INDETERMINATE"
    assert any(r.startswith("INVALID_ELECTION") for r in e["reasons"])


def test_scrip_secu_leg():
    e = _setup({"A001": "SECU"})["entitlements"][0]
    assert e["status"] == "ENTITLED"
    assert e["elected_option"] == "SECU"
    assert e["delivered"] is None
    assert e["receivable"] == {"isin": ISIN, "quantity": "2500"}
    assert e["evidence"]["rule"] == "SCRIP_ELECTION_CASH_OR_SECU"


def test_scrip_cash_leg():
    e = _setup({"A001": "CASH"})["entitlements"][0]
    assert e["status"] == "ENTITLED"
    assert e["elected_option"] == "CASH"
    assert e["receivable"] is None
    assert e["receivable_cash"]["normalized"] == "18750.00"
    assert e["receivable_cash"]["currency"] == "EUR"


def test_scrip_mixed_accounts():
    terms = _terms(_dvop_facts())
    positions = _positions_doc(
        _pos("125000", isin=ISIN, account="A001"),
        _pos("50000", isin=ISIN, account="A002"),
        as_of="2026-07-15")
    doc = compute_securities_entitlements(
        terms, positions,
        election={"A001": "SECU", "A002": "CASH"}, now=NOW)
    e1, e2 = doc["entitlements"]
    assert e1["elected_option"] == "SECU"
    assert e1["receivable"]["quantity"] == "2500"
    assert e2["elected_option"] == "CASH"
    assert e2["receivable_cash"]["normalized"] == "7500.00"


def test_scrip_impact_by_leg():
    terms = _terms(_dvop_facts())
    positions = _positions_doc(
        _pos("125000", isin=ISIN, account="A001"), as_of="2026-07-15")
    ent = compute_securities_entitlements(
        terms, positions, election={"A001": "SECU"}, now=NOW)
    impact = compute_security_impact(ent, positions, now=NOW)
    types = {i["impact_type"] for i in impact["impacts"]}
    assert types == {"SECURITY_UNCHANGED", "SECURITY_RECEIPT"}
    assert impact["rule_id"] == "SCRIP_ELECTION_CASH_OR_SECU"

    ent = compute_securities_entitlements(
        terms, positions, election={"A001": "CASH"}, now=NOW)
    impact = compute_security_impact(ent, positions, now=NOW)
    types = {i["impact_type"]: i for i in impact["impacts"]}
    assert set(types) == {"SECURITY_UNCHANGED", "CASH_RECEIVABLE"}
    assert types["CASH_RECEIVABLE"]["cash_amount"]["normalized"] \
        == "18750.00"


@requires_jar
def test_e2e_dvop_real_fixture():
    facts, code = swift_mt.parse_mt(
        (RES / "mt564-dvop.fin").read_text(encoding="utf-8"))
    assert code == 0
    msg = project_ca_message(facts, now=NOW)
    assert msg["event_type"] == "SCRIP_DIVIDEND"
    terms = build_event_terms(msg, now=NOW)
    assert terms["terms_status"] == "PROVEN", terms["reasons"]
    assert terms["gross_per_share"] == "0.15"
    assert terms["ratio"] == {"new": "1", "old": "50"}
    positions = _positions_doc(
        _pos("125000", isin=ISIN, account="A001"),
        as_of="2026-07-15")
    ent = compute_securities_entitlements(
        terms, positions, election={"A001": "CASH"}, now=NOW)
    e = ent["entitlements"][0]
    assert e["status"] == "ENTITLED"
    assert e["receivable_cash"]["normalized"] == "18750.00"
    ent = compute_securities_entitlements(
        terms, positions, election={"A001": "SECU"}, now=NOW)
    assert ent["entitlements"][0]["receivable"]["quantity"] == "2500"
    impact = compute_security_impact(ent, positions, now=NOW)
    proj = project_positions(positions, impact, now=NOW)
    assert proj["lines"][0]["projected_quantity"] == "127500"
