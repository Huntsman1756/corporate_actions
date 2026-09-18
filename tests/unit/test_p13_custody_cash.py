"""P13 — cash observation, binding, feed recon, cases, profile,
health (logica pura, sin JVM)."""

import pytest

from ca_es.custody_bind import (
    AMBIGUOUS,
    BOUND,
    INSUFFICIENT_IDENTITY,
    NO_MATCH,
    bind_cash,
    movements_doc,
)
from ca_es.custody_cash import cash_observation
from ca_es.custody_health import DEGRADED, FAILED, HEALTHY, feed_health
from ca_es.custody_profile import validate_profile
from ca_es.custody_recon import cash_feed_recon, position_recon
from ca_es.exceptions import classify_cases, merge_cases


def _mt940_facts(entries=(), ref="S-1", acct="ACC-1", ccy="EUR"):
    facts = [
        {"source_tag": "20", "value": ref, "occurrence": 0,
         "field_path": "MT940.20.reference",
         "evidence_locator": "block4.tag[0]", "input_sha256": "x",
         "message_identifier": "MT940"},
        {"source_tag": "25", "value": acct, "occurrence": 0,
         "field_path": "MT940.25.account",
         "evidence_locator": "block4.tag[1]", "input_sha256": "x",
         "message_identifier": "MT940"},
        {"source_tag": "60F", "value": ccy, "occurrence": 0,
         "field_path": "MT940.60F.currency",
         "evidence_locator": "block4.tag[2]", "input_sha256": "x",
         "message_identifier": "MT940"},
    ]
    ti = 3
    for occ, e in enumerate(entries):
        labels = [
            ("value date", e.get("value_date", "260506")),
            ("entry date", e.get("entry_date", "0506")),
            ("debit/credit mark", e.get("mark", "C")),
            ("amount", e.get("amount", "100,00")),
            ("transaction type", "N"),
            ("identification code", "TRF"),
            ("reference for the account owner", e.get("owner_ref")),
            ("reference of the account servicing institution",
             e.get("servicer_ref")),
            ("supplementary details", e.get("supp")),
        ]
        for label, value in labels:
            if value is None:
                continue
            facts.append({
                "source_tag": "61", "value": value, "occurrence": occ,
                "field_path": f"MT940.61.{label}",
                "evidence_locator": f"block4.tag[{ti}]",
                "input_sha256": "x", "message_identifier": "MT940"})
        ti += 1
        if e.get("narrative"):
            facts.append({
                "source_tag": "86", "value": e["narrative"],
                "occurrence": occ, "field_path": "MT940.86.narrative",
                "evidence_locator": f"block4.tag[{ti}]",
                "input_sha256": "x", "message_identifier": "MT940"})
            ti += 1
    return {
        "schema_version": "CA_ES_SWIFT_MT_FACTS_V1",
        "parse_status": "OK",
        "message_identifier": "MT940",
        "standard_family": "ISO15022",
        "input_sha256": "sha-940",
        "generated_at": "2026-05-08T00:00:00Z",
        "facts": facts,
    }


def _camt_facts(entries=(), acct="IBAN-1", ref="N-1"):
    facts = [
        {"model_path": "/D/B/Ntfctn/Id", "value": ref, "occurrence": 0,
         "evidence_locator": "e:/D[0]/B[0]/N[0]/Id[0]",
         "input_sha256": "x", "message_identifier": "camt.054.001.13"},
        {"model_path": "/D/B/Ntfctn/Acct/Id/IBAN", "value": acct,
         "occurrence": 0,
         "evidence_locator": "e:/D[0]/B[0]/N[0]/A[0]/Id[0]/IBAN[0]",
         "input_sha256": "x", "message_identifier": "camt.054.001.13"},
    ]
    for i, e in enumerate(entries):
        base = f"e:/D[0]/B[0]/N[0]/Ntry[{i}]"
        for suffix, value in (
                ("/NtryRef", e.get("ntry_ref", f"N-{i}")),
                ("/Amt", e.get("amount", "10.00")),
                ("/Amt/@Ccy", e.get("ccy", "EUR")),
                ("/CdtDbtInd", e.get("dc", "CRDT")),
                ("/RvslInd", e.get("reversal", "false")),
                ("/Sts/Cd", e.get("status", "BOOK")),
                ("/BookgDt/Dt", e.get("booking", "2026-05-06")),
                ("/ValDt/Dt", e.get("value", "2026-05-06")),
                ("/AcctSvcrRef", e.get("svcr_ref")),
                ("/AddtlNtryInf", e.get("info"))):
            if value is None:
                continue
            facts.append({
                "model_path": f"/D/B/Ntfctn/Ntry{suffix}",
                "value": value, "occurrence": 0,
                "evidence_locator": base + "/" + suffix.strip("/"),
                "input_sha256": "x",
                "message_identifier": "camt.054.001.13"})
        for key, value in (e.get("refs") or {}).items():
            facts.append({
                "model_path":
                    f"/D/B/Ntfctn/Ntry/NtryDtls/TxDtls/Refs/{key}",
                "value": value, "occurrence": 0,
                "evidence_locator": base + "/Refs/" + key,
                "input_sha256": "x",
                "message_identifier": "camt.054.001.13"})
    return {
        "schema_version": "CA_ES_SWIFT_MX_FACTS_V1",
        "parse_status": "PARSE_OK",
        "message_identifier": "camt.054.001.13",
        "standard_family": "ISO20022",
        "input_sha256": "sha-054",
        "generated_at": "2026-05-08T00:00:00Z",
        "facts": facts,
    }


class TestMt940Observation:
    def test_entry_fields(self):
        obs = cash_observation(_mt940_facts(entries=[{
            "owner_ref": "REF-1", "servicer_ref": "SRV-1",
            "amount": "1562,50", "mark": "C",
            "value_date": "260506", "entry_date": "0506",
            "narrative": "dividend payment"}]))
        e = obs["entries"][0]
        assert e["debit_credit"] == "CREDIT"
        assert e["amount"] == "1562.50"
        assert e["currency"] == "EUR"
        assert e["value_date"] == "2026-05-06"
        assert e["booking_date"] == "2026-05-06"
        assert e["booking_date_rule"].startswith("DERIVED_BY_DEFINITION")
        assert e["customer_reference"] == "REF-1"
        assert e["account_servicer_reference"] == "SRV-1"
        assert e["status"] == "BOOKED"
        assert e["narrative"] == ["dividend payment"]

    def test_reversal_mark_preserved(self):
        obs = cash_observation(_mt940_facts(entries=[{
            "owner_ref": "R", "mark": "RD"}]))
        e = obs["entries"][0]
        assert e["debit_credit"] == "DEBIT"
        assert e["reversal"] is True

    def test_narrative_only_associated_to_own_entry(self):
        obs = cash_observation(_mt940_facts(entries=[
            {"owner_ref": "A", "narrative": "for A"},
            {"owner_ref": "B"}]))
        assert obs["entries"][0]["narrative"] == ["for A"]
        assert obs["entries"][1]["narrative"] == []


class TestCamtObservation:
    def test_entry_fields_and_refs(self):
        obs = cash_observation(_camt_facts(entries=[{
            "ntry_ref": "N-1", "amount": "1562.50", "dc": "CRDT",
            "status": "BOOK", "booking": "2026-05-06",
            "value": "2026-05-06", "svcr_ref": "SRV-9",
            "refs": {"EndToEndId": "EVT-1", "TxId": "TX-9"}}]))
        e = obs["entries"][0]
        assert e["debit_credit"] == "CREDIT"
        assert e["status"] == "BOOKED"
        assert e["amount"] == "1562.50"
        assert e["currency"] == "EUR"
        assert e["booking_date"] == "2026-05-06"
        assert e["booking_date_rule"] == "EXPLICIT"
        assert e["customer_reference"] == "EVT-1"
        assert e["transaction_reference"] == "TX-9"
        assert e["structured_details"]["refs"]["EndToEndId"] == "EVT-1"

    def test_pending_status_preserved(self):
        obs = cash_observation(_camt_facts(
            entries=[{"status": "PDNG"}]))
        assert obs["entries"][0]["status"] == "PENDING"

    def test_camt053_stmt_paths(self):
        """camt.053 usa /Stmt en lugar de /Ntfctn; mismo modelo Ntry."""
        doc = _camt_facts(entries=[{
            "ntry_ref": "N-1", "amount": "42.00",
            "refs": {"EndToEndId": "EVT-9"}}])
        doc["message_identifier"] = "camt.053.001.13"
        for f in doc["facts"]:
            f["message_identifier"] = "camt.053.001.13"
            f["model_path"] = (f.get("model_path") or "").replace(
                "/Ntfctn", "/Stmt")
        obs = cash_observation(doc)
        assert obs["parse_status"] == "OK"
        assert obs["statement_reference"] == "N-1"  # /Stmt/Id
        e = obs["entries"][0]
        assert e["amount"] == "42.00"
        assert e["customer_reference"] == "EVT-9"


class TestMt950Observation:
    def test_mt950_entries_without_narrative(self):
        doc = _mt940_facts(entries=[{
            "owner_ref": "R-950", "servicer_ref": "S-950",
            "amount": "800,00", "mark": "C"}])
        doc["message_identifier"] = "MT950"
        for f in doc["facts"]:
            f["message_identifier"] = "MT950"
            f["field_path"] = (f.get("field_path") or "").replace(
                "MT940.", "MT950.")
        obs = cash_observation(doc)
        assert obs["source_message_identifier"] == "MT950"
        e = obs["entries"][0]
        assert e["amount"] == "800.00"
        assert e["customer_reference"] == "R-950"
        assert e["narrative"] == []


class TestBinding:
    def _obs(self):
        return cash_observation(_camt_facts(entries=[
            {"ntry_ref": "N-1", "amount": "1562.50",
             "refs": {"EndToEndId": "EVT-1"}},
            {"ntry_ref": "N-2", "amount": "200.00",
             "refs": {"EndToEndId": "FEE-1"}},
        ]))

    def test_explicit_ref_binds(self):
        obs = self._obs()
        binding = bind_cash(obs, {"EVT-1": {
            "event_id": "evt-a", "amount_basis": "GROSS"}},
            {"IBAN-1": "ACC-1"})
        b = binding["bindings"][0]
        assert b["status"] == BOUND
        assert b["movement"]["event_id"] == "evt-a"
        assert b["movement"]["amount"] == "1562.50"
        assert b["movement"]["amount_basis"] == "GROSS"
        assert b["movement"]["direction"] == "CREDIT"

    def test_unknown_ref_no_match_not_guessed(self):
        obs = self._obs()
        binding = bind_cash(obs, {"EVT-1": {"event_id": "evt-a"}},
                            {"IBAN-1": "ACC-1"})
        b = binding["bindings"][1]
        assert b["status"] == NO_MATCH
        assert b["movement"] is None

    def test_no_refs_insufficient_identity(self):
        obs = cash_observation(_camt_facts(entries=[{
            "ntry_ref": "N-1", "amount": "1562.50"}]))
        binding = bind_cash(obs, {}, {"IBAN-1": "ACC-1"})
        assert binding["bindings"][0]["status"] == INSUFFICIENT_IDENTITY

    def test_conflicting_refs_ambiguous(self):
        obs = cash_observation(_camt_facts(entries=[{
            "ntry_ref": "N-1", "refs": {
                "EndToEndId": "EVT-1", "InstrId": "EVT-2"}}]))
        binding = bind_cash(obs, {
            "EVT-1": {"event_id": "evt-a"},
            "EVT-2": {"event_id": "evt-b"}}, {"IBAN-1": "ACC-1"})
        assert binding["bindings"][0]["status"] == AMBIGUOUS
        assert binding["bindings"][0]["movement"] is None

    def test_amount_never_used_for_binding(self):
        """Mismo importe+fecha+cuenta no liga nada: entry sin refs
        queda sin ligar aunque el mapa tenga un evento con ese
        importe."""
        obs = cash_observation(_camt_facts(entries=[{
            "ntry_ref": "N-1", "amount": "1562.50",
            "value": "2026-05-06"}]))
        binding = bind_cash(obs, {"EVT-1": {
            "event_id": "evt-a", "amount_basis": "GROSS"}},
            {"IBAN-1": "ACC-1"})
        assert binding["summary"]["bound"] == 0
        assert movements_doc(binding)["movements"] == []

    def test_basis_unknown_not_inferred(self):
        """basis ausente en el mapa -> UNKNOWN; nunca GROSS por
        coincidencia de importe."""
        obs = self._obs()
        binding = bind_cash(obs, {"EVT-1": {"event_id": "evt-a"}},
                            {"IBAN-1": "ACC-1"})
        assert binding["bindings"][0]["movement"][
            "amount_basis"] == "UNKNOWN"

    def test_unmapped_account_no_movement(self):
        obs = self._obs()
        binding = bind_cash(obs, {"EVT-1": {"event_id": "evt-a"}}, {})
        assert binding["bindings"][0]["status"] == INSUFFICIENT_IDENTITY
        assert binding["bindings"][0]["reason"] == "UNMAPPED_ACCOUNT"

    def test_movements_doc_schema(self):
        obs = self._obs()
        binding = bind_cash(obs, {"EVT-1": {"event_id": "e"}},
                            {"IBAN-1": "A"})
        doc = movements_doc(binding)
        assert doc["schema"] == "CA_ES_CASH_MOVEMENTS_V2"
        required = {"movement_id", "account_id", "event_id",
                    "currency", "amount", "amount_basis"}
        assert required <= set(doc["movements"][0])


class TestPositionRecon:
    def _snapshot(self, positions):
        # lado custodio = doc CA_ES_POSITIONS_V1 proyectado; la
        # completitud viaja en _snapshot (ver positions_doc())
        return {"schema": "CA_ES_POSITIONS_V1",
                "_snapshot": {"completeness": "COMPLETE",
                              "snapshot_id": "S"},
                "positions": positions}

    def test_match_and_mismatch_exact_decimal(self):
        expected = {"schema": "CA_ES_POSITIONS_V1", "positions": [
            {"account_id": "A", "isin": "X", "quantity": "100"},
            {"account_id": "A", "isin": "Y", "quantity": "50.5"}]}
        snap = self._snapshot([
            {"account_id": "A", "isin": "X", "quantity": "100"},
            {"account_id": "A", "isin": "Y", "quantity": "50.4"}])
        doc = position_recon(expected, snap)
        by_isin = {i["isin"]: i for i in doc["items"]}
        assert by_isin["X"]["status"] == "MATCH"
        assert by_isin["Y"]["status"] == "POSITION_QUANTITY_MISMATCH"
        assert by_isin["Y"]["delta"]["normalized"] == "-0.1"

    def test_missing_and_unexpected(self):
        expected = {"schema": "CA_ES_POSITIONS_V1", "positions": [
            {"account_id": "A", "isin": "X", "quantity": "100"}]}
        snap = self._snapshot([
            {"account_id": "A", "isin": "Z", "quantity": "7"}])
        doc = position_recon(expected, snap)
        statuses = {i["isin"]: i["status"] for i in doc["items"]}
        assert statuses["X"] == "POSITION_MISSING_AT_CUSTODIAN"
        assert statuses["Z"] == "POSITION_UNEXPECTED_AT_CUSTODIAN"

    def test_incomplete_snapshot_indeterminate(self):
        doc = position_recon(
            {"positions": []},
            {"_snapshot": {"completeness": "PARTIAL"},
             "positions": []})
        assert doc["status"] == "INDETERMINATE"
        assert doc["items"] == []


class TestCashFeedRecon:
    def _obs(self):
        return cash_observation(_camt_facts(entries=[{
            "ntry_ref": "N-1", "amount": "1562.50",
            "refs": {"EndToEndId": "EVT-1", "TxId": "TX-9"}},
            {"ntry_ref": "N-2", "amount": "10.00"}]))

    def test_match_by_explicit_ref(self):
        movements = {"movements": [{
            "movement_id": "M-1", "account_id": "A",
            "source_reference": "EVT-1",
            "amount": "1562.50", "currency": "EUR"}]}
        doc = cash_feed_recon(movements, self._obs())
        item = doc["items"][0]
        assert item["status"] == "MATCH"
        assert item["entry_id"] == "N-1"

    def test_amount_mismatch(self):
        movements = {"movements": [{
            "movement_id": "M-1", "source_reference": "EVT-1",
            "amount": "1500.00", "currency": "EUR"}]}
        doc = cash_feed_recon(movements, self._obs())
        assert doc["items"][0]["status"] == "CASH_ACCOUNT_AMOUNT_MISMATCH"

    def test_missing_in_feed(self):
        movements = {"movements": [{
            "movement_id": "M-1", "source_reference": "ABSENT-REF",
            "amount": "1.00"}]}
        doc = cash_feed_recon(movements, self._obs())
        assert doc["items"][0]["status"] == "CASH_MISSING_IN_ACCOUNT_FEED"

    def test_no_reference_indeterminate(self):
        movements = {"movements": [{
            "movement_id": "M-1", "amount": "1562.50"}]}
        doc = cash_feed_recon(movements, self._obs())
        assert doc["items"][0]["status"] == "INDETERMINATE"
        assert doc["items"][0]["reason"] == "NO_REFERENCE_ON_MOVEMENT"


class TestCustodyCases:
    def test_position_case_stable_key(self):
        snap = {"_snapshot": {"completeness": "COMPLETE",
                              "snapshot_id": "S"},
                "positions": [{"account_id": "A", "isin": "X",
                               "quantity": "9"}]}
        expected = {"positions": [{"account_id": "A", "isin": "X",
                                   "quantity": "10"}]}
        recon = position_recon(expected, snap)
        cases = classify_cases(recon)
        assert len(cases) == 1
        c = cases[0]
        assert c["factual_status"] == "POSITION_QUANTITY_MISMATCH"
        assert c["case_key"] == "custody-positions|expected:A:X"
        # re-observar con nueva cantidad -> mismo case_key
        snap2 = {"_snapshot": {"completeness": "COMPLETE",
                               "snapshot_id": "S2"},
                 "positions": [{"account_id": "A", "isin": "X",
                                "quantity": "8"}]}
        cases2 = classify_cases(position_recon(expected, snap2))
        assert cases2[0]["case_key"] == c["case_key"]

    def test_match_produces_no_case(self):
        expected = {"positions": [{"account_id": "A", "isin": "X",
                                   "quantity": "10"}]}
        snap = {"_snapshot": {"completeness": "COMPLETE",
                              "snapshot_id": "S"},
                "positions": [{"account_id": "A", "isin": "X",
                               "quantity": "10"}]}
        assert classify_cases(position_recon(expected, snap)) == []

    def test_case_merges_without_fragmenting(self):
        snap = {"_snapshot": {"completeness": "COMPLETE",
                              "snapshot_id": "S"},
                "positions": [{"account_id": "A", "isin": "X",
                               "quantity": "9"}]}
        expected = {"positions": [{"account_id": "A", "isin": "X",
                                   "quantity": "10"}]}
        cases = classify_cases(position_recon(expected, snap))
        merged = merge_cases(None, cases, now="2026-05-06T00:00:00Z")
        assert len(merged) == 1
        snap["positions"][0]["quantity"] = "8"
        cases2 = classify_cases(position_recon(expected, snap))
        merged2 = merge_cases(merged, cases2,
                              now="2026-05-07T00:00:00Z")
        assert len(merged2) == 1
        assert merged2[0]["factual_status"] == (
            "POSITION_QUANTITY_MISMATCH")


class TestProfile:
    def test_valid_profile(self):
        doc = validate_profile({
            "schema": "CA_ES_CUSTODY_PROFILE_V1",
            "profile_id": "p",
            "account_map": {"RAW-1": "A1"},
            "reference_map": {"R": {"event_id": "e",
                                    "amount_basis": "GROSS"}}})
        assert doc["profile_id"] == "p"

    def test_unknown_key_rejected(self):
        with pytest.raises(ValueError, match="desconocidas"):
            validate_profile({"schema": "CA_ES_CUSTODY_PROFILE_V1",
                              "profile_id": "p", "secret_api_key": "x"})

    def test_duplicate_account_target_rejected(self):
        with pytest.raises(ValueError, match="duplicado"):
            validate_profile({
                "schema": "CA_ES_CUSTODY_PROFILE_V1",
                "profile_id": "p",
                "account_map": {"R1": "A", "R2": "A"}})

    def test_reference_without_event_rejected(self):
        with pytest.raises(ValueError, match="event_id"):
            validate_profile({
                "schema": "CA_ES_CUSTODY_PROFILE_V1",
                "profile_id": "p",
                "reference_map": {"R": {"note": "looks like evt"}}})


class TestFeedHealth:
    def _index(self, **kw):
        return {
            "schema": "CA_ES_CUSTODY_FEED_STATE_V1",
            "statements": kw.get("statements", [{
                "snapshot_id": "S", "account_id_raw": "SAFE-1",
                "completeness": "COMPLETE",
                "statement_as_of": "2026-05-04"}]),
            "conflicting_slots": kw.get("conflicts", []),
            "cash_reports": kw.get("cash", [{"x": 1}]),
            "bindings_summary": kw.get("bindings", {
                "unbound_entries": 0}),
        }

    def test_healthy(self):
        doc = feed_health(self._index(), now="2026-05-06",
                          required_accounts=["SAFE-1"])
        assert doc["status"] == HEALTHY

    def test_no_index_failed(self):
        doc = feed_health(None, now="2026-05-06")
        assert doc["status"] == FAILED

    def test_stale_degraded_not_zero(self):
        doc = feed_health(self._index(), now="2026-06-01",
                          max_position_age_days=7)
        assert doc["status"] == DEGRADED
        check = {c["check"]: c for c in doc["checks"]}
        assert "stale" in check["position_freshness"]["detail"]

    def test_conflict_failed(self):
        doc = feed_health(self._index(conflicts=[{"a": 1}]),
                          now="2026-05-06")
        assert doc["status"] == FAILED

    def test_missing_required_account_failed(self):
        doc = feed_health(self._index(), now="2026-05-06",
                          required_accounts=["SAFE-1", "SAFE-2"])
        assert doc["status"] == FAILED
