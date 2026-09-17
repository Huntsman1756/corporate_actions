"""P6 — CA_ES_PORTFOLIO_IMPACT_V1 (read-only roll-up).

Solo agregacion semanticamente aditiva: cash por moneda, deltas de
valores por (account, isin); items no PROJECTED se excluyen contados;
sin FX ni valoracion.
"""

import pytest

from ca_es.canonical import canonical_json
from ca_es.portfolio_impact import aggregate_portfolio_impact

NOW = "2026-09-17T00:00:00Z"
EID = "E1"


def _item(account="A001", source="ES0105448007", target=None,
          status="PROJECTED", impact_type="CASH_RECEIVABLE",
          cash=None, delta=None):
    return {
        "canonical_event_id": EID,
        "account_id": account,
        "source_isin": source,
        "target_isin": target,
        "impact_type": impact_type,
        "status": status,
        "input_quantity": "100",
        "output_quantity": None,
        "quantity_delta": delta,
        "cash_amount": cash,
        "currency": (cash or {}).get("currency"),
        "rule_id": "R1",
        "basis_date": None,
        "reasons": [],
        "evidence": {},
    }


def _impact(*items):
    return {
        "schema": "CA_ES_POSITION_IMPACT_V1",
        "canonical_event_id": EID,
        "event_type": "CASH_DIVIDEND",
        "impacts": list(items),
    }


def _cash(amount, currency="EUR"):
    return {"normalized": amount, "currency": currency, "scale": 2}


def test_cash_aggregates_by_currency_only():
    doc = aggregate_portfolio_impact(_impact(
        _item(cash=_cash("10.50")),
        _item(account="A002", cash=_cash("2.50")),
        _item(account="A003", cash=_cash("5", currency="USD")),
    ), now=NOW)
    assert doc["schema"] == "CA_ES_PORTFOLIO_IMPACT_V1"
    assert doc["cash_by_currency"] == [
        {"currency": "EUR", "expected_amount": "13.00"},
        {"currency": "USD", "expected_amount": "5"},
    ]


def test_security_deltas_aggregate_by_account_isin():
    doc = aggregate_portfolio_impact(_impact(
        _item(impact_type="SECURITY_RECEIPT", target="ES9",
              delta="100"),
        _item(impact_type="SECURITY_RECEIPT", target="ES9",
              delta="50"),
        _item(account="A002", impact_type="SECURITY_DELIVERY",
              delta="-20"),
    ), now=NOW)
    assert doc["securities_by_account_isin"] == [
        {"account_id": "A001", "isin": "ES9",
         "expected_quantity_delta": "150"},
        {"account_id": "A002", "isin": "ES0105448007",
         "expected_quantity_delta": "-20"},
    ]


def test_non_projected_items_are_counted_not_summed():
    doc = aggregate_portfolio_impact(_impact(
        _item(cash=_cash("10")),
        _item(status="INDETERMINATE", cash=None),
        _item(status="UNSUPPORTED", cash=_cash("99")),
    ), now=NOW)
    assert doc["cash_by_currency"] == [
        {"currency": "EUR", "expected_amount": "10"}]
    assert doc["excluded_items"] == {
        "INDETERMINATE": 1, "UNSUPPORTED": 1}


def test_cash_without_currency_is_flagged():
    doc = aggregate_portfolio_impact(_impact(
        _item(cash={"normalized": "10", "currency": None}),
    ), now=NOW)
    assert doc["cash_by_currency"] == []
    assert doc["reasons"] == ["CASH_WITHOUT_CURRENCY"]


def test_determinism_and_schema_guard():
    doc = _impact(_item(cash=_cash("1")))
    a = aggregate_portfolio_impact(doc, now=NOW)
    b = aggregate_portfolio_impact(doc, now=NOW)
    assert canonical_json(a) == canonical_json(b)
    with pytest.raises(ValueError):
        aggregate_portfolio_impact({"schema": "X"}, now=NOW)
