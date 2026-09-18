# P7.3 — MT/MX inbox (CA_ES_INBOX_OBSERVATION_V1)

Adapter filesystem de inbox para el runtime operativo. Sin
conectores de red (email/FTP/SWIFT) en V1.

## Layout

```
<state>/inbox/incoming/     ficheros nuevos (MT .fin / MX .xml)
<state>/inbox/processed/    procesados o duplicados
<state>/inbox/failed/       parse/adapter error
```

El directorio puede venir de `config.inbox.path`; por defecto
`<state>/inbox`.

## Observacion

Cada fichero observado produce una fila `inbox_messages` +
transiciones append-only en `inbox_observations`:

```
input_sha256            identidad byte-exacta (PK)
semantic_fingerprint    identidad de negocio (ver abajo) o NULL
standard_family         "ISO_15022_MT" | "ISO_20022_MX" | NULL
message_identifier      "MT564" | "seev.031.002.10" | ...
received_at             timestamp de observacion (ejecucion)
source_path             ruta original
processing_status       OBSERVED|PARSED|PROCESSED|FAILED|
                        EXACT_DUPLICATE|DUPLICATE_SEMANTIC
duplicate_status        NONE|EXACT|SEMANTIC
artifact_refs           raw input + facts doc
```

Transiciones (append-only, `inbox_observations`):

```
OBSERVED -> PARSED -> PROCESSED
OBSERVED -> FAILED
OBSERVED -> EXACT_DUPLICATE
OBSERVED -> PARSED -> DUPLICATE_SEMANTIC
```

## Deteccion de familia

Por contenido, nunca por extension: XML (`<?xml` / `<` tras
whitespace) -> `parse_mx`; resto -> `parse_mt`. Ambos via el
boundary JVM existente (`swift_mt.parse_mt`, `mx_facts.parse_mx`);
el core sigue stdlib-only y no parsea FIN/XML.

Exit codes del adapter: 0 OK / 2 PARSE_ERROR / 3 UNSUPPORTED /
4 ADAPTER_ERROR -> FAILED con `detail` (nunca contenido del
mensaje en logs/DB).

## Deduplicacion

- **Exacta**: mismo `input_sha256` -> `EXACT_DUPLICATE`, no se
  reprocesa el pipeline de negocio; se mueve a `processed/`
  (idempotente).
- **Semantica**: `input_sha256` distinto pero mismo
  `semantic_fingerprint` -> `DUPLICATE_SEMANTIC`. Ambas
  observaciones quedan; NUNCA se borra ni colapsa ninguna.
- **Fingerprint** = `semantic_sha256` del multiset normalizado de
  facts: `{standard_family, message_identifier, facts: sorted
  [(field_path, value, source_tag, source_qualifier, sequence,
  occurrence)]}` excluyendo `input_sha256`, `evidence_locator` y
  `generated_at` (ejecucion/posicion, no negocio). Cubre
  SEME/CORP/23G/CAEV en MT y BizMsgIdr/referencias/payload en MX
  porque los facts los contienen. Sin parse OK o facts vacios ->
  fingerprint NULL -> no se afirma duplicado semantico
  (conservador: solo se marca lo demostrable).
- Mensajes de ciclo de vida distinto (otro 23G, otro SEME, otro
  payload) producen fingerprints distintos -> jamas colapsan.

## Movimiento de ficheros y crash-safety

1. Fila `inbox_messages` + artefactos (raw + facts) -> commit.
2. Mover fichero a `processed/` o `failed/`.

Crash entre (1) y (2): el fichero queda en `incoming/`; el
siguiente scan ve `input_sha256` ya registrado -> observacion
`EXACT_DUPLICATE` y mueve a `processed/`. Sin perdida ni
reproceso de negocio.

Nunca se escribe FIN/XML crudo en logs ni en columnas de texto
libre: solo sha256, fingerprints y refs a artefactos
content-addressed.

## Paso DAG

`process_inbox` (impuro, opcional): depende de `validate_inputs`;
sin `inbox.path` ni directorio existente -> BLOCKED. Output:
`CA_ES_OPS_INBOX_V1` con el indice de mensajes observados en el
run.
