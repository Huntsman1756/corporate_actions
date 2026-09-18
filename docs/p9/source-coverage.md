# P9 — Source discovery coverage

Qué significa "completo" en cada superficie descubierta por P9.
Ninguna clasificación afirma cobertura del universo completo de
corporate actions españolas — solo la enumeración de la superficie
oficial descrita.

## Clasificación por superficie

| source_id | surface_id | clasificación | qué cubre |
|---|---|---|---|
| `CNMV` | `OIR` | `ENUMERABLE_COMPLETE` | el registro oficial OIR por ventana de fechas con paginación completa (`max_page` + break en página vacía); identidad = número de registro CNMV |
| `CNMV` | `IP` | `ENUMERABLE_COMPLETE` | idem para Información Privilegiada |
| `BME_GROWTH` | `CORPORATE_ACTIONS` | `ENUMERABLE_COMPLETE` | re-enumeración completa de las 9 categorías del endpoint JSON oficial (`Market/v1/EQ/CorporateActions/{kind}`); sin paginación (la API devuelve la tabla entera) |
| `PORTFOLIO_STOCK_EXCHANGE` | `PORTFOLIO_MARKET` | `ENUMERABLE_WITH_LIMITATIONS` | index → página de producto → documentos `/poex/document/{id}`; completo solo para productos visibles en el index público del momento; sin política de desaparición prerregistrada |
| `BOE_BORME` | — | `REPLAY_ONLY` | sin mecanismo de discovery incremental demostrado en el repo; la evidencia existente se reproduce desde manifests |
| `ISSUER_IR` | — | `REPLAY_ONLY` | discovery query-driven no determinista; no hay superficie enumerable probada |
| `ESMA_FIRDS` | — | `REFERENCE_ONLY` | capa de referencia externa vía `ListingResolver`; no es fuente de eventos |
| `IBERCLEAR` | — | `REFERENCE_ONLY` | `PUBLIC_INGEST_INTERFACE_NOT_PROVEN`; sin ingestión |

## Notas por fuente

### CNMV (`ENUMERABLE_COMPLETE`)

- "Completo" = todos los registros del portal OIR/IP en la ventana
  `[desde, hasta]` que el buscador oficial devuelve, con todas las
  páginas recorridas. No afirma que todo CA español pase por OIR.
- Identidad: `CNMV-{OIR|IP}-<registration_number>`. Filas sin
  número de registro se descartan y se cuentan en
  `dropped_no_identity` — nunca se inventa identidad.
- Checkpoint: `last_publication_date` + `overlap_days` con
  re-query solapado (las publicaciones pueden retrasarse o
  corregirse); nunca `last+1s`.

### BME (`ENUMERABLE_COMPLETE`)

- "Completo" = la tabla oficial de operaciones financieras que la
  API devuelve en el momento del refresh, en las 9 categorías
  configuradas. Es disclosure del venue, no el universo CNMV.
- Identidad: `BMEG-{kind}-{isin}-{fecha}`; fallback por emisor
  normalizado cuando falta ISIN. La unidad de evidencia es el row
  canonizado (`BME_API_ROW_SNAPSHOT`), no la respuesta entera.
- Sin paginación ni cursor de discovery: re-enumeración completa
  cada refresh; el cursor solo registra `last_refresh_at` +
  `documents_seen`.

### Portfolio (`ENUMERABLE_WITH_LIMITATIONS`)

- "Completo" solo dentro del index público de productos en el
  momento del snapshot. Productos sin página enlazada desde el
  index quedan fuera por construcción de la superficie.
- La ausencia de un documento en un snapshot posterior **no**
  implica desaparición: las observaciones previas persisten y su
  `chosen` sigue entrando al canon.
- Identidad: `POEX-DOC-<id>` (id numérico del API de documentos).

## Lo que NO se afirma

- Completitud del universo CA español: ni CNMV+BME+Portfolio juntos
  garantizan todos los eventos; cada fuente tiene su rol en
  `source-policy.json` (primaria regulatoria vs disclosure de
  venue).
- Recall porcentual: sin denominador verificable no hay cifra. Lo
  que sí está instrumentado es `dropped_no_identity`,
  `pagination_complete` y `discovery_only` por refresh.
