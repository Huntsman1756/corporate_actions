# P7.7 — OpenLineage export (opcional)

Adapter OPCIONAL: el core no depende de OpenLineage. Se emite
JSONL determinista (un evento por linea) con stdlib — sin client,
sin transporte de red. Fichero/stdout basta en V1.

## Mapping

```
ca-es                     OpenLineage
────────────────────────────────────────────────
run (CA_ES_OPERATIONAL_RUN_V1)   parent RunEvent (START+COMPLETE|FAIL)
step                             RunEvent propio (COMPLETE|FAIL)
input artifacts                  inputs[] datasets
output artifact                  outputs[] dataset
```

- `job.namespace` = `ca-es`; `job.name` = `ops-run` (run) o
  `ops-run.<step_id>` (step).
- `run.runId` = run_id / `<run_id>:<step_id>` (determinista).
- Dataset `namespace` = `ca-es-artifacts`; `name` =
  `artifact:<sha256>` (content-addressed, nunca contenido).
- Facet custom `caEs` con `semantic_sha256`, `step_version`,
  `config_semantic_sha256`, `expected_output_schema/version`,
  `cache_source_run_id` (provenance de reuse).
- `eventType`: START (run) + COMPLETE | FAIL. Pasos reutilizados
  emiten COMPLETE con facet `cache_source_run_id` — el reuse
  queda auditado.
- `eventTime` = started_at/completed_at persistidos (metadata de
  ejecucion, no de negocio).
- `producer` = `https://github.com/romeotech/ca-es` +
  `schemaURL` OpenLineage 1-0-5.

## Config

```json
"lineage": {"enabled": true, "required": false,
            "path": "<state>/lineage/<run_id>.jsonl"}
```

- `enabled=false` (default) -> paso emite doc `enabled:false`.
- Fallo de export con `required=false` -> paso SUCCEEDED con
  `error` en el doc (nunca invalida el run de negocio).
- `required=true` + fallo -> step FAILED -> run FAILED.

Determinista: eventos ordenados por step; misma entrada -> mismo
JSONL byte-a-byte salvo eventTime.
