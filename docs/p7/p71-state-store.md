# P7.1 — SQLite state store (scope preregistrado)

Status: DONE

`src/ca_es/ops_state.py` — SQLite stdlib unico. El state DB es
metadata operativa; la verdad de negocio sigue en los artefactos
content-addressed.

## Artefactos: ficheros + metadata (opcion B)

Los outputs pueden ser grandes (canon, brief); se guardan como
ficheros content-addressed:

```text
<state>/artifacts/<sha256[:2]>/<sha256>.json
<state>/ops.db
<state>/inbox/ (incoming/processed/failed)
```

Escritura atomica: temp file -> flush+fsync -> `os.replace` ->
commit de la fila DB. Nunca DB apuntando a artefacto parcial.
Lectura re-verifica byte SHA-256: `corrupted` detectable.

Cada artefacto registra: `sha256`, `semantic_sha256`, `schema`,
`schema_version`, `media_type`, `byte_length`, `path`, `run_id`.

## Tablas

```text
state_meta(key, value)                       -- schema_version
runs(run_id PK, as_of, started_at, completed_at, run_status,
     config_sha256, config_semantic_sha256,
     previous_successful_run_id, manifest_json, error_summary)
run_steps(run_id, step_id, PK(run_id,step_id), step_version,
          status, started_at, completed_at,
          input_semantic_hashes_json, config_semantic_hash,
          expected_output_schema, expected_output_version,
          output_ref, output_sha256, output_semantic_sha256,
          cache_source_run_id, error_code, error_detail)
artifacts(sha256 PK, semantic_sha256, schema, schema_version,
          media_type, byte_length, path, created_at, run_id)
inbox_messages(input_sha256 PK, semantic_fingerprint,
               standard_family, message_identifier, received_at,
               source_path, processing_status, duplicate_status,
               artifact_refs_json)
inbox_observations(id PK AUTOINCREMENT, input_sha256, run_id,
                   observed_at, transition, detail)
outbox(alert_key PK, category, subject_type, subject_key, state,
       first_observed_run_id, last_observed_run_id,
       payload_json, evidence_refs_json, semantic_sha256,
       delivery_state, delivery_attempts, created_at, updated_at)
run_lock(id CHECK(id=1), run_id, owner_token, acquired_at)
```

`PRAGMA foreign_keys=ON`. Sin WAL: single-writer local, el journal
por defecto basta.

## Locking single-writer

Conexion dedicada mantiene `BEGIN IMMEDIATE` abierto durante todo
el run (`lock_conn`). Si el proceso muere, la conexion muere y el
lock desaparece — sin PID files. Segundo writer ->
`OPS_RUN_ALREADY_ACTIVE` (busy_timeout corto). Lectores
(ops-status/ops-latest/desk) usan conexiones propias sin lock.

## Versionado

`OPS_STATE_SCHEMA_VERSION = "1"` en `state_meta`. `ops-init` crea;
`open` exige coincidencia exacta — sin migraciones automaticas
destructivas; schema mismatch -> error cerrado.

## Transacciones

Cada transicion de estado atomica via `BEGIN IMMEDIATE` +
commit/rollback explicito. Rollback probado en tests.
