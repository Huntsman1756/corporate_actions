"""P8.2 — RIGHTS_ISSUE staged: RHDI (distribucion MAND) + EXRI
(ejercicio CHOS con eleccion explicita).

Cubre: mapping CAEV RHDI/EXRI + mechanism, subscription_price
(90B::PRPP), terms PROVEN/INCOMPLETE/UNSUPPORTED por camv, math de
derechos (receipt-only) y de ejercicio (delivery lapse/exercise +
receipt acciones + cash payable), PENDING_ELECTION y propagation,
impact items, y e2e JVM con los fixtures reales.
"""
import pytest

from ca_es import swift_mt
from ca_es.event_terms import (
    TERMS_SCHEMA,
    build_event_terms,
)
from ca_es.projected_positions import project_positions
from ca_es.securities_entitlement import (
    compute_securities_entitlements,
)
from ca_es.security_impact import compute_security_impact
from ca_es.swift_ca import project_ca_message
from tests.unit.test_p81_split import (
    NOW,
    SHA,
    _fact,
    _facts_doc,
    _pos,
    _positions_doc,
)
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "adapters" / "iso-adapter-jvm" / "src" / "test" / "resources"
JAR = swift_mt.default_adapter_jar()

requires_jar = pytest.mark.skipif(
    not JAR.is_file(), reason="iso-adapter.jar no construido")

SHARES_ISIN = "ES0105857033"
RIGHTS_ISIN = "ES0605857004"


# ---------------------------------------------------------- helpers

def _rhdi_facts(caev="RHDI", camv="MAND", rdte="20260615",
                disf="RDDN", new="1", old="10",
                src=SHARES_ISIN, dst=RIGHTS_ISIN,
                payd="20260616"):
    facts = [
        _fact("GENL", "20C", "SEME", "reference", "RHDI-1"),
        _fact("GENL", "23G", None, "function", "NEWM"),
        _fact("GENL", "22F", "CAEV", "indicator", caev),
        _fact("GENL", "25D", "PROC", "status code", "COMP"),
        _fact("USECU", "35B", "ISIN", "isin", src),
        _fact("USECU/CADETL", "98A", "RDTE", "date", rdte),
    ]
    if camv is not None:
        facts.append(_fact("GENL", "22F", "CAMV", "indicator", camv))
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


def _exri_facts(price="1,5", ccy="EUR", camv="CHOS", **kw):
    facts = _rhdi_facts(
        caev="EXRI", camv=camv, rdte="20260620", disf="STAN",
        src=RIGHTS_ISIN, dst=SHARES_ISIN, **kw)["facts"]
    if price is not None:
        facts += [
            _fact("USECU/CAOPTN/CASHMOVE", "90B", "PRPP",
                  "price", price),
            _fact("USECU/CAOPTN/CASHMOVE", "90B", "PRPP",
                  "currency code", ccy),
        ]
    return _facts_doc(*facts)


def _terms(facts, **kw):
    return build_event_terms(project_ca_message(facts, now=NOW),
                             now=NOW)


# ---------------------------------------------------- proyeccion

def test_rhdi_maps_to_rights_issue():
    msg = project_ca_message(_rhdi_facts(), now=NOW)
    assert msg["status"] == "OK"
    assert msg["event_type"] == "RIGHTS_ISSUE"
    assert msg["mechanism"] == "RIGHTS_DISTRIBUTION"


def test_exri_maps_to_exercise():
    msg = project_ca_message(_exri_facts(), now=NOW)
    assert msg["event_type"] == "RIGHTS_ISSUE"
    assert msg["mechanism"] == "RIGHTS_EXERCISE"


def test_rhts_prio_unmapped():
    for caev in ("RHTS", "PRIO"):
        msg = project_ca_message(_rhdi_facts(caev=caev), now=NOW)
        assert msg["status"] == "UNSUPPORTED_CA_EVENT"


def test_subscription_price_projected():
    msg = project_ca_message(_exri_facts(), now=NOW)
    price = msg["fields"]["subscription_price"]
    assert price["status"] == "PRESENT"
    assert price["value"] == {"normalized": "1.5", "currency": "EUR"}
    assert price["raw"] == "1,5"


def test_subscription_price_conflicting():
    facts = _exri_facts()["facts"] + [
        _fact("USECU/CAOPTN/CASHMOVE", "90B", "PRPP", "price",
              "2,0", occ=1),
        _fact("USECU/CAOPTN/CASHMOVE", "90B", "PRPP",
              "currency code", "EUR", occ=1),
    ]
    msg = project_ca_message(_facts_doc(*facts), now=NOW)
    assert msg["fields"]["subscription_price"]["status"] == \
        "CONFLICTING"


# ---------------------------------------------------- event_terms

def test_rhdi_terms_proven():
    t = _terms(_rhdi_facts())
    assert t["terms_status"] == "PROVEN"
    assert t["event_type"] == "RIGHTS_ISSUE"
    assert t["mechanism"] == "RIGHTS_DISTRIBUTION"
    assert t["basis_date"]["value"] == "2026-06-15"
    assert t["ratio"] == {"new": "1", "old": "10"}
    assert t["source_isin"] == SHARES_ISIN
    assert t["target_isin"] == RIGHTS_ISIN


def test_rhdi_chos_is_unsupported():
    t = _terms(_rhdi_facts(camv="CHOS"))
    assert t["terms_status"] == "UNSUPPORTED"
    assert any(r.startswith("NON_ADMISSIBLE_CAMV")
               for r in t["reasons"])


def test_exri_terms_proven_with_price():
    t = _terms(_exri_facts())
    assert t["terms_status"] == "PROVEN"
    assert t["mechanism"] == "RIGHTS_EXERCISE"
    assert t["subscription_price"] == {"normalized": "1.5",
                                       "currency": "EUR"}


def test_exri_without_price_incomplete():
    t = _terms(_exri_facts(price=None))
    assert t["terms_status"] == "INCOMPLETE"
    assert "MISSING_SUBSCRIPTION_PRICE" in t["reasons"]


def test_exri_mand_is_unsupported():
    t = _terms(_exri_facts(camv="MAND"))
    assert t["terms_status"] == "UNSUPPORTED"
    assert "NON_ADMISSIBLE_CAMV:MAND" in t["reasons"]


# ------------------------------------------------- distribucion

def test_rhdi_entitlement_receipt_only():
    terms = _terms(_rhdi_facts())
    doc = compute_securities_entitlements(
        terms, _positions_doc(
            _pos("125000", isin=SHARES_ISIN), as_of="2026-06-15"),
        now=NOW)
    e = doc["entitlements"][0]
    assert e["status"] == "ENTITLED"
    assert e["delivered"] is None                  # acciones intactas
    assert e["receivable"] == {"isin": RIGHTS_ISIN,
                              "quantity": "12500"}
    assert e["evidence"]["rule"] == "RIGHTS_DISTRIBUTION_POSITION_X_NEWO"


def test_rhdi_fraction_floors():
    terms = _terms(_rhdi_facts())  # DISF RDDN
    doc = compute_securities_entitlements(
        terms, _positions_doc(
            _pos("125", isin=SHARES_ISIN), as_of="2026-06-15"),
        now=NOW)
    e = doc["entitlements"][0]
    assert e["receivable"]["quantity"] == "12"
    assert e["fraction"]["amount"] == "0.5"


def test_rhdi_impact_receipt_only():
    terms = _terms(_rhdi_facts())
    positions = _positions_doc(
        _pos("125000", isin=SHARES_ISIN), as_of="2026-06-15")
    ent = compute_securities_entitlements(terms, positions, now=NOW)
    impact = compute_security_impact(ent, positions, now=NOW)
    types = {i["impact_type"]: i for i in impact["impacts"]}
    unchanged = types["SECURITY_UNCHANGED"]
    assert unchanged["quantity_delta"] == "0"
    item = types["SECURITY_RECEIPT"]
    assert item["target_isin"] == RIGHTS_ISIN
    assert item["quantity_delta"] == "12500"
    proj = project_positions(positions, impact, now=NOW)
    by_isin = {l["isin"]: l for l in proj["lines"]}
    assert by_isin[SHARES_ISIN]["projected_quantity"] == "125000"
    assert by_isin[RIGHTS_ISIN]["projected_quantity"] == "12500"
    assert "NEW_INSTRUMENT_RECEIPT" in \
        by_isin[RIGHTS_ISIN]["reasons"]


# ----------------------------------------------------- ejercicio

def _exri_setup(election=None, rights_qty="12500"):
    terms = _terms(_exri_facts())
    positions = _positions_doc(
        _pos(rights_qty, isin=RIGHTS_ISIN, account="A001"),
        as_of="2026-06-20")
    return terms, positions, election


def test_exri_pending_election():
    terms, positions, _ = _exri_setup()
    doc = compute_securities_entitlements(terms, positions, now=NOW)
    e = doc["entitlements"][0]
    assert e["status"] == "INDETERMINATE"
    assert "PENDING_ELECTION" in e["reasons"]


def test_exri_full_exercise():
    terms, positions, _ = _exri_setup()
    doc = compute_securities_entitlements(
        terms, positions, election={"A001": "12500"}, now=NOW)
    e = doc["entitlements"][0]
    assert e["status"] == "ENTITLED"
    assert e["delivered"] == {"isin": RIGHTS_ISIN,
                             "quantity": "12500",
                             "exercised": "12500", "lapsed": "0"}
    assert e["receivable"] == {"isin": SHARES_ISIN,
                              "quantity": "1250"}
    assert e["payable"]["normalized"] == "1875.0"
    assert e["payable"]["currency"] == "EUR"


def test_exri_partial_exercise_lapse():
    terms, positions, _ = _exri_setup()
    doc = compute_securities_entitlements(
        terms, positions, election={"A001": "10000"}, now=NOW)
    e = doc["entitlements"][0]
    assert e["status"] == "ENTITLED"
    assert e["delivered"]["exercised"] == "10000"
    assert e["delivered"]["lapsed"] == "2500"
    assert e["receivable"]["quantity"] == "1000"
    assert e["payable"]["normalized"] == "1500.0"


def test_exri_zero_election_lapses_all():
    terms, positions, _ = _exri_setup()
    doc = compute_securities_entitlements(
        terms, positions, election={"A001": "0"}, now=NOW)
    e = doc["entitlements"][0]
    assert e["status"] == "NOT_ENTITLED"
    assert "ZERO_ELECTION_LAPSE" in e["reasons"]


def test_exri_elected_exceeds_rights():
    terms, positions, _ = _exri_setup()
    doc = compute_securities_entitlements(
        terms, positions, election={"A001": "20000"}, now=NOW)
    e = doc["entitlements"][0]
    assert e["status"] == "INDETERMINATE"
    assert "ELECTED_EXCEEDS_RIGHTS" in e["reasons"]


def test_exri_fractional_election_indeterminate():
    terms, positions, _ = _exri_setup()
    doc = compute_securities_entitlements(
        terms, positions, election={"A001": "125.5"}, now=NOW)
    assert doc["entitlements"][0]["status"] == "INDETERMINATE"
    assert "NON_INTEGRAL_ELECTION" in \
        doc["entitlements"][0]["reasons"]


def test_exri_impact_three_items():
    terms, positions, _ = _exri_setup()
    ent = compute_securities_entitlements(
        terms, positions, election={"A001": "12500"}, now=NOW)
    impact = compute_security_impact(ent, positions, now=NOW)
    types = {i["impact_type"]: i for i in impact["impacts"]}
    assert types["SECURITY_DELIVERY"]["quantity_delta"] == "-12500"
    recv = types["SECURITY_RECEIPT"]
    assert recv["target_isin"] == SHARES_ISIN
    assert recv["quantity_delta"] == "1250"
    pay = types["CASH_PAYABLE"]
    assert pay["cash_amount"]["normalized"] == "1875.0"
    assert pay["currency"] == "EUR"
    assert impact["rule_id"] == \
        "RIGHTS_EXERCISE_ELECTED_X_NEWO_X_PRICE"


# ------------------------------------------------------- jvm e2e

@requires_jar
def test_e2e_rhdi_real_fixture():
    facts, code = swift_mt.parse_mt(
        (RES / "mt564-rhdi.fin").read_text(encoding="utf-8"))
    assert code == 0
    msg = project_ca_message(facts, now=NOW)
    assert msg["event_type"] == "RIGHTS_ISSUE"
    assert msg["mechanism"] == "RIGHTS_DISTRIBUTION"
    terms = build_event_terms(msg, now=NOW)
    assert terms["terms_status"] == "PROVEN", terms["reasons"]
    assert terms["target_isin"] == RIGHTS_ISIN
    positions = _positions_doc(
        _pos("125000", isin=SHARES_ISIN, account="A001"),
        as_of="2026-06-15")
    ent = compute_securities_entitlements(terms, positions, now=NOW)
    e = ent["entitlements"][0]
    assert e["status"] == "ENTITLED"
    assert e["receivable"]["quantity"] == "12500"


@requires_jar
def test_e2e_exri_real_fixture_chain():
    """RHDI entrega 12500 derechos -> EXRI ejerce todos -> 1250
    acciones + 1875 EUR payable."""
    facts, code = swift_mt.parse_mt(
        (RES / "mt564-exri.fin").read_text(encoding="utf-8"))
    assert code == 0
    msg = project_ca_message(facts, now=NOW)
    assert msg["mechanism"] == "RIGHTS_EXERCISE"
    terms = build_event_terms(msg, now=NOW)
    assert terms["terms_status"] == "PROVEN", terms["reasons"]
    assert terms["subscription_price"] == {"normalized": "1.5",
                                           "currency": "EUR"}
    positions = _positions_doc(
        _pos("12500", isin=RIGHTS_ISIN, account="A001"),
        as_of="2026-06-20")
    ent = compute_securities_entitlements(
        terms, positions, election={"A001": "12500"}, now=NOW)
    e = ent["entitlements"][0]
    assert e["status"] == "ENTITLED"
    assert e["receivable"]["quantity"] == "1250"
    assert e["payable"]["normalized"] == "1875.0"
    impact = compute_security_impact(ent, positions, now=NOW)
    proj = project_positions(positions, impact, now=NOW)
    by_isin = {l["isin"]: l for l in proj["lines"]}
    assert by_isin[RIGHTS_ISIN]["projected_quantity"] == "0"
    assert by_isin[SHARES_ISIN]["projected_quantity"] == "1250"
