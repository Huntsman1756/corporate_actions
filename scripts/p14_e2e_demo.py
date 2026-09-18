"""P14 — demo e2e de aceptacion: Tax, Withholding & Net Entitlement
(ad-hoc, no en CI).

Evidencia fiscal REAL via adapter JVM/Prowide (fatJar requerido;
sin jar -> SKIP explicito). Entitlement gross sintetico (el lado
gross ya quedo probado e2e en el demo P13; aqui se prueba la rama
fiscal completa).

Legs:

  T1: MT564 TAXR real -> evidence -> profile+rules ES 19% ->
      gross 1562.50 -> withholding 296.88 -> expected net 1265.62.
  T2: movimiento NET real 1265.62 -> reconcile -> MATCH.
  T3: NET erroneo 1200.00 -> AMOUNT_MISMATCH -> caso P3.5 estable.
  T4: sin tax profile -> INDETERMINATE, net no fabricado.
  T5: TAXR fuente 15% vs regla 19% -> CONFLICTING, sin ganador.
  T6: payment date 2013 -> regla historica 21% -> 328.13.
  T7: mismo evento + perfil distinto (residencia FR) ->
      RULE_NOT_APPLICABLE: la rama fiscal cambia, el gross no.
  T8: actual MT566 con gross+WTAX+net explicitos -> tax recon
      MATCH + cash recon MATCH consistentes.
  T9: gross-net sin componente tax explicito -> tax actual sigue
      desconocido (MISSING_TAX_COMPONENT, no se infiere).

Uso: python scripts/p14_e2e_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ca_es.exceptions import classify_cases  # noqa: E402
from ca_es.reconciliation import reconcile  # noqa: E402
from ca_es.swift_mt import default_adapter_jar, parse_mt  # noqa: E402
from ca_es.tax_entitlement import (expected_cash,  # noqa: E402
                                   tax_entitlement)
from ca_es.tax_evidence import tax_evidence  # noqa: E402
from ca_es.tax_recon import tax_recon  # noqa: E402

RES = REPO / "adapters" / "iso-adapter-jvm" / "src" / "test" / "resources"

_results: list[tuple[str, str]] = []


def leg(name: str, status: str, detail: str = "") -> None:
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    _results.append((name, status))


def _facts(fin_name: str) -> dict:
    fin = (RES / fin_name).read_bytes().decode("utf-8")
    doc, code = parse_mt(fin)
    assert code == 0, f"parse {fin_name} -> {code}"
    return doc


def _entitlement(gross="1562.50", ccy="EUR"):
    return {
        "schema": "CA_ES_ENTITLEMENT_V1",
        "canonical_event_id": "evt-demo",
        "entitlements": [{
            "account_id": "ACC-ES-1",
            "isin": "ES0113900J37",
            "status": "ENTITLED",
            "gross_cash": {"normalized": gross, "currency": ccy},
            "reasons": [],
            "evidence": {},
        }],
    }


def _rules(periods=None):
    base = {
        "rule_id": "ES-DIV-WH-CURRENT",
        "jurisdiction": "ES",
        "income_type": "DIVIDEND",
        "valid_from": "2016-01-01",
        "rate_source": "CONFIGURED_STATUTORY_RATE",
        "rate": "19",
        "rate_unit": "PERCENTAGE",
        "calculation_basis": "GROSS_ENTITLEMENT",
        "conditions": {
            "tax_residency": ["ES"],
            "entity_person_classification": ["PERSON", "ENTITY"],
        },
        "rounding": {"mode": "HALF_UP", "scale": 2,
                     "currency": "EUR"},
        "authority": "L35/2006 art.101; AEAT cuadro 2026",
    }
    rules = [base]
    for p in periods or []:
        rules.append({**base, **p})
    return {"schema": "CA_ES_TAX_RULES_V1",
            "ruleset_id": "es-dividend-v1", "rules": rules}


def _profile(**kw):
    p = {
        "account_id": "ACC-ES-1",
        "valid_from": "2020-01-01",
        "tax_residency": "ES",
        "entity_person_classification": "PERSON",
    }
    p.update(kw)
    return {"schema": "CA_ES_TAX_PROFILE_V1",
            "profile_id": "demo", "profiles": [p]}


def _movements(amount, basis="NET"):
    return {
        "schema": "CA_ES_CASH_MOVEMENTS_V2",
        "movements": [{
            "movement_id": "M-DEMO-1",
            "event_id": "evt-demo",
            "account_id": "ACC-ES-1",
            "isin": "ES0113900J37",
            "amount": amount,
            "currency": "EUR",
            "amount_basis": basis,
        }],
    }


def _tax(ev_extra=(), profile=None, rules=None, date="2026-07-20"):
    ev = [tax_evidence(_facts("mt564-tax.fin"))]
    ev.extend(ev_extra)
    return tax_entitlement(
        _entitlement(), ev, profile or _profile(),
        rules or _rules(), jurisdiction="ES",
        income_type="DIVIDEND", calculation_date=date,
        now="2026-07-20T09:00:00Z")


def main() -> int:
    print("P14 e2e demo — Tax, Withholding & Net Entitlement")
    if not default_adapter_jar().exists():
        print("SKIP — iso-adapter fatJar no construido "
              "(cd adapters/iso-adapter-jvm && ./gradlew fatJar)")
        leg("adapter", "SKIP")
        return 0

    ev = tax_evidence(_facts("mt564-tax.fin"))
    rate = next(i for s in ev["scopes"] for i in s["items"]
                if i["kind"] == "rate"
                and i["tax_type"] == "WITHHOLDING_PRIMARY")
    leg("T0 evidence", "PASS" if rate["rate"] == "19" else "FAIL",
        f"TAXR={rate['rate']}% scoped {ev['scopes'][0]['scope']}")

    # T1 — gross -> withholding -> expected net
    tax = _tax()
    item = tax["items"][0]
    ok = (item["status"] == "CALCULATED"
          and item["total_withholding"]["normalized"] == "296.88"
          and item["expected_net_cash"]["normalized"] == "1265.62")
    leg("T1 withholding+net", "PASS" if ok else "FAIL",
        f"status={item['status']} wh="
        f"{item['total_withholding']} net={item['expected_net_cash']}")
    exp = expected_cash(tax)

    # T2 — NET real MATCH
    recon = reconcile(_entitlement(), _movements("1265.62"),
                      expected_cash_doc=exp)
    leg("T2 NET MATCH", "PASS"
        if recon["items"][0]["status"] == "MATCH" else "FAIL",
        recon["items"][0]["status"])

    # T3 — NET erroneo -> mismatch + caso
    recon3 = reconcile(_entitlement(), _movements("1200.00"),
                       expected_cash_doc=exp)
    cases = classify_cases(recon3)
    ok = (recon3["items"][0]["status"] == "AMOUNT_MISMATCH"
          and len(cases) == 1
          and cases[0]["factual_status"] == "AMOUNT_MISMATCH")
    leg("T3 mismatch+case", "PASS" if ok else "FAIL",
        f"{recon3['items'][0]['status']} "
        f"key={cases[0]['case_key'] if cases else '-'}")

    # T4 — sin perfil
    tax4 = tax_entitlement(
        _entitlement(), [], None, _rules(), jurisdiction="ES",
        income_type="DIVIDEND", calculation_date="2026-07-20")
    exp4 = expected_cash(tax4)
    recon4 = reconcile(_entitlement(), _movements("1265.62"),
                       expected_cash_doc=exp4)
    ok = (tax4["items"][0]["status"] == "INDETERMINATE"
          and tax4["items"][0]["expected_net_cash"] is None
          and recon4["items"][0]["status"] == "INDETERMINATE")
    leg("T4 no profile", "PASS" if ok else "FAIL",
        f"{tax4['items'][0]['reason_codes']}")

    # T5 — conflicto fuente vs regla
    import copy
    facts5 = _facts("mt564-tax.fin")
    for f in facts5["facts"]:
        if f.get("source_qualifier") == "TAXR" and f.get(
                "source_tag") == "92A":
            f["value"] = "15,"
    ev5 = tax_evidence(facts5)
    tax5 = tax_entitlement(
        _entitlement(), [ev5], _profile(), _rules(),
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    ok = tax5["items"][0]["status"] == "CONFLICTING"
    leg("T5 source-vs-rule conflict", "PASS" if ok else "FAIL",
        f"{tax5['items'][0]['status']} "
        f"{tax5['items'][0].get('conflicts')}")

    # T6 — regla historica (2013 -> 21%)
    rules6 = _rules(periods=[{
        "rule_id": "ES-DIV-WH-2012", "rate": "21",
        "valid_from": "2012-01-01", "valid_to": "2014-12-31",
        "authority": "RDL 20/2011 DA35 LIRPF"}])
    tax6 = tax_entitlement(
        _entitlement(), [],
        _profile(valid_from="2010-01-01"), rules6,
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2013-06-15")
    item6 = tax6["items"][0]
    ok = (item6["status"] == "CALCULATED"
          and item6["rule_id"] == "ES-DIV-WH-2012"
          and item6["total_withholding"]["normalized"] == "328.13")
    leg("T6 historical rule", "PASS" if ok else "FAIL",
        f"rule={item6.get('rule_id')} wh="
        f"{item6.get('total_withholding')}")

    # T7 — perfil distinto: rama fiscal cambia, gross intacto
    tax7 = _tax(profile=_profile(tax_residency="FR"))
    ok = (tax7["items"][0]["status"] == "INDETERMINATE"
          and "RULE_NOT_APPLICABLE" in tax7["items"][0][
              "reason_codes"]
          and tax7["items"][0]["gross_entitlement"][
              "normalized"] == "1562.50")
    leg("T7 profile branch", "PASS" if ok else "FAIL",
        f"{tax7['items'][0]['reason_codes']}")

    # T8 — actual explicito consistente (MT566 real con WTAX)
    facts8 = _facts("mt564-tax.fin")
    facts8["message_identifier"] = "MT566"
    for f in facts8["facts"]:
        if f.get("source_tag") == "19B" and f.get(
                "source_qualifier") == "TAXR":
            f["source_qualifier"] = "WTAX"
    ev8 = tax_evidence(facts8)
    tr8 = tax_recon(tax, [ev8])
    recon8 = reconcile(_entitlement(), _movements("1265.62"),
                       expected_cash_doc=exp)
    ok = (tr8["items"][0]["status"] == "MATCH"
          and recon8["items"][0]["status"] == "MATCH")
    leg("T8 tax+cash recon", "PASS" if ok else "FAIL",
        f"tax={tr8['items'][0]['status']} "
        f"cash={recon8['items'][0]['status']}")

    # T9 — gross-net sin componente: tax actual desconocido
    facts9 = _facts("mt564-tax.fin")
    facts9["message_identifier"] = "MT566"
    facts9["facts"] = [f for f in facts9["facts"]
                       if f.get("source_qualifier") != "TAXR"]
    ev9 = tax_evidence(facts9)
    tr9 = tax_recon(tax, [ev9])
    ok = tr9["items"][0]["status"] == "MISSING_TAX_COMPONENT"
    leg("T9 no inferred tax", "PASS" if ok else "FAIL",
        tr9["items"][0]["status"])

    passed = sum(1 for _, s in _results if s == "PASS")
    skipped = sum(1 for _, s in _results if s == "SKIP")
    failed = sum(1 for _, s in _results if s == "FAIL")
    print(f"\n{passed} PASS / {skipped} SKIP / {failed} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
