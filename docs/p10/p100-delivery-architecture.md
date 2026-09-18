# P10.0 — Delivery capability audit / architecture

Auditoría del baseline P1–P9 y decisión de alcance para el boundary
de entrega de alertas. P10 **no** es una fase semántica de corporate
actions: no recalcula deadlines, no toca excepciones, no cambia
identidades de alerta, no envía MT/MX. Es el subsistema
transport-agnóstico que convierte el outbox determinista existente
en entrega real, auditable e idempotente.

## Baseline auditado

| pieza | estado | implicación para P10 |
|---|---|---|
| `outbox` (SQLite) | `alert_key` PK estable `category\|subject_key`; `state` OPEN/CLEARED; `semantic_sha256` del payload de negocio; `delivery_state` PENDING_DELIVERY/DELIVERED/FAILED_DELIVERY; `delivery_attempts` counter | identidad de alerta ya existe y es correcta — NO se toca. `delivery_state` es alert-level: pasa a ser agregado derivado del ledger por destino (P10.7), nunca verdad primaria |
| `apply_alerts` | rearma `delivery_state=PENDING_DELIVERY` solo si el payload semántico cambia o la alerta reabre; run idéntico NO rearma | el dispatcher puede confiar en semantic_sha256 para deduplicar generaciones |
| `ops_state` v2 | schema_version="2", migración aditiva v1→v2 transaccional en `open()`/`acquire_run_lock()` | mismo patrón para v2→v3: `deliveries` + `delivery_attempts` + `delivery_transitions`, aditivas |
| `acquire_run_lock` + `checkpoint()` | BEGIN IMMEDIATE sostenido; `checkpoint()` commitea y re-adquiere | permite persistir el intent `STARTED` **antes** del side effect → crash detectable como UNKNOWN_OUTCOME |
| `semantic_sha256` | excluye solo claves execution-only | base de `delivery_key` y del payload hash |
| `ops_config` | whitelist fail-closed por sección | sección `delivery` aditiva; destinos con allowlist de claves por adapter; rechazo de claves de secreto en claro |
| `ops_read`/`ops_status_doc` | `CA_ES_OPS_STATUS_V1` ya cuenta `pending_alerts` | extensión aditiva con resumen `delivery` |
| P7.6 scheduling | cron/systemd/TaskScheduler/GHA invocan `ops-run` | se añade `ca-es alert-deliver` como comando separado posterior — la entrega NO entra en el DAG transaccional |
| P9 sources | red solo en `run_source_refresh` | webhook/smtp son la segunda superficie de red del proyecto, aislada en `alert-deliver`, nunca dentro de `run_ops` |

## Decisiones de arquitectura

```text
ops-run (DAG P7)
   └─ alert_outbox  → outbox rows (state, semantic_sha256)
                         │
scheduler externo         │ ledger read
   └─ ca-es alert-deliver ─┘
        derive deliveries (alerta x destino x generación)
        per delivery:
          persist attempt STARTED → checkpoint()
          adapter.deliver(request)
          persist result → checkpoint()
        recompute outbox.delivery_state (agregado)
```

### Identidad de entrega (P10.1)

```text
delivery_key = "DLV-" + sha256(
    "CA_ES_ALERT_DELIVERY_V1"
    | alert_key
    | outbound_payload_semantic_sha256
    | destination_id
    | adapter_policy_version )
```

- mismo hecho + mismo destino → mismo `delivery_key` → nunca re-envío
  tras `DELIVERED`;
- hechos cambiados o clear notificado → nuevo `delivery_key` → nueva
  `generation` por (alert_key, destination_id);
- el número de intento NO entra en la identidad.

### Estados por entrega

```text
PENDING → (attempt SUCCEEDED) → DELIVERED
        → (attempt FAILED, retryable, attempts < max) → FAILED_RETRYABLE
        → (attempt FAILED, permanent | retry agotado) → FAILED_PERMANENT
        → (crash con STARTED huérfano | fallo tras bytes enviados)
          → UNKNOWN_OUTCOME
FAILED_PERMANENT/UNKNOWN_OUTCOME → (operador) → PENDING  [audit]
cualquiera → (operador) → ABANDONED  [terminal, audit]
```

### Agregado `outbox.delivery_state` (compat)

Se recalcula solo sobre deliveries de la **generación vigente**
(alert_semantic_sha256 + alert_state actuales) y solo sobre destinos
actualmente enrutados:

```text
DELIVERED         si todos los destinos enrutados DELIVERED
FAILED_DELIVERY   si alguno FAILED_PERMANENT o ABANDONED
PENDING_DELIVERY  en cualquier otro caso (incl. UNKNOWN_OUTCOME)
```

Sin deliveries de la generación vigente (p.ej. CLEARED sin
`notify_on_clear`): el `delivery_state` previo se conserva.

## Evaluación de adapters V1

| adapter | decisión | rationale |
|---|---|---|
| FILE | **MUST — implementado** | referencia determinista, cero red, usable en CI y operación local; atomic tmp→fsync→replace; idempotencia por delivery_key |
| WEBHOOK | **SHOULD — implementado** | `http.client` stdlib (más control de fases que urllib → distinción FAILED_RETRYABLE vs UNKNOWN_OUTCOME); HTTPS por defecto, http solo localhost explícito; SSRF: sin redirects por defecto, redirects same-origin limitados y configurables; headers de idempotencia |
| SMTP | **SHOULD — implementado** | stdlib `smtplib`+`ssl` es limpio: STARTTLS/SMTPS, credenciales solo por env, Message-ID determinista desde delivery_key. Complejidad aceptable; tests via transport factory inyectable (sin servidor SMTP real) |
| Slack/Teams/Discord | NO | perfiles de webhook posteriores si hicieran falta; ninguna lógica específica |

## Secretos

Solo variables de entorno (`*_env` en config). El config validador
rechaza claves tipo `password|token|api_key|authorization|secret|
credential` salvo el sufijo `_env`. Nada de secretos en SQLite,
artefactos, logs ni argv.

## Privacidad por defecto

`CA_ES_ALERT_DELIVERY_PAYLOAD_V1` minimizado: identidad, categoría,
estado, summary corto, `details` con allowlist por categoría,
`evidence_refs` (hashes). Sin posiciones, sin account_id por defecto,
sin raw MT/MX, sin documentos fuente.

## Limitaciones deliberadas (V1)

- At-least-once en el boundary; NUNCA se afirma exactly-once.
- Retries dirigidos por scheduler (`alert-deliver` hace 1 intento por
  entrega elegible por invocación; sin sleeps en el core).
- UNKNOWN_OUTCOME no se reintenta automáticamente.
- Sin attachments, sin HTML, sin loteo/batching (un POST por entrega).
- Sin auto-alertas DELIVERY_FAILED (protección anti-recursión: el
  fallo de entrega se reporta via status, no via outbox).
