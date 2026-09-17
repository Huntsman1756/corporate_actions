# P5.3 — Election Eligibility

Status: **DONE** (`f6a288d`).
Parent: P5.2 Election Opportunity DONE (`e5111db`).

Pregunta única:

> Para cada posición y cada opción explícitamente comunicada, ¿qué cantidad puede demostrarse como elegible bajo una regla de eligibility explícita?

P5.3 no representa una elección del cliente, no crea una instrucción y no genera MT565.

```text
CA_ES_ELECTION_OPPORTUNITY_V1
+ canonical event
+ CA_ES_POSITIONS_V1
+ CA_ES_ELECTION_ELIGIBILITY_RULES_V1
        ↓
compute_election_eligibility()
        ↓
CA_ES_ELECTION_ELIGIBILITY_V1
```

## Fronteras

```text
election opportunity != eligibility
eligibility          != instructed quantity
eligibility          != client choice
client choice         != MT565
response deadline     != position eligibility basis
```

El deadline operativo indica **cuándo actuar**. Nunca determina por sí mismo **qué posición es elegible**.

## Binding fail-closed

La opportunity debe pertenecer exactamente al canon utilizado:

```text
opportunity.source_canon_logical_sha256
    == canon.logical_sha256
```

Mismatch:

```text
OPPORTUNITY_CANON_MISMATCH
```

El output conserva además una huella determinista del documento de posiciones para que P5.4 pueda quedar ligado al mismo input:

```text
source_positions_logical_sha256
```

No se modifica `CA_ES_POSITIONS_V1`.

## Reglas de eligibility

Nuevo input:

```text
CA_ES_ELECTION_ELIGIBILITY_RULES_V1
```

Regla mínima V1:

```text
rule_id
event_types[]          optional
option_kinds[]         optional
option_codes[]         optional
position_basis         POSITION_AT_DATE_FIELD
basis_field            e.g. date.record_date
quantity_rule          FULL_POSITION
```

P5.3 sólo soporta inicialmente:

```text
position_basis = POSITION_AT_DATE_FIELD
quantity_rule  = FULL_POSITION
```

Cualquier otra semántica:

```text
UNSUPPORTED_ELIGIBILITY_RULE
```

Las reglas son datos, no lógica de custodio hardcodeada.

Matching de reglas:

```text
0 reglas  -> INDETERMINATE / NO_APPLICABLE_RULE
1 regla   -> usarla
>1 reglas -> INDETERMINATE / AMBIGUOUS_ELIGIBILITY_RULE
```

No existe precedencia implícita por “regla más específica”.

## Position eligibility

La fecha base se obtiene exclusivamente del `basis_field` canónico indicado por la regla.

Estados de la fecha:

```text
CURRENT válido       -> continuar
ausente               -> MISSING_BASIS_DATE
CONFLICTING           -> CONFLICTING_BASIS_DATE
valor no ISO          -> INVALID_BASIS_DATE
```

La posición usa `position.as_of` o, si falta, el `as_of` del documento `CA_ES_POSITIONS_V1`.

Para `POSITION_AT_DATE_FIELD`:

```text
position_as_of == basis_date -> elegibilidad demostrada
position_as_of <  basis_date -> POSITION_SNAPSHOT_BEFORE_BASIS
position_as_of >  basis_date -> POSITION_SNAPSHOT_AFTER_BASIS
```

Antes/después son `INDETERMINATE`; nunca se supone continuidad de titularidad.

## Cantidad

Decimal exclusivamente.

Para `FULL_POSITION`:

```text
eligible_quantity = position.quantity
```

Sólo cuando la posición ha superado todas las comprobaciones de eligibility.

```text
quantity > 0 -> ELIGIBLE
quantity = 0 -> NOT_ELIGIBLE / ZERO_QUANTITY
quantity < 0 -> INDETERMINATE / NEGATIVE_QUANTITY_UNSUPPORTED
invalid      -> INDETERMINATE / INVALID_QUANTITY
```

No rounding, no netting, no agregación y no suma silenciosa de líneas duplicadas.

Una clave de posición duplicada (`account_id + isin + position_as_of`) produce:

```text
INDETERMINATE / DUPLICATE_POSITION_KEY
```

## Instrument identity

La posición sólo puede asociarse mediante identidad explícita del evento.

Cero instrumentos identificables:

```text
MISSING_INSTRUMENT_IDENTITY
```

Más de una identidad compatible sin una regla explícita que seleccione:

```text
AMBIGUOUS_INSTRUMENT_IDENTITY
```

No fuzzy matching ni ticker fallback.

## Output

```text
CA_ES_ELECTION_ELIGIBILITY_V1

source_canon_logical_sha256
source_positions_logical_sha256
source_message_input_sha256
canonical_event_id
generated_at

eligibilities[]
  eligibility_key
  account_id
  isin

  option_key
  option_identifier
  option_code_raw
  option_kind

  rule_id
  position_basis
  basis_field
  basis_date

  position_quantity
  position_as_of
  eligible_quantity

  eligibility_status
      ELIGIBLE
      NOT_ELIGIBLE
      INDETERMINATE
      UNSUPPORTED

  reasons[]
  evidence
```

`eligibility_key`:

```text
event_id | account_id | option_key
```

No depende del status.

## Option semantics

`option_kind == UNSUPPORTED`:

```text
eligibility_status = UNSUPPORTED
```

P5.3 no interpreta `terms[]` raw para inventar mínimos, múltiplos, ratios, prorrateos o cantidades instruibles.

Esas restricciones quedan para P5.4 cuando estén normalizadas y preregistradas.

## Invariantes

* Opportunity distinta de `PROJECTED` nunca produce `ELIGIBLE`.
* Canon nunca se modifica.
* Positions nunca se modifican.
* Cada `ELIGIBLE` enlaza a regla + fecha canónica + posición + opción.
* Un snapshot anterior/posterior nunca prueba eligibility.
* Nunca se infiere eligibility desde el deadline.
* Nunca se agrega posiciones duplicadas.
* Nunca se interpreta un término raw para aumentar/reducir cantidad.
* Reejecutar con los mismos inputs y `--now` fijo produce output idéntico.

## Tests preregistrados

1. Una posición exacta en basis date × dos opciones → dos ELIGIBLE.
2. Zero quantity → NOT_ELIGIBLE.
3. Snapshot anterior → INDETERMINATE.
4. Snapshot posterior → INDETERMINATE.
5. Missing/conflicting/invalid basis date.
6. Invalid/negative quantity.
7. Opportunity/canon SHA mismatch → fail closed.
8. Sin regla → NO_APPLICABLE_RULE.
9. Dos reglas → AMBIGUOUS_ELIGIBILITY_RULE.
10. Regla no soportada → UNSUPPORTED.
11. Option kind unsupported → UNSUPPORTED.
12. Duplicate position key → INDETERMINATE, nunca suma.
13. Instrument identity ausente/ambigua.
14. Provenance completa hasta option + canon assertion + position.
15. Canon, opportunity y positions no mutados.
16. Determinismo con `--now` fijo.

## Fuera de alcance

* elección del cliente;
* instructed quantity;
* validación de mínimos/múltiplos/ratios raw;
* partial elections;
* oversubscription;
* prorrateo;
* instruction lifecycle;
* MT565;
* generación SWIFT;
* exceptions P3.5;
* ISO 20022.

Siguiente fase:

```text
P5.4
CA_ES_ELECTION_ELIGIBILITY_V1
+ selected option
+ requested quantity
+ actor/timestamp
+ términos normalizados soportados
    -> CA_ES_ELECTION_INSTRUCTION_V1
```

Sólo después se diseña la serialización MT565 fuera del core según ADR-010.
