# P5.0 — Operational Deadlines

Status: **FROZEN — PENDING IMPLEMENTATION**.
Parent: P4 vertical MT CLOSED (`0dea10d`).

Corrige la línea imprecisa del roadmap (“business-day awareness via
pandas_market_calendars”): **no existe un business day genérico**. El
calendario es un dato explícito del input, nunca un default.

```text
canonical event/date
+ explicit deadline rule   (CA_ES_DEADLINE_RULES_V1)
+ explicit calendar        (CA_ES_CALENDARS_V1)
        ↓
compute_deadlines()
        ↓
CA_ES_OPERATIONAL_DEADLINE_V1
```

## Invariantes

```text
official_date   != operational_deadline
calendar_date   != business-day-adjusted date
source deadline != derived deadline
```

- Fechas oficiales del canon: **intactas**, read-only.
- Sólo se deriva un deadline cuando existe una **regla
  preregistrada** (`rule_id` + `source_field` + `business_days_offset`
  + `calendar_id`).
- `calendar_id` es **obligatorio** para cualquier offset business-day.
- Calendario desconocido → `INDETERMINATE` / `UNKNOWN_CALENDAR`,
  **nunca** “lunes-viernes” por defecto.
- Fines de semana/festivos no se corrigen heurísticamente: la cuenta
  business-day usa exclusivamente `business_week` + `holidays`
  declarados en el calendario.
- Ninguna regla de custodio inventada: las reglas son input externo
  (`CA_ES_DEADLINE_RULES_V1`), no código.
- Sin elections voluntarias complejas; sin `ACTION_REQUIRED` (fase
  posterior).

## Contratos

`CA_ES_DEADLINE_RULES_V1`:

```json
{"schema": "CA_ES_DEADLINE_RULES_V1",
 "rules": [{"rule_id": "ES-CSD-RESPONSE-T1",
            "deadline_type": "RESPONSE_DEADLINE",
            "event_types": ["CASH_DIVIDEND"],
            "source_field": "date.payment_date",
            "business_days_offset": -1,
            "calendar_id": "TARGET2"}]}
```

`CA_ES_CALENDARS_V1` — calendario explícito, datos no código:

```json
{"schema": "CA_ES_CALENDARS_V1",
 "calendars": [{"calendar_id": "TARGET2",
                "business_week": [0, 1, 2, 3, 4],
                "holidays": ["2026-05-01"]}]}
```

`CA_ES_OPERATIONAL_DEADLINE_V1` — cada deadline lleva:

```text
deadline_key            event_id | deadline_type | rule_id|SOURCE
canonical_event_id
deadline_type
deadline_date           ISO o null
derivation_status       SOURCE | DERIVED | INDETERMINATE
source_date
rule_id                 null si SOURCE
calendar_id             null si SOURCE
business_days_offset    null si SOURCE
reasons                 [] o códigos INDETERMINATE
assertion_ids           facts canónicos usados
evidence                field_path + value + assertion_ids
```

`SOURCE`: fact canónico vigente con `field_path` = `deadline.<type>`.
`DERIVED`: regla + calendario + fecha fuente vigente, offset aplicado.
`INDETERMINATE` razones: `MISSING_SOURCE_DATE`,
`CONFLICTING_SOURCE_DATE`, `INVALID_SOURCE_DATE`, `UNKNOWN_CALENDAR`.

## CLI

```bash
ca-es deadlines --canon <canon.json> --rules <rules.json> \
    --calendars <calendars.json> [--event <id>] [--now <iso>]
```

## Fuera de alcance

Elections/instrucciones, `ACTION_REQUIRED`, agregación de deadlines en
brief, calendarios embebidos, inferencia de reglas, deduplicación entre
fuentes.
