# P11.2 — Send ledger SQLite (schema v4)

Extensión aditiva del OpsState existente. Sin segunda base de
datos; sin pérdida de estado P7/P9/P10.

## DDL

```sql
CREATE TABLE IF NOT EXISTS sends (
    delivery_id           TEXT PRIMARY KEY,
    instruction_id        TEXT NOT NULL,
    message_reference     TEXT,
    message_schema        TEXT NOT NULL,
    message_text          TEXT NOT NULL,
    content_sha256        TEXT NOT NULL,
    destination_id        TEXT NOT NULL,
    adapter_type          TEXT NOT NULL,
    generation            INTEGER NOT NULL,
    status                TEXT NOT NULL,
    transport_reference   TEXT,
    attempt_count         INTEGER NOT NULL DEFAULT 0,
    first_prepared_at     TEXT NOT NULL,
    spooled_at            TEXT,
    last_attempt_at       TEXT,
    next_attempt_after    TEXT,
    external_receipt_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_sends_instruction
    ON sends(instruction_id);
CREATE INDEX IF NOT EXISTS idx_sends_status
    ON sends(status);

CREATE TABLE IF NOT EXISTS send_attempts (
    attempt_id              TEXT PRIMARY KEY,
    delivery_id             TEXT NOT NULL,
    attempt_number          INTEGER NOT NULL,
    started_at              TEXT,
    completed_at            TEXT,
    status                  TEXT NOT NULL,
    retryable               INTEGER,
    error_code              TEXT,
    error_detail_safe       TEXT,
    transport_metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_send_attempts_delivery
    ON send_attempts(delivery_id);

CREATE TABLE IF NOT EXISTS send_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    delivery_id      TEXT NOT NULL,
    at               TEXT,
    from_status      TEXT,
    to_status        TEXT NOT NULL,
    actor            TEXT,
    note             TEXT
);
CREATE INDEX IF NOT EXISTS idx_send_transitions_delivery
    ON send_transitions(delivery_id);

CREATE TABLE IF NOT EXISTS send_receipts (
    receipt_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    delivery_id       TEXT NOT NULL,
    receipt_sha256    TEXT NOT NULL,
    status            TEXT NOT NULL,   -- ACCEPTED|REJECTED|QUARANTINED
    gateway_reference TEXT,
    received_at       TEXT,
    reason            TEXT,
    source_path       TEXT,
    quarantine_reason TEXT,
    ingested_at       TEXT NOT NULL
);
```

## Migración

`OPS_STATE_SCHEMA_VERSION = "4"`. Additiva:

- v1/v2/v3 → se aplican los DDL acumulados (source + delivery +
  send) y se fija `"4"`.
- Transaccional, probada con fixtures v1/v2/v3 reales.
- Sin ALTER destructivo; outbox/deliveries intactos.

## Invariantes

- `send_attempts` y `send_transitions` son append-only; jamás
  DELETE ni UPDATE de filas históricas.
- `message_text` + `content_sha256` son la evidencia: el receipt
  debe citar el mismo hash.
- `transport_reference` solo llega desde un receipt válido —
  nunca lo escribe el core por sí mismo.
- El ledger no guarda credenciales ni configuración de destinos.
