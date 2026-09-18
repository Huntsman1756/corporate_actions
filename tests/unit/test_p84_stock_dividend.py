"""P8.4 — STOCK_DIVIDEND (DVSE MAND): distribucion obligatoria de
valores, misma forma receipt-only que RHDI pero regla propia.

Cubre: mapping DVSE + mechanism, terms PROVEN/UNSUPPORTED por camv,
entitlement receipt-only con DISF, target==source (bonus mismo
ISIN), impact SECURITY_UNCHANGED+RECEIPT, projection, e2e JVM.
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
from tests.unit.test_p82_rights import _rhdi_facts, _terms
from tests.unit.test_p81_split import (
    NOW,
    _fact,
    _facts_doc,
    _pos,
    _positions_doc,
)

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "adapters" / "iso-adapter-jvm" / "src" / "test" / "resources"
JAR = swift_mt.default_adapter_jar()

requires_jar = pytest.mark.skipif(
    not JAR.is_file(), reason="iso-adapter.jar no construido")

ISIN = "ES0105857033"


def _dvse_facts(camv="MAND", dst=ISIN, **kw):
    return _rhdi_facts(caev="DVSE", camv=camv, rdte="20260708",
                       disf="RDDN", new="1", old="20",
                       src=ISIN, dst=dst, **kw)


def test_dvse_maps_to_stock_dividend():
    msg = project_ca_message(_dvse_facts(), now=NOW)
    assert msg["status"] == "OK"
    assert msg["event_type"] == "STOCK_DIVIDEND"
    assert msg["mechanism"] == "STOCK_DIVIDEND"


def test_dvse_chos_is_unsupported():
    t = _terms(_dvse_facts(camv="CHOS"))
    assert t["terms_status"] == "UNSUPPORTED"
    assert "NON_ADMISSIBLE_CAMV:CHOS" in t["reasons"]


def test_dvse_terms_proven_same_isin():
    t = _terms(_dvse_facts())
    assert t["terms_status"] == "PROVEN"
    assert t["mechanism"] == "STOCK_DIVIDEND"
    assert t["target_isin"] == ISIN  # bonus en la misma accion
    assert t["ratio"] == {"new": "1", "old": "20"}


def test_dvse_entitlement_receipt_only():
    terms = _terms(_dvse_facts())
    positions = _positions_doc(
        _pos("125000", isin=ISIN), as_of="2026-07-08")
    doc = compute_securities_entitlements(terms, positions, now=NOW)
    e = doc["entitlements"][0]
    assert e["status"] == "ENTITLED"
    assert e["delivered"] is None
    assert e["receivable"] == {"isin": ISIN, "quantity": "6250"}
    assert e["evidence"]["rule"] == "STOCK_DIVIDEND_POSITION_X_NEWO"


def test_dvse_fraction_floors():
    terms = _terms(_dvse_facts())
    positions = _positions_doc(
        _pos("125", isin=ISIN), as_of="2026-07-08")
    doc = compute_securities_entitlements(terms, positions, now=NOW)
    e = doc["entitlements"][0]
    assert e["receivable"]["quantity"] == "6"    # 125/20 = 6.25 -> 6
    assert e["fraction"]["amount"] == "0.25"


def test_dvse_impact_and_projection_same_isin():
    terms = _terms(_dvse_facts())
    positions = _positions_doc(
        _pos("125000", isin=ISIN), as_of="2026-07-08")
    ent = compute_securities_entitlements(terms, positions, now=NOW)
    impact = compute_security_impact(ent, positions, now=NOW)
    assert impact["rule_id"] == "STOCK_DIVIDEND_POSITION_X_NEWO"
    types = {i["impact_type"] for i in impact["impacts"]}
    assert types == {"SECURITY_UNCHANGED", "SECURITY_RECEIPT"}
    proj = project_positions(positions, impact, now=NOW)
    line = proj["lines"][0]
    assert line["isin"] == ISIN
    assert line["status"] == "PROJECTED"
    assert line["delta_quantity"] == "6250"
    assert line["projected_quantity"] == "131250"


@requires_jar
def test_e2e_dvse_real_fixture():
    facts, code = swift_mt.parse_mt(
        (RES / "mt564-dvse.fin").read_text(encoding="utf-8"))
    assert code == 0
    msg = project_ca_message(facts, now=NOW)
    assert msg["event_type"] == "STOCK_DIVIDEND"
    assert msg["mechanism"] == "STOCK_DIVIDEND"
    terms = build_event_terms(msg, now=NOW)
    assert terms["terms_status"] == "PROVEN", terms["reasons"]
    assert terms["target_isin"] == ISIN
    positions = _positions_doc(
        _pos("125000", isin=ISIN, account="A001"), as_of="2026-07-08")
    ent = compute_securities_entitlements(terms, positions, now=NOW)
    assert ent["entitlements"][0]["status"] == "ENTITLED"
    assert ent["entitlements"][0]["receivable"]["quantity"] == "6250"
    impact = compute_security_impact(ent, positions, now=NOW)
    proj = project_positions(positions, impact, now=NOW)
    assert proj["lines"][0]["projected_quantity"] == "131250"
