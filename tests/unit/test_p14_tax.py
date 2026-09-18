"""P14 — tax evidence, rules, profile, entitlement, recon, cases."""

import pytest

from ca_es.exceptions import classify_cases
from ca_es.reconciliation import reconcile
from ca_es.tax_entitlement import (CALCULATED, CONFLICTING,
                                   INDETERMINATE, PENDING_ELECTION,
                                   UNSUPPORTED, expected_cash,
                                   tax_entitlement)
from ca_es.tax_evidence import tax_evidence
from ca_es.tax_profile import (PROFILE_SCHEMA, profile_for_account,
                               validate_profile)
from ca_es.tax_recon import (MISSING_TAX_COMPONENT, tax_recon,
                             UNEXPECTED_TAX_COMPONENT,
                             WITHHOLDING_AMOUNT_MISMATCH,
                             WITHHOLDING_RATE_MISMATCH)
from ca_es.tax_rules import (RULES_SCHEMA, conditions_satisfied,
                             rule_candidates, validate_ruleset)


# ------------------------------------------------------------------
# facts builders

def _fact(tag, qual, value, label, seq="USEQ/CACASH/CSMV", occ=0,
          locator=None, path=None):
    return {
        "source_tag": tag,
        "source_qualifier": qual,
        "field_path": path or f"MT564.{seq.replace('/', '.')}."
                              f"{tag}:{qual}.{label}",
        "sequence": seq,
        "occurrence": occ,
        "evidence_locator": locator or f"block4.tag[{tag}]",
        "value": value,
        "input_sha256": "sha-src",
        "message_identifier": "MT564",
    }


def _facts_mt564(components, seq="USEQ/CACASH/CSMV"):
    facts = [
        _fact("20C", "CORP", "CORP-1", "reference", "GENL"),
    ]
    for tag, qual, label, value in components:
        facts.append(_fact(tag, qual, value, label, seq))
    return {
        "schema": "CA_ES_SWIFT_MT_FACTS_V1",
        "parse_status": "OK",
        "message_identifier": "MT564",
        "standard_family": "MT",
        "input_sha256": "sha-src",
        "facts": facts,
    }


def _fact_mx(path, value, locator=None):
    return {
        "model_path": path,
        "evidence_locator": (
            locator or f"element:{path.replace('/', '[0]/')[0:]}"),
        "value": value,
        "occurrence": 0,
        "input_sha256": "sha-mx",
        "message_identifier": "seev.031.002.15",
    }


def _facts_seev031():
    opt = "/Document/CorpActnNtfctn/CorpActnOptnDtls"
    csmv = opt + "/CshMvmntDtls"
    return {
        "schema": "CA_ES_SWIFT_MX_FACTS_V1",
        "parse_status": "OK",
        "message_identifier": "seev.031.002.15",
        "standard_family": "MX",
        "input_sha256": "sha-mx",
        "facts": [
            _fact_mx(opt + "/OptnNb", "001",
                     f"element:{opt}[0]/OptnNb[0]"),
            _fact_mx(opt + "/OptnTp/Cd", "CASH",
                     f"element:{opt}[0]/OptnTp[0]/Cd[0]"),
            _fact_mx(csmv + "/CdtDbtInd", "CRDT",
                     f"element:{opt}[0]/CshMvmntDtls[0]/CdtDbtInd[0]"),
            _fact_mx(csmv + "/CtryOfIncmSrc", "ES",
                     f"element:{opt}[0]/CshMvmntDtls[0]/"
                     f"CtryOfIncmSrc[0]"),
            _fact_mx(csmv + "/AmtDtls/GrssAmt", "1562.50",
                     f"element:{opt}[0]/CshMvmntDtls[0]/AmtDtls[0]/"
                     f"GrssAmt[0]"),
            _fact_mx(csmv + "/AmtDtls/GrssAmt/@Ccy", "EUR",
                     f"element:{opt}[0]/CshMvmntDtls[0]/AmtDtls[0]/"
                     f"GrssAmt[0]/@Ccy[0]"),
            _fact_mx(csmv + "/AmtDtls/WhldgTaxAmt", "296.88",
                     f"element:{opt}[0]/CshMvmntDtls[0]/AmtDtls[0]/"
                     f"WhldgTaxAmt[0]"),
            _fact_mx(csmv + "/AmtDtls/WhldgTaxAmt/@Ccy", "EUR",
                     f"element:{opt}[0]/CshMvmntDtls[0]/AmtDtls[0]/"
                     f"WhldgTaxAmt[0]/@Ccy[0]"),
            _fact_mx(csmv + "/RateAndAmtDtls/WhldgTaxRate/Rate",
                     "19",
                     f"element:{opt}[0]/CshMvmntDtls[0]/"
                     f"RateAndAmtDtls[0]/WhldgTaxRate[0]/Rate[0]"),
        ],
    }


# ------------------------------------------------------------------
# docs builders

def _entitlement(gross="1562.50", ccy="EUR", account="ACC-1",
                 status="ENTITLED"):
    return {
        "schema": "CA_ES_ENTITLEMENT_V1",
        "canonical_event_id": "evt-1",
        "entitlements": [{
            "account_id": account,
            "isin": "ES0113900J37",
            "status": status,
            "gross_cash": {"normalized": gross, "currency": ccy},
            "reasons": [],
            "evidence": {},
        }],
    }


def _rules_es(rate="19", valid_from="2016-01-01", valid_to=None,
              rate_source="CONFIGURED_STATUTORY_RATE",
              rounding=None, conditions=None, basis="GROSS_ENTITLEMENT"):
    return {
        "schema": RULES_SCHEMA,
        "ruleset_id": "es-v1",
        "rules": [{
            "rule_id": "ES-DIV-WH-001",
            "jurisdiction": "ES",
            "income_type": "DIVIDEND",
            "valid_from": valid_from,
            "valid_to": valid_to,
            "rate_source": rate_source,
            "rate": rate if rate_source.startswith("CONFIGURED")
            else None,
            "rate_unit": "PERCENTAGE"
            if rate_source.startswith("CONFIGURED") else None,
            "calculation_basis": basis,
            "conditions": conditions or {
                "tax_residency": ["ES"],
                "entity_person_classification": ["PERSON", "ENTITY"],
            },
            "rounding": rounding if rounding is not None else {
                "mode": "HALF_UP", "scale": 2, "currency": "EUR"},
        }],
    }


def _profile_es(account="ACC-1", residency="ES",
                classification="PERSON", valid_from="2020-01-01"):
    return {
        "schema": PROFILE_SCHEMA,
        "profile_id": "demo",
        "profiles": [{
            "account_id": account,
            "valid_from": valid_from,
            "tax_residency": residency,
            "entity_person_classification": classification,
        }],
    }


def _movements(amount, basis="NET", account="ACC-1", mid="M-1"):
    return {
        "schema": "CA_ES_CASH_MOVEMENTS_V2",
        "movements": [{
            "movement_id": mid,
            "event_id": "evt-1",
            "account_id": account,
            "isin": "ES0113900J37",
            "amount": amount,
            "currency": "EUR",
            "amount_basis": basis,
        }],
    }


# ------------------------------------------------------------------
# TAX EVIDENCE (MT)

def test_mt564_taxr_rate_and_amount():
    doc = tax_evidence(_facts_mt564([
        ("92A", "TAXR", "rate", "19,"),
        ("19B", "TAXR", "amount", "296,88"),
        ("19B", "TAXR", "currency code", "EUR"),
        ("19B", "NETT", "amount", "1265,62"),
        ("19B", "NETT", "currency code", "EUR"),
    ]))
    assert doc["schema"] == "CA_ES_TAX_EVIDENCE_V1"
    assert doc["evidence_role"] == "EXPECTED"
    assert len(doc["scopes"]) == 1
    scope = doc["scopes"][0]
    assert scope["scope"] == "CASH_MOVEMENT"
    kinds = {(i["tax_type"], i["kind"]) for i in scope["items"]}
    assert ("WITHHOLDING_PRIMARY", "rate") in kinds
    assert ("WITHHOLDING_PRIMARY", "amount") in kinds
    assert ("NET_AMOUNT", "amount") in kinds
    rate = next(i for i in scope["items"] if i["kind"] == "rate")
    assert rate["rate"] == "19"
    assert rate["rate_unit"] == "PERCENTAGE"
    amt = next(i for i in scope["items"]
               if i["tax_type"] == "WITHHOLDING_PRIMARY"
               and i["kind"] == "amount")
    assert amt["amount"] == "296.88"
    assert amt["currency"] == "EUR"


def test_mt564_repeated_taxr_preserved():
    doc = tax_evidence(_facts_mt564([
        ("92A", "TAXR", "rate", "19,"),
        ("92A", "TAXR", "rate", "15,"),
    ]))
    rates = [i for i in doc["scopes"][0]["items"]
             if i["kind"] == "rate"]
    assert len(rates) == 2  # nunca "first TAXR wins"


def test_mt564_witl_second_level():
    doc = tax_evidence(_facts_mt564([
        ("92A", "WITL", "rate", "5,"),
    ]))
    assert doc["scopes"][0]["items"][0]["tax_type"] == (
        "WITHHOLDING_SECOND_LEVEL")


def test_mt564_option_scoping_two_options():
    facts = _facts_mt564([
        ("11A", "OPTN", "option number", "001"),
        ("22H", "CAOP", "indicator", "CASH"),
    ], seq="USEQ/CAOPTN")
    facts["facts"] += [
        _fact("92A", "TAXR", "19,", "rate",
              seq="USEQ/CAOPTN/CASHMOVE"),
        _fact("11A", "OPTN", "002", "option number",
              seq="USEQ/CAOPTN[1]"),
        _fact("92A", "TAXR", "25,", "rate",
              seq="USEQ/CAOPTN[1]/CASHMOVE",
              path="MT564.USEQ.CAOPTN[1].CASHMOVE.92A:TAXR.rate"),
    ]
    doc = tax_evidence(facts)
    cash = [s for s in doc["scopes"] if s["scope"] == "CASH_MOVEMENT"]
    assert len(cash) == 2
    rates = {i["rate"] for s in cash for i in s["items"]
             if i["kind"] == "rate"}
    assert rates == {"19", "25"}


def test_mt564_unknown_qualifier_unclassified():
    doc = tax_evidence(_facts_mt564([
        ("19B", "ZZZZ", "amount", "10,"),
        ("19B", "ZZZZ", "currency code", "EUR"),
    ]))
    item = doc["scopes"][0]["items"][0]
    assert item["tax_type"] == "UNCLASSIFIED"
    assert item["raw_qualifier"] == "ZZZZ"


def test_mt566_actual_role():
    doc_in = _facts_mt564([
        ("19B", "WTAX", "amount", "296,88"),
        ("19B", "WTAX", "currency code", "EUR"),
        ("19B", "GRSS", "amount", "1562,5"),
        ("19B", "GRSS", "currency code", "EUR"),
        ("19B", "NETT", "amount", "1265,62"),
        ("19B", "NETT", "currency code", "EUR"),
    ])
    doc_in["message_identifier"] = "MT566"
    for f in doc_in["facts"]:
        f["message_identifier"] = "MT566"
    doc = tax_evidence(doc_in)
    assert doc["evidence_role"] == "ACTUAL"


def test_seev031_tax_evidence():
    doc = tax_evidence(_facts_seev031())
    assert doc["evidence_role"] == "EXPECTED"
    scope = doc["scopes"][0]
    assert scope["scope"] == "CASH_MOVEMENT"
    assert scope["option_number"] == "001"
    items = {(i["tax_type"], i["kind"]): i for i in scope["items"]}
    assert items[("WITHHOLDING_PRIMARY", "amount")][
        "amount"] == "296.88"
    assert items[("WITHHOLDING_PRIMARY", "amount")][
        "currency"] == "EUR"
    assert items[("WITHHOLDING_PRIMARY", "rate")]["rate"] == "19"
    assert items[("JURISDICTION", "selector")][
        "jurisdiction_code"] == "ES"


def _facts_seev036():
    # paths reales del adapter sobre seev.036.002.16: la opcion
    # cuelga de CorpActnConfDtls y OptnNb lleva wrapper <Nb>
    conf = "/Document/CorpActnMvmntConf/CorpActnConfDtls"
    csmv = conf + "/CshMvmntDtls"
    return {
        "schema": "CA_ES_SWIFT_MX_FACTS_V1",
        "parse_status": "OK",
        "message_identifier": "seev.036.002.16",
        "standard_family": "MX",
        "input_sha256": "sha-mx",
        "facts": [
            _fact_mx("/Document/CorpActnMvmntConf/CorpActnGnlInf/"
                     "CorpActnEvtId", "BME-DVCA-0001",
                     "element:/Document[0]/CorpActnMvmntConf[0]/"
                     "CorpActnGnlInf[0]/CorpActnEvtId[0]"),
            _fact_mx(conf + "/OptnNb/Nb", "001",
                     f"element:{conf}[0]/OptnNb[0]/Nb[0]"),
            _fact_mx(conf + "/OptnTp/Cd", "CASH",
                     f"element:{conf}[0]/OptnTp[0]/Cd[0]"),
            _fact_mx(csmv + "/AmtDtls/GrssAmt", "1562.50",
                     f"element:{conf}[0]/CshMvmntDtls[0]/AmtDtls[0]/"
                     f"GrssAmt[0]"),
            _fact_mx(csmv + "/AmtDtls/GrssAmt/@Ccy", "EUR",
                     f"element:{conf}[0]/CshMvmntDtls[0]/AmtDtls[0]/"
                     f"GrssAmt[0]/@Ccy[0]"),
            _fact_mx(csmv + "/AmtDtls/WhldgTaxAmt", "296.88",
                     f"element:{conf}[0]/CshMvmntDtls[0]/AmtDtls[0]/"
                     f"WhldgTaxAmt[0]"),
            _fact_mx(csmv + "/AmtDtls/WhldgTaxAmt/@Ccy", "EUR",
                     f"element:{conf}[0]/CshMvmntDtls[0]/AmtDtls[0]/"
                     f"WhldgTaxAmt[0]/@Ccy[0]"),
            _fact_mx(csmv + "/AmtDtls/NetAmt", "1265.62",
                     f"element:{conf}[0]/CshMvmntDtls[0]/AmtDtls[0]/"
                     f"NetAmt[0]"),
        ],
    }


def test_seev036_actual_tax_evidence():
    doc = tax_evidence(_facts_seev036())
    assert doc["evidence_role"] == "ACTUAL"
    assert doc["event_references"][0]["reference"] == "BME-DVCA-0001"
    scope = doc["scopes"][0]
    assert scope["scope"] == "CASH_MOVEMENT"
    assert scope["option_number"] == "001"
    assert scope["option_type"] == "CASH"
    items = {(i["tax_type"], i["kind"]): i for i in scope["items"]}
    assert items[("WITHHOLDING_PRIMARY", "amount")][
        "amount"] == "296.88"
    assert items[("GROSS_AMOUNT", "amount")]["amount"] == "1562.50"
    assert items[("NET_AMOUNT", "amount")]["amount"] == "1265.62"


def test_seev031_mt564_parity():
    mt = tax_evidence(_facts_mt564([
        ("92A", "TAXR", "rate", "19,"),
        ("19B", "TAXR", "amount", "296,88"),
        ("19B", "TAXR", "currency code", "EUR"),
    ]))
    mx = tax_evidence(_facts_seev031())

    def rates(doc):
        return {i["rate"] for s in doc["scopes"]
                for i in s["items"]
                if i["tax_type"] == "WITHHOLDING_PRIMARY"
                and i["kind"] == "rate"}

    assert rates(mt) == rates(mx) == {"19"}


def test_unsupported_message():
    doc = tax_evidence({"schema": "X", "parse_status": "OK",
                        "message_identifier": "MT940", "facts": []})
    assert doc["status"] == "UNSUPPORTED"


# ------------------------------------------------------------------
# RULES / PROFILE

def test_ruleset_validates():
    assert validate_ruleset(_rules_es()) == []


def test_ruleset_rejects_missing_fields():
    bad = _rules_es()
    del bad["rules"][0]["rule_id"]
    errors = validate_ruleset(bad)
    assert errors


def test_ruleset_effective_dating():
    rules = _rules_es(valid_from="2016-01-01")
    active, reasons = rule_candidates(
        rules, "ES", "DIVIDEND", "2020-05-01")
    assert len(active) == 1 and not reasons
    active, reasons = rule_candidates(
        rules, "ES", "DIVIDEND", "2012-05-01")
    assert not active
    assert reasons == ["RULE_NOT_EFFECTIVE"]


def test_ruleset_overlap_rejected():
    rules = _rules_es()
    rules["rules"].append(dict(rules["rules"][0],
                             rule_id="ES-DIV-WH-002", rate="21"))
    errors = validate_ruleset(rules)
    assert any("solapan" in e for e in errors)


def test_ruleset_temporal_overlap_ok():
    rules = _rules_es(valid_from="2016-01-01")
    rules["rules"].append({
        **rules["rules"][0],
        "rule_id": "ES-DIV-WH-OLD",
        "rate": "21",
        "valid_from": "2012-01-01",
        "valid_to": "2014-12-31",
    })
    assert validate_ruleset(rules) == []
    active, _ = rule_candidates(rules, "ES", "DIVIDEND", "2013-06-01")
    assert active[0]["rule_id"] == "ES-DIV-WH-OLD"


def test_profile_unknown_field_rejected():
    profile = _profile_es()
    profile["profiles"][0]["iban"] = "ES00"
    errors = validate_profile(profile)
    assert errors


def test_profile_no_residency_guessing():
    profile = _profile_es(residency=None)
    del profile["profiles"][0]["tax_residency"]
    assert validate_profile(profile) == []
    ok, missing = conditions_satisfied(
        _rules_es()["rules"][0], profile["profiles"][0])
    assert not ok and "TAX_RESIDENCY" in missing


def test_profile_conflicting():
    profile = _profile_es()
    profile["profiles"].append({
        "account_id": "ACC-1",
        "valid_from": "2020-01-01",
        "tax_residency": "FR",
        "entity_person_classification": "PERSON",
    })
    errors = validate_profile(profile)
    assert errors  # duplicado account+valid_from


# ------------------------------------------------------------------
# TAX ENTITLEMENT

def test_entitlement_calculated_es_dividend():
    doc = tax_entitlement(
        _entitlement(), [], _profile_es(), _rules_es(),
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    item = doc["items"][0]
    assert item["status"] == CALCULATED
    # 1562.50 * 0.19 = 296.875 -> HALF_UP 2 -> 296.88
    assert item["total_withholding"]["normalized"] == "296.88"
    assert item["expected_net_cash"]["normalized"] == "1265.62"
    assert item["trace"]["rule_id"] == "ES-DIV-WH-001"
    from decimal import Decimal
    assert Decimal(item["trace"]["raw_tax"]) == Decimal("296.875")


def test_entitlement_no_profile():
    doc = tax_entitlement(
        _entitlement(), [], None, _rules_es(),
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    assert doc["items"][0]["status"] == INDETERMINATE
    assert "NO_TAX_PROFILE" in doc["items"][0]["reason_codes"]
    assert doc["items"][0]["expected_net_cash"] is None


def test_entitlement_no_ruleset():
    doc = tax_entitlement(
        _entitlement(), [], _profile_es(), None,
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    assert doc["items"][0]["status"] == INDETERMINATE


def test_entitlement_source_declared_rate():
    rules = _rules_es(rate_source="SOURCE_DECLARED_RATE",
                      conditions={})
    doc = tax_entitlement(
        _entitlement(), [tax_evidence(_facts_mt564([
            ("92A", "TAXR", "rate", "19,"),
        ]))], _profile_es(), rules,
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    assert doc["items"][0]["status"] == CALCULATED
    assert doc["items"][0]["total_withholding"][
        "normalized"] == "296.88"


def test_entitlement_multiple_source_rates_conflict():
    rules = _rules_es(rate_source="SOURCE_DECLARED_RATE",
                      conditions={})
    doc = tax_entitlement(
        _entitlement(), [tax_evidence(_facts_mt564([
            ("92A", "TAXR", "rate", "19,"),
            ("92A", "TAXR", "rate", "15,"),
        ]))], _profile_es(), rules,
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    assert doc["items"][0]["status"] == CONFLICTING
    assert "MULTIPLE_TAX_RATES" in doc["items"][0]["reason_codes"]


def test_entitlement_source_rule_conflict():
    doc = tax_entitlement(
        _entitlement(), [tax_evidence(_facts_mt564([
            ("92A", "TAXR", "rate", "15,"),  # fuente dice 15%
        ]))], _profile_es(), _rules_es(),  # regla dice 19%
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    item = doc["items"][0]
    assert item["status"] == CONFLICTING
    assert "SOURCE_RULE_RATE_CONFLICT" in item["reason_codes"]
    assert item["expected_net_cash"] is None


def test_entitlement_source_rate_match_ok():
    doc = tax_entitlement(
        _entitlement(), [tax_evidence(_facts_mt564([
            ("92A", "TAXR", "rate", "19,"),
        ]))], _profile_es(), _rules_es(),
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    assert doc["items"][0]["status"] == CALCULATED


def test_entitlement_witl_unsupported():
    doc = tax_entitlement(
        _entitlement(), [tax_evidence(_facts_mt564([
            ("92A", "TAXR", "rate", "19,"),
            ("92A", "WITL", "rate", "5,"),
        ]))], _profile_es(), _rules_es(),
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    assert doc["items"][0]["status"] == UNSUPPORTED
    assert "UNSUPPORTED_MULTI_LEVEL_TAX" in doc["items"][0][
        "reason_codes"]


def test_entitlement_rounding_none_preserves_exact():
    rules = _rules_es(rounding={"mode": "NONE"})
    doc = tax_entitlement(
        _entitlement(), [], _profile_es(), rules,
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    from decimal import Decimal
    assert Decimal(doc["items"][0]["total_withholding"][
        "normalized"]) == Decimal("296.875")
    assert Decimal(doc["items"][0]["expected_net_cash"][
        "normalized"]) == Decimal("1265.625")


def test_entitlement_historical_rule():
    rules = _rules_es(valid_from="2016-01-01")
    rules["rules"].insert(0, {
        **rules["rules"][0],
        "rule_id": "ES-DIV-WH-2012",
        "rate": "21",
        "valid_from": "2012-01-01",
        "valid_to": "2014-12-31",
    })
    doc = tax_entitlement(
        _entitlement(), [], _profile_es(valid_from="2010-01-01"),
        rules,
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2013-06-15")
    item = doc["items"][0]
    assert item["status"] == CALCULATED
    assert item["rule_id"] == "ES-DIV-WH-2012"
    # 1562.50 * 0.21 = 328.125 -> 328.13
    assert item["total_withholding"]["normalized"] == "328.13"


def test_entitlement_fx_required():
    ev = tax_evidence(_facts_mt564([
        ("19B", "TAXB", "amount", "1000,"),
        ("19B", "TAXB", "currency code", "USD"),  # basis en USD
    ]))
    rules = _rules_es(basis="EXPLICIT_BASIS")
    rules["rules"][0]["basis_tax_type"] = "TAXABLE_BASIS"
    doc = tax_entitlement(
        _entitlement(), [ev], _profile_es(), rules,
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    assert doc["items"][0]["status"] == INDETERMINATE
    assert "FX_REQUIRED" in doc["items"][0]["reason_codes"]


def test_entitlement_pending_election():
    doc = tax_entitlement(
        _entitlement(), [], _profile_es(), _rules_es(),
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20",
        requires_election=True)
    assert doc["items"][0]["status"] == PENDING_ELECTION


def test_entitlement_option_scope_filter():
    ev = tax_evidence(_facts_mt564([
        ("92A", "TAXR", "rate", "19,"),
    ], seq="USEQ/CAOPTN/CASHMOVE"))
    rules = _rules_es(rate_source="SOURCE_DECLARED_RATE",
                      conditions={})
    # scope a la opcion 001: la evidencia no tiene option_number
    # -> no aplica -> SOURCE_RATE_MISSING
    doc = tax_entitlement(
        _entitlement(), [ev], _profile_es(), rules,
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20",
        option_scope={"option_number": "001"})
    assert "SOURCE_RATE_MISSING" in doc["items"][0]["reason_codes"]


def test_entitlement_exempt():
    rules = _rules_es(rate_source="EXEMPT",
                      conditions={"tax_exempt_status": ["EXEMPT"]})
    profile = _profile_es()
    profile["profiles"][0]["tax_exempt_status"] = "EXEMPT"
    doc = tax_entitlement(
        _entitlement(), [], profile, rules,
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    item = doc["items"][0]
    assert item["status"] == CALCULATED
    from decimal import Decimal
    assert Decimal(item["total_withholding"][
        "normalized"]) == Decimal("0")
    assert Decimal(item["expected_net_cash"][
        "normalized"]) == Decimal("1562.50")


# ------------------------------------------------------------------
# EXPECTED CASH + RECON

def test_expected_cash_and_net_match():
    tax = tax_entitlement(
        _entitlement(), [], _profile_es(), _rules_es(),
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    exp = expected_cash(tax)
    assert exp["schema"] == "CA_ES_EXPECTED_CASH_V1"
    assert exp["items"][0]["net_expected"]["normalized"] == "1265.62"
    recon = reconcile(_entitlement(), _movements("1265.62"),
                      expected_cash_doc=exp)
    assert recon["items"][0]["status"] == "MATCH"


def test_net_mismatch():
    tax = tax_entitlement(
        _entitlement(), [], _profile_es(), _rules_es(),
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    exp = expected_cash(tax)
    recon = reconcile(_entitlement(), _movements("1200.00"),
                      expected_cash_doc=exp)
    item = recon["items"][0]
    assert item["status"] == "AMOUNT_MISMATCH"
    assert item["delta"]["normalized"].startswith("-")


def test_net_without_expected_stays_indeterminate():
    tax = tax_entitlement(
        _entitlement(), [], None, _rules_es(),
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    exp = expected_cash(tax)
    assert exp["items"][0]["net_status"] == "NOT_AVAILABLE"
    recon = reconcile(_entitlement(), _movements("1265.62"),
                      expected_cash_doc=exp)
    assert recon["items"][0]["status"] == "INDETERMINATE"
    assert "NET_EXPECTED_NOT_AVAILABLE" in recon["items"][0][
        "reasons"]


def test_gross_recon_unchanged():
    tax = tax_entitlement(
        _entitlement(), [], _profile_es(), _rules_es(),
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    exp = expected_cash(tax)
    recon = reconcile(_entitlement(), _movements(
        "1562.50", basis="GROSS"), expected_cash_doc=exp)
    assert recon["items"][0]["status"] == "MATCH"


def test_recon_no_expected_cash_legacy():
    recon = reconcile(_entitlement(), _movements("1265.62"))
    assert recon["items"][0]["status"] == "INDETERMINATE"


# ------------------------------------------------------------------
# TAX RECON

def _actual_evidence(amount="296.88", rate=None):
    comps = [("19B", "WTAX", "amount", amount),
             ("19B", "WTAX", "currency code", "EUR")]
    if rate is not None:
        comps.append(("92A", "TAXR", "rate", rate))
    doc = _facts_mt564(comps)
    doc["message_identifier"] = "MT566"
    return tax_evidence(doc)


def test_tax_recon_match():
    tax = tax_entitlement(
        _entitlement(), [], _profile_es(), _rules_es(),
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    doc = tax_recon(tax, [_actual_evidence()])
    assert doc["schema"] == "CA_ES_TAX_RECON_V1"
    assert doc["items"][0]["status"] == "MATCH"


def test_tax_recon_amount_mismatch():
    tax = tax_entitlement(
        _entitlement(), [], _profile_es(), _rules_es(),
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    doc = tax_recon(tax, [_actual_evidence(amount="300.00")])
    assert doc["items"][0]["status"] == WITHHOLDING_AMOUNT_MISMATCH


def test_tax_recon_rate_mismatch():
    tax = tax_entitlement(
        _entitlement(), [], _profile_es(), _rules_es(),
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    doc = tax_recon(tax, [_actual_evidence(rate="15,")])
    assert doc["items"][0]["status"] == WITHHOLDING_RATE_MISMATCH


def test_tax_recon_missing_component():
    tax = tax_entitlement(
        _entitlement(), [], _profile_es(), _rules_es(),
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    doc = tax_recon(tax, [])
    assert doc["items"][0]["status"] == MISSING_TAX_COMPONENT


def test_tax_recon_unexpected_component():
    tax = tax_entitlement(
        _entitlement(), [], _profile_es(), _rules_es(),
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    actual = _facts_mt564([
        ("19B", "WTAX", "amount", "296,88"),
        ("19B", "WTAX", "currency code", "EUR"),
        ("19B", "TXRC", "amount", "50,"),
        ("19B", "TXRC", "currency code", "EUR"),
    ])
    actual["message_identifier"] = "MT566"
    doc = tax_recon(tax, [tax_evidence(actual)])
    statuses = {i["component_type"]: i["status"] for i in doc["items"]}
    assert statuses["WITHHOLDING_PRIMARY"] == "MATCH"
    assert statuses["TAX_RECLAIM"] == UNEXPECTED_TAX_COMPONENT


def test_tax_recon_gross_net_not_inferred():
    # MT566 con GRSS+NETT pero sin componente tax explicito:
    # no se deriva tax = gross - net
    actual = _facts_mt564([
        ("19B", "GRSS", "amount", "1562,5"),
        ("19B", "GRSS", "currency code", "EUR"),
        ("19B", "NETT", "amount", "1265,62"),
        ("19B", "NETT", "currency code", "EUR"),
    ])
    actual["message_identifier"] = "MT566"
    tax = tax_entitlement(
        _entitlement(), [], _profile_es(), _rules_es(),
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    doc = tax_recon(tax, [tax_evidence(actual)])
    assert doc["items"][0]["status"] == MISSING_TAX_COMPONENT


def test_tax_recon_indeterminate_no_case():
    tax = tax_entitlement(
        _entitlement(), [], None, _rules_es(),
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    doc = tax_recon(tax, [])
    cases = classify_cases(doc)
    assert cases == []


def test_tax_cases_stable_key():
    tax = tax_entitlement(
        _entitlement(), [], _profile_es(), _rules_es(),
        jurisdiction="ES", income_type="DIVIDEND",
        calculation_date="2026-07-20")
    doc = tax_recon(tax, [_actual_evidence(amount="300.00")])
    cases = classify_cases(doc)
    assert len(cases) == 1
    assert cases[0]["case_key"] == (
        "tax|evt-1|tax:ACC-1:WITHHOLDING_PRIMARY")
    assert cases[0]["factual_status"] == WITHHOLDING_AMOUNT_MISMATCH
    assert cases[0]["priority"] == "HIGH"
