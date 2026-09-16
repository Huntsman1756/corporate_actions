"""P5.2 — CA_ES_ELECTION_OPPORTUNITY_V1.

Opciones desde CAOPTN del MT564 (CAON/CAOP/DFLT/RDDT, whitelist
CASH/SECU); ausencia de evidencia nunca se convierte en semantica;
deadline operativo via queue con binding fail-closed.
"""

import copy
import json
from pathlib import Path

import pytest

from ca_es import swift_mt
from ca_es.action_queue import build_action_queue
from ca_es.deadlines import compute_deadlines
from ca_es.election import (
    INDETERMINATE,
    OPPORTUNITY_SCHEMA,
    PROJECTED,
    UNSUPPORTED,
    project_election,
)

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "adapters" / "iso-adapter-jvm" / "src" / "test" / "resources"
JAR = swift_mt.default_adapter_jar()
CANON_PATH = ROOT / "g3" / "input" / "canon.json"

requires_jar = pytest.mark.skipif(
    not JAR.is_file(), reason="iso-adapter.jar no construido"
)

NOW = "2026-09-16T00:00:00Z"
SHA = "ab" * 32


def _fact(seq, tag, qual, label, value, occ=0):
    return {
        "message_identifier": "MT564",
        "field_path": f"MT564.{seq.replace('/', '.')}.{tag}"
                      + (f":{qual}" if qual else "") + f".{label}",
        "value": value,
        "source_tag": tag,
        "source_qualifier": qual,
        "sequence": seq,
        "occurrence": occ,
        "evidence_locator": "block4.tag[0].component[1]",
        "input_sha256": SHA,
    }


def _opt(opt_seq, number, code, dflt=None, rddt="20260703",
         terms=None):
    """Facts de un bloque CAOPTN, en orden de documento."""
    seq = f"USEQ/{opt_seq}"
    out = [
        _fact(seq, "22F", "CAON", "indicator", number),
        _fact(seq, "22F", "CAOP", "indicator", code),
    ]
    if dflt is not None:
        out.append(_fact(seq, "17B", "DFLT", "flag", dflt))
    if rddt is not None:
        out.append(_fact(seq, "98A", "RDDT", "date", rddt))
    out.extend(terms or [])
    return out


def _facts(*opt_groups, identifier="MT564", caev="DVCA"):
    base = [
        _fact("GENL", "20C", "CORP", "reference", "CORP-1"),
        _fact("GENL", "23G", None, "function", "NEWM"),
        _fact("GENL", "22F", "CAEV", "indicator", caev),
        _fact("USEQ", "35B", "ISIN", "isin", "ES0105448007"),
    ]
    for g in opt_groups:
        base.extend(g)
    return {
        "schema_version": "CA_ES_SWIFT_MT_FACTS_V1",
        "generated_at": NOW,
        "message_identifier": identifier,
        "input_sha256": SHA,
        "parse_status": "OK",
        "facts": base,
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
         "logical_sha256": "aa" * 32,
         "events": [_event("E1", isin="ES0105448007")]}

TERM = [_fact("USEQ/CAOPTN/CASHMOVE", "19B", "GRSS", "amount", "200,")]


def test_one_explicit_option():
    doc = project_election(
        _facts(_opt("CAOPTN", "001", "CASH", dflt="Y", terms=TERM)),
        CANON, now=NOW)
    assert doc["schema"] == OPPORTUNITY_SCHEMA
    assert doc["projection_status"] == PROJECTED
    o = doc["options"][0]
    assert o["option_identifier"] == "001"
    assert o["option_code_raw"] == "CASH"
    assert o["option_kind"] == "CASH"
    assert o["default_status"] == "DEFAULT"
    assert o["source_response_deadline"] == "2026-07-03"
    assert o["terms"] and o["terms"][0]["raw"] == "200,"
    assert o["provenance"]


def test_two_options_stable_order():
    doc = project_election(
        _facts(_opt("CAOPTN", "001", "CASH", dflt="Y"),
               _opt("CAOPTN", "002", "SECU", dflt="N",
                    rddt="20260703")),
        CANON, now=NOW)
    assert doc["projection_status"] == PROJECTED
    ids = [o["option_identifier"] for o in doc["options"]]
    assert ids == ["001", "002"]
    assert doc["options"][1]["option_kind"] == "SECURITIES"
    assert doc["options"][1]["default_status"] == "NOT_DEFAULT"
    assert doc["source_response_deadline"] == "2026-07-03"


def test_stable_option_key():
    a = project_election(
        _facts(_opt("CAOPTN", "001", "CASH")), CANON, now=NOW)
    b = project_election(
        _facts(_opt("CAOPTN", "001", "CASH")), CANON, now=NOW)
    assert a["options"][0]["option_key"] == b["options"][0]["option_key"]
    assert a["options"][0]["option_key"] == "E1|option:001"


def test_no_option_sequence_is_indeterminate_not_non_elective():
    doc = project_election(_facts(), CANON, now=NOW)
    assert doc["projection_status"] == INDETERMINATE
    assert "NO_OPTION_EVIDENCE" in doc["reasons"]
    assert doc["options"] == []


def test_missing_option_identity():
    group = [
        _fact("USEQ/CAOPTN", "22F", "CAOP", "indicator", "CASH"),
        _fact("USEQ/CAOPTN", "17B", "DFLT", "flag", "Y"),
    ]
    doc = project_election(_facts(group), CANON, now=NOW)
    assert doc["projection_status"] == INDETERMINATE
    assert "MISSING_OPTION_IDENTITY" in doc["reasons"]


def test_conflicting_option_facts():
    group = [
        _fact("USEQ/CAOPTN", "22F", "CAON", "indicator", "001"),
        _fact("USEQ/CAOPTN", "22F", "CAOP", "indicator", "CASH"),
        _fact("USEQ/CAOPTN", "22F", "CAOP", "indicator", "SECU", occ=1),
    ]
    doc = project_election(_facts(group), CANON, now=NOW)
    assert doc["projection_status"] == INDETERMINATE
    assert "CONFLICTING_OPTION_FACTS" in doc["reasons"]


def test_duplicate_option_identity():
    doc = project_election(
        _facts(_opt("CAOPTN", "001", "CASH"),
               _opt("CAOPTN", "001", "SECU")),
        CANON, now=NOW)
    assert doc["projection_status"] == INDETERMINATE
    assert "CONFLICTING_OPTION_IDENTITY" in doc["reasons"]


def test_unknown_option_code_preserved_not_inferred():
    doc = project_election(
        _facts(_opt("CAOPTN", "001", "MPUT")), CANON, now=NOW)
    o = doc["options"][0]
    assert o["option_code_raw"] == "MPUT"
    assert o["option_kind"] == "UNSUPPORTED"


def test_no_dflt_is_unknown_not_first_default():
    doc = project_election(
        _facts(_opt("CAOPTN", "001", "CASH"),
               _opt("CAOPTN", "002", "SECU")),
        CANON, now=NOW)
    assert all(o["default_status"] == "UNKNOWN"
               for o in doc["options"])


def test_non_mt564_unsupported():
    facts = _facts(_opt("CAOPTN", "001", "CASH"), identifier="MT566")
    doc = project_election(facts, CANON, now=NOW)
    assert doc["projection_status"] == UNSUPPORTED
    assert doc["reasons"] == ["UNSUPPORTED_MESSAGE_TYPE"]


def test_unsupported_caev():
    facts = _facts(_opt("CAOPTN", "001", "CASH"), caev="TEND")
    doc = project_election(facts, CANON, now=NOW)
    assert doc["projection_status"] == UNSUPPORTED


def test_event_not_bound():
    canon = {"canon_version": "X", "logical_sha256": "aa" * 32,
             "events": [_event("E2", isin="ES9999999999")]}
    doc = project_election(
        _facts(_opt("CAOPTN", "001", "CASH")), canon, now=NOW)
    assert doc["projection_status"] == INDETERMINATE
    assert "EVENT_NOT_BOUND" in doc["reasons"]


def _queue_with(items, sha="aa" * 32):
    return {"schema": "CA_ES_ACTION_QUEUE_V1", "as_of": "2026-07-01",
            "window_days": 7, "due_soon_days": 2,
            "source_canon_logical_sha256": sha,
            "items": items, "indeterminate": []}


def _qitem(eid="E1", dtype="RESPONSE_DEADLINE"):
    return {"deadline_key": f"{eid}|{dtype}|R",
            "canonical_event_id": eid, "deadline_type": dtype,
            "deadline_date": "2026-07-03", "derivation_status": "DERIVED",
            "source_date": "2026-07-10", "rule_id": "R",
            "calendar_id": "TARGET2", "business_days_offset": -1,
            "days_until": 2, "action_status": "DUE_SOON",
            "assertion_ids": ["a1"], "evidence": []}


def test_deadline_bound_single():
    doc = project_election(
        _facts(_opt("CAOPTN", "001", "CASH")), CANON,
        queue_doc=_queue_with([_qitem()]),
        deadline_types=("RESPONSE_DEADLINE",), now=NOW)
    assert doc["deadline_binding_status"] == "BOUND"
    assert len(doc["operational_deadlines"]) == 1
    # el deadline operativo no es el comunicado por la fuente
    assert doc["source_response_deadline"] == "2026-07-03"


def test_deadline_missing():
    doc = project_election(
        _facts(_opt("CAOPTN", "001", "CASH")), CANON,
        queue_doc=_queue_with([]),
        deadline_types=("RESPONSE_DEADLINE",), now=NOW)
    assert doc["deadline_binding_status"] == "MISSING"


def test_deadline_ambiguous_no_winner():
    doc = project_election(
        _facts(_opt("CAOPTN", "001", "CASH")), CANON,
        queue_doc=_queue_with([_qitem(), _qitem(dtype="OTHER")]),
        deadline_types=("RESPONSE_DEADLINE", "OTHER"), now=NOW)
    assert doc["deadline_binding_status"] == "AMBIGUOUS"
    assert len(doc["operational_deadlines"]) == 2


def test_no_queue_not_applicable():
    doc = project_election(
        _facts(_opt("CAOPTN", "001", "CASH")), CANON, now=NOW)
    assert doc["deadline_binding_status"] == "NOT_APPLICABLE"


def test_queue_canon_mismatch_fail_closed():
    queue = _queue_with([_qitem()], sha="ff" * 32)
    with pytest.raises(ValueError, match="QUEUE_CANON_MISMATCH"):
        project_election(
            _facts(_opt("CAOPTN", "001", "CASH")), CANON,
            queue_doc=queue,
            deadline_types=("RESPONSE_DEADLINE",), now=NOW)


def test_queue_without_types_fail_closed():
    with pytest.raises(ValueError, match="MISSING_DEADLINE_TYPE_CONFIG"):
        project_election(
            _facts(_opt("CAOPTN", "001", "CASH")), CANON,
            queue_doc=_queue_with([_qitem()]),
            deadline_types=(), now=NOW)


def test_deterministic_and_canon_untouched():
    canon = copy.deepcopy(CANON)
    a = project_election(
        _facts(_opt("CAOPTN", "001", "CASH", terms=TERM)), canon,
        now=NOW)
    b = project_election(
        _facts(_opt("CAOPTN", "001", "CASH", terms=TERM)), canon,
        now=NOW)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert canon == CANON


@requires_jar
def test_e2e_real_mt564_volu():
    fin = (RES / "mt564-volu.fin").read_text(encoding="utf-8")
    facts_doc, code = swift_mt.parse_mt(fin)
    assert code == 0
    canon = json.loads(CANON_PATH.read_text(encoding="utf-8"))
    doc = project_election(facts_doc, canon, now=NOW)
    assert doc["projection_status"] == PROJECTED
    assert doc["canonical_event_id"] == \
        "6881d24a-ef46-5053-80ce-1743a1792f8b"
    assert [o["option_identifier"] for o in doc["options"]] == \
        ["001", "002"]
    assert doc["options"][0]["option_kind"] == "CASH"
    assert doc["options"][0]["default_status"] == "DEFAULT"
    assert doc["options"][1]["option_kind"] == "SECURITIES"
    assert doc["source_response_deadline"] == "2026-07-03"
    # terms: CASHMOVE en opcion 1, SECMOVE en opcion 2
    assert doc["options"][0]["terms"]
    assert doc["options"][1]["terms"]
    assert doc["options"][0]["terms"][0]["sequence"].endswith(
        "CASHMOVE")
