# ADR-008 — Financial Decimal/scale policy

Status: ACCEPTED (G0 freeze, 2026-09-13)

## Context

`float` binario no representa exactamente importes ni ratios y pierde la
escala publicada.

## Decision

- Prohibido `float` para facts financieros canónicos.
- `FinancialAmount` preserva: `raw_lexeme`, `normalized` (`Decimal`),
  `scale`, `currency`.
- El lexema raw es la autoridad; la normalización solo sustituye el
  separador decimal y valida. Nunca redondea.
- Un lexema ambiguo (p. ej. `1.234,56`) se rechaza; no se interpreta.
- La serialización canónica usa el string decimal normalizado.

Ejemplo P3: `raw_lexeme="0,11840672"`, `normalized="0.11840672"`,
`scale=8`, `currency="EUR"`.

Gates: `NO_BINARY_FLOAT_FOR_FINANCIAL_FACTS`,
`PUBLISHED_SCALE_PRESERVED`, `NO_IMPLICIT_ROUNDING`.
