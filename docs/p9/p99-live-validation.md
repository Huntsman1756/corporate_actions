# P9.9 — Live validation / CI strategy

## CI: determinista y offline

El CI normal **nunca** depende de la disponibilidad de
CNMV/BME/Portfolio. Todos los tests de P9 corren con fetchers
inyectados sobre fixtures mínimas construidas a partir de la
estructura probada de cada fuente (rows BME canonizados, páginas
WebForms CNMV sintéticas, índice Portfolio sintético) — no se
commitea raw real, que es `LOCAL_ONLY` por policy.

Cobertura offline (mapa del mandato):

| # | comportamiento | test |
|---|---|---|
| 1 | discovery parsing | `test_p91_source_refresh`, adapters |
| 2 | paginación | `test_p91` (CNMV `max_page`/break) |
| 3 | checkpointing | `test_p92_source_state`, `test_p91` |
| 4 | rediscovery solapado | `test_p91` (overlap window) |
| 5 | bytes duplicados exactos | `test_p91`, `test_p92` (SAME_BYTES) |
| 6 | bytes cambiados mismo id | `test_p91`, `test_p95` (CONTENT_CHANGED) |
| 7 | fallo de página parcial | `test_p91` (PARTIAL, pagination_incomplete) |
| 8 | timeout/red simulado | `test_p91`, `test_p96`, `test_p97` |
| 9 | outage preserva evidencia | `test_p95`, `test_p96` |
| 10 | parse failure preserva chosen | `test_p95`, `test_p97` |
| 11 | doc nuevo → canon delta | `test_p95` |
| 12 | refresh sin cambios reutiliza canon | `test_p95`, `test_p98` |
| 13 | canon cambiado invalida DAG selectivo | `test_p96`, `test_p72` |
| 14 | alert/health | `test_p97` |
| 15 | replay offline | `test_p98` |
| 16 | fixity de bytes | `test_p92` (blob store, sha reverify) |
| 17 | enforcement de source policy | `test_p91` (policy-gated) |
| 18 | LOCAL_ONLY fuera de export/Git | `export_run` solo copia artifacts/*.json; `state/` ignorado por `.gitignore` |
| 19 | rebuild determinista | `test_p95`, `test_p98` (mismo logical_sha) |

## Live smoke (opt-in)

```bash
python -m pytest tests/live --live          # o CA_ES_LIVE_SMOKE=1
```

`tests/live/test_live_smoke.py` ejecuta `discover()` real por cada
fuente OPERATIONALIZABLE (BME completo; Portfolio index→productos;
CNMV OIR/IP en ventana de ~31 días) y verifica:

- `discovery.complete == True` (paginación recorrida);
- fetch byte-exacto de una muestra acotada (`MAX_DOCS=3`) → blob
  store con re-verificación SHA-256.

Emite `CA_ES_LIVE_SMOKE_REPORT_V1` con solo metadatos seguros:
ids, hashes, counts, statuses, errores. Nunca bytes raw.

Un fallo del smoke por outage temporal upstream **no** es fallo de
CI (el test es opt-in y fuera del CI normal); se reporta tal cual
en `error` del reporte.

## Hallazgos live corregidos

La primera ejecución e2e real (`scripts/p9_e2e_demo.py`, leg LIVE
contra la API BME) expuso dos defectos que ninguna fixture offline
reproducía:

1. **Floats en la API BME** — la API devuelve números como float
   JSON (`"disbursement": 0.0`). La serialización inicial del
   adapter los conservaba como float y `strict_json_loads` los
   rechazaba en la frontera de parse → 167/167 `PARSE_FAILED`.
   Fix: `live/bme.py` aplica la misma normalización probada de
   `build_g1_frame.no_floats` (float → lexema `repr`) al serializar
   la row. El doc almacenado sigue siendo determinista y la regla
   no-float del canon queda intacta (los valores financieros entran
   como `raw_lexeme` string). Regresión:
   `test_p95.test_api_float_serializes_as_lexeme_and_parses`.

2. **Doc-ids con caracteres ilegales en path** — un emisor real
   produce doc-ids como `BMEG-CapitalIncreases-BRBBDCACNPR8-(*)`,
   que rompen `mkdir` del corpus scratch en Windows (`WinError
   123`). El `source_document_id` es identidad de evidencia y no
   se toca; `ops_canon._safe_path_component` sanea solo el
   componente de directorio (la unicidad real la da el SHA del
   nombre de archivo, así que un colapso de directorio es
   inofensivo).

Tras ambos fixes, el leg LIVE completo es verde: 167 docs →
167 eventos → canon build → `SKIPPED_UNCHANGED` en leg 2 → delta
selectivo en leg 3.
