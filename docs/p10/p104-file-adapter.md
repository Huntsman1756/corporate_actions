# P10.4 — FILE adapter (referencia determinista)

`src/ca_es/delivery/file_adapter.py`. Sink de un fichero por
entrega; usado en CI y como smoke live.

## Layout

```text
<config.directory>/
    <delivery_key>.json        # payload bytes, atomic write
```

`delivery_key` es `DLV-<sha256hex>` — siempre seguro como nombre de
fichero en Windows/Linux aunque `alert_key` contenga `|` u otros
caracteres ilegales.

## Escritura atómica

1. `mkdir -p` del directorio (error → `FAILED_PERMANENT`,
   `DESTINATION_MKDIR_FAILED`).
2. temp `.tmp-<pid>-<delivery_key>.json` en el mismo directorio
   (mismo filesystem → `os.replace` atómico).
3. `fsync` del fichero, `os.replace` al destino, `fsync` del dir.

## Idempotencia

Si `<delivery_key>.json` ya existe:

- bytes idénticos → `SUCCEEDED` con
  `receipt.idempotent_replay=true` (replay seguro tras crash);
- bytes distintos bajo la misma clave → `FAILED_PERMANENT`
  `DELIVERY_KEY_COLLISION`. Nunca se sobrescribe en silencio.

## Config

```json
{"adapter": "file", "config": {"directory": "<abs path>"}}
```

Sin `directory` → `FAILED_PERMANENT` `DESTINATION_NO_DIRECTORY`
(fail-closed).

## Clasificación de errores

| condición | outcome |
|---|---|
| write OK | SUCCEEDED |
| replay idempotente | SUCCEEDED |
| colisión de clave | FAILED_PERMANENT |
| falta `directory` | FAILED_PERMANENT |
| mkdir/permiso falla | FAILED_PERMANENT |
| IO error en write | FAILED_RETRYABLE |
| no creable el temp | FAILED_RETRYABLE |

## Receipt persistido

```text
path, sha256, bytes, idempotent_replay?
```

Determinista bajo inputs fijos: mismo request + mismo directorio
→ mismo fichero, mismos bytes.
