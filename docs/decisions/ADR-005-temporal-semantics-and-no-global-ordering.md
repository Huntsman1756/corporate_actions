# ADR-005 — Temporal semantics and no global ordering

Status: ACCEPTED (G0 freeze, 2026-09-13)

## Context

Iberclear y P3 Spain demuestran semánticas de fecha distintas. Asumir
`ex < record < payment` universalmente corrompería eventos válidos.

## Decision

`NO_GLOBAL_DATE_ORDER_ASSUMPTION`. Las restricciones temporales son:

- source-scoped,
- infrastructure-scoped,
- event-type-scoped,

y deben declararse. Sin restricción declarada, cualquier orden se acepta
tal cual y se preserva sin inferencias.

Reglas G0 declaradas (canario P3, Portfolio):

- `RECORD_DATE < EX_DATE`
- `PAYMENT_DATE == EX_DATE`

Una fecha publicada es `EXPLICIT`; una derivada con definición demostrada
es `DERIVED_BY_DEFINITION`; si no se sabe, `UNKNOWN`.

Gates: `NO_GLOBAL_DATE_ORDER_ASSUMPTION`, `DATE_SEMANTICS_SOURCE_SCOPED`,
`NO_INFERRED_CANONICAL_DATES`, `UNKNOWN_PRESERVED`.
