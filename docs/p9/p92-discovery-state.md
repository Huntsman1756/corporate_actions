# P9.2 — Estado incremental de discovery (preregistro)

Extensión **aditiva** del state store P7 (`ops.db`). No hay segunda
DB. `OPS_STATE_SCHEMA_VERSION` pasa `1 → 2`: `open()` migra al vuelo
(`CREATE TABLE IF NOT EXISTS` + bump de `state_meta`); estados v1 se
abren sin pérdida.

## Tablas nuevas

```sql
source_documents (
  source_id, surface_id, source_document_id,   -- PK (source_id, source_document_id)
  first_seen_at, last_seen_at,
  publication_date,
  latest_content_sha256,      -- último contenido observado con bytes
  chosen_content_sha256,      -- último contenido PARSEADO OK (input del canon)
  latest_locator,
  metadata_json
);

source_observations (
  observation_id PK,          -- sha256(source|surface|doc|content_sha|refresh_id)
  refresh_id,
  source_id, surface_id, source_document_id,
  source_locator, discovered_at, retrieved_at,
  retrieval_status, http_status, media_type,
  content_sha256, byte_length,
  change_status, source_metadata_json
);

source_parse_results (
  source_id, source_document_id, content_sha256,  -- PK triple
  parse_status,               -- OK | FAILED
  error, parsed_at
);

source_checkpoints (
  source_id, surface_id,      -- PK
  cursor_json, updated_at
);

source_refreshes (
  refresh_id PK,
  started_at, completed_at, status, summary_json
);
```

## Blobs raw

`<state>/blobs/<xx>/<sha256>.bin` — mismo patrón que artifacts:
tmp → fsync → `os.replace` → fila en `source_observations` en la
misma transacción. Lectura re-verifica SHA-256; corrupto = fail
closed. `raw_storage=LOCAL_ONLY` vive solo en el state (gitignored).

## Checkpoints por fuente (nunca watermark global)

| superficie | cursor |
|---|---|
| CNMV_OIR/CNMV_IP | `{"last_publication_date": "YYYY-MM-DD", "window_days": N}` — re-consulta ventana solapada desde `max(ultima_fecha - overlap, desde_config)`; la fuente puede registrar con retraso |
| BME_GROWTH | `{"last_refresh_at": "ISO", "known_keys": 0}` — la API es ventana reciente; el cursor no filtra, solo marca edad; dedup por `BMEG-{kind}-{isin}-{date}` |
| PORTFOLIO | `{"last_refresh_at": "ISO", "document_ids_seen": 0}` — re-enumeración integral por snapshot |

Regla de avance: `discover → fetch → persist observations → commit →
advance checkpoint`. Un retrieval incompleto no avanza el checkpoint
más allá de lo duramente observado (`pagination.complete=false` →
checkpoint no avanza y status PARTIAL/PAGINATION_INCOMPLETE).

## Replay protection

- Ventanas solapadas deliberadas: re-consultar periodos previos es
  deseable (la fuente puede enmendar/registrar tarde).
- Dedup por `(source_id, source_document_id)` + `content_sha256`.
- Nunca `last_timestamp + 1s`: el overlap se calcula por días.

## chosen vs latest (regla de oro P9.5)

`latest_content_sha256` = último blob observado.
`chosen_content_sha256` = último blob cuyo parse devolvió OK.
El canon se construye SIEMPRE sobre `chosen`. Un documento que cambia
y deja de parsear conserva su evidencia anterior (chosen no se
degrada) y queda `SOURCE_PARSE_FAILED` en health/alerts.
