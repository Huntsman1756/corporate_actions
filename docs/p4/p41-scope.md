# P4.1 — SWIFT semantic projection + deterministic event binding

Status: **DONE** (implementado en `4c54644`).
Parent: P4.0 DONE (`fb94702`). Frontera ADR-010/018.

```text
MT564/566 FIN
   -> CA_ES_SWIFT_MT_FACTS_V1        (P4.0)
   -> semantic projection
   -> CA_ES_SWIFT_CA_MESSAGE_V1
   -> bind against canonical events
   -> CA_ES_SWIFT_EVENT_BINDING_V1
```

Scope inicial exclusivamente `DVCA -> CASH_DIVIDEND` (única familia
con cadena completa entitlement -> recon -> exceptions).

## Regla esencial

La proyección SWIFT **no modifica el canon**. Produce una observación
adicional y un binding. Cero fuzzy matching, cero mutación.

## `CA_ES_SWIFT_CA_MESSAGE_V1`

Proyectado desde facts, conservando provenance original por campo
(`source_tag`, `source_qualifier`, `sequence`, `evidence_locator`,
`input_sha256`). Campos iniciales:

```text
message_type
corporate_action_reference    20C::CORP (GENL)
related_reference             20C::RELA (GENL)
caev                          22F::CAEV indicator (GENL)
event_type                    DVCA -> CASH_DIVIDEND
isin                          35B componente isin
ex_date                       98A::XDTE  (YYYYMMDD -> ISO)
record_date                   98A::RDTE
payment_date                  98A::PAYD
gross_per_share               92J/92B::GRSS (decimal coma -> punto)
currency                      19B::GRSS currency code
message_function              23G
processing_status             25D
```

Cada campo: `{value, status: PRESENT|ABSENT|CONFLICTING, raw,
provenance[]}`. Ocurrencias múltiples que coinciden -> un valor con
varias provenances; que difieren -> `CONFLICTING` (nunca se elige).

Cualquier CAEV no preregistrado -> status `UNSUPPORTED_CA_EVENT`,
nunca se infiere el event_type.

## `CA_ES_SWIFT_EVENT_BINDING_V1`

```text
BOUND / AMBIGUOUS / NO_MATCH / INSUFFICIENT_IDENTITY
(+ UNSUPPORTED_CA_EVENT cuando el mensaje no es soportado)
```

- identidad explícita: `isin` + `event_type`;
- 1 candidato -> `BOUND` (las fechas NO filtran: un BOUND con
  `DIFFERS` en payment_date es evidencia visible, no NO_MATCH);
- >1 candidatos -> las fechas disponibles desambiguan; si aun asi
  quedan >1 -> `AMBIGUOUS`; si ninguno -> `NO_MATCH`;
- falta isin o event_type -> `INSUFFICIENT_IDENTITY`.

Cuando `BOUND`, comparacion por campo solo cuando semanticamente
equivalente:

```text
AGREES / DIFFERS / CANON_MISSING / SWIFT_MISSING / CANON_CONFLICTING
```

(`CANON_CONFLICTING` se añade respecto al enumerado original: un canon
en conflicto no es ni ausencia ni desacuerdo — es un estado factual
propio que nunca se colapsa a `DIFFERS`). Sin seleccionar ganador.

MT566: proyeccion semantica read-only; NO se proyecta aun a
`CA_ES_CASH_MOVEMENTS_V2` (decidir que importe es reconciliable y con
que `amount_basis` es decision posterior).

## Fuera de alcance

MT565, ISO 20022, actualizacion de canon, cash movement projection,
workflow nuevo, heuristicas probabilisticas.
