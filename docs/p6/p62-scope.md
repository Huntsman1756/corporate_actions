# P6.2 — Projected Post-Event Positions

Status: **FROZEN — PENDING IMPLEMENTATION**.
Parent: P6.1 DONE (`CA_ES_POSITION_IMPACT_V1`).

Pregunta única:

> Dado un snapshot de posiciones y un impacto ya adjudicado, ¿cuál es
> la posición económica proyectada post-evento — línea a línea, sin
> mutar el input?

```text
CA_ES_POSITIONS_V1
+ CA_ES_POSITION_IMPACT_V1
        ↓
project_positions()
        ↓
CA_ES_PROJECTED_POSITIONS_V1
```

## Semántica de proyección (preregistrada)

Una línea proyectada por cada posición del input (mismo orden, sin
agregación):

```text
impact item PROJECTED, quantity_delta null   -> delta 0
    (CASH_RECEIVABLE: el evento no mueve valores)
impact item PROJECTED, quantity_delta = D    -> delta D aplicado a la
    línea del instrumento target_isin (si set) o source_isin, en la
    misma cuenta
impact item INDETERMINATE / UNSUPPORTED      -> línea INDETERMINATE /
    UNSUPPORTED, projected_quantity null
posición sin impact item                     -> INDETERMINATE
    MISSING_IMPACT_ITEM
```

Varios items PROJECTED sobre la misma línea (mismo account+isin): cada
delta se aplica; son aditivos por contrato. Si alguno no es PROJECTED
la línea hereda el peor estado (INDETERMINATE > UNSUPPORTED... orden:
INDETERMINATE gana sobre UNSUPPORTED gana sobre PROJECTED — el estado
menos decidido es el honesto).

En V1 ninguna regla emite `quantity_delta` (P6.0): toda proyección
alcanzable es delta 0. El contrato queda abierto para familias futuras
sin romper el schema.

## Projected line

```text
account_id
isin
pre_quantity               (Decimal string)
delta_quantity             (Decimal string; "0" en V1)
projected_quantity         (Decimal string | null si no PROJECTED)
effective_date             (basis_date del impacto | null)
impact_refs[]              índices "impacts[i]" aplicados
status                     PROJECTED | INDETERMINATE | UNSUPPORTED
reasons[]                  propagadas verbatim del/los item(s)
```

Nunca se fusionan instrumentos distintos en una línea; nunca se
agregan claves duplicadas de posición; no hay settlement assumption —
es proyección económica esperada, no prueba de posición anotada.

## Binding

- `positions.schema == CA_ES_POSITIONS_V1`
- `impact.schema == CA_ES_POSITION_IMPACT_V1`
- `impact.source_positions_logical_sha256` debe igualar
  `sha256(positions)` → si no: error `POSITIONS_HASH_MISMATCH`
  (proyectar sobre otra posición sería inventar).
- Cada impact item se aplica a la línea `(account_id, target_isin or
  source_isin)`; un item PROJECTED con `quantity_delta` cuyo
  instrumento no tiene línea de posición genera una línea proyectada
  nueva (`pre_quantity="0"`) — es una recepción esperada, no una
  posición sintetizada. Items INDETERMINATE/UNSUPPORTED sin línea se
  ignoran (no hay línea que contaminar).

## Tests preregistrados

1. CASH_RECEIVABLE PROJECTED → línea delta 0, projected = pre.
2. Impacto INDETERMINATE → línea INDETERMINATE, projected null,
   reasons verbatim.
3. Impacto UNSUPPORTED → línea UNSUPPORTED.
4. Posición sin item → INDETERMINATE MISSING_IMPACT_ITEM.
5. Hash positions distinto → POSITIONS_HASH_MISMATCH.
6. quantity_delta en item PROJECTED → aplicado a target/source isin
   (contrato, ejercitado sintéticamente).
7. Item con quantity_delta y target_isin ≠ source → la delta va a la
   línea del target, no del source.
8. Múltiples items sobre una línea → deltas aditivos; un INDETERMINATE
   contamina la línea.
9. Determinismo, no mutación, hashes preservados.
10. Schemas inválidos → ValueError.
</content>
