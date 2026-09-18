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
