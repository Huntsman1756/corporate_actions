# P10.7 — Delivery dispatcher

`run_alert_deliver` en `src/ca_es/ops_delivery.py`; CLI
`ca-es alert-deliver --state <s> --config <ops.json>`.

## Algoritmo (una pasada)

```text
run lock adquirido por el caller
        ↓
marca attempts STARTED huérfanos → UNKNOWN + checkpoint
        ↓
derivación: outbox × destinos habilitados × routing
   → crea deliveries (gen vigente) con payload persistido
   → dedup por delivery_key; checkpoint
        ↓
dispatch: deliveries elegibles
   → INSERT attempt STARTED + attempt_count++
   → checkpoint()  ← STARTED durable ANTES del side effect
   → adapter(request, dest_config)
   → _record_attempt(outcome) → transición + checkpoint
        ↓
_recompute_aggregate → outbox.delivery_state
        ↓
CA_ES_ALERT_DELIVERY_RESULT_V1
```

## Crash semantics

- Crash entre checkpoint STARTED y `_record_attempt` → el attempt
  queda STARTED huérfano; la siguiente pasada (cualquier proceso,
  el lock garantiza single-writer) lo marca UNKNOWN y la entrega
  `UNKNOWN_OUTCOME` — nunca reintento automático.
- El side effect externo nunca precede al STARTED durable.

## Elegibilidad

```text
PENDING                    → siempre
FAILED_RETRYABLE           → attempt_count < max_attempts
                             AND next_attempt_after <= now
FAILED_PERMANENT/ABANDONED → nunca (solo delivery-retry manual)
UNKNOWN_OUTCOME            → nunca (delivery-retry --force-unknown)
DELIVERED                  → skipped_delivered
```

Destino retirado/deshabilitado en config → entrega congelada (no
se intenta ni se borra).

## Derivación

Para cada alerta OPEN/CLEARED × destino cuyo `adapter` existe en
el registry y cuyo `categories` encaja:

- `delivery_key` ya existe → dedup (mismo sem+state+dest).
- no existe → generation = count(previas alert×dest)+1;
  gate `notify_on_open`/`notify_on_change`/`notify_on_clear`;
  `max_payload_bytes` excedido → fila FAILED_PERMANENT
  `PAYLOAD_TOO_LARGE` sin intento.
- `payload_json` se persiste en derivación: el envío usa SIEMPRE
  el payload persistido, nunca el outbox actual (la alerta puede
  cambiar entre derivación y dispatch).

## Agregado `outbox.delivery_state`

Compatibilidad con el contrato alert-level existente; el ledger
es la fuente de verdad por destino:

```text
solo deliveries de la generación vigente
(alert_semantic_sha256 + alert_state actuales)
× destinos actualmente habilitados y routed:

todas DELIVERED                          → DELIVERED
alguna FAILED_PERMANENT|ABANDONED        → FAILED_DELIVERY
resto (pending/retryable/unknown/mixta)  → PENDING_DELIVERY
```

Sin deliveries vigentes → conserva el valor previo (config sin
rutas no mueve el estado). El agregado se recalcula para toda
alerta tocada por derivación o dispatch — incluido dedup tras
rearmado por reopen con mismo sem-sha (vuelve a DELIVERED sin
reenvío).

## Exit codes CLI

`0`: SUCCESS | UNCHANGED | DISABLED · `2`: PARTIAL/error config ·
`3`: OPS_RUN_ALREADY_ACTIVE.
