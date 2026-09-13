# Adquisición de corpus real (G0-R)

Los originales **permanecen LOCAL_ONLY** en `g0/corpus/raw/<canario>/`.
En Git solo se commitean: manifest, identificador oficial, URL,
SHA-256, metadata de adquisición y expectativas permitidas (ADR-011).

## Casos y qué debe demostrar cada uno

| Caso | Fuente | Documento | Debe demostrar |
|------|--------|-----------|----------------|
| Almirall | CNMV | hecho relevante + corrección | misma CA, revisión, ratio 55→65, supersession |
| Parlem | BOE/BORME | BORME-C-2026-4914 | rights, entitlement basis, Iberclear (registro), rights trading |
| P3 Spain | Portfolio | OIR / anuncio | record<ex, payment=ex, Euroclear France, escala decimal |
| SAN | CNMV + issuer IR | anuncio dividendos + IR | reconciliación multi-fuente, conflicto explícito |

## Convención de manifest real

Cada entrada extiende `CA_ES_SOURCE_MANIFEST_V1` con metadata de
adquisición y `synthetic=false`:

```json
{
  "source_id": "BOE_BORME",
  "official_document_id": "BORME-C-2026-4914",
  "content_sha256": "<sha256 del raw>",
  "retrieved_at": "2026-09-13T00:00:00Z",
  "publication_date": "2026-08-28",
  "media_type": "text/html",
  "raw_relpath": "g0/corpus/raw/parlem/borme-c-2026-4914.html",
  "synthetic": false,
  "acquisition": {
    "url": "https://www.boe.es/...",
    "retrieved_by": "<agente>",
    "http_status": 200,
    "official_identifier": "BORME-C-2026-4914",
    "terms_reviewed_at": "2026-09-13",
    "redistribution": "HASH_AND_METADATA_ONLY"
  }
}
```

## Expectativas (no facts)

Las expectativas de test (p.ej. "ratio esperado 55") viven en
`g0/manifests/expectations/<canario>.json` y **no** son facts canónicos.
Sirven para `assessment`, nunca para construir el estado del evento.

## Parsers reales (R2–R5)

Cada parser real sustituye al `StructuredSourceParser` por fuente,
manteniendo la misma salida (`ParsedDocument`). Debe:

- extraer claims con `evidence_locator` (página/sección) y `raw_pointer`
  (XPath/offset/JSON pointer),
- no inferir campos ausentes (`UNKNOWN`),
- no mapear `venue_name` a `segment_mic` (eso es R6).

## R6 — ESMA/FIRDS real

`ESMA FIRDS snapshot → ISIN, LEI, segment MIC, admission, termination →
ESMA_FIRDS_LISTINGS_V1 → ListingResolver`.

La conversión de FIRDS a `ESMA_FIRDS_LISTINGS_V1` vive **fuera** del core
ca-es (capa ESMA). ca-es solo consume el artefacto y valida su versión.

## R7 — CNMV_CHANNEL_COVERAGE_P3

Investigar con red el canal CNMV para P3 Spain SOCIMI; registrar URL y
SHA-256 de cualquier extracto y resolver el gate como
`PROVEN`/`NOT_PROVEN`/`CONTRADICTED`. `INCONCLUSIVE` deja de ser válido.
