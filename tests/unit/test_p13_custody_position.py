"""P13 — custody position observation + snapshots (logica pura).

Facts docs sinteticos con la forma del adapter (sin JVM): cubre
mapping MT535/semt.002, completitud de paginas, conflictos e
idempotencia del snapshot.
"""

import pytest

from ca_es.custody_position import position_observation
from ca_es.custody_snapshot import (
    COMPLETE,
    CONFLICTING,
    INDETERMINATE,
    PARTIAL,
    build_snapshots,
    positions_doc,
)


def _fact(tag, value, qualifier=None, seq="GENL", occ=0, label="value",
          tag_i=0):
    return {
        "message_identifier": "MT535",
        "field_path": f"MT535.{seq.replace('/', '.')}.{tag}"
                      + (f":{qualifier}" if qualifier else "")
                      + f".{label}",
        "value": value,
        "source_tag": tag,
        "source_qualifier": qualifier,
        "sequence": seq,
        "occurrence": occ,
        "evidence_locator": f"block4.tag[{tag_i}]",
        "input_sha256": "sha-test",
    }


def _mt535_facts(page="1", cont="ONLY", ref="STMT-1", acct="SAFE-1",
                 positions=(), as_of="20260504", acty="Y"):
    facts = [
        _fact("28E", ":" + page, label="page number", tag_i=1),
        _fact("28E", cont, label="continuation indicator", tag_i=1),
        _fact("20C", ref, "SEME", label="reference", tag_i=2),
        _fact("98A", as_of, "STAT", label="date", tag_i=3),
        _fact("97A", acct, "SAFE", label="account number", tag_i=4),
        _fact("17B", acty, "ACTI", label="flag", tag_i=5),
    ]
    ti = 6
    for occ, (isin, qty) in enumerate(positions):
        facts.append(_fact("35B", isin, "ISIN", "SUBSAFE/FIN", occ,
                           "isin", tag_i=ti))
        ti += 1
        facts.append(_fact("93B", "UNIT", "AGGR", "SUBSAFE/FIN/SUBBAL",
                           occ, "quantity type code", tag_i=ti))
        ti += 1
        facts.append(_fact("93B", qty, "AGGR", "SUBSAFE/FIN/SUBBAL",
                           occ, "balance", tag_i=ti))
        ti += 1
    return {
        "schema_version": "CA_ES_SWIFT_MT_FACTS_V1",
        "parse_status": "OK",
        "message_identifier": "MT535",
        "standard_family": "ISO15022",
        "input_sha256": f"sha-{ref}-{page}",
        "generated_at": "2026-05-05T00:00:00Z",
        "facts": facts,
    }


def _obs(**kw):
    return position_observation(_mt535_facts(**kw))


class TestMt535Observation:
    def test_basic_fields(self):
        obs = _obs(positions=[("ES0105448007", "12500,")])
        assert obs["schema"] == "CA_ES_POSITION_OBSERVATION_V1"
        assert obs["statement_reference"] == "STMT-1"
        assert obs["statement_as_of"] == "2026-05-04"
        assert obs["account_id_raw"] == "SAFE-1"
        assert obs["pagination"]["page"] == 1
        assert obs["pagination"]["continuation"] == "ONLY"
        assert obs["pagination"]["last_page"] is True

    def test_swift_comma_decimal(self):
        obs = _obs(positions=[("X", "12500,50")])
        assert obs["positions"][0]["quantity"] == "12500.50"

    def test_occurrence_groups_instruments(self):
        obs = _obs(positions=[("AAA", "100,"), ("BBB", "200,")])
        assert [p["isin"] for p in obs["positions"]] == ["AAA", "BBB"]
        assert [p["quantity"] for p in obs["positions"]] == [
            "100", "200"]

    def test_zero_position(self):
        obs = _obs(positions=[("AAA", "0,")])
        assert obs["positions"][0]["quantity"] == "0"

    def test_missing_isin_flagged_not_guessed(self):
        obs = _obs(positions=[("AAA", "100,")])
        # quita el fact ISIN pero deja el balance -> position sin isin
        facts = _mt535_facts(positions=[("AAA", "100,")])
        facts["facts"] = [f for f in facts["facts"]
                          if f["source_tag"] != "35B"]
        obs = position_observation(facts)
        assert obs["positions"] == [] or all(
            p["isin"] != "AAA" for p in obs["positions"])

    def test_empty_statement_flagged(self):
        obs = _obs(positions=[])
        assert "EMPTY_STATEMENT" in obs["reasons"]

    def test_unsupported_message(self):
        facts = _mt535_facts()
        facts["message_identifier"] = "MT999"
        obs = position_observation(facts)
        assert obs["parse_status"] == "UNSUPPORTED"

    def test_semt002_old_version_unsupported(self):
        facts = _mt535_facts()
        facts["message_identifier"] = "semt.002.001.09"
        obs = position_observation(facts)
        assert obs["parse_status"] == "UNSUPPORTED"
        assert "UNSUPPORTED_SEMT002_VERSION" in obs["reasons"]


def _semt_facts(isins_qtys, page="1", last="true", upd="COMP",
                ref="STMT-1", acct="SAFE-1", dt="2026-05-04"):
    facts = [
        {"model_path": "/D/SctiesBalCtdyRpt/Pgntn/PgNb", "value": page,
         "occurrence": 0, "evidence_locator": "e:/D[0]/R[0]/P[0]/PgNb[0]",
         "input_sha256": "x", "message_identifier": "semt.002.001.12"},
        {"model_path": "/D/SctiesBalCtdyRpt/Pgntn/LastPgInd",
         "value": last, "occurrence": 0,
         "evidence_locator": "e:/D[0]/R[0]/P[0]/LastPgInd[0]",
         "input_sha256": "x", "message_identifier": "semt.002.001.12"},
        {"model_path": "/D/SctiesBalCtdyRpt/StmtGnlDtls/StmtId",
         "value": ref, "occurrence": 0,
         "evidence_locator": "e:/D[0]/R[0]/S[0]/StmtId[0]",
         "input_sha256": "x", "message_identifier": "semt.002.001.12"},
        {"model_path": "/D/SctiesBalCtdyRpt/StmtGnlDtls/StmtDtTm/Dt",
         "value": dt, "occurrence": 0,
         "evidence_locator": "e:/D[0]/R[0]/S[0]/StmtDtTm[0]/Dt[0]",
         "input_sha256": "x", "message_identifier": "semt.002.001.12"},
        {"model_path": "/D/SctiesBalCtdyRpt/StmtGnlDtls/UpdTp/Cd",
         "value": upd, "occurrence": 0,
         "evidence_locator": "e:/D[0]/R[0]/S[0]/UpdTp[0]/Cd[0]",
         "input_sha256": "x", "message_identifier": "semt.002.001.12"},
        {"model_path": "/D/SctiesBalCtdyRpt/SfkpgAcct/Id",
         "value": acct, "occurrence": 0,
         "evidence_locator": "e:/D[0]/R[0]/SfkpgAcct[0]/Id[0]",
         "input_sha256": "x", "message_identifier": "semt.002.001.12"},
    ]
    for i, (isin, qty) in enumerate(isins_qtys):
        facts.append({
            "model_path": "/D/R/BalForAcct/FinInstrmId/ISIN",
            "value": isin, "occurrence": 0,
            "evidence_locator":
                f"e:/D[0]/R[0]/BalForAcct[{i}]/FinInstrmId[0]/ISIN[0]",
            "input_sha256": "x",
            "message_identifier": "semt.002.001.12"})
        facts.append({
            "model_path": "/D/R/BalForAcct/AggtBal/Qty/Qty/Qty/Unit",
            "value": qty, "occurrence": 0,
            "evidence_locator":
                f"e:/D[0]/R[0]/BalForAcct[{i}]/AggtBal[0]/Qty[0]"
                "/Qty[0]/Qty[0]/Unit[0]",
            "input_sha256": "x",
            "message_identifier": "semt.002.001.12"})
    return {
        "schema_version": "CA_ES_SWIFT_MX_FACTS_V1",
        "parse_status": "PARSE_OK",
        "message_identifier": "semt.002.001.12",
        "standard_family": "ISO20022",
        "input_sha256": f"sha-mx-{ref}-{page}",
        "generated_at": "2026-05-05T00:00:00Z",
        "facts": facts,
    }


class TestSemt002Observation:
    def test_mapping(self):
        obs = position_observation(_semt_facts(
            [("ES0105448007", "12500"), ("ES0113900J37", "3000")]))
        assert obs["statement_reference"] == "STMT-1"
        assert obs["statement_as_of"] == "2026-05-04"
        assert obs["account_id_raw"] == "SAFE-1"
        assert obs["pagination"]["last_page"] is True
        assert obs["pagination"]["update_type"] == "COMP"
        assert [p["isin"] for p in obs["positions"]] == [
            "ES0105448007", "ES0113900J37"]
        assert [p["quantity"] for p in obs["positions"]] == [
            "12500", "3000"]

    def test_parity_with_mt535(self):
        """MT535 y semt.002 equivalentes -> mismas posiciones
        semanticas (cuenta/as_of/isin/cantidad)."""
        mt = _obs(positions=[("ES0105448007", "12500,"),
                             ("ES0113900J37", "3000,")])
        mx = position_observation(_semt_facts(
            [("ES0105448007", "12500"), ("ES0113900J37", "3000")]))
        for key in ("account_id_raw", "statement_as_of",
                    "statement_reference"):
            assert mt[key] == mx[key]
        mt_rows = sorted((p["isin"], p["quantity"])
                         for p in mt["positions"])
        mx_rows = sorted((p["isin"], p["quantity"])
                         for p in mx["positions"])
        assert mt_rows == mx_rows

    def test_delta_update_type_not_complete(self):
        obs = position_observation(_semt_facts(
            [("AAA", "1")], upd="DELT"))
        index = build_snapshots([obs])
        snap = index["snapshots"][0]
        assert snap["completeness"] == PARTIAL
        assert any("DELTA" in r for r in snap["reasons"])


class TestSnapshotCompleteness:
    def test_single_page_only_complete(self):
        index = build_snapshots([_obs(positions=[("A", "1,")])])
        assert index["snapshots"][0]["completeness"] == COMPLETE

    def test_multi_page_all_present_complete(self):
        obs = [_obs(page="1", cont="MORE", positions=[("A", "1,")]),
               _obs(page="2", cont="LAST", positions=[("B", "2,")])]
        index = build_snapshots(obs)
        snap = index["snapshots"][0]
        assert snap["completeness"] == COMPLETE
        assert len(snap["positions"]) == 2

    def test_missing_page_partial(self):
        obs = [_obs(page="1", cont="MORE", positions=[("A", "1,")]),
               _obs(page="3", cont="LAST", positions=[("B", "2,")])]
        index = build_snapshots(obs)
        snap = index["snapshots"][0]
        assert snap["completeness"] == PARTIAL
        assert any("MISSING_PAGES" in r for r in snap["reasons"])

    def test_no_last_page_partial(self):
        obs = [_obs(page="1", cont="MORE", positions=[("A", "1,")]),
               _obs(page="2", cont="MORE", positions=[("B", "2,")])]
        index = build_snapshots(obs)
        assert index["snapshots"][0]["completeness"] == PARTIAL

    def test_conflicting_complete_snapshots_fail_closed(self):
        obs = [_obs(ref="S1", positions=[("A", "1,")]),
               _obs(ref="S2", positions=[("A", "9,")])]
        index = build_snapshots(obs)
        assert len(index["snapshots"]) == 2
        assert all(s["completeness"] == CONFLICTING
                   for s in index["snapshots"])
        assert index["conflicting_slots"]

    def test_same_content_different_bytes_not_conflict(self):
        """Mismo statement semantico, distinto input_sha -> un slot,
        sin conflicto (misma semantic_sha)."""
        o1 = _obs(ref="S1", positions=[("A", "1,")])
        o2 = _obs(ref="S2", positions=[("A", "1,")])
        index = build_snapshots([o1, o2])
        assert not index["conflicting_slots"]

    def test_idempotent_snapshot_id(self):
        o1 = _obs(positions=[("A", "1,")])
        o2 = _obs(positions=[("A", "1,")])
        assert (build_snapshots([o1])["snapshots"][0]["snapshot_id"]
                == build_snapshots([o2])["snapshots"][0]
                ["snapshot_id"])

    def test_partial_never_replaces_complete(self):
        """Un snapshot PARTIAL no produce positions_doc."""
        obs = [_obs(page="1", cont="MORE", positions=[("A", "1,")])]
        index = build_snapshots(obs)
        snap = index["snapshots"][0]
        doc = positions_doc(snap, {"SAFE-1": "A001"})
        assert doc["positions"] == []
        assert doc["_snapshot"]["completeness"] == PARTIAL


class TestPositionsDoc:
    def test_projection_uses_explicit_map(self):
        index = build_snapshots([_obs(positions=[("A", "1,")])])
        snap = index["snapshots"][0]
        doc = positions_doc(snap, {"SAFE-1": "A001"})
        assert doc["schema"] == "CA_ES_POSITIONS_V1"
        assert doc["as_of"] == "2026-05-04"
        assert doc["positions"] == [
            {"account_id": "A001", "isin": "A", "quantity": "1"}]

    def test_unmapped_account_dropped_not_guessed(self):
        index = build_snapshots([_obs(positions=[("A", "1,")])])
        snap = index["snapshots"][0]
        doc = positions_doc(snap, {})
        assert doc["positions"] == []
        assert doc["_skipped_accounts"] == ["SAFE-1"]
        assert doc["_snapshot"]["completeness"] == "UNMAPPED_ACCOUNT"

    def test_deterministic_ordering(self):
        index = build_snapshots([_obs(positions=[
            ("ZZZ", "1,"), ("AAA", "2,")])])
        snap = index["snapshots"][0]
        doc = positions_doc(snap, {"SAFE-1": "A"})
        assert [p["isin"] for p in doc["positions"]] == ["AAA", "ZZZ"]

    def test_missing_isin_position_dropped(self):
        facts = _mt535_facts(positions=[("AAA", "100,")])
        facts["facts"] = [f for f in facts["facts"]
                          if f["source_tag"] != "35B"]
        obs = position_observation(facts)
        obs["positions"] = [{"isin": None, "quantity": "100",
                             "quantity_type": "UNIT",
                             "balances": [], "reasons": ["MISSING_ISIN"],
                             "provenance": []}]
        index = build_snapshots([obs])
        doc = positions_doc(index["snapshots"][0], {"SAFE-1": "A"})
        assert doc["positions"] == []
        assert doc["_dropped_positions"][0]["reason"] == "MISSING_ISIN"


class TestCrossTransportParity:
    def test_snapshot_semantics_identical_mt_mx(self):
        """El snapshot semantico de MT535 y semt.002 equivalentes
        comparte semantic_sha (modulo provenance)."""
        mt = _obs(ref="STMT-X", positions=[("ES0105448007", "12500,")])
        mx = position_observation(_semt_facts(
            [("ES0105448007", "12500")], ref="STMT-X"))
        mt_snap = build_snapshots([mt])["snapshots"][0]
        mx_snap = build_snapshots([mx])["snapshots"][0]
        assert mt_snap["semantic_sha256"] == mx_snap["semantic_sha256"]
        assert mt_snap["completeness"] == mx_snap["completeness"]
