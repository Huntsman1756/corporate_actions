# P5.4 — Election Instruction Intent

Status: **FROZEN — PENDING IMPLEMENTATION**.
Parent: P5.3 Election Eligibility DONE (`f6a288d`).

Pregunta única:

> Dada una celda de eligibility demostrada, ¿qué instrucción intenta
> emitir el actor, con qué cantidad y sobre qué opción explícita?

P5.4 produce un artefacto de negocio interno. **No** es un MT565, no
genera SWIFT, no representa ack del custodio y no muta eligibility,
opportunity, positions ni canon.

```text
CA_ES_ELECTION_ELIGIBILITY_V1
+ CA_ES_ELECTION_OPPORTUNITY_V1
+ instruction request explicita
        ↓
build_instruction()
        ↓
CA_ES_ELECTION_INSTRUCTION_V1
```

## Instruction request

Campos obligatorios, todos explícitos del caller:

```text
instruction_id        idempotency/business key del caller
account_id
option_key
requested_quantity    Decimal-only
actor
instructed_at         timestamp ISO explicito
```

`instruction_id` nunca se sintetiza desde timestamps ni de otro dato.

## Binding fail-closed

```text
eligibility.source_canon_logical_sha256
    == opportunity.source_canon_logical_sha256

eligibility.source_message_input_sha256
    == opportunity.input_sha256            (donde aplique)

eligibility.canonical_event_id
    == opportunity.canonical_event_id
```

Mismatch -> `ValueError`:

```text
ELIGIBILITY_OPPORTUNITY_MISMATCH
```

El documento de instrucción conserva las huellas para que P5.5 quede
ligado a los mismos inputs:

```text
source_canon_logical_sha256
source_positions_logical_sha256
source_message_input_sha256
```

## Resolución de la celda

`account_id + option_key` debe resolver a **exactamente una** celda de
`eligibilities[]`:

```text
0  -> INDETERMINATE / ELIGIBILITY_CELL_NOT_FOUND
>1 -> INDETERMINATE / AMBIGUOUS_ELIGIBILITY_CELL
 1 -> continuar
```

Sobre la celda resuelta:

```text
eligibility_status != ELIGIBLE -> INDETERMINATE / CELL_NOT_ELIGIBLE
option_key ausente en opportunity.options[]
    -> INDETERMINATE / OPTION_NOT_IN_OPPORTUNITY
option_kind == UNSUPPORTED -> UNSUPPORTED / UNSUPPORTED_OPTION_KIND
```

## Cantidad

Decimal exclusivamente (`requested_quantity`).

```text
invalido   -> INDETERMINATE / INVALID_REQUESTED_QUANTITY
<= 0       -> INDETERMINATE / NON_POSITIVE_REQUESTED_QUANTITY
> eligible -> INDETERMINATE / REQUEST_EXCEEDS_ELIGIBLE_QUANTITY
< eligible -> UNSUPPORTED / PARTIAL_ELECTION_TERMS_NOT_MODELED
= eligible -> READY
```

P5.3 V1 solo demuestra `FULL_POSITION`; P5.4 V1 solo soporta
instrucción por la totalidad elegible. Nunca se infiere que una
instrucción parcial esté permitida y nunca se interpreta `terms[]` raw
(mínimos, múltiplos, ratios, fracciones, oversubscription, prorrateo).

## Output

```text
CA_ES_ELECTION_INSTRUCTION_V1

schema
generated_at
instruction_id
canonical_event_id
account_id
isin
option_key
option_identifier
option_code_raw
option_kind

requested_quantity
eligible_quantity

instruction_status      READY | INDETERMINATE | UNSUPPORTED
reasons[]

actor
instructed_at

source_canon_logical_sha256
source_positions_logical_sha256
source_message_input_sha256

eligibility_key
eligibility_rule_id

evidence
  assertion_ids           (de la celda)
  option_provenance       (de la celda/opportunity)
  position_index          (de la celda)
```

Sin estados de workflow (SENT/ACKNOWLEDGED): eso es ciclo de vida de
transporte, no intención de instrucción.

## Invariantes

* Nunca se sintetiza `instruction_id`.
* Solo celdas `ELIGIBLE` producen `READY`.
* `requested < eligible` nunca se reinterpreta como parcial permitida.
* Inputs nunca mutados; mismo `--now` -> output idéntico.
* `eligibility_key` y `eligibility_rule_id` se conservan verbatim.

## Tests preregistrados

1. Instrucción full-position válida -> READY.
2. account desconocido -> ELIGIBILITY_CELL_NOT_FOUND.
3. option desconocido -> ELIGIBILITY_CELL_NOT_FOUND.
4. Celda no-ELIGIBLE -> CELL_NOT_ELIGIBLE.
5. requested zero/negative/invalid.
6. requested > eligible -> REQUEST_EXCEEDS_ELIGIBLE_QUANTITY.
7. requested < eligible -> PARTIAL_ELECTION_TERMS_NOT_MODELED.
8. Mismatch de artefactos -> fail closed.
9. Resolución ambigua (celdas duplicadas) -> AMBIGUOUS_ELIGIBILITY_CELL.
10. Option kind unsupported -> UNSUPPORTED.
11. Option ausente de opportunity -> OPTION_NOT_IN_OPPORTUNITY.
12. Inputs no mutados.
13. Determinismo con `--now` fijo.
14. Campos de request ausentes -> fail closed.

## CLI

```bash
ca-es election-instruction --eligibility <CA_ES_ELECTION_ELIGIBILITY_V1.json> \
    --opportunity <CA_ES_ELECTION_OPPORTUNITY_V1.json> \
    --request <instruction-request.json> [--now <iso>]
```

El request viaja como documento JSON explicito, no como flags, para que
`instruction_id`/`actor`/`instructed_at` queden fuera del argv.

## Fuera de alcance

* MT565 / generación SWIFT (P5.5, fuera del core segun ADR-010);
* partial elections y terminos normalizados;
* instruction lifecycle / workflow;
* ack del custodio / MT567 (P5.6);
* dedup de instruction_id entre documentos;
* ISO 20022.
