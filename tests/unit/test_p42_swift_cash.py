"""P4.2 — MT566 -> cash movement candidate (CA_ES_SWIFT_CASH_CANDIDATE_V1).

Whitelist cerrada PSTA/NETO/GRSS -> UNKNOWN/NET/GROSS; nunca se
infiere la base. Solo PROJECTABLE emite movement V2.
"""

import json
from pathlib import Path

import pytest

from ca_es import swift_mt
from ca_es.entitlement_engine import compute_entitlements, load_positions
from ca_es.reconciliation import reconcile
from ca_es.surface import load_surface
from ca_es.swift_cash import CANDIDATE_SCHEMA, cash_candidate

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "adapters" / "iso-adapter-jvm" / "src" / "test" / "resources"
JAR = swift_mt.default_adapter_jar()
CANON_PATH = ROOT / "g3" / "input" / "canon.json"
POLICY = ROOT / "docs" / "sources" / "source-policy.json"
POSITIONS = ROOT / "p1" / "smoke" / "positions.json"

requires_jar = pytest.mark.skipif(
    not JAR.is_file(), reason="iso-adapter.jar no construido"
)

NOW = "2026-09-16T00:00:00Z"
SHA = "cd" * 32


def _fact(seq, tag, qual, label, value, occ=0):
    return {
        "message_identifier": "MT566",
        "field_path": f"MT566.{seq.replace('/', '.')}.{tag}"
                      + (f":{qual}" if qual else "") + f".{label}",
        "value": value,
        "source_tag": tag,
        "source_qualifier": qual,
        "sequence": seq,
        "occurrence": occ,
        "evidence_locator": "block4.tag[0].component[1]",
        "input_sha256": SHA,
    }


def _facts(*extra):
    base = [
        _fact("GENL", "20C", "CORP", "reference", "CORP-1"),
        _fact("GENL", "23G", None, "function", "NEWM"),
        _fact("GENL", "22F", "CAEV", "indicator", "DVCA"),
        _fact("USEQ", "97A", "SAFE", "account number", "A001"),
        _fact("USEQ", "35B", "ISIN", "isin", "ES0105448007"),
        _fact("USEQ/CACASH/CSMV", "98A", "VALU", "date", "20260710"),
    ]
    return {
        "schema_version": "CA_ES_SWIFT_MT_FACTS_V1",
        "generated_at": NOW,
        "message_identifier": "MT566",
        "input_sha256": SHA,
        "parse_status": "OK",
        "facts": base + list(extra),
    }


def _event(eid, isin=None, etype="CASH_DIVIDEND"):
    facts = []
    if isin:
        facts.append({
            "field_path": "instrument.isin", "value": isin,
            "revision_id": "r1", "assertion_id": "a1",
        })
    return {"canonical_event_id": eid, "event_type": etype,
            "affected_instrument": {"isin": isin},
            "facts": facts, "conflicts": []}


CANON = {"canon_version": "CA_ES_OPERATIONAL_CANON_V1",
         "events": [_event("E1", isin="ES0105448007")]}


def _psta(amount="1562,5", ccy="EUR", occ=0):
    return [
        _fact("USEQ/CACASH/CSMV", "19B", "PSTA", "currency code", ccy,
              occ=occ),
        _fact("USEQ/CACASH/CSMV", "19B", "PSTA", "amount", amount,
              occ=occ),
    ]


def test_psta_projectable_unknown_basis():
    doc = cash_candidate(_facts(*_psta()), CANON, now=NOW)
    assert doc["schema"] == CANDIDATE_SCHEMA
    assert doc["status"] == "PROJECTABLE"
    assert doc["amount_source_qualifier"] == "PSTA"
    assert doc["amount_basis"] == "UNKNOWN"
    assert doc["basis_reason"] == "UNKNOWN_AMOUNT_BASIS"
    m = doc["movement"]
    assert m["account_id"] == "A001"
    assert m["event_id"] == "E1"
    assert m["amount"] == "1562.5"
    assert m["currency"] == "EUR"
    assert m["amount_basis"] == "UNKNOWN"
    assert m["value_date"] == "2026-07-10"


def test_neto_net_basis():
    facts = _facts(
        _fact("USEQ/CACASH/CSMV", "19B", "NETO", "amount", "1294,06"),
        _fact("USEQ/CACASH/CSMV", "19B", "NETO", "currency code", "EUR"),
        # GRSS presente pero NETO tiene prioridad
        _fact("USEQ/CACASH/CSMV", "19B", "GRSS", "amount", "1562,5"),
        _fact("USEQ/CACASH/CSMV", "19B", "GRSS", "currency code", "EUR"),
    )
    doc = cash_candidate(facts, CANON, now=NOW)
    assert doc["amount_source_qualifier"] == "NETO"
    assert doc["movement"]["amount_basis"] == "NET"
    assert doc["movement"]["amount"] == "1294.06"


def test_grss_gross_basis():
    doc = cash_candidate(_facts(*[
        _fact("USEQ/CACASH/CSMV", "19B", "GRSS", "amount", "1562,5"),
        _fact("USEQ/CACASH/CSMV", "19B", "GRSS", "currency code", "EUR"),
    ]), CANON, now=NOW)
    assert doc["amount_basis"] == "GROSS"
    assert doc["basis_reason"] is None


def test_event_not_bound():
    canon = {"canon_version": "CA_ES_OPERATIONAL_CANON_V1",
             "events": [_event("E1", isin="ES9999999999")]}
    doc = cash_candidate(_facts(*_psta()), canon, now=NOW)
    assert doc["status"] == "INDETERMINATE"
    assert "EVENT_NOT_BOUND" in doc["reasons"]
    assert doc["movement"] is None


def test_missing_account():
    facts = _facts(*_psta())
    facts["facts"] = [
        f for f in facts["facts"] if f["source_tag"] != "97A"
    ]
    doc = cash_candidate(facts, CANON, now=NOW)
    assert doc["status"] == "INDETERMINATE"
    assert "MISSING_ACCOUNT" in doc["reasons"]


def test_missing_amount():
    doc = cash_candidate(_facts(), CANON, now=NOW)
    assert "MISSING_AMOUNT" in doc["reasons"]
    assert doc["movement"] is None


def test_multiple_cash_movements():
    doc = cash_candidate(
        _facts(*_psta(occ=0), *_psta(amount="10,0", occ=1)),
        CANON, now=NOW)
    assert doc["status"] == "INDETERMINATE"
    assert "MULTIPLE_CASH_MOVEMENTS" in doc["reasons"]


def test_conflicting_amount():
    doc = cash_candidate(
        _facts(
            _fact("SEQ/A", "19B", "PSTA", "amount", "100,0"),
            _fact("SEQ/B", "19B", "PSTA", "amount", "200,0"),
            _fact("SEQ/A", "19B", "PSTA", "currency code", "EUR"),
        ),
        CANON, now=NOW)
    assert "CONFLICTING_AMOUNT" in doc["reasons"]


def test_missing_currency():
    doc = cash_candidate(
        _facts(_fact("USEQ/CACASH/CSMV", "19B", "PSTA", "amount",
                     "100,0")),
        CANON, now=NOW)
    assert "MISSING_CURRENCY" in doc["reasons"]


def test_mt564_unsupported_not_cash_candidate():
    facts = _facts(*_psta())
    facts["message_identifier"] = "MT564"
    doc = cash_candidate(facts, CANON, now=NOW)
    assert doc["status"] == "UNSUPPORTED"
    assert doc["reasons"] == ["UNSUPPORTED_MESSAGE_TYPE"]
    assert doc["movement"] is None


def test_unsupported_caev():
    facts = _facts(*_psta())
    facts["facts"] = [
        f if f["source_qualifier"] != "CAEV" else
        {**f, "value": "TEND"} for f in facts["facts"]
    ]
    doc = cash_candidate(facts, CANON, now=NOW)
    assert doc["status"] == "UNSUPPORTED"


def test_deterministic():
    a = cash_candidate(_facts(*_psta()), CANON, now=NOW)
    b = cash_candidate(_facts(*_psta()), CANON, now=NOW)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


@requires_jar
def test_e2e_full_circle_mt566_to_recon_match():
    """MT566 FIN -> facts -> candidate PROJECTABLE GROSS -> movement
    V2 -> reconcile contra entitlement real -> MATCH."""
    fin = (RES / "mt566-san.fin").read_text(encoding="utf-8")
    facts_doc, code = swift_mt.parse_mt(fin)
    assert code == 0
    canon = json.loads(CANON_PATH.read_text(encoding="utf-8"))
    cand = cash_candidate(facts_doc, canon, now=NOW)
    assert cand["status"] == "PROJECTABLE"
    assert cand["amount_basis"] == "GROSS"

    positions = load_positions(POSITIONS)
    surface = load_surface(CANON_PATH, POLICY)
    ent = compute_entitlements(
        surface, cand["canonical_event_id"], positions)
    movements = {"schema": "CA_ES_CASH_MOVEMENTS_V2",
                 "movements": [cand["movement"]]}
    recon = reconcile(ent, movements)
    match = [
        i for i in recon["items"]
        if i["account_id"] == "A001" and i["status"] == "MATCH"
    ]
    assert match, recon["items"]
    assert match[0]["movement_ids"] == [cand["movement"]["movement_id"]]
