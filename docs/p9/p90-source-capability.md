# P9.0 — Auditoría de capacidad de fuentes públicas

Preregistro del batch P9 (Live Source Refresh). Auditoría de las
superficies de adquisición ya demostradas en el repo antes de
operacionalizar ninguna. No se añade ninguna fuente por estar
disponible en la web.

## Método

Inspección de: `docs/sources/source-policy.json`,
`docs/sources/support-matrix.md`, `scripts/fetch_cnmv.py`,
`scripts/fetch_real_corpus.py`, `scripts/build_g1_frame.py`,
`scripts/build_g1r2_corpus.py`, `g1/manifests/sampling-frame.json`
(1419 items reales), `g0/manifests/real-corpus.json`,
`g2/manifests/qualification-corpus.json`, `src/ca_es/sources/`
(registry + parsers + locators), `src/ca_es/pipeline.py`,
`src/ca_es/export.py`, `src/ca_es/ops_state.py`, `src/ca_es/ops_dag.py`.

## Clasificación por superficie

| source_id | surface_id | clase |
|---|---|---|
| CNMV | OIR (resultado-oir.aspx) | **OPERATIONALIZABLE** |
| CNMV | IP (resultado-ip.aspx) | **OPERATIONALIZABLE** |
| BME_GROWTH | Market/v1/EQ/CorporateActions/* | **OPERATIONALIZABLE** |
| PORTFOLIO_STOCK_EXCHANGE | portfolio-market index+products | **OPERATIONALIZABLE** |
| BOE_BORME | buscar/doc.php?id= | **REPLAY_ONLY** |
| ISSUER_IR | páginas IR sueltas | **REPLAY_ONLY** |
| ESMA_FIRDS | listings | **REFERENCE_ONLY** |
| IBERCLEAR | — | **REFERENCE_ONLY** |

## Detalle por superficie

### CNMV_OIR / CNMV_IP — OPERATIONALIZABLE

- **Discovery**: enumeración total del registro por ventana de fechas
  — `resultado-{portal}.aspx?fechaDesde=dd/mm/yyyy&fechaHasta=&page=N`
  GET directo (probado por `enumerate_cnmv_portal` en G1: chunks
  mensuales sobre 2025-01→2026-09, sin filtro de emisor).
- **Identidad**: `registration_number` oficial ("Número de registro")
  → `CNMV-IP-{reg}` / `CNMV-OIR-{reg}`; dedup por registro.
- **Paginación**: enlaces `resultado-*.aspx?...&page=N`; se detecta
  `max_page`; página vacía = fin. Completitud demostrable por
  iteración de páginas enlazadas.
- **Fechas**: fecha de registro `dd/mm/yyyy` + hora (metadata; la
  fecha de publicación canónica sale del documento, no del listado).
- **Retrieval**: `document_url` por fila →
  `webservices/verdocumento/ver?t={guid}` → `application/pdf`.
- **Relaciones**: enlaces "Relacionado con la comunicación" →
  `relations[]` oficiales (evidencia, no heurística).
- **Media types**: `application/pdf` (observado), html posible.
- **Parser**: `cnmv.py` (PDF prosa regulatoria, mappings PROVEN).
- **Policy**: `raw_storage=LOCAL_ONLY`, `redistribution=NOT_REDISTRIBUTED`,
  `ingestion_status=ACTIVE`.
- **Checkpoint**: cursor por portal = última fecha de publicación
  observada; ventanas solapadas deliberadas (la fuente puede registrar
  con retraso). No se usa `last_ts+1s`.
- **Fallos conocidos**: WebForms puede devolver página de error HTML
  con status 200 (detectable: sin `repListaPrincipal` ni paginación);
  filas sin `registration_number` se descartan (`dropped_no_registration`
  ya medido en G1); timeouts/5xx transitorios.
- **Politeness**: `POLITE_SLEEP=0.35s` + sesión con cookies (el portal
  exige cookiejar del home antes del listado — probado en
  `build_opener`).
- **Cobertura**: ENUMERABLE_COMPLETE *para los registros OIR/IP* (no
  para el universo CA español).

### BME_GROWTH — OPERATIONALIZABLE

- **Discovery**: API JSON
  `apiweb.bolsasymercados.es/Market/v1/EQ/CorporateActions/{kind}` —
  9 kinds (Dividends, CapitalIncreases, Splits, Mergers, OtherPayments,
  NewListings, Delistings, PublicOfferings, TakeoverBids);
  `tradingSystem=MTF&mtfSegment=BMEGrowth`; `from/to` yyyymmdd;
  `pageSize=0` (todo).
- **Identidad**: sin document_id oficial — la fila se identifica por
  composición `BMEG-{kind}-{isin}-{date}` (convención ya usada en
  `qualification-corpus.json` y en el frame G1). Dedup por esa clave.
- **Paginación**: `page/pageSize`; `pageSize=0` devuelve todo el rango
  (probado). Completitud = respuesta única por kind.
- **Fechas**: múltiples claves por kind (`exDate`, `splitDate`,
  `startingDate`, `paymentDate`, ...); `bme_item_date` elige la primera
  presente (yyyymmdd).
- **Retrieval**: la propia respuesta JSON es el "documento"
  (`retrieval_method=BME_API_ROW_SNAPSHOT` ya usado en manifests).
  La fila se conserva como bytes del subdocumento.
- **Media type**: `application/json`.
- **Parser**: `bme_growth.py`.
- **Policy**: `LOCAL_ONLY`, `NOT_REDISTRIBUTED`, `ACTIVE`.
- **Limitación crítica**: la API solo publica ventana reciente
  (benchmark G1: "~último año; splits ~último mes"). Una fila que
  sale de la ventana NO desaparece de la evidencia: el store acumulado
  la conserva. Checkpoint = fecha de última consulta + set de claves
  observadas (no watermark de fechas).
- **Cobertura**: ENUMERABLE_COMPLETE *para la superficie API de
  operaciones financieras BME Growth en su ventana publicada*.

### PORTFOLIO_STOCK_EXCHANGE — OPERATIONALIZABLE

- **Discovery**: snapshot completo — `portfolio.exchange/es/portfolio-market`
  → URLs de producto (regex `-ES[A-Z0-9]{10}-\d+`) → página de producto
  → entradas de documento embebidas (probado G1 + G1-R2).
- **Identidad**: `document_id` numérico oficial → `POEX-DOC-{id}`
  (frame) / `PORTFOLIO-{id}` (corpus). Estable.
- **Paginación**: ninguna — snapshot integral por enumeración.
- **Retrieval**: `api.portfolio.exchange/poex/document/{id}` → PDF.
- **Media type**: `application/pdf` (algunos SCANNED_PDF_NO_TEXT_LAYER
  → el parser ya marca incapacidad, no es fallo de adquisición).
- **Parser**: `portfolio.py` (con `_ISSUE_PRICE_QUARANTINED` —
  enforcement vigente).
- **Policy**: `LOCAL_ONLY`, `NOT_REDISTRIBUTED`, `ACTIVE`.
- **Checkpoint**: set de `document_id` observados; la fuente puede
  republicar — ausencia en un snapshot NO implica borrado
  (invariante P9).
- **Cobertura**: ENUMERABLE_COMPLETE *para los documentos de producto
  visibles en portfolio-market* (los productos listados en el index).

### BOE_BORME — REPLAY_ONLY

- Solo está probada la recuperación puntual `buscar/doc.php?id=BORME-C-…`
  (Parlem). No existe en el repo ningún mecanismo de enumeración
  (sumario diario BORME → actos) demostrado ni testeado.
- Operationalizar exigiría descubrimiento nuevo fuera de lo probado:
  según el mandato, **REPLAY_ONLY**. Los BORME ya adquiridos
  (adquisición manual/manifest) sí entran en el refresh canónico como
  evidencia acumulada.

### ISSUER_IR — REPLAY_ONLY

- Solo una página Santander fijada a mano; sin superficie de
  descubrimiento determinista. REPLAY_ONLY.

### ESMA_FIRDS — REFERENCE_ONLY

- Capa externa vía `ListingResolver`; adquisición separada ya existente
  (`firds-acquisition.json`). No entra en P9.

### IBERCLEAR — REFERENCE_ONLY

- `PUBLIC_INGEST_INTERFACE_NOT_PROVEN` — inmutable por policy.

## Pipeline canónico reutilizable (sin segundo canonicalizer)

`load_and_parse(corpus_root, manifest, policy)` → `build_identity` →
`build_event_views` → `operational_canon(body, corpus_id)` →
`canon_payload` (`logical_sha256`). El refresh canónico = nuevo
manifest `CA_ES_SOURCE_MANIFEST_V1` sobre el conjunto acumulado de
documentos elegidos (última observación parseable por documento) →
mismo pipeline → nuevo canon inmutable. Una caída de CNMV no borra
nada: sus documentos ya adquiridos siguen en el manifest acumulado.

## Decisiones del audit

1. Los raw entran como blobs content-addressed en el state store P7
   (`<state>/blobs/<xx>/<sha>.bin`), no en un segundo store.
2. El "documento" BME es la fila JSON: se conserva byte-exacta como
   blob propio (no la respuesta agregada completa — la fila es la
   unidad de identidad; la respuesta completa se conserva además como
   observación de superficie para auditoría).
3. CNMV identity = registration_number; filas sin registro se cuentan
   pero no se ingestan (misma regla G1).
4. `required` por fuente afecta solo a health/status operativo, nunca
   a la evidencia.
5. Todo fetch: UA explícito, timeout, retries acotados solo para
   fallos técnicos transitorios, politeness por fuente.
