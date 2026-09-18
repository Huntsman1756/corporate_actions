# P7.0 — Execution model + semantic hashing (scope preregistrado)

Status: DONE

## Modelo

```text
CA_ES_OPERATIONAL_RUN_V1
  run_id                    UUID v4 (identidad del intento, nunca
                            clave de idempotencia)
  as_of                     fecha operativa (business input)
  started_at / completed_at
  run_status                RUNNING | SUCCEEDED | FAILED | PARTIAL
  config_sha256             bytes del config
  config_semantic_sha256    config sin claves execution-only
  previous_successful_run_id
  inputs[]                  {artifact_type, ref, sha256}
  steps[]                   CA_ES_RUN_STEP_V1
  outputs[]                 refs a artefactos persistidos
  error_summary
```

`PARTIAL` solo si el DAG declara pasos optional/not-applicable y
fallan sin tocar pasos obligatorios; ante la duda, FAILED.

```text
CA_ES_RUN_STEP_V1
  step_id / step_version
  status: PENDING RUNNING SUCCEEDED FAILED SKIPPED_UNCHANGED BLOCKED
  started_at / completed_at
  input_refs[] / input_semantic_hashes[]
  config_semantic_hash
  expected_output_schema / expected_output_version
  output_ref / output_sha256 / output_semantic_sha256
  cache_source_run_id
  error_code / error_detail
```

Run success = "runtime ejecutado correctamente". Un step puede
SUCCEED emitiendo un artefacto de dominio `INDETERMINATE` — eso es
un outcome de negocio valido, no un fallo tecnico.

## CA_ES_SEMANTIC_HASH_V1 — politica de hashing semantico

Implementacion unica en `src/ca_es/semantic_hash.py`; ningun otro
modulo borra claves ad-hoc.

**Claves excluidas (execution-only, auditadas sobre todos los
contratos actuales):**

```text
generated_at
executed_at
started_at
completed_at
run_id
```

Estos nombres solo existen en ca-es como metadatos de ejecucion; la
exclusion es por nombre de clave a cualquier profundidad, lo que la
hace schema-tolerant para contratos nuevos que sigan la convencion.

**Claves que NUNCA se excluyen (business/evidence):**

```text
as_of, instructed_at, resolved_at, first_seen_at, last_seen_at,
retrieved_at, reviewed_at, terms_reviewed_at, source_*,
publication/effective dates, actor
```

**Normalizacion:**

```text
canonicalize(obj):
  dict  -> {k: canonicalize(v) for k sorted, k not in EXCLUDED}
  list  -> [canonicalize(v)] (orden preservado — es semantico)
  resto -> tal cual
semantic_sha256 = sha256(json.dumps(canon, sort_keys=True,
                  separators=(",", ":"), ensure_ascii=True))
```

Determinista Windows/Linux: UTF-8, separadores fijos, sort_keys,
sin floats (los contratos ya usan strings/Decimal-lexemes).

Tests obligatorios: cambio de `generated_at` -> mismo hash; cambio
de `as_of` -> distinto; cambio de evidencia -> distinto; cambio de
`instructed_at` -> distinto; `run_id`/`started_at` anidados ->
mismo hash; clave `timestamp` (si existiera) nunca borrada.

## Idempotencia

`run_id` NUNCA determina igualdad. La identidad material de un run
es `config_semantic_sha256 + ordered input semantic hashes +
step_versions`. Dos runs con mismos bytes semanticos producen los
mismos outputs semanticos.

`SKIPPED_UNCHANGED` solo para steps puros respecto a la cache key
completa (ver politica de cache en p72). Un cache hit cuya
schema/version persistida ya no es aceptada se invalida y re-ejecuta.
