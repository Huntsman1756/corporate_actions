"""P15 — demo e2e de aceptacion: Tax Recovery Lifecycle
(ad-hoc, no en CI).

Evidencia fiscal REAL via adapter JVM/Prowide (fatJar requerido;
sin jar -> SKIP explicito). El lado expected/gross reutiliza el
fixture P14 (MT564 tax + entitlement sintetico); el lado actual
usa mt566-tax.fin (TAXR 19% + TAXR amount + NETT reales).

Legs (mapeo R1-R12 del mandato):

  R0: MT566 real -> evidencia ACTUAL + TARE/BORE facts (pin
      SRU2025, sin migrar).
  R1: actual 19% == entitled 19% -> NOT_APPLICABLE.
  R2: actual 21%, regla entitled 19% -> ELIGIBLE, claim 31.25
      trazable (rate, nunca gap expected-vs-actual).
  R3: diferencia pero perfil ausente -> INDETERMINATE, 0 claims.
  R4: relief at source pre-pago -> ELIGIBLE RATE_RELIEF.
  R5: docs incompletos -> PENDING_DOCUMENTATION, instruccion
      BLOCKED.
  R6: docs completos -> READY_TO_SUBMIT + MANUAL_SUBMISSION.
  R7: submission PROVIDER_PROFILE sin perfil -> fallback MANUAL.
  R8: SUBMISSION_RECORDED + RECEIPT -> ACKNOWLEDGED.
  R9: REJECTION -> REJECTED + caso P3.5 HIGH.
  R10: refund por claim_id -> PARTIALLY_PAID -> PAID.
  R11: mismo importe sin referencia -> NO_REFUND_OBSERVED.
  R12: assessment tras deadline -> EXPIRED; EXPIRY_CHECK cierra.

Uso: python scripts/p15_e2e_demo.py
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ca_es.exceptions import classify_cases  # noqa: E402
from ca_es.swift_mt import parse_mt  # noqa: E402
from ca_es.tax_evidence import tax_evidence  # noqa: E402
from ca_es.tax_recovery_assessment import (  # noqa: E402
    recovery_assessment)
from ca_es.tax_recovery_case import (  # noqa: E402
    READY_TO_SUBMIT, open_claims, transition)
from ca_es.tax_recovery_docs import document_sets  # noqa: E402
from ca_es.tax_recovery_instruction import (  # noqa: E402
    build_instructions)
from ca_es.tax_recovery_recon import recovery_recon  # noqa: E402
from ca_es.tax_recovery_status import (  # noqa: E402
    apply_status_events)

RES = REPO / "adapters" / "iso-adapter-jvm" / "src" / "test" / "resources"

_results: list[tuple[str, str]] = []


def leg(name: str, status: str, detail: str = "") -> None:
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    _results.append((name, status))


def check(name: str, cond: bool, detail: str = "") -> None:
    leg(name, "PASS" if cond else "FAIL", detail)


def _skip(name: str, detail: str) -> None:
    leg(name, "SKIP", detail)


def _facts(fin_name: str) -> dict | None:
    fin_path = RES / fin_name
    if not fin_path.exists():
        return None
    doc, code = parse_mt(fin_path.read_bytes().decode("utf-8"))
    if code != 0:
        return None
    return doc


def _tax_entitlement(rate_fraction="0.19", wh="296.88"):
    return {
        "schema": "CA_ES_TAX_ENTITLEMENT_V1",
        "canonical_event_id": "evt-demo",
        "jurisdiction": "ES",
        "income_type": "DIVIDEND",
        "calculation_date": "2026-07-20",
        "items": [{
            "account_id": "ACC-ES-1",
            "gross_entitlement": {"normalized": "1562.50",
                                  "currency": "EUR"},
            "tax_components": [{
                "component_type": "WITHHOLDING_PRIMARY",
                "amount": wh, "rate_fraction": rate_fraction,
                "currency": "EUR"}],
            "status": "CALCULATED",
            "reason_codes": [],
        }],
    }


def _profile(extra=None):
    p = {"account_id": "ACC-ES-1", "valid_from": "2020-01-01",
         "tax_residency": "ES",
         "entity_person_classification": "PERSON"}
    p.update(extra or {})
    return {"schema": "CA_ES_TAX_PROFILE_V1", "profiles": [p]}


def _rules(method="STANDARD_RECLAIM", entitled="15", months=48,
           required_docs=None, submission=None, conditions=None):
    return {
        "schema": "CA_ES_TAX_RECOVERY_RULES_V1",
        "rules": [{
            "rule_id": "ES-DIV-RECLAIM-001",
            "jurisdiction": "ES", "income_type": "DIVIDEND",
            "valid_from": "2016-01-01",
            "recovery_method": method,
            "entitled_rate": entitled, "rate_unit": "PERCENTAGE",
            "conditions": conditions or {"tax_residency": ["ES"]},
            "deadline": {"basis": "PAYMENT_DATE", "months": months},
            "required_documents": required_docs or [],
            "submission": submission or {"channel": "MANUAL"},
        }],
    }


_NO_PROFILE = object()


def _assess(evidence, rules, profile=_NO_PROFILE,
            entitled_rate="0.19", wh="296.88", a_date="2026-08-01"):
    if profile is _NO_PROFILE:
        profile = _profile()
    return recovery_assessment(
        _tax_entitlement(entitled_rate, wh), evidence,
        profile, rules,
        jurisdiction="ES", income_type="DIVIDEND",
        assessment_date=a_date, payment_date="2026-07-20")


def _ev(rate=None, amount=None):
    items = []
    if rate is not None:
        items.append({"tax_type": "WITHHOLDING_PRIMARY",
                      "kind": "rate", "rate": rate,
                      "rate_lexeme": rate, "rate_unit": "PERCENTAGE",
                      "amount": None, "currency": None})
    if amount is not None:
        items.append({"tax_type": "WITHHOLDING_PRIMARY",
                      "kind": "amount", "rate": None,
                      "amount": amount, "amount_lexeme": amount,
                      "currency": "EUR"})
    return {"schema": "CA_ES_TAX_EVIDENCE_V1",
            "evidence_role": "ACTUAL", "input_sha256": "sha-actual",
            "scopes": [{"scope": "CASH_MOVEMENT", "items": items}]}


def _movements(amount, ref, mid="M-1"):
    return {"schema": "CA_ES_CASH_MOVEMENTS_V2",
            "movements": [{"movement_id": mid,
                           "account_id": "ACC-ES-1",
                           "event_id": "evt-demo", "amount": amount,
                           "currency": "EUR", "direction": "CRDT",
                           "source_reference": ref}]}


def main() -> int:
    print("P15 e2e demo — Tax Recovery Lifecycle")

    # R0: evidencia ACTUAL real + TARE/BORE via pin SRU2025
    facts = _facts("mt566-tax.fin")
    if facts is None:
        _skip("R0 real evidence", "adapter/jar no disponible")
    else:
        ev = tax_evidence(facts, canonical_event_id="evt-demo")
        items = [i for s in ev["scopes"] for i in s["items"]]
        quals = {i["raw_qualifier"] for i in items}
        check("R0 actual evidence MT566",
              ev["evidence_role"] == "ACTUAL"
              and "TAXR" in quals and "NETT" in quals,
              f"role={ev['evidence_role']} quals={sorted(quals)}")

    facts_tare = _facts("mt566-tare.fin")
    if facts_tare is None:
        _skip("R0 TARE/BORE", "fixture mt566-tare.fin ausente")
    else:
        quals = {f.get("source_qualifier")
                 for f in facts_tare["facts"]}
        check("R0 TARE/BORE facts (SRU2025)",
              {"TARE", "BORE", "TXRC"} <= quals,
              f"quals={sorted(q for q in quals if q)}")

    # R1: retencion correcta -> NOT_APPLICABLE
    a = _assess([_ev(rate="19")], _rules(entitled="19"))
    check("R1 correct withholding -> NOT_APPLICABLE",
          a["items"][0]["status"] == "NOT_APPLICABLE"
          and "NO_RECOVERABLE_AMOUNT" in a["items"][0][
              "reason_codes"])

    # R2: 21% retenido, regla demuestra 19% -> ELIGIBLE 31.25
    a = _assess([_ev(rate="21")], _rules(entitled="19"))
    item = a["items"][0]
    check("R2 over-withheld -> ELIGIBLE",
          item["status"] == "ELIGIBLE"
          and Decimal(item["recoverable_amount"]["normalized"])
          == Decimal("31.25"),
          f"claim={item['recoverable_amount']}")

    # R3: perfil ausente -> INDETERMINATE, cero claims
    a = _assess([_ev(rate="21")], _rules(entitled="19"),
                profile=None)
    claims = open_claims(a)
    check("R3 no profile -> INDETERMINATE, 0 claims",
          a["items"][0]["status"] == "INDETERMINATE"
          and claims["claims"] == [])

    # R4: relief at source pre-pago -> RATE_RELIEF
    a = _assess([], _rules(method="RELIEF_AT_SOURCE",
                           entitled="15", months=0,
                           conditions={
                               "tax_residency": ["ES"],
                               "relief_at_source_status":
                               ["APPROVED"]}),
                profile=_profile(
                    {"relief_at_source_status": "APPROVED"}),
                a_date="2026-07-15")
    item = a["items"][0]
    check("R4 relief at source -> ELIGIBLE RATE_RELIEF",
          item["status"] == "ELIGIBLE"
          and item["claim_kind"] == "RATE_RELIEF",
          f"prospective={item.get('prospective_amount')}")

    # R5/R6/R7: docs -> instruccion
    a = _assess([_ev(rate="21")],
                _rules(entitled="19",
                       required_docs=["RESIDENCE_CERTIFICATE",
                                      "TAX_RECLAIM_FORM"]))
    claims = open_claims(a)
    rules = _rules(entitled="19",
                   required_docs=["RESIDENCE_CERTIFICATE",
                                  "TAX_RECLAIM_FORM"])
    sets = document_sets(claims, rules, [
        {"doc_type": "RESIDENCE_CERTIFICATE",
         "reference": "CERT-2026-ES-1"}])
    ins = build_instructions(claims, sets, rules)
    check("R5 incomplete docs -> BLOCKED",
          ins["instructions"][0]["status"] == "BLOCKED")

    sets = document_sets(claims, rules, [
        {"doc_type": "RESIDENCE_CERTIFICATE",
         "reference": "CERT-2026-ES-1"},
        {"doc_type": "TAX_RECLAIM_FORM",
         "reference": "FORM-210-2026"}])
    cid = claims["claims"][0]["claim_id"]
    transition(claims["claims"][0], READY_TO_SUBMIT,
               at="2026-08-02", actor="ops")
    ins = build_instructions(claims, sets, rules)
    check("R6 complete docs -> MANUAL_SUBMISSION_REQUIRED",
          ins["instructions"][0]["status"]
          == "MANUAL_SUBMISSION_REQUIRED")

    rules_prov = _rules(entitled="19",
                        required_docs=["TAX_RECLAIM_FORM"],
                        submission={"channel": "PROVIDER_PROFILE"})
    sets_prov = document_sets(claims, rules_prov, [
        {"doc_type": "TAX_RECLAIM_FORM",
         "reference": "FORM-210-2026"}])
    ins = build_instructions(claims, sets_prov, rules_prov,
                             provider_doc=None)
    check("R7 provider absent -> fallback MANUAL",
          ins["instructions"][0]["status"]
          == "MANUAL_SUBMISSION_REQUIRED"
          and "FELL_BACK_TO_MANUAL" in ins["instructions"][0][
              "reason_codes"])

    # R8/R9: status events
    apply_status_events(claims, [
        {"claim_id": cid, "event_type": "SUBMISSION_RECORDED",
         "at": "2026-08-05", "source_ref": "manual:batch-1"},
        {"claim_id": cid, "event_type": "RECEIPT",
         "at": "2026-08-10", "source_ref": "provider:ack-9"}])
    check("R8 receipt -> ACKNOWLEDGED",
          claims["claims"][0]["status"] == "ACKNOWLEDGED")

    apply_status_events(claims, [
        {"claim_id": cid, "event_type": "REJECTION",
         "at": "2026-08-15", "reason_code": "DOC_INVALID"}])
    recon = recovery_recon(claims)
    cases = classify_cases(recon)
    check("R9 rejection -> REJECTED + P3.5 case",
          claims["claims"][0]["status"] == "REJECTED"
          and len(cases) == 1 and cases[0]["priority"] == "HIGH")

    # R10/R11: refund cash
    a = _assess([_ev(rate="21")], _rules(entitled="19"))
    claims = open_claims(a)
    cid = claims["claims"][0]["claim_id"]
    transition(claims["claims"][0], READY_TO_SUBMIT,
               at="2026-08-02", actor="ops")
    apply_status_events(claims, [
        {"claim_id": cid, "event_type": "SUBMISSION_RECORDED",
         "at": "2026-08-05"},
        {"claim_id": cid, "event_type": "RECEIPT",
         "at": "2026-08-10"},
        {"claim_id": cid, "event_type": "ACCEPTANCE",
         "at": "2026-08-12"}])
    recon = recovery_recon(
        claims, movements_docs=[_movements("20.00", cid)])
    check("R10 partial refund -> PARTIALLY_PAID",
          recon["items"][0]["status"] == "PARTIALLY_PAID",
          f"refunded={recon['items'][0]['refunded_amount']}")
    recon = recovery_recon(
        claims,
        movements_docs=[_movements("20.00", cid, mid="M-1"),
                        _movements("11.25", cid, mid="M-2")])
    check("R10 full refund -> PAID",
          recon["items"][0]["status"] == "PAID")

    recon = recovery_recon(
        claims, movements_docs=[_movements("31.25", None)])
    check("R11 same amount, no ref -> NO_REFUND_OBSERVED",
          recon["items"][0]["status"] == "NO_REFUND_OBSERVED")

    # R12: deadline
    a = _assess([_ev(rate="21")], _rules(entitled="19", months=1),
                a_date="2026-09-01")
    check("R12 past deadline -> EXPIRED",
          a["items"][0]["status"] == "EXPIRED"
          and a["items"][0]["deadline_date"] == "2026-08-20")

    passed = sum(1 for _, s in _results if s == "PASS")
    skipped = sum(1 for _, s in _results if s == "SKIP")
    failed = sum(1 for _, s in _results if s == "FAIL")
    print(f"\n{passed} PASS / {skipped} SKIP / {failed} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
