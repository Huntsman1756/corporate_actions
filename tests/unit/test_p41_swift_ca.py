"""P4.1 — proyeccion semantica SWIFT + binding determinista a canon.

Cubre: DVCA->CASH_DIVIDEND, provenance end-to-end, BOUND/AMBIGUOUS/
NO_MATCH/INSUFFICIENT_IDENTITY, AGREES/DIFFERS/CANON_MISSING/
SWIFT_MISSING/CANON_CONFLICTING, UNSUPPORTED_CA_EVENT, determinismo.
"""

import json
from pathlib import Path

import pytest

from ca_es import swift_mt
from ca_es.swift_ca import (
    BINDING_SCHEMA,
    CA_MESSAGE_SCHEMA,
    bind_event,
    project_and_bind,
    project_ca_message,
)

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "adapters" / "iso-adapter-jvm" / "src" / "test" / "resources"
JAR = swift_mt.default_adapter_jar()
CANON = ROOT / "g3" / "input" / "canon.json"

requires_jar = pytest.mark.skipif(
    not JAR.is_file(), reason="iso-adapter.jar no construido"
)

NOW = "2026-09-16T00:00:00Z"
SHA = "ab" * 32


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
        "evidence_locator": f"block4.tag[0].component[1]",
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


def _dvca_facts(isin="ES0105448007", xdte="20260708", rdte="20260709",
                payd="20260710", grss="0,20", ccy="EUR",
                caev="DVCA"):
    return _facts_doc(
        _fact("GENL", "20C", "SEME", "reference", "S1"),
        _fact("GENL", "20C", "CORP", "reference", "CORP-1"),
        _fact("GENL", "23G", None, "function", "NEWM"),
        _fact("GENL", "22F", "CAEV", "indicator", caev),
        _fact("GENL", "25D", "PROC", "status code", "COMP"),
        _fact("USEQ", "35B", "ISIN", "isin", isin),
        _fact("USEQ/CADETL", "98A", "XDTE", "date", xdte),
        _fact("USEQ/CADETL", "98A", "RDTE", "date", rdte),
        _fact("USEQ/CADETL", "98A", "PAYD", "date", payd),
        _fact("USEQ/CACASH/CSMV", "92J", "GRSS", "amount", grss),
        _fact("USEQ/CACASH/CSMV", "19B", "GRSS", "currency code", ccy),
    )


def _event(eid, etype="CASH_DIVIDEND", isin=None, dates=None,
           gross=None, rev="r1"):
    facts = []
    if isin:
        facts.append({
            "field_path": "instrument.isin", "value": isin,
            "revision_id": rev, "assertion_id": f"as-{eid}-i",
            "evidence_locator": f"doc-{eid}:isin",
        })
    for path, val in (dates or {}).items():
        facts.append({
            "field_path": path, "value": val,
            "revision_id": rev, "assertion_id": f"as-{eid}-{path}",
            "evidence_locator": f"doc-{eid}:{path}",
        })
    if gross:
        facts.append({
            "field_path": "amount.gross_per_share",
            "value": {"__financial__": True, "normalized": gross,
                      "currency": "EUR", "scale": 3,
                      "raw_lexeme": gross},
            "revision_id": rev, "assertion_id": f"as-{eid}-g",
            "evidence_locator": f"doc-{eid}:gross",
        })
    return {
        "canonical_event_id": eid,
        "event_type": etype,
        "affected_instrument": {"isin": isin},
        "facts": facts,
        "conflicts": [],
    }


def _canon(*events):
    return {"canon_version": "CA_ES_OPERATIONAL_CANON_V1",
            "events": list(events)}


# ---------------------------------------------------------- projection

def test_dvca_projects_to_cash_dividend():
    msg = project_ca_message(_dvca_facts(), now=NOW)
    assert msg["schema"] == CA_MESSAGE_SCHEMA
    assert msg["status"] == "OK"
    assert msg["event_type"] == "CASH_DIVIDEND"
    assert msg["caev"] == "DVCA"
    f = msg["fields"]
    assert f["corporate_action_reference"]["value"] == "CORP-1"
    assert f["isin"]["value"] == "ES0105448007"
    assert f["ex_date"]["value"] == "2026-07-08"      # YYYYMMDD -> ISO
    assert f["ex_date"]["raw"] == "20260708"
    assert f["gross_per_share"]["value"] == "0.20"    # coma -> punto
    assert f["currency"]["value"] == "EUR"
    assert f["message_function"]["value"] == "NEWM"
    assert f["processing_status"]["value"] == "COMP"


def test_provenance_preserved_end_to_end():
    msg = project_ca_message(_dvca_facts(), now=NOW)
    prov = msg["fields"]["payment_date"]["provenance"]
    assert prov
    for p in prov:
        assert p["source_tag"] == "98A"
        assert p["source_qualifier"] == "PAYD"
        assert p["evidence_locator"]
        assert p["raw"] == "20260710"
    assert msg["input_sha256"] == SHA


def test_conflicting_swift_values_not_collapsed():
    doc = _facts_doc(
        _fact("GENL", "22F", "CAEV", "indicator", "DVCA"),
        _fact("USEQ", "35B", "ISIN", "isin", "ES0105448007"),
        _fact("A", "98A", "PAYD", "date", "20260710"),
        _fact("B", "98A", "PAYD", "date", "20260711"),  # difiere
    )
    msg = project_ca_message(doc, now=NOW)
    f = msg["fields"]["payment_date"]
    assert f["status"] == "CONFLICTING"
    assert f["value"] is None
    assert len(f["provenance"]) == 2


def test_unsupported_caev():
    msg = project_ca_message(_dvca_facts(caev="MERG"), now=NOW)
    assert msg["status"] == "UNSUPPORTED_CA_EVENT"
    assert msg["event_type"] is None
    assert msg["caev"] == "MERG"


def test_parse_not_ok_passthrough():
    doc = _dvca_facts()
    doc["parse_status"] = "PARSE_ERROR"
    msg = project_ca_message(doc, now=NOW)
    assert msg["status"] == "PARSE_NOT_OK"


# ------------------------------------------------------------- binding

def test_bound_unique():
    canon = _canon(_event(
        "E1", isin="ES0105448007",
        dates={"date.ex_date": "2026-07-08",
               "date.payment_date": "2026-07-10"},
        gross="0.200"))
    doc = project_and_bind(_dvca_facts(), canon, now=NOW)
    assert doc["schema"] == BINDING_SCHEMA
    assert doc["binding_status"] == "BOUND"
    assert doc["canonical_event_id"] == "E1"
    by = {c["field"]: c for c in doc["comparisons"]}
    assert by["ex_date"]["status"] == "AGREES"
    assert by["payment_date"]["status"] == "AGREES"
    assert by["gross_per_share"]["status"] == "AGREES"  # 0.20 == 0.200
    assert by["record_date"]["status"] == "CANON_MISSING"


def test_differs_without_winner():
    canon = _canon(_event(
        "E1", isin="ES0105448007",
        dates={"date.payment_date": "2026-07-12"},  # difiere
        gross="0.08690661"))
    doc = project_and_bind(_dvca_facts(), canon, now=NOW)
    assert doc["binding_status"] == "BOUND"  # fechas no filtran
    by = {c["field"]: c for c in doc["comparisons"]}
    assert by["payment_date"]["status"] == "DIFFERS"
    assert by["payment_date"]["swift_value"] == "2026-07-10"
    assert by["payment_date"]["canon_value"] == "2026-07-12"
    assert by["gross_per_share"]["status"] == "DIFFERS"
    assert by["gross_per_share"]["canon_currency"] == "EUR"
    # evidencia en ambos lados, sin ganador
    assert by["payment_date"]["swift_provenance"]
    assert by["payment_date"]["canon_assertion_ids"]


def test_swift_missing_field():
    facts = _dvca_facts()
    facts["facts"] = [
        f for f in facts["facts"] if f["source_qualifier"] != "RDTE"
    ]
    canon = _canon(_event(
        "E1", isin="ES0105448007",
        dates={"date.record_date": "2026-07-09"}))
    doc = project_and_bind(facts, canon, now=NOW)
    by = {c["field"]: c for c in doc["comparisons"]}
    assert by["record_date"]["status"] == "SWIFT_MISSING"


def test_canon_conflicting_is_not_differs():
    e = _event("E1", isin="ES0105448007")
    e["facts"] += [
        {"field_path": "date.payment_date", "value": "2026-07-10",
         "revision_id": "r1", "assertion_id": "a1"},
        {"field_path": "date.payment_date", "value": "2026-07-11",
         "revision_id": "r1", "assertion_id": "a2"},
    ]
    doc = project_and_bind(_dvca_facts(), _canon(e), now=NOW)
    by = {c["field"]: c for c in doc["comparisons"]}
    assert by["payment_date"]["status"] == "CANON_CONFLICTING"
    assert set(by["payment_date"]["canon_assertion_ids"]) == {"a1", "a2"}


def test_ambiguous_two_candidates_same_isin():
    canon = _canon(
        _event("E1", isin="ES0105448007",
               dates={"date.payment_date": "2026-03-10"}),
        _event("E2", isin="ES0105448007",
               dates={"date.payment_date": "2026-09-10"}),
    )
    doc = project_and_bind(_dvca_facts(), canon, now=NOW)
    # ninguna fecha coincide -> NO_MATCH tras desambiguacion
    assert doc["binding_status"] == "NO_MATCH"
    assert doc["reasons"] == ["DATES_EXCLUDE_ALL_CANDIDATES"]
    assert set(doc["candidates"]) == {"E1", "E2"}


def test_dates_disambiguate_to_bound():
    canon = _canon(
        _event("E1", isin="ES0105448007",
               dates={"date.payment_date": "2026-07-10"}),  # coincide
        _event("E2", isin="ES0105448007",
               dates={"date.payment_date": "2026-09-10"}),  # excluido
    )
    doc = project_and_bind(_dvca_facts(), canon, now=NOW)
    assert doc["binding_status"] == "BOUND"
    assert doc["canonical_event_id"] == "E1"


def test_ambiguous_when_dates_cannot_disambiguate():
    canon = _canon(
        _event("E1", isin="ES0105448007"),  # sin fechas
        _event("E2", isin="ES0105448007"),
    )
    doc = project_and_bind(_dvca_facts(), canon, now=NOW)
    assert doc["binding_status"] == "AMBIGUOUS"
    assert set(doc["candidates"]) == {"E1", "E2"}


def test_no_match():
    canon = _canon(_event("E1", isin="ES9999999999"))
    doc = project_and_bind(_dvca_facts(), canon, now=NOW)
    assert doc["binding_status"] == "NO_MATCH"


def test_insufficient_identity_no_isin():
    facts = _dvca_facts()
    facts["facts"] = [
        f for f in facts["facts"] if f["source_tag"] != "35B"
    ]
    doc = project_and_bind(facts, _canon(_event("E1")), now=NOW)
    assert doc["binding_status"] == "INSUFFICIENT_IDENTITY"
    assert "MISSING_ISIN" in doc["reasons"]


def test_unsupported_caev_not_bound():
    doc = project_and_bind(_dvca_facts(caev="TEND"),
                           _canon(_event("E1", isin="ES0105448007")),
                           now=NOW)
    assert doc["binding_status"] == "UNSUPPORTED_CA_EVENT"
    assert doc["comparisons"] == []


def test_currency_conflict_is_differs():
    canon = _canon(_event(
        "E1", isin="ES0105448007",
        gross="0.200"))  # canon EUR
    doc = project_and_bind(
        _dvca_facts(ccy="USD"), canon, now=NOW)
    by = {c["field"]: c for c in doc["comparisons"]}
    # misma magnitud, divisa distinta -> DIFFERS, no AGREES
    assert by["gross_per_share"]["status"] == "DIFFERS"


def test_deterministic_except_timestamps():
    canon = _canon(_event("E1", isin="ES0105448007",
                          dates={"date.ex_date": "2026-07-08"}))
    a = project_and_bind(_dvca_facts(), canon, now=NOW)
    b = project_and_bind(_dvca_facts(), canon, now=NOW)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ----------------------------------------------------------------- e2e

@requires_jar
def test_e2e_real_adapter_and_canon():
    fin = (RES / "mt564-bmeg.fin").read_text(encoding="utf-8")
    facts_doc, code = swift_mt.parse_mt(fin)
    assert code == 0
    canon = json.loads(CANON.read_text(encoding="utf-8"))
    doc = project_and_bind(facts_doc, canon, now=NOW)
    assert doc["binding_status"] == "BOUND"
    assert doc["canonical_event_id"].startswith("6881d24a")
    by = {c["field"]: c for c in doc["comparisons"]}
    assert by["ex_date"]["status"] == "AGREES"
    assert by["payment_date"]["status"] == "AGREES"
    assert by["record_date"]["status"] == "CANON_MISSING"
    assert by["gross_per_share"]["status"] == "DIFFERS"
