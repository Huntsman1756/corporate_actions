# P7.2 — Operational DAG + resume (scope preregistrado)

Status: DONE

`src/ca_es/ops_dag.py` — DAG explicito en codigo (sin Airflow/
Prefect/Dagster). Cada `OperationalStep` ejecuta funciones de
dominio ya cerradas; P7 no recalcula semantica.

## Config: `CA_ES_OPS_CONFIG_V1`

```json
{
  "schema": "CA_ES_OPS_CONFIG_V1",
  "inputs": {
    "canon":         {"path": "...", "required": true},
    "source_policy": {"path": "...", "required": true},
    "positions":     {"path": "...", "required": false},
    "deadline_rules":{"path": "...", "required": true},
    "calendars":     {"path": "...", "required": true},
    "cash_movements":{"path": "...", "required": false},
    "impact_rules":  {"path": "...", "required": false},
    "instructions":  {"paths": ["..."], "required": false}
  },
  "action_queue": {"window_days": 7, "due_soon_days": 3},
  "reconciliation": {"events": "all"},
  "inbox":   {"path": "..."},
  "health":  {"positions_max_age_days": 7,
              "canon_max_age_hours": 48},
  "alerts":  {"enabled": true},
  "lineage": {"enabled": false, "required": false,
              "path": "state/lineage.jsonl"}
}
```

Claves desconocidas -> `INVALID_OPS_CONFIG:unknown_key`. Inputs
required ausentes -> fallo en `validate_inputs` (run FAILED).
Ningun default introduce semantica de negocio (solo `state/`
dirs). Sin secretos en config.

## DAG V1

```text
validate_inputs (obligatorio)
   ├── process_inbox        (opcional: solo si config.inbox)
   ├── compute_deadlines    (obligatorio)
   │      └─ build_action_queue (obligatorio)
   │             └─ morning_brief_v2 (obligatorio)
   ├── entitlements         (opcional: positions)
   │      └─ cash_reconciliation (opcional: cash_movements)
   │             └─ exception_cases (opcional, merge con casos previos)
   ├── instruction_statuses (opcional: instructions + inbox facts)
   ├── health               (obligatorio, nunca cacheable)
   └─ alerts                (obligatorio, nunca cacheable)
```

Pasos opcionales sin inputs -> `BLOCKED` (run puede ser PARTIAL si
un opcional falla y los obligatorios van bien; ante la duda FAILED).

## Cache key

```text
cache_key = canonical_json({
  "step_id", "step_version",
  "inputs": [semantic_sha256 ordenados de los artefactos input],
  "config": semantic_sha256 de la subseccion relevante del config,
  "output_schema", "output_version",
  "as_of"                              # parametro operativo
})
```

`SKIPPED_UNCHANGED` solo si: step `pure`, existe SUCCEEDED previo
con la misma cache key en un run SUCCEEDED/PARTIAL, el artefacto
referenciado existe y re-verifica SHA-256, y la schema/version
persistida sigue siendo la esperada. `cache_source_run_id` apunta
al run donante.

Pasos de ingesta (`process_inbox`) incluyen el byte-SHA256 de los
ficheros en sus inputs — la identidad byte-exacta forma parte de
su semantica (exact-duplicate inbox).

## Resume

`ca-es ops-run --resume <run_id>`:

- el run debe existir y NO estar SUCCEEDED (un run SUCCEEDED es
  inmutable; re-ejecutar = nuevo run);
- steps SUCCEEDED con cache key vigente -> SKIPPED_UNCHANGED;
- steps FAILED/RUNNING/PENDING -> re-ejecutados (RUNNING huerfano
  = interrumpido, nunca exito);
- invalidacion automatica: un input semantico distinto rompe la
  cache key de los dependientes.

Sin retry loops: V1 reintenta solo via `--resume` explicito.

## CLI

```bash
ca-es ops-init --state <path>
ca-es ops-run --config ops.json --state <path> --as-of <date>
ca-es ops-run --state <path> --resume <run_id>
ca-es ops-status --state <path>
ca-es ops-latest --state <path>
ca-es ops-export-run --state <path> --run-id <id> --output <dir>
```

Single-writer: `acquire_run_lock` (BEGIN IMMEDIATE sostenido);
segundo writer -> `OPS_RUN_ALREADY_ACTIVE` exit 4.
