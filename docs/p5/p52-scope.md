# P5.2 — Election Opportunity

Status: **DONE** (`e5111db`).
Parent: P5.1.1 CLOSED (`526dd02`).

Pregunta única: ¿qué opciones ha comunicado explícitamente la fuente
para este evento y qué deadline operativo conocido está asociado?

NO responde: cuántos títulos puede instruir A001 (P5.3), qué eligió el
cliente ni qué MT565 enviar (P5.4+). Sin positions, sin elections
voluntarias complejas, sin instrucciones, sin MT565, sin mutar canon.

```text
MT564 FIN
  -> CA_ES_SWIFT_MT_FACTS_V1      (P4.0)
  -> CA_ES_SWIFT_CA_MESSAGE_V1
     + BOUND canonical event      (P4.1)
  + optional CA_ES_ACTION_QUEUE_V1 (P5.1)
  -> CA_ES_ELECTION_OPPORTUNITY_V1
```

## Mapping preregistrado (evidenciado en pw-swift-core
## SRU2025-10.3.19 + adapter P4.0)

Constantes confirmadas en el jar pinneado: `CAOPTN`, `CAON`, `CAOP`,
`DFLT`, `RDDT`. Salida real del adapter sobre fixture `mt564-volu.fin`:

```text
secuencia opción      .../CAOPTN              (16R:CAOPTN)
option identifier     22F:CAON -> .indicator  (001, 002...)
option code           22F:CAOP -> .indicator  (CASH, SECU...)
default flag          17B:DFLT -> .flag       (Y/N explícito)
source response dline 98a:RDDT -> .date       (YYYYMMDD)
términos              sub-secuencias bajo .../CAOPTN/*
                      (CASHMOVE, SECMOVE...) preservadas raw
```

Whitelist `option_kind` cerrada — sólo estos códigos se normalizan:

```text
CAOP=CASH -> CASH
CAOP=SECU -> SECURITIES
```

Cualquier otro valor: `option_code_raw` preservado,
`option_kind = UNSUPPORTED`. Nunca se infiere por descripción.

Agrupación: anclas = facts `22F:CAON` bajo `*/CAOPTN` en orden de
documento; cada opción cubre los facts entre su ancla y la siguiente.
Facts `*/CAOPTN*` anteriores al primer ancla -> `ORPHAN_OPTION_FACTS`.

`default_status`: `DFLT//Y -> DEFAULT`, `DFLT//N -> NOT_DEFAULT`,
ausente -> `UNKNOWN`. Nunca "primera opción = default".

## Contrato

```text
CA_ES_ELECTION_OPPORTUNITY_V1

source_canon_logical_sha256     (del canon de entrada; P5.1.1)
canonical_event_id
source_message_identifier
input_sha256
projection_status               PROJECTED | INDETERMINATE | UNSUPPORTED

options[]
  option_key                    event_id | option:<identifier>
  option_identifier             CAON raw
  option_code_raw               CAOP raw o null
  option_kind                   CASH | SECURITIES | UNSUPPORTED
  default_status                DEFAULT | NOT_DEFAULT | UNKNOWN
                                | CONFLICTING
  source_response_deadline      RDDT ISO o null
  terms[]                       facts raw de sub-secuencias
  provenance[]                  tag/qualifier/sequence/occurrence/
                                locator/input_sha256

source_response_deadline        único si todas las RDDT coinciden,
                                null si divergen (no se elige)
operational_deadlines[]         items de queue aplicables
deadline_binding_status         BOUND | MISSING | AMBIGUOUS
                                | NOT_APPLICABLE (sin queue)
reasons[]
```

## Estados y reglas duras

- MT564 only; otro `message_identifier` -> `UNSUPPORTED` /
  `UNSUPPORTED_MESSAGE_TYPE`.
- CAEV no mapeado -> `UNSUPPORTED` / `UNSUPPORTED_CA_EVENT`.
- binding != BOUND -> `INDETERMINATE` / `EVENT_NOT_BOUND`.
- Ausencia de CAOPTN -> `INDETERMINATE` / `NO_OPTION_EVIDENCE`;
  **nunca** NON_ELECTIVE.
- CAON ausente en un bloque de opción -> `MISSING_OPTION_IDENTITY`.
- Identificadores duplicados -> `CONFLICTING_OPTION_IDENTITY`.
- Facts contradictorios de una opción -> `CONFLICTING_OPTION_FACTS`.
- `source_response_deadline` es hecho comunicado; **no** es el
  deadline operativo P5.

## Deadline binding (sin recalcular)

Con `queue_doc`: requiere `deadline_types` explícitos (vacío ->
`ValueError(MISSING_DEADLINE_TYPE_CONFIG)`); valida
`queue.source_canon_logical_sha256 == canon.logical_sha256` ->
`ValueError(QUEUE_CANON_MISMATCH)` si no.

```text
items aplicables (evento + deadline_type):
  1 -> BOUND      operational_deadlines=[item]
  0 -> MISSING    operational_deadlines=[]
 >1 -> AMBIGUOUS  operational_deadlines=[todos]   (nunca el más
                                                   temprano)
sin queue -> NOT_APPLICABLE
```

## CLI

```bash
ca-es swift-election --fin|--facts <...> --canon <canon.json> \
    [--queue <CA_ES_ACTION_QUEUE_V1.json> --deadline-type <T>...] \
    [--now <iso>]
```

## Fuera de alcance

Positions/eligibility (P5.3), instrucción (P5.4), MT565, dedup entre
opciones, semántica de CAMV (VOLU/MAND no cambia la proyección),
elections fuera de MT564.
