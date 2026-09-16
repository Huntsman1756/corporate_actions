from __future__ import annotations

import pytest

from ca_es.errors import AmbiguousLexemeError, FloatingPointProhibited
from ca_es.numeric import FinancialAmount, ensure_exact


def test_published_scale_preserved():
    amount = FinancialAmount.parse("0,11840672", currency="EUR")
    assert amount.normalized_str() == "0.11840672"
    assert amount.scale == 8
    assert amount.raw_lexeme == "0,11840672"
    assert amount.to_canonical() == {
        "raw_lexeme": "0,11840672",
        "normalized": "0.11840672",
        "scale": 8,
        "currency": "EUR",
    }


def test_integer_lexeme_scale_zero():
    amount = FinancialAmount.parse("55")
    assert amount.scale == 0
    assert amount.normalized_str() == "55"


def test_float_is_rejected():
    with pytest.raises(FloatingPointProhibited):
        FinancialAmount.parse(0.11840672)
    with pytest.raises(FloatingPointProhibited):
        ensure_exact({"amount": 1.5})


def test_ambiguous_lexeme_rejected():
    with pytest.raises(AmbiguousLexemeError):
        FinancialAmount.parse("1.234,56")


def test_no_implicit_rounding():
    amount = FinancialAmount.parse("0.1184")
    assert amount.normalized_str() == "0.1184"
    assert amount.scale == 4


def test_localized_spanish_amount_preserves_lexeme_and_scale():
    amount = FinancialAmount.parse_localized("99.375,00", currency="EUR")
    assert amount.raw_lexeme == "99.375,00"
    assert amount.normalized_str() == "99375.00"
    assert amount.scale == 2


def test_localized_rejects_invalid_thousands_grouping():
    with pytest.raises(AmbiguousLexemeError):
        FinancialAmount.parse_localized("9.9375,00")


@pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity", "-Infinity"])
def test_non_finite_normalized_amount_rejected(value):
    from decimal import Decimal

    with pytest.raises(AmbiguousLexemeError):
        FinancialAmount(raw_lexeme=value, normalized=Decimal(value), scale=0)


@pytest.mark.parametrize("precision", [6, 28])
def test_from_cents_preserves_all_digits(precision):
    from decimal import localcontext

    with localcontext() as context:
        context.prec = precision
        amount = FinancialAmount.from_cents("123456789012345678901234567890,00")
    assert amount.normalized_str() == "1234567890123456789012345678.9000"
    assert amount.scale == 4
    assert amount.raw_lexeme == "123456789012345678901234567890,00"
