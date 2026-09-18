# P10.1 — Delivery contracts (preregistro)

Contratos nuevos; ninguno toca `CA_ES_ALERT_OUTBOX_V1` ni semántica
de negocio.

## CA_ES_ALERT_DELIVERY_REQUEST_V1

Derivado de (alerta outbox × destino configurado × generación).
Construido por el dispatcher, nunca persistido como artefacto — el
ledger es su representación durable.

```text
schema                  = CA_ES_ALERT_DELIVERY_REQUEST_V1
delivery_key            # PK lógica (ver fórmula)
alert_key
alert_semantic_sha256   # semantic_sha256 del payload outbox vigente
alert_state             # OPEN | CLEARED al derivar
adapter_type            # file | webhook | smtp
destination_id
generation              # N-ésima generación por (alert_key,destination_id)
payload_schema          = CA_ES_ALERT_DELIVERY_PAYLOAD_V1
payload                 # doc minimizado
created_at
```

### delivery_key

```text
delivery_key = "DLV-" + sha256(
    "CA_ES_ALERT_DELIVERY_V1|" +
    alert_key + "|" +
    alert_state + "|" +
    alert_semantic_sha256 + "|" +
    destination_id + "|" +
    adapter_policy_version )
```

- `alert_semantic_sha256` = `semantic_sha256` de la fila outbox
  (hash del payload de **negocio**). NO se usa el hash del payload
  outbound para la identidad: el outbound incluye metadatos de run
  volátiles (`last_observed_run_id`) que cambiarían la clave en
  cada re-observación aunque los hechos sean idénticos.
- `alert_state` distingue la generación OPEN de la generación
  CLEARED (notify_on_clear) con el mismo sem-sha.
- `adapter_policy_version` = `CA_ES_ALERT_DELIVERY_PAYLOAD_V1` —
  un cambio de contrato de payload versiona la identidad.
- Sin número de intento: los intentos cuelgan de la identidad.
- generation = count(deliveries de (alert_key, destination_id)) + 1
  al crear; determinista dentro del ledger.

## CA_ES_ALERT_DELIVERY_PAYLOAD_V1 (outbound)

```text
schema                  = CA_ES_ALERT_DELIVERY_PAYLOAD_V1
delivery_key
alert_key
category
subject_type
subject_key
state                   # OPEN | CLEARED
alert_semantic_sha256
first_observed_run_id
last_observed_run_id
summary                 # "<category> <subject_key>" truncado
details                 # allowlist por categoría (ver abajo)
evidence_refs           # refs/hash existentes, nunca contenido
```

Allowlist `details` por categoría (prefijo `*` permitido en routing,
no aquí — aquí es por familia exacta/prefijo):

| categoría | claves permitidas |
|---|---|
| DEADLINE_* | canonical_event_id, deadline_type, deadline_date, action_status, days_until |
| EXCEPTION_CASE | canonical_event_id, factual_status, workflow_status, reason_codes, last_action |
| PROCESSING_FAILURE | message_identifier, processing_status |
| RUN_FAILED | run_id, error_summary (truncado 300) |
| SOURCE_REFRESH_FAILED / SOURCE_PARTIAL | source_id, surface_id, status, error (truncado 300), fetch_failures, pagination_complete |
| SOURCE_PARSE_FAILED | document_id, content_sha256, error (truncado 300) |
| SOURCE_CONTENT_CHANGED | document_id, from, to, notice |
| SOURCE_STALE | source_id, surface_id, last_checkpoint_at, age_days, stale_after_days |
| cualquier otra | `{}` (solo campos base — fail-minimal, nunca payload crudo) |

Prohibido siempre: positions, account_id, raw MT/MX, raw source
documents, credenciales, URLs con query.

## CA_ES_ALERT_DELIVERY_ATTEMPT_V1 (ledger row)

```text
attempt_id          = "ATT-" + delivery_key + "-" + attempt_number
delivery_key        FK
attempt_number      # 1..n, append-only
started_at
completed_at
status              # STARTED | SUCCEEDED | FAILED | UNKNOWN
retryable           # bool al fallar
error_code          # corto, estable (HTTP_503, CONNECT_TIMEOUT, ...)
error_detail_safe   # <=200 chars, sin secretos/body/query
transport_metadata  # JSON seguro: http_status, request_id, path,
                    # sha256, accepted_recipients, retry_after_seconds
```

## CA_ES_ALERT_DELIVERY_RESULT_V1 (doc del dispatcher)

Resultado de una invocación `alert-deliver`:

```text
schema = CA_ES_ALERT_DELIVERY_RESULT_V1
generated_at
status                 # SUCCESS | PARTIAL | FAILED | DISABLED
deliveries_created
attempted / succeeded / failed_retryable /
failed_permanent / unknown
skipped_delivered
orphan_attempts_marked_unknown
per_destination: [{destination_id, adapter, attempted, succeeded,
                   failed_retryable, failed_permanent, unknown}]
```

## Clasificación de resultados por adapter

```text
outcome SUCCEEDED        → attempt SUCCEEDED, delivery DELIVERED
outcome FAILED_RETRYABLE → attempt FAILED retryable=true,
                           delivery FAILED_RETRYABLE (+next_attempt_after)
outcome FAILED_PERMANENT → attempt FAILED retryable=false,
                           delivery FAILED_PERMANENT
outcome UNKNOWN          → attempt UNKNOWN, delivery UNKNOWN_OUTCOME
                           (sin auto-retry)
```
