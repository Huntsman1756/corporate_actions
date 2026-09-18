# P11.3 — FileSpoolTransport (adapter V1)

`src/ca_es/transport/filespool.py`. Boundary de integración por
filesystem: durable handoff verificable, no "SWIFT transport".

## Layout

```text
<spool_directory>/
    outbox/
        <delivery_id>.msg          # bytes exactos del mensaje
        <delivery_id>.meta.json    # sidecar determinista
    receipts/
        <delivery_id>.ack.json     # escritos por consumidor EXTERNO
        <delivery_id>.nak.json
        processed/                 # receipts ya ingeridos
    quarantine/                    # receipts malformados/conflictivos
```

`delivery_id` es `SND-<sha256hex>` — nombre de fichero seguro
multiplataforma.

## Escritura transaccional

1. `mkdir -p outbox/ receipts/ quarantine/` (error → permanente).
2. tmp en `outbox/` vía `tempfile.mkstemp` (mismo filesystem →
   rename atómico).
3. `write` + `flush` + `fsync` del fichero.
4. `os.replace` msg, luego meta (meta = commit marker).
5. `fsync` del directorio `outbox/`.

### Precisión de la garantía "durable"

- **POSIX**: `fsync(fichero)` + rename atómico + `fsync(dir)`
  hacen persistente el rename ante fallo de sistema.
- **Windows**: el `fsync` de directorio no está expuesto por el
  SO (`os.open` sobre directorio falla → best-effort no-op). La
  durabilidad del rename queda entonces en lo que el
  SO/filesystem garantice para `os.replace`; el contenido del
  fichero sí está fsync'd antes del rename.
- La garantía se describe exactamente como la proporciona cada
  plataforma — no se afirma una durabilidad que el SO no expone.

## Idempotencia

Si `outbox/<delivery_id>.msg` ya existe:

- bytes idénticos al `content_sha256` del request →
  `idempotent_replay`, SPOOLED (recovery seguro);
- bytes distintos → FAILED_PERMANENT `DELIVERY_ID_COLLISION`.
  Nunca sobrescritura silenciosa.

## meta.json (determinista)

```json
{"schema": "CA_ES_SEND_META_V1",
 "delivery_id": "...", "instruction_id": "...",
 "message_reference": "...", "message_schema": "...",
 "content_sha256": "...", "destination_id": "...",
 "adapter_type": "filespool", "generation": N}
```

Sin timestamps ni campos volátiles: replay byte-idéntico.

El replay idempotente exige que **los bytes del `.msg`** casen
con `content_sha256` — no basta el meta declarado (meta válido +
`.msg` sustituido → `DELIVERY_ID_COLLISION`, nunca SPOOLED).

## verify() — post-crash

El dispatcher puede verificar el side effect tras un crash:

- msg+meta presentes y msg.sha256 == content_sha256 → `SPOOLED`
- ausentes o incompletos → `NOT_SPOOLED` (retry seguro)
- msg presente con hash distinto → `COLLISION`
- meta con hash distinto → `COLLISION` (boundary corrupto)

## Receipts

El dispatcher (no el adapter de escritura) escanea `receipts/`:

- válido → transición GATEWAY_* + mover a `receipts/processed/`
- malformado/conflictivo → mover a `quarantine/` + fila
  `send_receipts(status=QUARANTINED)` + transición audit
- colisión de nombre en quarantine → sufijo `.<sha8>` del receipt

## Clasificación de errores

| condición | outcome |
|---|---|
| write+rename OK | SPOOLED |
| replay idempotente (bytes verificados) | SPOOLED |
| `message_text` no casa con `content_sha256` del ledger | FAILED_PERMANENT CONTENT_HASH_MISMATCH |
| colisión id+sha distinto, o meta↔msg divergentes | FAILED_PERMANENT DELIVERY_ID_COLLISION |
| falta `spool_directory` | FAILED_PERMANENT MISSING_SPOOL_DIRECTORY |
| mkdir/permiso falla | FAILED_PERMANENT SPOOL_NOT_CREATABLE |
| meta existente ilegible | FAILED_PERMANENT META_UNREADABLE |
| IO en write/rename de `.msg` (pre-commit) | FAILED_RETRYABLE SPOOL_IO |
| IO en write/rename de `.meta` (post-`.msg`) | UNKNOWN SPOOL_IO_POST_MSG → verify() resuelve |
| IO en `.meta` tras `.msg` huérfano | FAILED_RETRYABLE SPOOL_IO |
