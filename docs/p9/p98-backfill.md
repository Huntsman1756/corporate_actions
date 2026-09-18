# P9.8 — Backfill / replay

Replay determinista sobre las observaciones almacenadas. La
evidencia durable (`source_documents.chosen` + blobs
content-addressed) **es** el backfill store: no hay una segunda
copia ni una vista histórica separada.

## Comandos

```bash
ca-es ops-source-refresh --state <state> --config <ops-config.json>
ca-es ops-canon-refresh  --state <state> --config <ops-config.json>
ca-es ops-source-status  --state <state>
ca-es ops-source-replay  --state <state> --config <ops-config.json> \
    [--source <SOURCE_ID>] [--from <YYYY-MM-DD>] [--to <YYYY-MM-DD>] \
    [--out <canon.json>]
```

### ops-source-refresh

Ejecuta `run_source_refresh` con fetchers urllib reales (timeouts,
reintentos y politeness desde `sources.*` del config). Es la única
superficie de red del grupo.

### ops-canon-refresh

Ejecuta `run_canon_refresh`: pase de promoción chosen←latest +
rebuild sobre evidencia acumulada + persistencia del puntero
`state_meta.current_canon_*`. Idempotente por el hash del evidence
set: segunda ejecución sin cambios → `UNCHANGED` reutilizando el
mismo canon artifact.

### ops-source-status

Doc read-only por fuente/superficie:

```text
source_id, surface_id
documents (total, con chosen, latest!=chosen divergentes)
parse_failures sobre latest
checkpoint.updated_at / cursor
último refresh (refresh_id, status, completed_at)
```

### ops-source-replay

Rebuild determinista **en memoria** del canon sobre los documentos
`chosen` almacenados, opcionalmente filtrado por `source_id` y/o
ventana de `publication_date` (`--from`/`--to` inclusivos).

Propiedades:

- **Sin red**: solo lee blobs del store; verifica SHA-256 al leer.
- **Sin mutación**: no promueve, no escribe `state_meta`, no crea
  observaciones ni artefactos en el store. El canon resultante se
  devuelve por stdout o se escribe en `--out`.
- **Idempotente**: mismo conjunto de chosen + misma policy → mismo
  `logical_sha256` del canon. Rejugar un periodo no duplica
  evidencia de negocio porque no inserta nada.
- `--from/--to` filtran por `publication_date` del documento
  fuente; documentos sin fecha no se excluyen salvo que se pida
  ventana (fail-closed: ventana excluye los sin-fecha).
- **No reescribe** manifiestos de runs históricos ni el canon
  apuntado por `state_meta`.

Un "qué habría dicho el canon entonces" temporal real (punto en el
tiempo con fechas de observación) queda como feature futura; la
maquinaria temporal existente no lo soporta sin reinterpretar
`retrieved_at`.
