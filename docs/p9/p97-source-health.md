# P9.7 — Source health + alerts

Salud de **disponibilidad** de fuentes dentro de
`CA_ES_OPERATIONAL_HEALTH_V1` + categorías de alerta nuevas en el
outbox. Nunca reinterpreta hechos de negocio: una fuente caída no
dice nada sobre la existencia de un corporate action.

## Checks de salud (nuevos)

Solo se evalúan cuando `sources.enabled` (si no: `INFO
NOT_CONFIGURED`).

| check | severidad | semántica |
|---|---|---|
| `source_refresh` | OK / DEGRADED / FAILED | último `source_refreshes.status`: SUCCESS/UNCHANGED→OK, PARTIAL→DEGRADED, FAILED→FAILED; sin refresh aún → DEGRADED `NO_REFRESH_YET` |
| `source_required` | FAILED / OK | algún `source_results[]` con `required=true` en estado FAILED/PARTIAL en el último refresh doc |
| `source_parse_failures` | DEGRADED si >0 | `source_parse_results` con `PARSE_FAILED` sobre el **latest** observado de cada documento |
| `source_checkpoints` | DEGRADED si viejo | antigüedad del checkpoint más viejo vs `health.source_checkpoint_max_age_days`; sin umbral → `INFO NO_THRESHOLD` |

Umbrales: solo desde `config.health` /
`config.sources.stale_after_days`. Nunca se asume "CNMV debe
publicar cada día".

## Categorías de alerta (nuevas)

Derivadas del `source_refresh`/`canon_refresh` **de este run** — si
el run no produjo esos docs, las categorías no se evalúan y las
alertas abiertas no se limpian espurio.

| categoría | subject | condición |
|---|---|---|
| `SOURCE_REFRESH_FAILED` | `source_id/surface_id` | source result FAILED (incluye policy-gated) |
| `SOURCE_PARTIAL` | `source_id/surface_id` | fetch failures o discovery error/paginación incompleta |
| `SOURCE_PARSE_FAILED` | `source_document_id` | `canon_refresh.parse_failures[]` (incluye NO_PARSER) |
| `SOURCE_CONTENT_CHANGED` | `source_document_id` | promoción chosen→latest con `from != null`; payload dice explícitamente "normal revision, not a source error" |
| `SOURCE_STALE` | `source_id/surface_id` | `source_checkpoints.updated_at` más viejo que `sources.stale_after_days` |

Reglas:

- `UNCHANGED` nunca alerta.
- Un conjunto de publicaciones legítimamente sin cambios no es
  "stale" salvo umbral explícito.
- `CONTENT_CHANGED` es informativo: una revisión del documento puede
  ser normal. La severidad no implica error de fuente.
- Las alertas de delta de negocio siguen siendo categorías
  separadas (`EXCEPTION_CASE`, `DEADLINE_*`).

## Evaluación / clear

`alert_outbox` añade `SOURCE_CATEGORIES` a `evaluated` solo cuando
`source_refresh` o `canon_refresh` produjeron doc este run. Un run
sin sources enabled no toca alertas de fuente abiertas (no las
borra ni las re-notifica).
