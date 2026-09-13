from __future__ import annotations

from ca_es.temporal import assert_no_global_order, check


def test_p3_record_before_ex_and_payment_equals_ex_accepted():
    dates = {
        "EX_DATE": "2026-05-20",
        "RECORD_DATE": "2026-05-19",
        "PAYMENT_DATE": "2026-05-20",
    }
    assert check(dates, source_id="PORTFOLIO_STOCK_EXCHANGE", event_type="CASH_DIVIDEND") == []


def test_p3_violation_is_detected():
    dates = {
        "EX_DATE": "2026-05-19",
        "RECORD_DATE": "2026-05-20",
        "PAYMENT_DATE": "2026-05-20",
    }
    violations = check(dates, source_id="PORTFOLIO_STOCK_EXCHANGE")
    assert any(v["rule_id"] == "P3_PORTFOLIO_RECORD_BEFORE_EX" for v in violations)


def test_no_global_date_order_assumption():
    # Un orden atipico en una fuente sin reglas declaradas se acepta tal cual.
    dates = {
        "EX_DATE": "2026-01-01",
        "RECORD_DATE": "2026-06-01",
        "PAYMENT_DATE": "2026-03-01",
    }
    assert check(dates, source_id="CNMV") == []
    assert_no_global_order(dates)
