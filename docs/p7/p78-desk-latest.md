# P7.8 — ops-status / ops-latest / desk --latest / ops-export-run

Interfaces READ-ONLY sobre el state store. Nunca recalculan
nada de negocio: consumen artefactos persistidos del ultimo run
SUCCEEDED (un FAILED/PARTIAL posterior nunca lo desplaza).

## Comandos

```
ca-es ops-status --state X     # resumen operativo (JSON)
ca-es ops-latest --state X     # artefactos top-level del ultimo
                               # run SUCCEEDED (JSON)
ca-es desk --state X --latest  # desk sobre el ultimo run OK
ca-es ops-export-run --state X --run-id R --output DIR
```

## ops-status

```
active_run:            run RUNNING (o null)
latest_successful_run: run_id/as_of/completed_at
latest_failed_run:     run_id/as_of/error_summary (o null)
steps:                 [{step_id,status,error_code}] del ultimo
                       run (cualquier estado)
health:                status del artefacto health del ultimo
                       run SUCCEEDED (o NO_HEALTH)
pending_alerts:        count outbox PENDING_DELIVERY
open_exceptions:       count cases workflow OPEN (ultimo run OK)
action_counts:         {OVERDUE, DUE_TODAY, DUE_SOON} de la
                       queue del ultimo run OK
inbox_failures:        count mensajes FAILED acumulados
```

## ops-latest

```
run_id, as_of, completed_at, run_status, config_semantic_sha256
artifacts: {step_id: {sha256, semantic_sha256, schema,
                      schema_version, ref, cache_source_run_id}}
```

## desk --latest

Carga del ultimo run SUCCEEDED: brief_v2 (artefacto persistido),
canon + source_policy (artefactos de input) -> Surface read-only
para el detalle/evidencia existente. Sin recalculo: `build_desk_model`
consume el brief persistido. Requiere extra `[desk]` como siempre.

## ops-export-run

Exporta a `<output>`:

```
manifest.json        manifest persistido del run
steps.json           registros de pasos (completos)
artifacts/           artefactos derivados referenciados por los
                     pasos (content-addressed)
lineage.jsonl        eventos OpenLineage del run
```

Por defecto solo metadata + artefactos derivados: NUNCA blobs
raw de inbox ni posiciones/mensajes crudos (privacidad).
`--include-inputs` permite ademas los artefactos de input
(uso bajo responsabilidad del operador).
