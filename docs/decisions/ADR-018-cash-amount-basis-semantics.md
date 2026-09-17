# ADR-018 — `amount_basis` en cash movements y no-compatibilidad semántica V1

Status: ACCEPTED (P3.1, implementado en `54dd0c7`)

## Context

P2.0 produce entitlements cuyo importe esperado es **explícitamente
bruto** (`gross_cash`). `CA_ES_CASH_MOVEMENTS_V1` sólo declaraba
`amount`, sin indicar si el abono observado era bruto, neto o de base
desconocida. La reconciliación P3.0 comparaba directamente:

```text
expected gross_cash == actual amount
```

En operativa real un abono de dividendo puede venir neto de
retenciones. Bajo V1, un movimiento neto producía un
`AMOUNT_MISMATCH` perfectamente calculado pero **conceptualmente
falso**: se comparaban magnitudes de bases distintas.

## Decision

`CA_ES_CASH_MOVEMENTS_V2` añade el campo obligatorio en semántica
(aunque opcional en sintaxis):

```text
movement.amount_basis = GROSS | NET | UNKNOWN
```

Reglas de reconciliación:

```text
GROSS   + expected gross_cash → reconciliable (MATCH / AMOUNT_MISMATCH)
NET     + sólo gross expected → INDETERMINATE / NET_EXPECTED_NOT_AVAILABLE
UNKNOWN + cualquier expected  → INDETERMINATE / UNKNOWN_AMOUNT_BASIS
```

`AMOUNT_MISMATCH` sólo se emite cuando la comparación es
semánticamente válida (gross contra gross). Nunca se infiere la base
desde relaciones numéricas (`actual < expected` no significa neto),
nunca se calcula withholding y nunca se hace conversión net↔gross.

`amount_basis` fuera del vocabulario convierte el movimiento en
`invalid_movements`; nunca participa en el match.

### Compatibilidad V1: ingestión sí, semántica no

`load_movements()` sigue aceptando `CA_ES_CASH_MOVEMENTS_V1`. La
ausencia de `amount_basis` se normaliza a `UNKNOWN`.

**Esto es compatibilidad de ingestión, NO compatibilidad semántica
de resultado.** Un documento V1 que bajo P3.0 producía `MATCH` ahora
produce `INDETERMINATE/UNKNOWN_AMOUNT_BASIS`. Es una corrección del
contrato, no una regresión: el `MATCH` anterior asumía bruto sin
evidencia.

Queda explícitamente prohibido «restaurar compatibilidad»
tratando la ausencia de `amount_basis` como `GROSS`. Quien quiera
`MATCH` debe declarar la base en V2.

## Consequences

- La frontera P2→P3 queda honesta: el expected tiene base declarada
  (gross) y el actual también.
- `INDETERMINATE` con `reason_code` conserva la causa exacta; no se
  degrada a excepción monetaria.
- La ampliación futura (expected net, withholding, FX) es aditiva:
  nuevas bases o nuevos expected, no reinterpretación de los
  existentes.

## References

- `src/ca_es/reconciliation.py` (`AMOUNT_BASES`, `MOVEMENTS_SCHEMAS`).
- ADR-008 (decimal/scale): las comparaciones siguen siendo `Decimal`
  exactas, sin tolerancias.
