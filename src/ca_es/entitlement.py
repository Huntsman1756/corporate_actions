"""Entitlement basis como assertion temporal.

La base de entitlement no es un atributo estatico: puede cambiar y se
asserta a una fecha concreta (``asserted_as_of``). Se preservan los
componentes publicados sin normalizarlos a categorias no demostradas.
"""
from __future__ import annotations

from .errors import InvariantViolation
from .sources.parsers.base import EntitlementBasis
from .vocab import EntitlementStatus


def validate_entitlement_basis(basis: EntitlementBasis) -> None:
    if not basis.asserted_as_of:
        raise InvariantViolation(
            "entitlement basis sin asserted_as_of: se promoveria a atributo sin tiempo"
        )
    if basis.status not in {status.value for status in EntitlementStatus}:
        raise InvariantViolation(f"status de entitlement desconocido: {basis.status!r}")
    if basis.eligible_shares is not None and not isinstance(basis.eligible_shares, int):
        raise InvariantViolation("eligible_shares debe ser entero exacto")
    if basis.status == EntitlementStatus.SUBJECT_TO_ADJUSTMENT.value:
        if not basis.adjustment_rule_present:
            raise InvariantViolation(
                "estado SUBJECT_TO_ADJUSTMENT exige adjustment_rule_present=true"
            )
