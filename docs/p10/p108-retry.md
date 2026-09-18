# P10.8 — Retry policy + operator control

Retries scheduler-driven: el core nunca duerme. El scheduler
externo (systemd timer / cron / Task Scheduler) invoca
`alert-deliver` periódicamente; la elegibilidad se decide por
`next_attempt_after`.

## Config

```json
"retry": {
  "max_attempts": 5,          // >=1
  "base_delay_seconds": 300,  // >=0
  "max_delay_seconds": 3600,  // >=0
  "backoff_factor": 2.0       // >=1.0
}
```

`delay(n) = min(base * factor^(n-1), max_delay)` — sin jitter:
reproducible; el scheduler ya dispersa las ejecuciones.
`Retry-After` de un 429/503 se usa como `next_attempt_after` si es
mayor que el backoff calculado.

## Transiciones automáticas

```text
FAILED_RETRYABLE + attempt_count >= max_attempts
    → FAILED_PERMANENT (nota RETRY_EXHAUSTED en el attempt)
```

## Controles de operador (auditoría append-only)

```bash
ca-es delivery-status [--config ops.json]
ca-es delivery-show --delivery-key <key>   # entrega+attempts+transitions
ca-es delivery-retry --delivery-key <key> [--actor <a>]
ca-es delivery-retry --delivery-key <key> --force-unknown
ca-es delivery-abandon --delivery-key <key> [--actor <a>] [--note <n>]
```

| estado | retry | abandon |
|---|---|---|
| PENDING | → PENDING (audit) | → ABANDONED |
| FAILED_RETRYABLE | → PENDING | → ABANDONED |
| FAILED_PERMANENT | → PENDING | → ABANDONED |
| UNKNOWN_OUTCOME | solo `--force-unknown` | → ABANDONED |
| DELIVERED | error | error |
| ABANDONED | error (terminal) | — |

`ABANDONED` es decisión de entrega, terminal: nunca cambia el
estado de la alerta de negocio; cuenta como permanente en el
agregado. Toda transición manual queda en `delivery_transitions`
con `actor` y `note`. Nunca hay DELETE.
