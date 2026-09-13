from __future__ import annotations

import pytest

from ca_es.entitlement import validate_entitlement_basis
from ca_es.errors import InvariantViolation
from ca_es.sources.parsers.base import EntitlementBasis


def test_entitlement_basis_requires_as_of():
    basis = EntitlementBasis(
        eligible_shares=19378125,
        asserted_as_of="",
        status="SUBJECT_TO_ADJUSTMENT",
        adjustment_rule_present=True,
    )
    with pytest.raises(InvariantViolation):
        validate_entitlement_basis(basis)


def test_subject_to_adjustment_requires_rule():
    basis = EntitlementBasis(
        eligible_shares=19378125,
        asserted_as_of="2026-08-31",
        status="SUBJECT_TO_ADJUSTMENT",
        adjustment_rule_present=False,
    )
    with pytest.raises(InvariantViolation):
        validate_entitlement_basis(basis)


def test_valid_entitlement_basis():
    basis = EntitlementBasis(
        eligible_shares=19378125,
        asserted_as_of="2026-08-31",
        status="SUBJECT_TO_ADJUSTMENT",
        adjustment_rule_present=True,
        components={"treasury_shares": "209745"},
    )
    validate_entitlement_basis(basis)
