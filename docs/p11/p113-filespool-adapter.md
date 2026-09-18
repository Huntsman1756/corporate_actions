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
2. tmp `.tmp-<pid>-<delivery_id>.msg` + `.meta.json` en `outbox/`
   (mismo filesystem → rename atómico).
3. `fsync` de ambos ficheros.
4. `os.replace` msg, luego meta (meta = commit marker).
5. `fsync` del directorio.

## Idempotencia

Si `outbox/<delivery_id>.msg` ya existe:

- bytes idénticos al `content_sha256` del request →
  `idempotent_replay`, SPOOLED (recovery seguro);
- bytes distintos → FAILED_PERMANENT `DELIVERY_ID_COLLISION`.
  Nunca sobrescritura silenciosa.

## meta.json (determinista)

```json
{"schema": "CA_ES_SEND_META_V1",
 "delivery_id": "...", "message_schema": "...",
 "message_reference": "...", "instruction_id": "...",
 "content_sha256": "...", "bytes": N}
```

Sin timestamps ni campos volátiles: replay byte-idéntico.

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
| replay idempotente | SPOOLED |
| colisión | FAILED_PERMANENT DELIVERY_ID_COLLISION |
| falta `spool_directory` | FAILED_PERMANENT SPOOL_NO_DIRECTORY |
| mkdir/permiso falla | FAILED_PERMANENT SPOOL_MKDIR_FAILED |
| IO en write/rename | FAILED_RETRYABLE SPOOL_IO_ERROR |
| meta verification post-write | FAILED_PERMANENT META_MISMATCH |
