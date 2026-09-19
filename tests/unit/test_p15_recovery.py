"""P15 — Tax Recovery Lifecycle (R1-R12).

Regla esencial bajo test: recoverable_amount NUNCA se deriva de
`actual > P14 expected`; solo de (regla recovery + perfil +
evidencia ACTUAL).
"""

from decimal import Decimal

from ca_es.exceptions import classify_cases
from ca_es.tax_recovery_assessment import (
    ELIGIBLE, EXPIRED, INDETERMINATE, NOT_APPLICABLE,
    recovery_assessment)
from ca_es.tax_recovery_case import (
    PENDING_DOCUMENTATION, READY_TO_SUBMIT, merge_claims,
    open_claims, transition)
from ca_es.tax_recovery_docs import document_sets
from ca_es.tax_recovery_instruction import (
    MANUAL_SUBMISSION_REQUIRED, READY, build_instructions)
from ca_es.tax_recovery_recon import recovery_recon
from ca_es.tax_recovery_rules import (
    RULES_SCHEMA, rule_deadline, validate_recovery_ruleset)
from ca_es.tax_recovery_status import apply_status_events

import pytest


# ------------------------------------------------------------------
# builders


def _tax_entitlement(gross="1562.50", account="ACC-1",
                     rate_fraction="0.19", wh="296.88",
                     status="CALCULATED"):
    item = {
        "account_id": account,
        "gross_entitlement": {"normalized": gross,
                              "currency": "EUR"},
        "tax_components": [{
            "component_type": "WITHHOLDING_PRIMARY",
            "amount": wh,
            "rate_fraction": rate_fraction,
            "currency": "EUR",
        }],
        "total_withholding": {"normalized": wh, "currency": "EUR"},
        "expected_net_cash": {"normalized": "1265.62",
                              "currency": "EUR"},
        "status": status,
        "reason_codes": [],
    }
    return {
        "schema": "CA_ES_TAX_ENTITLEMENT_V1",
        "canonical_event_id": "evt-1",
        "jurisdiction": "ES",
        "income_type": "DIVIDEND",
        "calculation_date": "2026-07-20",
        "items": [item],
    }


def _actual_evidence(rate=None, amount=None, ccy="EUR"):
    items = []
    if rate is not None:
        items.append({
            "tax_type": "WITHHOLDING_PRIMARY", "kind": "rate",
            "rate": rate, "rate_lexeme": rate,
            "rate_unit": "PERCENTAGE", "amount": None,
            "currency": None,
        })
    if amount is not None:
        items.append({
            "tax_type": "WITHHOLDING_PRIMARY", "kind": "amount",
            "rate": None, "amount": amount,
            "amount_lexeme": amount, "currency": ccy,
        })
    return {
        "schema": "CA_ES_TAX_EVIDENCE_V1",
        "evidence_role": "ACTUAL",
        "input_sha256": "sha-actual",
        "scopes": [{"scope": "CASH_MOVEMENT", "items": items}],
    }


def _profile(account="ACC-1", residency="ES", cls="PERSON",
             extra=None):
    p = {
        "account_id": account,
        "valid_from": "2020-01-01",
        "tax_residency": residency,
        "entity_person_classification": cls,
    }
    p.update(extra or {})
    return {"schema": "CA_ES_TAX_PROFILE_V1", "profiles": [p]}


def _rec_rules(method="STANDARD_RECLAIM", entitled="15",
               conditions=None, months=48,
               required_docs=None, submission=None,
               rule_id="ES-DIV-RECLAIM-001"):
    return {
        "schema": RULES_SCHEMA,
        "ruleset_id": "es-rec-v1",
        "rules": [{
            "rule_id": rule_id,
            "jurisdiction": "ES",
            "income_type": "DIVIDEND",
            "valid_from": "2016-01-01",
            "recovery_method": method,
            "entitled_rate": entitled,
            "rate_unit": "PERCENTAGE",
            "conditions": conditions if conditions is not None else {
                "tax_residency": ["ES"]},
            "deadline": {"basis": "PAYMENT_DATE", "months": months},
            "required_documents": required_docs or [],
            "submission": submission or {"channel": "MANUAL"},
        }],
    }


def _movements(amount, ref=None, ccy="EUR", direction="CRDT",
               mid="M-1"):
    return {
        "schema": "CA_ES_CASH_MOVEMENTS_V2",
        "movements": [{
            "movement_id": mid,
            "account_id": "ACC-1",
            "event_id": "evt-1",
            "amount": amount,
            "currency": ccy,
            "direction": direction,
            "source_reference": ref,
        }],
    }


def _eligible_setup(actual_rate="21", entitled="15",
                    method="STANDARD_RECLAIM", profile=None,
                    required_docs=None):
    """Escenario R2 base: actual 21%, regla demuestra 15%."""
    assessment = recovery_assessment(
        _tax_entitlement(), [_actual_evidence(rate=actual_rate)],
        profile if profile is not None else _profile(),
        _rec_rules(method=method, entitled=entitled,
                   required_docs=required_docs),
        jurisdiction="ES", income_type="DIVIDEND",
        assessment_date="2026-08-01", payment_date="2026-07-20")
    return assessment


# ------------------------------------------------------------------
# reglas: validacion estatica


def test_ruleset_valid():
    assert validate_recovery_ruleset(_rec_rules()) == []


def test_ruleset_rejects_bad_method_and_deadline():
    rules = _rec_rules()
    rules["rules"][0]["recovery_method"] = "TELEPORT"
    rules["rules"][0]["deadline"] = {"basis": "PAYMENT_DATE"}
    errors = validate_recovery_ruleset(rules)
    assert any("recovery_method" in e for e in errors)
    assert any("deadline.months" in e for e in errors)


def test_ruleset_rejects_overlap_same_method():
    rules = _rec_rules()
    rules["rules"].append(dict(rules["rules"][0],
                               rule_id="ES-DIV-RECLAIM-002"))
    errors = validate_recovery_ruleset(rules)
    assert any("solapan" in e for e in errors)


def test_rule_deadline_effective_dated():
    rule = _rec_rules(months=48)["rules"][0]
    assert rule_deadline(rule, "2026-07-20") == "2030-07-20"
    assert rule_deadline(rule, None) is None


# ------------------------------------------------------------------
# R1: 19% correcto desde origen -> NOT_APPLICABLE


def test_r1_correct_withholding_not_applicable():
    doc = recovery_assessment(
        _tax_entitlement(), [_actual_evidence(rate="19")],
        _profile(), _rec_rules(entitled="19"),
        jurisdiction="ES", income_type="DIVIDEND",
        assessment_date="2026-08-01", payment_date="2026-07-20")
    item = doc["items"][0]
    assert item["status"] == NOT_APPLICABLE
    assert "NO_RECOVERABLE_AMOUNT" in item["reason_codes"]
    assert item["recoverable_amount"] is None


# ------------------------------------------------------------------
# R2: 21% retenido, regla demuestra 19% -> ELIGIBLE, claim 2%


def test_r2_overwithholding_eligible():
    doc = _eligible_setup(actual_rate="21", entitled="19")
    item = doc["items"][0]
    assert item["status"] == ELIGIBLE
    recoverable = Decimal(item["recoverable_amount"]["normalized"])
    # 1562.50 * (0.21 - 0.19) = 31.25
    assert recoverable == Decimal("31.25")
    assert item["recoverable_amount"]["currency"] == "EUR"
    assert item["claim_reference"] == (
        "evt-1|ACC-1|ES-DIV-RECLAIM-001|STANDARD_RECLAIM")


def test_r2_claim_amount_never_from_expected_gap():
    # P14 expected (19%) != regla entitled (15%): el claim usa la
    # REGLA, no el gap expected-vs-actual
    doc = _eligible_setup(actual_rate="21", entitled="15")
    item = doc["items"][0]
    recoverable = Decimal(item["recoverable_amount"]["normalized"])
    assert recoverable == Decimal("93.75")  # 1562.50 * 0.06


# ------------------------------------------------------------------
# R3: diferencia fiscal pero perfil incompleto -> INDETERMINATE


def test_r3_incomplete_profile_indeterminate():
    doc = recovery_assessment(
        _tax_entitlement(), [_actual_evidence(rate="21")],
        None, _rec_rules(entitled="19"),
        jurisdiction="ES", income_type="DIVIDEND",
        assessment_date="2026-08-01", payment_date="2026-07-20")
    item = doc["items"][0]
    assert item["status"] == INDETERMINATE
    assert "NO_TAX_PROFILE" in item["reason_codes"]
    # y nunca se fabrica un claim desde INDETERMINATE
    claims = open_claims(doc)
    assert claims["claims"] == []


def test_r3_profile_field_missing():
    rules = _rec_rules(entitled="15",
                       conditions={"treaty_profile": ["ES-FR"]})
    doc = recovery_assessment(
        _tax_entitlement(), [_actual_evidence(rate="21")],
        _profile(), rules,
        jurisdiction="ES", income_type="DIVIDEND",
        assessment_date="2026-08-01", payment_date="2026-07-20")
    item = doc["items"][0]
    assert item["status"] == INDETERMINATE
    assert any("TREATY_PROFILE" in r
               for r in item["reason_codes"])


# ------------------------------------------------------------------
# R4: relief at source aprobado antes del pago


def test_r4_relief_at_source():
    rules = _rec_rules(method="RELIEF_AT_SOURCE", entitled="15",
                       conditions={
                           "tax_residency": ["ES"],
                           "relief_at_source_status": ["APPROVED"]},
                       months=0)
    profile = _profile(extra={"relief_at_source_status": "APPROVED"})
    doc = recovery_assessment(
        _tax_entitlement(), [], profile, rules,
        jurisdiction="ES", income_type="DIVIDEND",
        assessment_date="2026-07-15", payment_date="2026-07-20")
    item = doc["items"][0]
    assert item["status"] == ELIGIBLE
    assert item["claim_kind"] == "RATE_RELIEF"
    # prospective: 1562.50 * (0.19 - 0.15) = 62.50
    assert Decimal(item["prospective_amount"]["normalized"]) == \
        Decimal("62.50")


def test_r4_relief_closed_after_payment():
    rules = _rec_rules(method="RELIEF_AT_SOURCE", entitled="15",
                       months=0)
    doc = recovery_assessment(
        _tax_entitlement(), [_actual_evidence(rate="19")],
        _profile(), rules,
        jurisdiction="ES", income_type="DIVIDEND",
        assessment_date="2026-08-01", payment_date="2026-07-20")
    item = doc["items"][0]
    assert item["status"] == NOT_APPLICABLE
    assert "PAYMENT_ALREADY_EVIDENCED" in item["reason_codes"]


# ------------------------------------------------------------------
# R5/R6: documentacion -> PENDING vs READY


def _claim_with_docs(required_docs, provided):
    assessment = _eligible_setup(
        required_docs=required_docs)
    claims = open_claims(assessment)
    rules = _rec_rules(entitled="19",
                       required_docs=required_docs)
    sets = document_sets(claims, rules, provided)
    return claims, rules, sets


def test_r5_incomplete_docs_pending():
    claims, rules, sets = _claim_with_docs(
        ["RESIDENCE_CERTIFICATE", "TAX_RECLAIM_FORM"],
        [{"doc_type": "RESIDENCE_CERTIFICATE",
          "reference": "CERT-1"}])
    ds = sets["sets"][claims["claims"][0]["claim_id"]]
    assert ds["set_status"] == "INCOMPLETE"
    ins = build_instructions(claims, sets, rules)
    assert ins["instructions"][0]["status"] == "BLOCKED"
    # y el claim no puede saltar a SUBMITTED sin docs
    claim = claims["claims"][0]
    with pytest.raises(ValueError):
        transition(claim, "SUBMITTED", at="2026-08-02",
                   actor="ops")


def test_r5_claim_opens_pending_documentation():
    assessment = _eligible_setup(required_docs=["TAX_RECLAIM_FORM"])
    claims = open_claims(
        assessment,
        doc_complete={assessment["items"][0][
            "claim_reference"]: False})
    assert claims["claims"][0]["status"] == PENDING_DOCUMENTATION


def test_r6_complete_docs_ready():
    claims, rules, sets = _claim_with_docs(
        ["RESIDENCE_CERTIFICATE"],
        [{"doc_type": "RESIDENCE_CERTIFICATE",
          "reference": "CERT-1"}])
    ds = sets["sets"][claims["claims"][0]["claim_id"]]
    assert ds["set_status"] == "COMPLETE"
    claim = claims["claims"][0]
    transition(claim, READY_TO_SUBMIT, at="2026-08-02",
               actor="ops")
    ins = build_instructions(claims, sets, rules)
    assert ins["instructions"][0]["status"] == (
        MANUAL_SUBMISSION_REQUIRED)


# ------------------------------------------------------------------
# R7: provider ausente -> MANUAL, nunca fabricar canal


def test_r7_no_provider_manual_required():
    claims, rules, sets = _claim_with_docs(
        ["TAX_RECLAIM_FORM"],
        [{"doc_type": "TAX_RECLAIM_FORM",
          "reference": "FORM-210"}])
    rules["rules"][0]["submission"] = {
        "channel": "PROVIDER_PROFILE"}
    claim = claims["claims"][0]
    transition(claim, READY_TO_SUBMIT, at="2026-08-02",
               actor="ops")
    ins = build_instructions(claims, sets, rules,
                             provider_doc=None)
    item = ins["instructions"][0]
    assert item["status"] == MANUAL_SUBMISSION_REQUIRED
    assert "FELL_BACK_TO_MANUAL" in item["reason_codes"]
    assert item["payload"]["payload_format"] == "INTERNAL_V1"


def test_r7_provider_profile_ready():
    claims, rules, sets = _claim_with_docs(
        ["TAX_RECLAIM_FORM"],
        [{"doc_type": "TAX_RECLAIM_FORM",
          "reference": "FORM-210"}])
    rules["rules"][0]["submission"] = {
        "channel": "PROVIDER_PROFILE"}
    provider = {
        "schema": "CA_ES_TAX_RECOVERY_PROVIDER_V1",
        "provider_id": "cust-x",
        "channel": "SFTP",
        "endpoint_ref": "sftp://configured-endpoint-ref",
    }
    claim = claims["claims"][0]
    transition(claim, READY_TO_SUBMIT, at="2026-08-02",
               actor="ops")
    ins = build_instructions(claims, sets, rules, provider)
    item = ins["instructions"][0]
    assert item["status"] == READY
    assert item["submission_channel"] == "SFTP"
    assert item["provider_id"] == "cust-x"


# ------------------------------------------------------------------
# R8/R9: receipts y rechazos


def _ready_claim(**kw):
    """Claim abierto y llevado a READY_TO_SUBMIT (docs no
    requeridos / set completo evaluado)."""
    assessment = _eligible_setup(**kw)
    cid = assessment["items"][0]["claim_reference"]
    claims = open_claims(assessment, doc_complete={cid: True})
    assert claims["claims"][0]["status"] == READY_TO_SUBMIT
    return claims, cid


def _submitted_claim():
    claims, cid = _ready_claim()
    events = [
        {"claim_id": cid,
         "event_type": "SUBMISSION_RECORDED",
         "at": "2026-08-05", "source_ref": "manual:batch-1"},
        {"claim_id": cid,
         "event_type": "RECEIPT",
         "at": "2026-08-10", "source_ref": "provider:ack-9"},
    ]
    status = apply_status_events(claims, events)
    return claims, status


def test_r8_receipt_acknowledges():
    claims, status = _submitted_claim()
    assert claims["claims"][0]["status"] == "ACKNOWLEDGED"
    assert all(o["outcome"] == "APPLIED"
               for o in status["outcomes"])


def test_r9_explicit_rejection_case():
    claims, _ = _submitted_claim()
    cid = claims["claims"][0]["claim_id"]
    apply_status_events(claims, [{
        "claim_id": cid, "event_type": "REJECTION",
        "at": "2026-08-15", "source_ref": "provider:rej-1",
        "reason_code": "DOC_INVALID"}])
    assert claims["claims"][0]["status"] == "REJECTED"
    recon = recovery_recon(claims)
    assert recon["items"][0]["status"] == "REJECTED"
    cases = classify_cases(recon)
    assert len(cases) == 1
    assert cases[0]["priority"] == "HIGH"
    assert cases[0]["case_key"].startswith("tax-recovery|")


def test_invalid_transition_rejected_event():
    assessment = _eligible_setup()
    claims = open_claims(assessment)
    cid = claims["claims"][0]["claim_id"]
    status = apply_status_events(claims, [{
        "claim_id": cid, "event_type": "ACCEPTANCE",
        "at": "2026-08-05"}])
    assert status["outcomes"][0]["outcome"] == "REJECTED_EVENT"
    assert claims["claims"][0]["status"] == "ASSESSED"


# ------------------------------------------------------------------
# R10/R11: refund cash por referencia explicita


def test_r10_partial_and_full_refund():
    claims, cid = _ready_claim(actual_rate="21", entitled="19")
    movements = _movements("20.00", ref=cid, mid="M-1")
    recon = recovery_recon(claims, movements_docs=[movements])
    item = recon["items"][0]
    # claim NO esta submitted aun -> NOT_SUBMITTED
    assert item["status"] == "NOT_SUBMITTED"

    apply_status_events(claims, [
        {"claim_id": cid, "event_type": "SUBMISSION_RECORDED",
         "at": "2026-08-05"},
        {"claim_id": cid, "event_type": "RECEIPT",
         "at": "2026-08-10"},
        {"claim_id": cid, "event_type": "ACCEPTANCE",
         "at": "2026-08-12"}])
    recon = recovery_recon(claims, movements_docs=[movements])
    item = recon["items"][0]
    assert item["status"] == "PARTIALLY_PAID"
    assert Decimal(item["refunded_amount"]) == Decimal("20.00")
    assert Decimal(item["outstanding_amount"]) == Decimal("11.25")

    movements["movements"].append({
        "movement_id": "M-2", "account_id": "ACC-1",
        "event_id": "evt-1", "amount": "11.25",
        "currency": "EUR", "direction": "CRDT",
        "source_reference": cid})
    recon = recovery_recon(claims, movements_docs=[movements])
    assert recon["items"][0]["status"] == "PAID"


def test_r10_refund_via_tare_reference():
    claims, cid = _ready_claim(actual_rate="21", entitled="19")
    sets = document_sets(
        claims, _rec_rules(entitled="19"),
        [{"doc_type": "RECLAIM_DOCUMENTATION_REFERENCE",
          "reference": "TAXFORM-2026-0042"}])
    movements = _movements("31.25", ref="TAXFORM-2026-0042")
    recon = recovery_recon(claims, doc_sets_doc=sets,
                           movements_docs=[movements])
    # claim no submitted aun -> NOT_SUBMITTED (binding no evaluado)
    assert recon["items"][0]["status"] == "NOT_SUBMITTED"
    apply_status_events(claims, [
        {"claim_id": cid, "event_type": "SUBMISSION_RECORDED",
         "at": "2026-08-05"},
        {"claim_id": cid, "event_type": "RECEIPT",
         "at": "2026-08-10"}])
    recon = recovery_recon(claims, doc_sets_doc=sets,
                           movements_docs=[movements])
    assert recon["items"][0]["status"] == "PAID"


def test_r11_same_amount_no_reference_no_match():
    claims, cid = _ready_claim(actual_rate="21", entitled="19")
    apply_status_events(claims, [
        {"claim_id": cid, "event_type": "SUBMISSION_RECORDED",
         "at": "2026-08-05"},
        {"claim_id": cid, "event_type": "RECEIPT",
         "at": "2026-08-10"}])
    # mismo importe exacto, sin referencia: NUNCA liga
    movements = _movements("31.25", ref=None)
    recon = recovery_recon(claims, movements_docs=[movements])
    item = recon["items"][0]
    assert item["status"] == "NO_REFUND_OBSERVED"
    assert "NO_EXPLICIT_REFERENCE_MATCH" in item["reason_codes"]
    assert item["bound_movement_ids"] == []


def test_r11_overpaid_is_case():
    claims, cid = _ready_claim(actual_rate="21", entitled="19")
    apply_status_events(claims, [
        {"claim_id": cid, "event_type": "SUBMISSION_RECORDED",
         "at": "2026-08-05"}])
    movements = _movements("50.00", ref=cid)
    recon = recovery_recon(claims, movements_docs=[movements])
    assert recon["items"][0]["status"] == "OVERPAID"
    cases = classify_cases(recon)
    assert len(cases) == 1
    assert cases[0]["priority"] == "HIGH"


def test_fx_divergent_refund_blocked():
    claims, cid = _ready_claim(actual_rate="21", entitled="19")
    apply_status_events(claims, [
        {"claim_id": cid, "event_type": "SUBMISSION_RECORDED",
         "at": "2026-08-05"}])
    movements = _movements("31.25", ref=cid, ccy="USD")
    recon = recovery_recon(claims, movements_docs=[movements])
    assert recon["items"][0]["status"] == "INDETERMINATE"
    assert "FX_REQUIRED" in recon["items"][0]["reason_codes"]


# ------------------------------------------------------------------
# R12: deadline vencido


def test_r12_expired_assessment():
    doc = recovery_assessment(
        _tax_entitlement(), [_actual_evidence(rate="21")],
        _profile(), _rec_rules(entitled="19", months=1),
        jurisdiction="ES", income_type="DIVIDEND",
        assessment_date="2026-09-01",  # deadline 2026-08-20
        payment_date="2026-07-20")
    item = doc["items"][0]
    assert item["status"] == EXPIRED
    assert "RECOVERY_DEADLINE_PASSED" in item["reason_codes"]
    assert item["deadline_date"] == "2026-08-20"


def test_r12_expiry_check_event():
    assessment = _eligible_setup(actual_rate="21", entitled="19")
    claims = open_claims(assessment)
    cid = claims["claims"][0]["claim_id"]
    status = apply_status_events(claims, [{
        "claim_id": cid, "event_type": "EXPIRY_CHECK",
        "at": "2031-01-01"}])
    assert claims["claims"][0]["status"] == "EXPIRED"
    assert status["outcomes"][0]["to_status"] == "EXPIRED"


# ------------------------------------------------------------------
# extras: evidencia en amount (single account), conflicting actual


def test_amount_level_evidence_single_account():
    doc = recovery_assessment(
        _tax_entitlement(),
        [_actual_evidence(amount="328.13")],  # 21% de 1562.50
        _profile(), _rec_rules(entitled="19"),
        jurisdiction="ES", income_type="DIVIDEND",
        assessment_date="2026-08-01", payment_date="2026-07-20")
    item = doc["items"][0]
    assert item["status"] == ELIGIBLE
    # 328.13 - 1562.50*0.19 = 328.13 - 296.875 = 31.255
    assert Decimal(item["recoverable_amount"]["normalized"]) == \
        Decimal("31.255")


def test_conflicting_actual_rates_indeterminate():
    ev = _actual_evidence(rate="21")
    ev["scopes"][0]["items"].append({
        "tax_type": "WITHHOLDING_PRIMARY", "kind": "rate",
        "rate": "22", "rate_lexeme": "22",
        "rate_unit": "PERCENTAGE", "amount": None,
        "currency": None})
    doc = recovery_assessment(
        _tax_entitlement(), [ev], _profile(),
        _rec_rules(entitled="19"),
        jurisdiction="ES", income_type="DIVIDEND",
        assessment_date="2026-08-01", payment_date="2026-07-20")
    item = doc["items"][0]
    assert item["status"] == INDETERMINATE
    assert "CONFLICTING_ACTUAL_WITHHOLDING" in item["reason_codes"]


def test_no_actual_evidence_indeterminate():
    doc = recovery_assessment(
        _tax_entitlement(), [], _profile(),
        _rec_rules(entitled="19"),
        jurisdiction="ES", income_type="DIVIDEND",
        assessment_date="2026-08-01", payment_date="2026-07-20")
    assert doc["items"][0]["status"] == INDETERMINATE
    assert "NO_ACTUAL_WITHHOLDING_EVIDENCE" in \
        doc["items"][0]["reason_codes"]


def test_claim_persistence_merge():
    assessment = _eligible_setup()
    claims1 = open_claims(assessment)
    cid = claims1["claims"][0]["claim_id"]
    transition(claims1["claims"][0], READY_TO_SUBMIT,
               at="2026-08-02", actor="ops")
    # re-assessment: el claim vivo no se reabre ni se duplica
    claims2 = merge_claims(claims1, open_claims(assessment))
    assert len(claims2["claims"]) == 1
    assert claims2["claims"][0]["status"] == READY_TO_SUBMIT
    assert claims2["claims"][0]["claim_id"] == cid
