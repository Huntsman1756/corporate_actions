# P5.6 — MT567 Status / Advice + Instruction Binding

Status: **FROZEN — PENDING IMPLEMENTATION**.
Parent: P5.5 MT565 Projection DONE.

Pregunta única:

> Dado un MT567 (CA status/advice) y una instrucción emitida, ¿puede
> demostrarse — solo con referencias explícitas del mensaje — a qué
> instrucción se refiere y qué status comunica?

La observación de status queda separada del intent P5.4:
`CA_ES_ELECTION_INSTRUCTION_V1` nunca se muta; custodian status !=
workflow humano; MT567 no reinterpreta recon P3.5.

```text
MT567 FIN -> adapter JVM (Prowide genérico, mismo pipeline P4.0)
          -> CA_ES_SWIFT_MT_FACTS_V1 (message_identifier=MT567)
CA_ES_ELECTION_INSTRUCTION_V1 (target de binding)
          -> bind_instruction_status()
          -> CA_ES_ELECTION_INSTRUCTION_STATUS_V1
```

## Adapter

`SUPPORTED` pasa a `{"564","566","567"}`. Sin parser nuevo: el
extractor genérico 16R/16S + reflexión `FieldNN` ya produce facts con
sequence path (`GENL/LINK`, `GENL/STAT`, `GENL/STAT/REAS`).

## Semántica evidenciada (SRU2025-10.3.19, UHB ISO 15022)

- `GENL/A1/LINK` (O rep) referencia el mensaje previo:
  `:13A::LINK//565` + `:20C::PREV//<SEME de nuestro MT565>`.
  Como P5.5 emite `20C::SEME//<instruction_id>`, el binding es
  determinista sin fuzzy matching.
- `GENL` lleva `23G` función (`INST` = instruction status),
  `20C::SEME` (ref del advice) y `20C::CORP`.
- `GENL/A2/STAT` (O rep): `25D` status code con qualifier
  `IPRC` (instruction processing; también existen `CPRC`/`EPRC`
  para otras funciones del mensaje).
- `GENL/A2/STAT/REAS` (A2a): `24B` reason code, `70D` narrativa.

## Binding (fail closed, nunca fuzzy)

Input: instruction doc (contiene `instruction_id` + referencias de
origen). Candidates = valores distintos de facts
`sequence=GENL/LINK, tag=20C, qualifier=PREV`.

```text
target en PREV y |PREV distintos| == 1  -> BOUND
target en PREV y |PREV distintos| > 1   -> AMBIGUOUS
                 (mensaje multi-instrucción; V1 no selecciona)
target no en PREV, PREV existe          -> NO_MATCH
sin fact PREV                           -> INSUFFICIENT_IDENTITY
```

`RELA` no se usa para binding en V1 (PREV es la referencia al mensaje
previo; RELA es relación genérica). `CORP` del MT567 se conserva como
provenance, no como clave.

## normalized_status (whitelist preregistrada)

Solo `25D` con qualifier `IPRC`:

```text
PACK -> ACCEPTED
REJT -> REJECTED
PEND -> PENDING
DFLA -> DEFAULT_ACTION_APPLIED
```

Cualquier otro código u otro qualifier (`CPRC`, `EPRC`, ...) ->
`normalized_status = UNSUPPORTED` y `status_code_raw`/`status_qualifier`
se preservan verbatim.

Si `23G != INST` -> reason `MESSAGE_FUNCTION_NOT_INST` (los statuses se
reportan igualmente, raw).

## Output

```text
CA_ES_ELECTION_INSTRUCTION_STATUS_V1

schema, generated_at
source_message_identifier   "MT567"
input_sha256
instruction_id              (target)
instruction_binding_status  BOUND | AMBIGUOUS | NO_MATCH |
                            INSUFFICIENT_IDENTITY
canonical_event_id          (solo si BOUND; desde la instrucción)
source_canon_logical_sha256     (idem)
source_positions_logical_sha256 (idem)
source_message_input_sha256     (idem: sha del MT564 origen)
message_function            (23G raw o null)
reasons[]                   (doc-level)
statuses[]
  sequence                  "GENL/STAT"
  sequence_occurrence
  status_qualifier          (IPRC/CPRC/EPRC raw o null)
  status_code_raw
  normalized_status
  reason_code_raw           (24B o null)
  reason_qualifier
  reason_narrative          (70D o null)
  provenance[]              field_paths del 25D + REAS del STAT
```

Agrupación STAT->REAS: posicional por `evidence_locator`
(`block4.tag[i]`); un REAS pertenece al STAT cuyo 25D lo precede y al
que le sigue el siguiente 25D de `GENL/STAT`. Determinista.

Fail closed: doc facts no-MT567 o schema distinto -> `ValueError`
(`INVALID_SWIFT_FACTS_DOCUMENT` / `EXPECTED_MT567`). Instruction schema
distinto -> `INVALID_INSTRUCTION_DOCUMENT`.

## CLI

```bash
ca-es instruction-status (--fin <mt567.fin> | --facts <facts.json>) \
    --instruction <CA_ES_ELECTION_INSTRUCTION_V1.json> [--now <iso>]
```

## Tests preregistrados

1. MT567 válido (`PREV//INS-0001`, `IPRC//PACK`) -> BOUND +
   ACCEPTED + refs de origen copiadas.
2. PREV distinto -> NO_MATCH.
3. Multi-PREV conteniendo el target -> AMBIGUOUS.
4. Sin LINK/PREV -> INSUFFICIENT_IDENTITY.
5. Status conocido -> normalización whitelist (PACK/REJT/PEND/DFLA).
6. Status desconocido u otro qualifier -> UNSUPPORTED + raw.
7. 23G != INST -> reason MESSAGE_FUNCTION_NOT_INST.
8. REAS (24B/70D) asociado posicionalmente a su STAT; multi-STAT
   agrupa correctamente.
9. Doc facts no MT567 -> fail closed.
10. Provenance end-to-end (field_paths presentes).
11. Determinismo con --now fijo; inputs no mutados.
12. e2e JVM real: fixture .fin -> parse_mt -> bind -> BOUND
    (NoSkips en job jvm).
13. Malformed MT567 -> PARSE_ERROR por adapter.

## Fuera de alcance

* transiciones de estado del instruction doc (nunca se muta);
* reinterpretación como workflow P3.5;
* MT568 (extended status), cancelaciones, ISO 20022;
* matching por CORP/SEME/narrativa;
* agregación de múltiples mensajes por instrucción.
