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
