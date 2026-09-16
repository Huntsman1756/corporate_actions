# P5.1 — Action Queue

Status: **FROZEN — PENDING IMPLEMENTATION**.
Parent: P5.0 DONE (`8418549`).

Motivación: `ACTION_REQUIRED` de `CA_ES_MORNING_BRIEF_V1` considera
accionable *cualquier* `date.*` vigente dentro de la ventana —
proximidad temporal, no obligación operativa. V1 queda congelado; la
corrección es un artefacto nuevo.

```text
CA_ES_OPERATIONAL_DEADLINE_V1   (P5.0)
+ as_of
+ window_days, due_soon_days    (umbrales explícitos, obligatorios)
        ↓
build_action_queue()
        ↓
CA_ES_ACTION_QUEUE_V1
        ↓
CA_ES_MORNING_BRIEF_V2          action_required := queue.items
```

## Reglas

- Sólo `SOURCE`/`DERIVED` con `deadline_date` producen queue item.
- `INDETERMINATE` se conserva en `indeterminate`, nunca se inventa
  fecha.
- `days_until` = `deadline_date - as_of` en **días naturales**; no se
  vuelve a contar business days.
- `OVERDUE` siempre visible aunque esté fuera de la ventana futura;
  `UPCOMING` sólo hasta `window_days`.
- `SOURCE` y `DERIVED` del mismo `deadline_type` coexisten, sin
  ganador.
- Orden determinista: `OVERDUE → DUE_TODAY → DUE_SOON → UPCOMING`,
  luego fecha/event/deadline_key.
- Umbrales explícitos: `--window-days` y `--due-soon-days` son
  **required** en CLI; ningún default financiero/custodio oculto.
- Cero knowledge de elections.

## Item

```text
deadline_key, canonical_event_id, deadline_type, deadline_date,
derivation_status, source_date, rule_id, calendar_id,
business_days_offset, days_until, action_status, assertion_ids,
evidence
```

`action_status`: `OVERDUE | DUE_TODAY | DUE_SOON | UPCOMING`.

## Morning Brief V2

`CA_ES_MORNING_BRIEF_V1` **no se modifica**. V2 = V1 con:

- `brief_version: CA_ES_MORNING_BRIEF_V2`;
- `action_required` := items de la cola, enriquecidos con
  `issuer_name`/`event_type` para el desk (la cola no se muta);
- `indeterminate_deadlines` := deadlines INDETERMINATE;
- `recent_changes`/`conflicts`/`unsupported`/`new_since_previous`
  idénticos a V1.

Desk consume V2 sin recalcular: sección extra
`INDETERMINATE DEADLINES` sólo cuando el brief la trae; detalle del
item muestra deadline/status/rule/calendar + evidence.

## CLI

```bash
ca-es action-queue --deadlines <doc> --as-of <date> \
    --window-days N --due-soon-days N [--now <iso>]

ca-es brief --canon <canon> --as-of <date> --queue <queue.json>
ca-es desk  --canon <canon> --as-of <date> --queue <queue.json>
```

## Fuera de alcance

Elections/instrucciones, cambios a V1, deduplicación SOURCE/DERIVED,
severidad de workflow (eso ya vive en P3.5 exceptions).
