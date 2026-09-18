"""P8.3 — CAPITAL_INCREASE parcial: solo BONU (ampliacion liberada)
demostrado; CAPI/CAPG/PRIO quedan UNSUPPORTED.
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
from tests.unit.test_p82_rights import _rhdi_facts, _terms

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "adapters" / "iso-adapter-jvm" / "src" / "test" / "resources"
JAR = swift_mt.default_adapter_jar()

requires_jar = pytest.mark.skipif(
    not JAR.is_file(), reason="iso-adapter.jar no construido")

ISIN = "ES0105857033"


def _bonu_facts(caev="BONU", camv="MAND", **kw):
    return _rhdi_facts(caev=caev, camv=camv, rdte="20260805",
                       disf="RDDN", new="1", old="10",
                       src=ISIN, dst=ISIN, **kw)


def test_bonu_maps_to_capital_increase():
    msg = project_ca_message(_bonu_facts(), now=NOW)
    assert msg["event_type"] == "CAPITAL_INCREASE"
    assert msg["mechanism"] == "BONUS_ISSUE"


def test_capi_capg_prio_unsupported():
    for caev in ("CAPI", "CAPG", "PRIO"):
        msg = project_ca_message(_bonu_facts(caev=caev), now=NOW)
        assert msg["status"] == "UNSUPPORTED_CA_EVENT"


def test_bonu_terms_proven():
    t = _terms(_bonu_facts())
    assert t["terms_status"] == "PROVEN"
    assert t["event_type"] == "CAPITAL_INCREASE"
    assert t["mechanism"] == "BONUS_ISSUE"
    assert t["target_isin"] == ISIN


def test_bonu_entitlement_and_projection():
    terms = _terms(_bonu_facts())
    positions = _positions_doc(
        _pos("125000", isin=ISIN), as_of="2026-08-05")
    ent = compute_securities_entitlements(terms, positions, now=NOW)
    e = ent["entitlements"][0]
    assert e["status"] == "ENTITLED"
    assert e["delivered"] is None
    assert e["receivable"]["quantity"] == "12500"
    assert e["evidence"]["rule"] == "BONUS_ISSUE_POSITION_X_NEWO"
    impact = compute_security_impact(ent, positions, now=NOW)
    assert impact["rule_id"] == "BONUS_ISSUE_POSITION_X_NEWO"
    proj = project_positions(positions, impact, now=NOW)
    assert proj["lines"][0]["projected_quantity"] == "137500"


@requires_jar
def test_e2e_bonu_real_fixture():
    facts, code = swift_mt.parse_mt(
        (RES / "mt564-bonu.fin").read_text(encoding="utf-8"))
    assert code == 0
    msg = project_ca_message(facts, now=NOW)
    assert msg["event_type"] == "CAPITAL_INCREASE"
    terms = build_event_terms(msg, now=NOW)
    assert terms["terms_status"] == "PROVEN", terms["reasons"]
    positions = _positions_doc(
        _pos("125000", isin=ISIN, account="A001"), as_of="2026-08-05")
    ent = compute_securities_entitlements(terms, positions, now=NOW)
    assert ent["entitlements"][0]["status"] == "ENTITLED"
    assert ent["entitlements"][0]["receivable"]["quantity"] == "12500"
