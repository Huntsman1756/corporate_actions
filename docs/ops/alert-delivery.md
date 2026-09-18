# Alert Delivery — guía de operador (P10)

Entrega del outbox de alertas (`CA_ES_ALERT_OUTBOX_V1`) a destinos
externos configurados. Boundary fuera del run transaccional de
negocio: **un fallo de entrega nunca convierte un run SUCCEEDED en
FAILED**.

## Semántica fundamental

```text
alert OPEN / CLEARED        ≠   delivery pending/delivered/failed
entrega DELIVERED           ≠   excepción de negocio resuelta
```

- Una alerta OPEN con `DELIVERED` es válido (aviso enviado, el
  problema sigue abierto).
- Una alerta CLEARED con `DELIVERED` es válido (aviso enviado
  antes de que se resolviera; por defecto no hay "recovery
  message" — ver `notify_on_clear`).
- La entrega es **at-least-once**; ca-es aporta idempotencia vía
  `delivery_key` estable (mismo facts + mismo destino → misma
  clave → no reenvío tras éxito registrado). No se promete
  exactly-once.

## Setup

### FILE (referencia determinista)

```json
{"destination_id": "ops-file", "adapter": "file", "enabled": true,
 "categories": ["*"],
 "config": {"directory": "/var/lib/ca-es/delivery/file"}}
```

Un `<delivery_key>.json` por entrega; replay idempotente por
comparación de bytes; colisión = permanente.

### WEBHOOK (HTTPS)

```json
{"destination_id": "ops-hook", "adapter": "webhook", "enabled": true,
 "categories": ["DEADLINE_*", "EXCEPTION_CASE"],
 "config": {
   "url_env": "CA_ES_WEBHOOK_URL",
   "token_env": "CA_ES_WEBHOOK_TOKEN",
   "timeout_seconds": 10,
   "host_allowlist": ["hooks.example.com"]}}
```

```bash
export CA_ES_WEBHOOK_URL="https://hooks.example.com/ca-es"
export CA_ES_WEBHOOK_TOKEN="..."   # solo env; jamás en config/state
```

HTTPS por defecto; `http://` solo localhost con
`allow_insecure_http`. Redirects deshabilitados por defecto.

### SMTP

```json
{"destination_id": "ops-mail", "adapter": "smtp", "enabled": true,
 "categories": ["RUN_FAILED", "SOURCE_*"],
 "config": {
   "host": "smtp.example.com", "port": 587, "security": "starttls",
   "username_env": "CA_ES_SMTP_USER",
   "password_env": "CA_ES_SMTP_PASS",
   "from_address": "ca-es@example.com",
   "to_addresses": ["ops@example.com"]}}
```

STARTTLS por defecto; `plain` solo localhost explícito.

### Config completa

```json
{"schema": "CA_ES_OPS_CONFIG_V1",
 "action_queue": {"window_days": 30, "due_soon_days": 7},
 "delivery": {
   "enabled": true,
   "destinations": [ ... ],
   "retry": {"max_attempts": 5, "base_delay_seconds": 300,
             "max_delay_seconds": 3600, "backoff_factor": 2.0},
   "payload_policy": {"max_payload_bytes": 16384,
                      "notify_on_open": true,
                      "notify_on_change": true,
                      "notify_on_clear": false}}}
```

`enabled=false` (o sección ausente) → el dispatcher es no-op
`DISABLED`; el runtime de negocio sigue igual.

## Operación diaria

```bash
ca-es ops-run --state $STATE --config ops.json --as-of 2026-09-18
ca-es alert-deliver --state $STATE --config ops.json
ca-es delivery-status --state $STATE --config ops.json
ca-es ops-status --state $STATE        # incluye bloque delivery
```

`alert-deliver` exit codes: `0` SUCCESS/UNCHANGED/DISABLED,
`2` PARTIAL (algún fallo de entrega) o config inválida,
`3` otro writer activo.

## Recuperación

```bash
ca-es delivery-show --state $STATE --delivery-key DLV-<...>
```

| estado | significado | acción |
|---|---|---|
| PENDING | esperando intento | siguiente tick |
| FAILED_RETRYABLE | reintento programado (`next_attempt_after`) | automático |
| FAILED_PERMANENT | agotado o irrecuperable | revisar `delivery-show`; `delivery-retry` tras corregir causa |
| UNKNOWN_OUTCOME | side effect incierto (crash/timeout post-send) | **manual**: `delivery-retry --force-unknown` tras verificar el receptor, o `delivery-abandon` |
| ABANDONED | decisión operadora terminal | n/a |

`UNKNOWN_OUTCOME` nunca se reintenta solo: puede haber llegado —
reenviar sin verificación duplicaría el mensaje.

## Seguridad

- Credenciales solo por `*_env`; el config rechaza claves
  secret-like literales (`password`, `token`, `api_key`,
  `authorization`, `secret`, `credential`, `bearer`).
- SQLite guarda metadata de entrega (claves, estados, receipts
  seguros), nunca secretos ni cuerpos de respuesta.
- Payload outbound minimizado (`CA_ES_ALERT_DELIVERY_PAYLOAD_V1`):
  campos base + allowlist por categoría. Nunca positions,
  account_id, raw MT/MX ni documentos fuente.
- `max_payload_bytes` excedido → entrega permanente
  `PAYLOAD_TOO_LARGE` (fail-closed, no truncado).
- Webhook: HTTPS, TLS verify siempre ON, sin redirects por
  defecto, `host_allowlist`, `Idempotency-Key` = delivery_key.

## Troubleshooting

- `OPS_RUN_ALREADY_ACTIVE` → otro writer; esperar al siguiente
  tick (single-writer por diseño).
- `DELIVERY_KEY_COLLISION` (file) → un fichero previo distinto
  bajo la misma clave; integridad comprometida, inspección manual.
- `PAYLOAD_TOO_LARGE` → subir `max_payload_bytes` o revisar la
  alerta; la fila queda permanente hasta entonces.
- Entrega "congelada" → el destino fue retirado/deshabilitado en
  config; la fila permanece para auditoría.
