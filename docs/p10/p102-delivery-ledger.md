# P10.2 — SQLite delivery ledger (preregistro)

Extensión **aditiva** del mismo `ops.db` (no segundo DB).
`OPS_STATE_SCHEMA_VERSION` pasa de `"2"` a `"3"`; migración
transaccional en `open()`/`acquire_run_lock()` igual que v1→v2:

```text
v1 → SOURCE_SCHEMA_SQL + DELIVERY_SCHEMA_SQL → "3"
v2 → DELIVERY_SCHEMA_SQL → "3"
v3 → no-op
```

Ninguna tabla P7/P9 se altera; el outbox conserva su esquema.

## Tablas

```sql
CREATE TABLE IF NOT EXISTS deliveries (
    delivery_key TEXT PRIMARY KEY,          -- "DLV-<sha256>"
    alert_key TEXT NOT NULL,
    alert_semantic_sha256 TEXT,
    alert_state TEXT,                        -- OPEN | CLEARED al derivar
    payload_semantic_sha256 TEXT,
    destination_id TEXT NOT NULL,
    adapter_type TEXT NOT NULL,
    generation INTEGER NOT NULL,
    status TEXT NOT NULL,                    -- PENDING | DELIVERED |
                                             -- FAILED_RETRYABLE |
                                             -- FAILED_PERMANENT |
                                             -- UNKNOWN_OUTCOME | ABANDONED
    next_attempt_after TEXT,                 -- NULL = elegible ya
    attempt_count INTEGER DEFAULT 0,
    first_created_at TEXT,
    delivered_at TEXT,
    last_attempt_at TEXT,
    external_receipt_json TEXT               -- metadata segura
);
CREATE INDEX IF NOT EXISTS idx_deliveries_alert
    ON deliveries(alert_key);
CREATE INDEX IF NOT EXISTS idx_deliveries_status
    ON deliveries(status);

CREATE TABLE IF NOT EXISTS delivery_attempts (
    attempt_id TEXT PRIMARY KEY,             -- "ATT-<dk>-<n>"
    delivery_key TEXT NOT NULL
        REFERENCES deliveries(delivery_key),
    attempt_number INTEGER NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    status TEXT,                             -- STARTED | SUCCEEDED |
                                             -- FAILED | UNKNOWN
    retryable INTEGER,
    error_code TEXT,
    error_detail_safe TEXT,
    transport_metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_attempts_delivery
    ON delivery_attempts(delivery_key);

CREATE TABLE IF NOT EXISTS delivery_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delivery_key TEXT NOT NULL,
    at TEXT,
    from_status TEXT,
    to_status TEXT,
    actor TEXT,                              -- "dispatcher" | operador
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_transitions_delivery
    ON delivery_transitions(delivery_key);
```

## Reglas

- **Sin `delivery_destinations`**: la config de destinos vive en
  `CA_ES_OPS_CONFIG_V1.delivery.destinations` (source of truth
  operatoria). El ledger guarda `destination_id`/`adapter_type`
  desnormalizados por auditoría — un destino retirado del config no
  borra historia.
- **Sin secretos**: ninguna columna admite credenciales.
- **Append-only**: `delivery_attempts` y `delivery_transitions` solo
  INSERT; `deliveries` actualiza status/contadores/timestamps.
- **STARTED huérfano**: un attempt `STARTED` presente al inicio de
  una invocación del dispatcher (que es single-writer por run lock)
  es resto de un crash → `UNKNOWN` + `UNKNOWN_OUTCOME`, nunca
  reintento ciego.
- **Compat outbox**: `outbox.delivery_attempts` sigue
  incrementándose por intento sobre esa alerta (columna legacy,
  informativa).
- Migración testeada: fixture de state v2 real migra sin pérdida y
  conserva outbox/runs/artifacts/source_*.
