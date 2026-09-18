# P10.3 — Delivery policy / config (preregistro)

Extensión aditiva de `CA_ES_OPS_CONFIG_V1`: nueva sección `delivery`
con validación fail-closed por whitelist (mismo patrón que el
resto). Config por defecto = nada se envía.

## Esquema de sección

```json
{
  "delivery": {
    "enabled": true,
    "destinations": [
      {
        "destination_id": "ops-file",
        "adapter": "file",
        "enabled": true,
        "categories": ["*"],
        "config": {"directory": "delivery/ops-file"}
      },
      {
        "destination_id": "ops-hook",
        "adapter": "webhook",
        "enabled": true,
        "categories": ["DEADLINE_*", "EXCEPTION_CASE"],
        "config": {
          "url_env": "CA_ES_WEBHOOK_URL",
          "token_env": "CA_ES_WEBHOOK_TOKEN",
          "timeout_seconds": 10,
          "max_response_bytes": 16384,
          "expected_statuses": [200, 201, 202, 204],
          "max_redirects": 0,
          "host_allowlist": ["hooks.internal.example"],
          "allow_insecure_http": false
        }
      },
      {
        "destination_id": "ops-mail",
        "adapter": "smtp",
        "enabled": false,
        "categories": ["RUN_FAILED", "SOURCE_*"],
        "config": {
          "host": "smtp.internal.example",
          "port": 587,
          "security": "starttls",
          "username_env": "CA_ES_SMTP_USER",
          "password_env": "CA_ES_SMTP_PASS",
          "from_address": "ca-es@internal.example",
          "to_addresses": ["ops@internal.example"],
          "message_id_domain": "internal.example",
          "timeout_seconds": 10
        }
      }
    ],
    "retry": {
      "max_attempts": 5,
      "base_delay_seconds": 300,
      "max_delay_seconds": 3600,
      "backoff_factor": 2.0
    },
    "payload_policy": {
      "max_payload_bytes": 32768,
      "notify_on_open": true,
      "notify_on_change": true,
      "notify_on_clear": false
    }
  }
}
```

## Routing

- `categories` es obligatorio por destino; `"*"` = todas; entradas
  terminadas en `*` = prefijo (`DEADLINE_*`, `SOURCE_*`).
- Sin routing oculto: una categoría no listada en ningún destino
  habilitado simplemente no genera entregas (la alerta queda
  PENDING_DELIVERY — veraz, visible en status).
- `enabled: false` en destino = no-op exitoso (sus entregas ya
  creadas quedan congeladas; no se derivan nuevas ni se agregan).
- `delivery.enabled` ausente/false = subsistema DISABLED; el runtime
  de negocio no se ve afectado en nada.

## Secretos

- Solo `*_env`: el valor es el **nombre** de la variable, nunca el
  secreto. `url` literal también permitido para endpoints sin
  credencial.
- Claves rechazadas en cualquier `config` de destino:
  `password|passwd|token|api_key|apikey|authorization|secret|
  credential|bearer` (salvo con sufijo `_env`).
- `url`/`url_env` resuelto no puede llevar `userinfo`
  (`https://user:pass@host` → fail closed).
- Los valores resueltos nunca se escriben: ni en DB, ni en
  artefacts, ni en logs, ni en `error_detail_safe`.

## Validación fail-closed

- Claves desconocidas en `delivery`, `destinations[]`, `retry` o
  `payload_policy` → `INVALID_OPS_CONFIG:*`.
- `adapter` desconocido → `INVALID_OPS_CONFIG`.
- `destination_id` duplicado o vacío → error.
- `categories` ausente/no-lista → error.
- `config` por adapter con allowlist propia de claves.
- Números: timeouts > 0, max_bytes > 0, max_attempts >= 1,
  backoff_factor >= 1.0.

## Defaults de notify (operativos, documentados)

```text
notify_on_open   = true   → primera generación OPEN se entrega
notify_on_change = true   → payload cambiado (mismo alert_key)
                            genera nueva entrega
notify_on_clear  = false  → un CLEARED no notifica salvo opt-in
```

`notify_on_clear: true` genera una **nueva generación** con
`alert_state=CLEARED` y payload propio — nunca reutiliza la
identidad de la entrega OPEN.
