"""P16 — Market Claims Lifecycle (M1-M15).

Invariante bajo test: una market claim NUNCA se infiere de
`trade before ex-date + settlement after record date` — exige
regla de mercado explicita; sin ella -> MARKET_PRACTICE_REQUIRED.
"""

from ca_es.exceptions import classify_cases
from ca_es.market_claim_assessment import (
    INDETERMINATE, MARKET_PRACTICE_REQUIRED, NOT_APPLICABLE,
    PROVEN, claim_assessment)
from ca_es.market_claim_basis import (
    AFTER_RECORD_DATE, BEFORE_EX_DATE, UNKNOWN, claim_basis)
from ca_es.market_claim_cancellation import cancellation_doc
from ca_es.market_claim_case import (
    ACCEPTED, CANCELLATION_REQUESTED, CANCELLED, EXPECTED,
    NOTIFIED, SETTLED, find_claim, merge_claims, open_claims)
from ca_es.market_claim_messages import (
    bind_claim, project_claim_cancellation, project_claim_status,
    project_market_claim)
from ca_es.market_claim_recon import (
    AMOUNT_MISMATCH, MATCH, NO_SETTLEMENT_OBSERVED,
    QUANTITY_MISMATCH, claim_recon)
from ca_es.market_claim_rules import (
    RULES_SCHEMA, validate_claim_ruleset)
from ca_es.market_claim_status import apply_claim_events

import pytest

EID = "evt-mc-1"
ISIN = "ES0105022000"


# ------------------------------------------------------------------
# builders


def _tx(tid="TX-1", siid="SI-1", direction="BUY", qty="1000",
        trade="2026-07-20", settle="2026-07-30",
        status="PENDING", isin=ISIN, account="ACC-1"):
    return {
        "transaction_id": tid,
        "settlement_instruction_id": siid,
        "account_id": account,
        "isin": isin,
        "quantity": qty,
        "direction": direction,
        "trade_date": trade,
        "settlement_date": settle,
        "settlement_status": status,
        "counterparty_ref": "CPTY-1",
        "provenance": [{"source": "settlement-feed",
                        "ref": tid}],
    }


def _tx_doc(txs):
    return {"schema": "CA_ES_SECURITIES_TRANSACTIONS_V1",
            "transactions": txs}


def _basis(txs, ex="2026-07-27", record="2026-07-28",
           pay="2026-07-29", event_type="CASH_DIVIDEND"):
    return claim_basis(
        _tx_doc(txs), canonical_event_id=EID,
        event_type=event_type, ex_date=ex, record_date=record,
        payment_date=pay, now="2026-08-01T00:00:00Z")


def _mc_rules(direction="BUYER_COMPENSATED", claim_type="MKTC",
              kind="CASH", rule_id="ES-DVCA-MKTC-001",
              event_type="CASH_DIVIDEND", days=30):
    return {
        "schema": RULES_SCHEMA,
        "ruleset_id": "es-mc-v1",
        "rules": [{
            "rule_id": rule_id,
            "jurisdiction": "ES",
            "event_type": event_type,
            "valid_from": "2020-01-01",
            "claim_type": claim_type,
            "claim_direction": direction,
            "eligibility": {
                "trade_date_relation": "BEFORE_EX_DATE",
                "settlement_status": ["PENDING", "SETTLED_LATE"],
                "settlement_date_relation": "AFTER_RECORD_DATE",
            },
            "proceeds": {"kind": kind},
            "deadline": {"basis": "RECORD_DATE", "days": days},
        }],
    }


def _proven_claims(rate="0.125", qty="1000"):
    basis = _basis([_tx(qty=qty)])
    assessment = claim_assessment(
        basis, _mc_rules(), jurisdiction="ES",
        assessment_date="2026-08-01",
        proceeds_rate=rate, proceeds_currency="EUR",
        now="2026-08-01T00:00:00Z")
    return open_claims(assessment, now="2026-08-01T00:00:00Z")


def _notified_claims(rate="0.125", qty="1000"):
    claims = _proven_claims(rate, qty)
    cid = claims["claims"][0]["claim_id"]
    apply_claim_events(claims, [{
        "event_type": "NOTIFICATION", "claim_id": cid,
        "at": "2026-08-02", "source_ref": "sha-050"}],
        now="2026-08-02T00:00:00Z")
    return claims


def _fact(path, value, occ=0):
    loc = "element:" + re_indexed(path)
    return {"message_identifier": None, "input_sha256": "sha-050",
            "model_path": path, "value": value,
            "occurrence": occ, "evidence_locator": loc}


def re_indexed(path):
    out = []
    for seg in path.split("/"):
        if not seg:
            continue
        if "[" in seg:
            out.append(seg)
        else:
            out.append(seg + "[0]")
    return "/" + "/".join(out)


def _facts_doc(mid, facts):
    for f in facts:
        f["message_identifier"] = mid
    return {"schema_version": "CA_ES_SWIFT_MX_FACTS_V1",
            "message_identifier": mid,
            "input_sha256": "sha-" + mid,
            "parse_status": "PARSE_OK",
            "facts": facts}


def _seev050(claim_ref="CLM-EXT-1", evt_ref="CORP-1",
             siid="SI-1", amount="125.00", ccy="EUR",
             mkt_tp="MKTC", isin=ISIN, acct="ACC-1"):
    D = "/Document/MktClmCre"
    facts = [
        _fact(f"{D}/TxRef/AcctSvcrTxId", claim_ref),
        _fact(f"{D}/CorpActnGnlInf/CorpActnEvtId", evt_ref),
        _fact(f"{D}/CorpActnGnlInf/FinInstrmId/ISIN", isin),
        _fact(f"{D}/AcctDtls/SfkpgAcct", acct),
        _fact(f"{D}/RltdSttlmInstrDtls/RltdSttlmInstrId", siid),
        _fact(f"{D}/RltdSttlmInstrDtls/TrfOfPrcdsTpInd", "CLFT"),
        _fact(f"{D}/MktClmTp", mkt_tp),
        _fact(f"{D}/MktClmDtls/CshMvmntDtls[0]/CdtDbtInd", "CRDT"),
        _fact(f"{D}/MktClmDtls/CshMvmntDtls[0]/EntitldAmt",
              amount),
        _fact(f"{D}/MktClmDtls/CshMvmntDtls[0]/EntitldAmt/@Ccy",
              ccy),
    ]
    return _facts_doc("seev.050.001.03", facts)


def _seev052(claim_ref="CLM-EXT-1", choice="AccptdForFrthrPrcg"):
    D = "/Document/MktClmStsAdvc"
    facts = [
        _fact(f"{D}/MktClmCreId/Id", claim_ref),
        _fact(f"{D}/MktClmPrcgSts/{choice}/NoSpcfdRsn", "NOSE"),
    ]
    return _facts_doc("seev.052.001.03", facts)


def _seev051(claim_ref="CLM-EXT-1"):
    D = "/Document/MktClmCxlReq"
    facts = [_fact(f"{D}/MktClmCreId/Id", claim_ref)]
    return _facts_doc("seev.051.001.02", facts)


def _seev053(cxl_ref="CXL-1", claim_ref="CLM-EXT-1",
             choice="Accptd"):
    D = "/Document/MktClmCxlReqStsAdvc"
    facts = [
        _fact(f"{D}/MktClmCxlReqId/Id", cxl_ref),
        _fact(f"{D}/TxRef/AcctSvcrTxId", claim_ref),
        _fact(f"{D}/MktClmCxlReqSts/{choice}/NoSpcfdRsn", "NOSE"),
    ]
    return _facts_doc("seev.053.001.03", facts)


def _movements(amount, ref=None, ccy="EUR", direction="CRDT",
               mid="M-1"):
    m = {"movement_id": mid, "account_id": "ACC-1",
         "amount": amount, "currency": ccy,
         "direction": direction, "amount_basis": "NET"}
    if ref:
        m["source_reference"] = ref
    return {"schema": "CA_ES_CASH_MOVEMENTS_V2",
            "movements": [m]}


def _bound_via_050(claims, siid="SI-1", ref="CLM-EXT-1"):
    """Proyecta una seev.050, la liga y aplica NOTIFICATION."""
    proj = project_market_claim(_seev050(siid=siid, claim_ref=ref))
    binding = bind_claim(proj["projection"], claims)
    assert binding["binding_status"] == "BOUND"
    apply_claim_events(claims, [{
        "event_type": "NOTIFICATION",
        "claim_id": binding["claim_id"], "at": "2026-08-02",
        "source_ref": "sha-seev.050.001.03",
        "projection": proj["projection"],
        "observed_amount": "125.00"}],
        now="2026-08-02T00:00:00Z")
    return binding["claim_id"]


# ------------------------------------------------------------------
# M1: mandatory cash distribution + transaccion elegible -> PROVEN


def test_m1_cash_distribution_eligible_tx_proven():
    assessment = claim_assessment(
        _basis([_tx()]), _mc_rules(), jurisdiction="ES",
        assessment_date="2026-08-01",
        proceeds_rate="0.125", proceeds_currency="EUR")
    item = assessment["items"][0]
    assert item["status"] == PROVEN
    assert item["expected_amount"] == "125.000"
    assert item["claim_type"] == "MKTC"
    assert item["proceeds_direction"] == "RECEIPT"
    assert item["claim_id"].startswith("MC-")
    assert item["rule_id"] == "ES-DVCA-MKTC-001"


def test_m1_claim_id_deterministic():
    a1 = claim_assessment(_basis([_tx()]), _mc_rules(),
                          jurisdiction="ES",
                          assessment_date="2026-08-01",
                          proceeds_rate="0.125")
    a2 = claim_assessment(_basis([_tx()]), _mc_rules(),
                          jurisdiction="ES",
                          assessment_date="2026-08-01",
                          proceeds_rate="0.125")
    assert a1["items"][0]["claim_id"] == a2["items"][0]["claim_id"]


def test_basis_relations_explicit():
    basis = _basis([_tx()])
    item = basis["items"][0]
    assert item["trade_date_relation"] == BEFORE_EX_DATE
    assert item["settlement_date_relation"] == AFTER_RECORD_DATE
    assert item["facts_proven"] is True


# ------------------------------------------------------------------
# M2: sin basis suficiente -> INDETERMINATE


def test_m2_no_transaction_basis_indeterminate():
    assessment = claim_assessment(
        _basis([]), _mc_rules(), jurisdiction="ES",
        assessment_date="2026-08-01", proceeds_rate="0.125")
    assert assessment["items"] == []
    assert assessment["summary"] == {}


def test_m2_missing_dates_unknown_relation():
    basis = claim_basis(
        _tx_doc([_tx(trade=None, settle=None)]),
        canonical_event_id=EID, event_type="CASH_DIVIDEND",
        ex_date=None, record_date=None, payment_date=None)
    item = basis["items"][0]
    assert item["trade_date_relation"] == UNKNOWN
    item_a = claim_assessment(
        basis, _mc_rules(), jurisdiction="ES",
        assessment_date="2026-08-01",
        proceeds_rate="0.125")["items"][0]
    assert item_a["status"] == NOT_APPLICABLE
    assert "TRADE_DATE_RELATION_UNKNOWN" in item_a["reason_codes"]


# ------------------------------------------------------------------
# M3: seev.050 incoming -> binding determinista


def test_m3_seev050_projects_and_binds():
    claims = _proven_claims()
    proj = project_market_claim(_seev050())
    assert proj["status"] == "PROJECTED"
    assert proj["projection"]["market_claim_type"] == "MKTC"
    assert proj["projection"][
        "related_settlement_instruction_id"] == "SI-1"
    binding = bind_claim(proj["projection"], claims)
    assert binding["binding_status"] == "BOUND"
    assert "SI-1" in binding["matched_references"]
    cid = binding["claim_id"]
    apply_claim_events(claims, [{
        "event_type": "NOTIFICATION", "claim_id": cid,
        "at": "2026-08-02", "source_ref": "sha-050-a",
        "projection": proj["projection"],
        "observed_amount": "125.00"}])
    assert find_claim(claims, cid)["status"] == NOTIFIED
    # la ref externa queda registrada para ligar 052/053
    assert "CLM-EXT-1" in find_claim(
        claims, cid)["binding_references"]


def test_m3_seev052_status_binds_via_creation_ref():
    claims = _proven_claims()
    cid = _bound_via_050(claims)
    proj = project_claim_status(_seev052())
    assert proj["projection"]["internal_status"] == "ACCEPTED"
    binding = bind_claim(proj["projection"], claims)
    assert binding["binding_status"] == "BOUND"
    assert binding["claim_id"] == cid


# ------------------------------------------------------------------
# M4: seev.050 desconocida/ambigua -> NO_MATCH / AMBIGUOUS


def test_m4_unknown_seev050_no_match():
    claims = _proven_claims()
    proj = project_market_claim(_seev050(siid="SI-UNKNOWN"))
    binding = bind_claim(proj["projection"], claims)
    assert binding["binding_status"] == "NO_MATCH"


def test_m4_ambiguous_seev050():
    basis = _basis([_tx(tid="TX-1", siid="SI-X"),
                    _tx(tid="TX-2", siid="SI-X")])
    assessment = claim_assessment(
        basis, _mc_rules(), jurisdiction="ES",
        assessment_date="2026-08-01", proceeds_rate="0.125")
    claims = open_claims(assessment)
    proj = project_market_claim(_seev050(siid="SI-X"))
    binding = bind_claim(proj["projection"], claims)
    assert binding["binding_status"] == "AMBIGUOUS"
    assert len(binding["candidates"]) == 2


# ------------------------------------------------------------------
# M5/M6: cash claim settlement


def test_m5_cash_claim_match():
    claims = _notified_claims()
    cid = claims["claims"][0]["claim_id"]
    recon = claim_recon(claims, [_movements("125.000", ref=cid)])
    item = recon["items"][0]
    assert item["status"] == MATCH
    assert item["outstanding_amount"] == "0"


def test_m6_cash_claim_mismatch_case():
    claims = _notified_claims()
    cid = claims["claims"][0]["claim_id"]
    recon = claim_recon(claims, [_movements("120.00", ref=cid)])
    item = recon["items"][0]
    assert item["status"] == AMOUNT_MISMATCH
    assert item["settled_amount"] == "120.00"
    assert item["outstanding_amount"] == "5.000"
    cases = classify_cases(recon)
    assert len(cases) == 1
    assert cases[0]["factual_status"] == AMOUNT_MISMATCH
    assert cases[0]["case_key"].startswith("market-claim|")


def test_m6_no_reference_no_match():
    claims = _notified_claims()
    recon = claim_recon(claims, [_movements("125.000")])
    assert recon["items"][0]["status"] == NO_SETTLEMENT_OBSERVED
    # sin referencia explicita: NUNCA bind por amount+date
    assert classify_cases(recon) == []


# ------------------------------------------------------------------
# M7: securities claim -> expected quantity recon


def test_m7_securities_claim():
    basis = _basis([_tx()])
    rules = _mc_rules(kind="SECURITIES")
    assessment = claim_assessment(
        basis, rules, jurisdiction="ES",
        assessment_date="2026-08-01",
        proceeds_quantity_ratio="1.0",
        proceeds_target_isin="ES0105022001")
    item = assessment["items"][0]
    assert item["status"] == PROVEN
    assert item["expected_quantity"] == "1000.0"
    claims = open_claims(assessment)
    cid = claims["claims"][0]["claim_id"]
    apply_claim_events(claims, [{
        "event_type": "NOTIFICATION", "claim_id": cid,
        "at": "2026-08-02", "source_ref": "sha-050"}])
    mv = {"movements": [{"movement_id": "MS-1",
                         "account_id": "ACC-1",
                         "quantity": "500", "isin": "ES0105022001",
                         "source_reference": cid}]}
    recon = claim_recon(claims, [mv])
    assert recon["items"][0]["status"] == QUANTITY_MISMATCH
    assert recon["items"][0]["outstanding_quantity"] == "500.0"


# ------------------------------------------------------------------
# M8: seev.052 -> status lifecycle


def test_m8_status_lifecycle():
    claims = _proven_claims()
    cid = _bound_via_050(claims)
    for choice, expected in [("Pdg", "PENDING"),
                             ("MtchgSts", "MATCHING"),
                             ("AccptdForFrthrPrcg", "ACCEPTED")]:
        proj = project_claim_status(_seev052(choice=choice))
        out = apply_claim_events(claims, [{
            "event_type": "STATUS", "claim_id": cid,
            "at": "2026-08-03",
            "source_ref": f"sha-{choice}",
            "internal_status": proj["projection"]["internal_status"],
            "status_choice": choice}])
        assert out["outcomes"][0]["outcome"] == "APPLIED"
        assert find_claim(claims, cid)["status"] == expected


def test_m8_rejected_terminal():
    claims = _proven_claims()
    cid = _bound_via_050(claims)
    out = apply_claim_events(claims, [{
        "event_type": "STATUS", "claim_id": cid, "at": "2026-08-03",
        "source_ref": "sha-r", "internal_status": "REJECTED",
        "status_choice": "Rjctd"}])
    assert out["outcomes"][0]["outcome"] == "APPLIED"
    claim = find_claim(claims, cid)
    assert claim["status"] == "REJECTED"
    # terminal: cualquier evento posterior -> REJECTED_EVENT
    out2 = apply_claim_events(claims, [{
        "event_type": "STATUS", "claim_id": cid, "at": "2026-08-04",
        "source_ref": "sha-r2", "internal_status": "ACCEPTED"}])
    assert out2["outcomes"][0]["outcome"] == "REJECTED_EVENT"
    assert claim["status"] == "REJECTED"


def test_m8_skip_transition_rejected():
    claims = _proven_claims()
    cid = claims["claims"][0]["claim_id"]
    out = apply_claim_events(claims, [{
        "event_type": "STATUS", "claim_id": cid, "at": "2026-08-03",
        "source_ref": "sha-jump", "internal_status": "ACCEPTED"}])
    assert out["outcomes"][0]["outcome"] == "REJECTED_EVENT"
    assert find_claim(claims, cid)["status"] == EXPECTED


# ------------------------------------------------------------------
# M9/M10: cancellation intent != outcome


def test_m9_cancellation_intent_separate():
    claims = _proven_claims()
    cid = _bound_via_050(claims)
    proj = project_claim_cancellation(_seev051())
    assert proj["kind"] == "CANCELLATION_REQUEST"
    binding = bind_claim(proj["projection"], claims)
    assert binding["binding_status"] == "BOUND"
    out = apply_claim_events(claims, [{
        "event_type": "CANCELLATION_REQUEST", "claim_id": cid,
        "at": "2026-08-04", "source_ref": "sha-051"}])
    claim = find_claim(claims, cid)
    assert out["outcomes"][0]["outcome"] == "APPLIED"
    assert claim["status"] == CANCELLATION_REQUESTED
    assert claim["pre_cancellation_status"] == NOTIFIED
    # el intent por si solo NO cancela: claim sigue vivo
    assert claim["status"] != CANCELLED


def test_m10_cancel_accepted_explicit():
    claims = _proven_claims()
    cid = _bound_via_050(claims)
    apply_claim_events(claims, [{
        "event_type": "CANCELLATION_REQUEST", "claim_id": cid,
        "at": "2026-08-04", "source_ref": "sha-051"}])
    proj = project_claim_cancellation(_seev053())
    assert proj["projection"]["internal_status"] == \
        "CANCEL_ACCEPTED"
    out = apply_claim_events(claims, [{
        "event_type": "CANCELLATION_STATUS", "claim_id": cid,
        "at": "2026-08-05", "source_ref": "sha-053",
        "cancel_outcome": "CANCEL_ACCEPTED"}])
    assert out["outcomes"][0]["outcome"] == "APPLIED"
    assert find_claim(claims, cid)["status"] == CANCELLED


def test_m10_cancel_rejected_restores():
    claims = _proven_claims()
    cid = _bound_via_050(claims)
    apply_claim_events(claims, [{
        "event_type": "CANCELLATION_REQUEST", "claim_id": cid,
        "at": "2026-08-04", "source_ref": "sha-051"}])
    apply_claim_events(claims, [{
        "event_type": "CANCELLATION_STATUS", "claim_id": cid,
        "at": "2026-08-05", "source_ref": "sha-053r",
        "cancel_outcome": "CANCEL_REJECTED"}])
    claim = find_claim(claims, cid)
    assert claim["status"] == NOTIFIED
    assert "pre_cancellation_status" not in claim


def test_cancellation_doc_tracks_intent_outcome():
    claims = _proven_claims()
    cid = _bound_via_050(claims)
    events = [
        {"event_type": "CANCELLATION_REQUEST", "claim_id": cid,
         "at": "2026-08-04", "source_ref": "sha-051",
         "message_identifier": "seev.051.001.02"},
        {"event_type": "CANCELLATION_STATUS", "claim_id": cid,
         "at": "2026-08-05", "source_ref": "sha-053",
         "cancel_outcome": "CANCEL_ACCEPTED",
         "message_identifier": "seev.053.001.03"},
    ]
    apply_claim_events(claims, events)
    doc = cancellation_doc(claims, events)
    item = doc["items"][0]
    assert item["current_outcome"] == "ACCEPTED"
    assert item["claim_status"] == CANCELLED
    assert len(item["intents"]) == 1
    assert len(item["outcomes"]) == 1


# ------------------------------------------------------------------
# M11: duplicate seev.050 -> idempotent


def test_m11_duplicate_notification_ignored():
    claims = _proven_claims()
    cid = claims["claims"][0]["claim_id"]
    ev = {"event_type": "NOTIFICATION", "claim_id": cid,
          "at": "2026-08-02", "source_ref": "sha-050"}
    out1 = apply_claim_events(claims, [ev])
    out2 = apply_claim_events(claims, [ev])
    assert out1["outcomes"][0]["outcome"] == "APPLIED"
    assert out2["outcomes"][0]["outcome"] == "DUPLICATE_IGNORED"
    assert find_claim(claims, cid)["status"] == NOTIFIED


# ------------------------------------------------------------------
# M12: changed claim amount -> conflicto, nunca overwrite


def test_m12_changed_amount_conflict_not_overwrite():
    claims = _proven_claims()  # expected 125.000
    cid = claims["claims"][0]["claim_id"]
    out = apply_claim_events(claims, [{
        "event_type": "NOTIFICATION", "claim_id": cid,
        "at": "2026-08-02", "source_ref": "sha-050",
        "observed_amount": "130.00"}])
    assert out["outcomes"][0]["outcome"] == \
        "CONFLICTING_NOTIFICATION"
    claim = find_claim(claims, cid)
    assert claim["expected_amount"] == "125.000"  # no overwrite
    assert any(h["type"] == "CONFLICTING_NOTIFICATION"
               for h in claim["history"])


# ------------------------------------------------------------------
# M13: transaccion desaparece del feed -> evidencia previa intacta


def test_m13_tx_disappears_prior_evidence_kept():
    claims = _proven_claims()
    cid = claims["claims"][0]["claim_id"]
    # un run posterior sin transacciones: assessment sin items
    empty = claim_assessment(
        _basis([]), _mc_rules(), jurisdiction="ES",
        assessment_date="2026-08-02", proceeds_rate="0.125")
    new = open_claims(empty)
    merged = merge_claims(claims, new)
    claim = find_claim(merged, cid)
    assert claim is not None
    assert claim["expected_amount"] == "125.000"
    assert claim["status"] == EXPECTED


# ------------------------------------------------------------------
# M14: sin regla de mercado -> MARKET_PRACTICE_REQUIRED


def test_m14_no_rule_market_practice_required():
    assessment = claim_assessment(
        _basis([_tx()]), None, jurisdiction="ES",
        assessment_date="2026-08-01", proceeds_rate="0.125")
    assert assessment["items"][0]["status"] == \
        MARKET_PRACTICE_REQUIRED


def test_m14_rule_for_other_event_not_applicable():
    rules = _mc_rules(event_type="STOCK_DIVIDEND")
    assessment = claim_assessment(
        _basis([_tx()]), rules, jurisdiction="ES",
        assessment_date="2026-08-01", proceeds_rate="0.125")
    item = assessment["items"][0]
    assert item["status"] == MARKET_PRACTICE_REQUIRED
    assert "NO_APPLICABLE_RULE" in item["reason_codes"]


def test_m14_window_not_met_not_applicable():
    # trade post ex-date: la ventana no se cumple -> NOT_APPLICABLE
    assessment = claim_assessment(
        _basis([_tx(trade="2026-07-28")]), _mc_rules(),
        jurisdiction="ES", assessment_date="2026-08-01",
        proceeds_rate="0.125")
    item = assessment["items"][0]
    assert item["status"] == NOT_APPLICABLE
    assert any(r.startswith("TRADE_RELATION_NOT_MET")
               for r in item["reason_codes"])


# ------------------------------------------------------------------
# M15: run identico -> determinismo / sin duplicados


def test_m15_deterministic_assessment_and_merge():
    a1 = claim_assessment(_basis([_tx()]), _mc_rules(),
                          jurisdiction="ES",
                          assessment_date="2026-08-01",
                          proceeds_rate="0.125")
    a2 = claim_assessment(_basis([_tx()]), _mc_rules(),
                          jurisdiction="ES",
                          assessment_date="2026-08-01",
                          proceeds_rate="0.125")
    a1.pop("generated_at")
    a2.pop("generated_at")
    assert a1 == a2
    c1 = open_claims(a1)
    merged = merge_claims(c1, open_claims(a2))
    assert len(merged["claims"]) == 1  # mismo claim_id: sin dup


# ------------------------------------------------------------------
# estatico: validacion del ruleset


def test_ruleset_validation_static():
    assert validate_claim_ruleset(_mc_rules()) == []
    bad = _mc_rules()
    bad["rules"][0]["claim_type"] = "XXXX"
    errors = validate_claim_ruleset(bad)
    assert errors
    bad2 = _mc_rules()
    bad2["rules"].append(dict(bad2["rules"][0]))
    errors2 = validate_claim_ruleset(bad2)
    assert any("duplicado" in e or "solapan" in e
               for e in errors2)


def test_settlement_status_gate():
    # SETTLED en fecha no cuenta: solo PENDING/SETTLED_LATE
    assessment = claim_assessment(
        _basis([_tx(status="SETTLED")]), _mc_rules(),
        jurisdiction="ES", assessment_date="2026-08-01",
        proceeds_rate="0.125")
    item = assessment["items"][0]
    assert item["status"] == NOT_APPLICABLE
    assert any(r.startswith("SETTLEMENT_STATUS_NOT_ELIGIBLE")
               for r in item["reason_codes"])


def test_settled_event_terminal():
    claims = _notified_claims()
    cid = claims["claims"][0]["claim_id"]
    recon = claim_recon(claims, [_movements("125.000", ref=cid)])
    assert recon["items"][0]["status"] == MATCH
    apply_claim_events(claims, [{
        "event_type": "SETTLEMENT_OBSERVED", "claim_id": cid,
        "at": "2026-08-03", "fully_settled": True}])
    assert find_claim(claims, cid)["status"] == SETTLED
    recon2 = claim_recon(claims, [_movements("125.000", ref=cid)])
    assert recon2["items"][0]["status"] == SETTLED
    assert classify_cases(recon2) == []
