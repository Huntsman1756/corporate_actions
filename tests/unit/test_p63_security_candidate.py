"""P6.3 — CA_ES_SWIFT_SECURITY_MOVEMENT_CANDIDATE_V1.

Un candidato por SECMOVE; agrupacion por ventanas de tag index
ancladas en 22H; whitelist CRDB CRED/DEBT; cantidad solo 36B::PSTA
UNIT; binding BOUND obligatorio; nunca se combinan movimientos.
"""

import copy
import json
from pathlib import Path

import pytest

from ca_es.swift_mt import default_adapter_jar, parse_mt
from ca_es.swift_securities import (
    CANDIDATE_SCHEMA,
    INDETERMINATE,
    PROJECTABLE,
    UNSUPPORTED,
    security_movement_candidate,
)

NOW = "2026-09-17T00:00:00Z"
SHA = "aa" * 32
OLD_ISIN = "ES0105857009"
NEW_ISIN = "ES0105857033"
EID = "E-SPLIT"

REPO = Path(__file__).resolve().parents[2]
FIXTURE_FIN = (
    REPO / "adapters" / "iso-adapter-jvm" / "src" / "test"
    / "resources" / "mt566-secmove.fin"
)


def _fact(tag, qual, value, seq, occ=0, loc=0, suffix="value"):
    path = f"MT566.{seq.replace('/', '.')}.{tag}"
    if qual:
        path += f":{qual}"
    if occ:
        path += f"[{occ}]"
    return {
        "message_identifier": "MT566",
        "field_path": f"{path}.{suffix}",
        "value": value,
        "source_tag": tag,
        "source_qualifier": qual,
        "sequence": seq,
        "occurrence": occ,
        "evidence_locator": f"block4.tag[{loc}]",
        "input_sha256": SHA,
    }


def _genl_facts(caev="SPLF"):
    return [
        _fact("20C", "SEME", "REFSEME005", "GENL", loc=1,
              suffix="reference"),
        _fact("20C", "CORP", "RDG-SPLIT-2026", "GENL", loc=2,
              suffix="reference"),
        _fact("23G", None, "NEWM", "GENL", loc=3, suffix="function"),
        _fact("22F", "CAEV", caev, "GENL", loc=4, suffix="indicator"),
        _fact("22F", "CAMV", "MAND", "GENL", loc=5, suffix="indicator"),
    ]


def _usecu_facts(account="A001", isin=OLD_ISIN, loc=10):
    facts = [
        _fact("97A", "SAFE", account, "USECU", loc=loc,
              suffix="account number"),
    ]
    if isin is not None:
        facts.append(
            _fact("35B", "ISIN", isin, "USECU", loc=loc + 1,
                  suffix="isin"))
    return facts


def _secmove_facts(loc, direction, isin, qty, post="20260609",
                   qty_type="UNIT", dir_qual="CRDB"):
    facts = [
        _fact("22H", dir_qual, direction, "CACONF/SECMOVE", loc=loc,
              suffix="indicator"),
        _fact("35B", "ISIN", isin, "CACONF/SECMOVE", loc=loc + 1,
              suffix="isin"),
        _fact("36B", "PSTA", qty_type, "CACONF/SECMOVE", loc=loc + 2,
              suffix="quantity type code"),
        _fact("36B", "PSTA", qty, "CACONF/SECMOVE", occ=0, loc=loc + 2,
              suffix="quantity"),
        _fact("98A", "POST", post, "CACONF/SECMOVE", loc=loc + 3,
              suffix="date"),
    ]
    return facts


def _facts_doc(facts, mt="MT566"):
    return {
        "schema_version": "CA_ES_SWIFT_MT_FACTS_V1",
        "generated_at": NOW,
        "message_identifier": mt,
        "input_sha256": SHA,
        "parse_status": "OK",
        "facts": list(facts),
    }


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


def _two_secmove_doc():
    facts = (
        _genl_facts()
        + _usecu_facts()
        + [
            _fact("13A", "CAON", "001", "CACONF", loc=14,
                  suffix="number id"),
            _fact("22F", "CAOP", "SECU", "CACONF", loc=15,
                  suffix="indicator"),
        ]
        + _secmove_facts(16, "DEBT", OLD_ISIN, "12500,")
        + _secmove_facts(23, "CRED", NEW_ISIN, "125000,")
    )
    return _facts_doc(facts)


def test_two_secmoves_project_independently():
    doc = security_movement_candidate(_two_secmove_doc(), _canon(),
                                      now=NOW)
    assert doc["schema"] == CANDIDATE_SCHEMA
    assert doc["status"] == PROJECTABLE
    assert doc["binding_status"] == "BOUND"
    assert doc["canonical_event_id"] == EID
    assert doc["event_type"] == "SPLIT"
    assert doc["caon"] == "001"
    assert doc["caop"] == "SECU"

    debt, cred = doc["movements"]
    assert debt["direction"] == "DELIVERY"
    assert debt["isin"] == OLD_ISIN
    assert debt["quantity"] == "12500"
    assert debt["quantity_type"] == "UNIT"
    assert debt["posting_date"] == "2026-06-09"
    assert debt["status"] == PROJECTABLE
    assert debt["account_id"] == "A001"
    assert debt["movement_id"].endswith("-SECMOVE0")

    assert cred["direction"] == "RECEIPT"
    assert cred["isin"] == NEW_ISIN
    assert cred["quantity"] == "125000"
    assert cred["status"] == PROJECTABLE


def test_unknown_crdb_code_is_unsupported():
    facts = (_genl_facts() + _usecu_facts()
             + _secmove_facts(16, "XXXX", OLD_ISIN, "100,"))
    doc = security_movement_candidate(_facts_doc(facts), _canon(),
                                      now=NOW)
    m = doc["movements"][0]
    assert m["status"] == UNSUPPORTED
    assert "UNSUPPORTED_DIRECTION_CODE" in m["reasons"]
    assert m["direction"] is None


def test_non_crdb_direction_qualifier_is_unsupported():
    facts = (_genl_facts() + _usecu_facts()
             + _secmove_facts(16, "RECE", OLD_ISIN, "100,",
                              dir_qual="REDE"))
    doc = security_movement_candidate(_facts_doc(facts), _canon(),
                                      now=NOW)
    m = doc["movements"][0]
    assert m["status"] == UNSUPPORTED
    assert "UNSUPPORTED_DIRECTION_QUALIFIER" in m["reasons"]


def test_non_unit_quantity_type_is_unsupported():
    facts = (_genl_facts() + _usecu_facts()
             + _secmove_facts(16, "CRED", OLD_ISIN, "100,",
                              qty_type="FAMT"))
    doc = security_movement_candidate(_facts_doc(facts), _canon(),
                                      now=NOW)
    m = doc["movements"][0]
    assert m["status"] == UNSUPPORTED
    assert "UNSUPPORTED_QUANTITY_TYPE" in m["reasons"]
    assert m["quantity_type"] == "FAMT"


def test_conflicting_psta_quantities():
    facts = (_genl_facts() + _usecu_facts()
             + _secmove_facts(16, "CRED", OLD_ISIN, "100,"))
    facts.append(
        _fact("36B", "PSTA", "200,", "CACONF/SECMOVE", occ=1, loc=19,
              suffix="quantity"))
    doc = security_movement_candidate(_facts_doc(facts), _canon(),
                                      now=NOW)
    m = doc["movements"][0]
    assert m["status"] == INDETERMINATE
    assert "CONFLICTING_QUANTITY" in m["reasons"]


def test_ambiguous_secmove_structure_fails_doc():
    # dos 22H, un solo 35B -> fieldset-22 repetido, no atribuible
    facts = (_genl_facts() + _usecu_facts()
             + _secmove_facts(16, "CRED", OLD_ISIN, "100,"))
    facts.append(
        _fact("22H", "REDE", "DELI", "CACONF/SECMOVE", occ=0, loc=21,
              suffix="indicator"))
    doc = security_movement_candidate(_facts_doc(facts), _canon(),
                                      now=NOW)
    assert doc["status"] == INDETERMINATE
    assert "AMBIGUOUS_SECMOVE_STRUCTURE" in doc["reasons"]
    assert doc["movements"] == []


def test_missing_and_conflicting_account():
    facts = (_genl_facts()
             + _secmove_facts(16, "CRED", OLD_ISIN, "100,"))
    doc = security_movement_candidate(_facts_doc(facts), _canon(),
                                      now=NOW)
    m = doc["movements"][0]
    assert "MISSING_ACCOUNT" in m["reasons"]
    assert m["status"] == INDETERMINATE

    facts2 = (_genl_facts()
              + _usecu_facts(account="A001")
              + [_fact("97A", "SAFE", "A002", "USECU", occ=1, loc=12,
                       suffix="account number")]
              + _secmove_facts(16, "CRED", OLD_ISIN, "100,"))
    doc2 = security_movement_candidate(_facts_doc(facts2), _canon(),
                                       now=NOW)
    assert "CONFLICTING_ACCOUNT" in doc2["movements"][0]["reasons"]


def test_missing_isin_in_window():
    facts = [
        *_genl_facts(), *_usecu_facts(),
        _fact("22H", "CRDB", "CRED", "CACONF/SECMOVE", loc=16,
              suffix="indicator"),
        _fact("36B", "PSTA", "100,", "CACONF/SECMOVE", loc=17,
              suffix="quantity"),
        _fact("36B", "PSTA", "UNIT", "CACONF/SECMOVE", loc=17,
              suffix="quantity type code"),
        _fact("98A", "POST", "20260609", "CACONF/SECMOVE", loc=18,
              suffix="date"),
    ]
    doc = security_movement_candidate(_facts_doc(facts), _canon(),
                                      now=NOW)
    assert "AMBIGUOUS_SECMOVE_STRUCTURE" in doc["reasons"]


def test_conflicting_isin_in_window():
    facts = (_genl_facts() + _usecu_facts()
             + _secmove_facts(16, "CRED", OLD_ISIN, "100,"))
    facts.append(
        _fact("35B", "ISIN", NEW_ISIN, "CACONF/SECMOVE", occ=1, loc=19,
              suffix="isin"))
    doc = security_movement_candidate(_facts_doc(facts), _canon(),
                                      now=NOW)
    assert "AMBIGUOUS_SECMOVE_STRUCTURE" in doc["reasons"]


def test_unbound_event_makes_movements_indeterminate():
    canon = _canon(event_type="CASH_DIVIDEND")
    doc = security_movement_candidate(_two_secmove_doc(), canon,
                                      now=NOW)
    assert doc["binding_status"] == "NO_MATCH"
    for m in doc["movements"]:
        assert m["status"] == INDETERMINATE
        assert "EVENT_NOT_BOUND" in m["reasons"]


def test_non_mt566_is_unsupported():
    doc = security_movement_candidate(
        _facts_doc(_genl_facts(), mt="MT564"), _canon(), now=NOW)
    assert doc["status"] == UNSUPPORTED
    assert doc["reasons"] == ["UNSUPPORTED_MESSAGE_TYPE"]


def test_no_secmove_blocks_is_indeterminate():
    doc = security_movement_candidate(
        _facts_doc(_genl_facts() + _usecu_facts()), _canon(), now=NOW)
    assert doc["status"] == INDETERMINATE
    assert "NO_SECMOVE_BLOCKS" in doc["reasons"]


def test_unsupported_caev_is_unsupported():
    doc = security_movement_candidate(
        _facts_doc(_genl_facts(caev="XXXX") + _usecu_facts()
                   + _secmove_facts(16, "CRED", OLD_ISIN, "100,")),
        _canon(), now=NOW)
    assert doc["status"] == UNSUPPORTED
    assert doc["reasons"] == ["UNSUPPORTED_CA_EVENT"]


def test_determinism_and_no_mutation():
    facts_doc = _two_secmove_doc()
    canon = _canon()
    snap = [copy.deepcopy(facts_doc), copy.deepcopy(canon)]
    a = security_movement_candidate(facts_doc, canon, now=NOW)
    b = security_movement_candidate(facts_doc, canon, now=NOW)
    assert a == b
    assert facts_doc == snap[0] and canon == snap[1]


requires_jar = pytest.mark.skipif(
    not default_adapter_jar().is_file(),
    reason="adapter jar no construido",
)


@requires_jar
def test_e2e_real_mt566_secmove_binds_and_projects():
    fin = FIXTURE_FIN.read_text(encoding="utf-8")
    facts_doc, code = parse_mt(fin)
    assert code == 0
    assert facts_doc["message_identifier"] == "MT566"

    doc = security_movement_candidate(facts_doc, _canon(), now="N")
    assert doc["status"] == PROJECTABLE
    assert doc["binding_status"] == "BOUND"
    assert doc["canonical_event_id"] == EID
    debt, cred = doc["movements"]
    assert (debt["direction"], debt["isin"], debt["quantity"]) == (
        "DELIVERY", OLD_ISIN, "12500")
    assert (cred["direction"], cred["isin"], cred["quantity"]) == (
        "RECEIPT", NEW_ISIN, "125000")
    # provenance apunta a tags reales del mensaje
    assert any(
        p["source_tag"] == "22H" for p in debt["provenance"])
    assert any(
        "block4.tag[" in (p["evidence_locator"] or "")
        for p in cred["provenance"])


@requires_jar
def test_e2e_malformed_mt566():
    bad = "{4:\n:16R:GENL\n:20C::SEME//X\n"
    facts_doc, code = parse_mt(bad)
    assert code == 2
    assert facts_doc["parse_status"] == "PARSE_ERROR"
