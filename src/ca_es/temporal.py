"""Semantica temporal: nunca un orden global de fechas.

Regla fundamental: NO_GLOBAL_DATE_ORDER_ASSUMPTION.

No existe la regla universal ``ex < record < payment``. Las restricciones
temporales solo se aplican cuando estan declaradas y scoped por fuente,
infraestructura o tipo de evento. Sin restriccion declarada, cualquier
orden observado se acepta y se preserva tal cual.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class TemporalConstraint:
    rule_id: str
    scope_source_id: str | None
    scope_event_type: str | None
    left: str
    operator: str  # "<" | "<=" | "==" | "!="
    right: str
    description: str


# Solo restricciones demostradas. Deliberadamente NO hay una restriccion
# global: la ausencia de regla significa "sin supuesto".
CONSTRAINTS: tuple[TemporalConstraint, ...] = (
    TemporalConstraint(
        rule_id="P3_PORTFOLIO_RECORD_BEFORE_EX",
        scope_source_id="PORTFOLIO_STOCK_EXCHANGE",
        scope_event_type=None,
        left="RECORD_DATE",
        operator="<",
        right="EX_DATE",
        description="P3 Spain SOCIMI: record date anterior a ex date.",
    ),
    TemporalConstraint(
        rule_id="P3_PORTFOLIO_PAYMENT_EQUALS_EX",
        scope_source_id="PORTFOLIO_STOCK_EXCHANGE",
        scope_event_type=None,
        left="PAYMENT_DATE",
        operator="==",
        right="EX_DATE",
        description="P3 Spain SOCIMI: payment date igual a ex date.",
    ),
)

RULESET_VERSION = "CA_ES_TEMPORAL_RULESET_V1"
GLOBAL_DATE_ORDER_ASSUMED = False


def _compare(left: date, operator: str, right: date) -> bool:
    if operator == "<":
        return left < right
    if operator == "<=":
        return left <= right
    if operator == "==":
        return left == right
    if operator == "!=":
        return left != right
    raise ValueError(f"operador temporal desconocido: {operator!r}")


def check(
    dates: dict[str, str],
    source_id: str | None = None,
    event_type: str | None = None,
) -> list[dict]:
    """Evalua solo las restricciones declaradas aplicables al scope.

    Devuelve violaciones (vacio = sin restriccion violada, no necesariamente
    orden valido universal). Si falta alguna fecha referenciada por una
    restriccion aplicable, no se evalua esa restriccion.
    """
    violations: list[dict] = []
    for constraint in CONSTRAINTS:
        if constraint.scope_source_id is not None and constraint.scope_source_id != source_id:
            continue
        if constraint.scope_event_type is not None and constraint.scope_event_type != event_type:
            continue
        raw_left = dates.get(constraint.left)
        raw_right = dates.get(constraint.right)
        if raw_left is None or raw_right is None:
            continue
        left = date.fromisoformat(raw_left)
        right = date.fromisoformat(raw_right)
        if not _compare(left, constraint.operator, right):
            violations.append(
                {
                    "rule_id": constraint.rule_id,
                    "expected": f"{constraint.left}{constraint.operator}{constraint.right}",
                    "observed": f"{constraint.left}={raw_left},{constraint.right}={raw_right}",
                    "scope": {
                        "source_id": source_id,
                        "event_type": event_type,
                    },
                }
            )
    return violations


def assert_no_global_order(dates: dict[str, str]) -> None:
    """Demuestra que un orden atipico no dispara ningun supuesto global."""
    if GLOBAL_DATE_ORDER_ASSUMED:  # pragma: no cover - invariante
        raise AssertionError("G0 prohibe el supuesto de orden global de fechas")
