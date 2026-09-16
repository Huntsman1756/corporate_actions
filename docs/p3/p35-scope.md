# P3.5 — Exceptions / Workflow

Status: **FROZEN — PENDING IMPLEMENTATION**.
Parent: P3.1 cerrado — ADR-018 (`amount_basis`), commit `54dd0c7`.

P3.5 no es una lista de errores. Es un subsistema operativo con una
frontera clara:

```text
evidence/result → exception classification → operational case
              → human workflow → auditable resolution
```

La cola **consume los estados existentes sin reinterpretarlos**.
P3.5 no vuelve a calcular dinero ni decide si algo «debería» ser
bruto/neto: recibe hechos ya adjudicados por las fases anteriores.

**P3.1 = verdad semántica del cash.**
**P3.5 = hacer esa verdad operable sin alterarla.**

## Principios congelados

1. `MATCH` normalmente no crea excepción.
2. `AMOUNT_MISMATCH`, `MISSING_CASH`, `UNEXPECTED_CASH`,
   `INDETERMINATE`, etc. se transforman mediante **reglas
   deterministas** en casos operativos.
3. `INDETERMINATE` no se degrada a «error»: conserva el
   `reason_code` exacto, especialmente `NET_EXPECTED_NOT_AVAILABLE`
   y `UNKNOWN_AMOUNT_BASIS`.
4. Cada caso tiene `case_key` **estable**: reejecutar el motor no
   duplica trabajo.
5. La prioridad se basa en hechos observables —tipo de excepción,
   fecha, importe cuando sea comparable, antigüedad— nunca en
   heurísticas financieras inventadas.
6. **Estado workflow separado del estado factual.** Algo puede
   seguir siendo `INDETERMINATE` aunque operacionalmente esté
   `RESOLVED` porque una persona lo haya revisado. `RESOLVED` nunca
   modifica el resultado factual.
7. Toda transición deja actor, timestamp, estado anterior/nuevo y
   nota/reason.
8. Reprocesar nueva evidencia puede cerrar, actualizar o reabrir un
   caso **sin destruir su historia**.

## Modelo mínimo

```text
Case
  case_key
  event_id / entitlement_id / movement_id
  exception_type
  factual_status
  reason_code
  amount_basis
  expected_amount
  actual_amount
  delta                  # solo cuando semánticamente válido
  workflow_status
  priority
  first_seen_at
  last_seen_at
  assigned_to
  resolution_code
  resolution_note
  resolved_at
```

## Taxonomías separadas

```text
factual_status:
  MATCH
  AMOUNT_MISMATCH
  MISSING_CASH
  UNEXPECTED_CASH
  INDETERMINATE
  ...

workflow_status:
  OPEN
  IN_REVIEW
  WAITING_EXTERNAL
  RESOLVED
  DISMISSED
```

El desacoplamiento factual/workflow es la decisión más importante de
P3.5.

## Casos preregistrados (edge cases que rompen workflows)

- Misma excepción observada en dos ejecuciones **no duplica** el
  caso (`case_key` estable).
- Desaparición de la excepción al reprocesar cierra/supersede el
  caso de forma trazable.
- Una excepción `RESOLVED` que reaparece tras nueva evidencia se
  **reabre** (no se crea una nueva ni se ignora).
- `UNKNOWN_AMOUNT_BASIS` nunca genera `AMOUNT_MISMATCH`.
- `NET_EXPECTED_NOT_AVAILABLE` conserva `actual_amount` pero no
  inventa `delta`.
- `UNEXPECTED_CASH` mantiene `amount_basis` aunque no tenga
  expected.

## Fuera de alcance (P3.5)

- SLA, notificaciones, dashboards.
- Asignación automática sofisticada.
- Recalcular dinero, withholding, net↔gross, FX, netting,
  agregación.
- Reinterpretar `factual_status` ni `reason_code`.

## Cierre

Primero se implementa **case identity + lifecycle + audit trail +
deterministic queue projection**. Todo lo demás puede crecer encima
sin contaminar el núcleo.
