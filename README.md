# Corporate Actions ES (`ca-es`)

Capa abierta, verificable, versionada y evidence-first de corporate
actions para valores vinculados al ecosistema español de negociación y
post-trade.

> No es un scraper de CNMV, ni un clon de BME, ni un calendario de
> dividendos, ni un security master. El evento pertenece al instrumento
> y a la operación societaria, no a una fuente concreta.

## Pregunta de G0

> ¿Podemos reconstruir corporate actions reales con identidad estable,
> revisiones correctas, facts exactos y provenance completa sin permitir
> que heurísticas o humanos inventen el estado económico del evento?

## Arquitectura

```
SOURCE DOCUMENTS (bytes congelados, sha256)
      │
      ▼
parsers          doc → claims observados (sin decidir verdad)
      │
      ▼
assertions       hechos atómicos con evidence_locator + raw_pointer
      │
      ├──────────────► identity ledger (candidate IDs UUIDv5,
      │                 relaciones, alias, canonical append-only)
      ▼
revisions        supersession explícita (Almirall 55→65)
      │
      ▼
facts            SOURCE_ASSERTION | DETERMINISTIC_DERIVATION |
      │           REFERENCE_ENRICHMENT, con conflictos explícitos
      ▼
reference        ListingResolver (ESMA/FIRDS) point-in-time, segment MIC
```

`canonical.py` fija `CA_ES_CANONICAL_JSON_V1` (sin floats, sin claves
duplicadas, rechaza NaN/Infinity). Todo hash deriva de ahí.

## Garantías

- Identidad canónica determinista dados raw inputs, config, identity
  ledger y adjudication ledger.
- `candidate_event_id = UUIDv5(ns, source_id + ":" + official_document_id)`.
- Cero merges fuzzy; ante duda, candidatos separados.
- Importes/ratios en `Decimal` con lexema raw y escala publicada.
- Semántica temporal source-scoped sin orden global de fechas.
- Iberclear `REFERENCE_ONLY` (`PUBLIC_INGEST_INTERFACE_NOT_PROVEN`).
- ISO 15022/20022 fuera del core (ADR-010, `iso-adapter-jvm`/Prowide).

## Reproducir

```bash
export PYTHONPATH=src          # Windows: $env:PYTHONPATH='src'
python -m pytest               # 53 tests offline

python -m ca_es.cli run --firds-listings g0/corpus/reference/esma-firds-listings.json
python -m ca_es.cli gates --second-run --firds-listings g0/corpus/reference/esma-firds-listings.json
python -m ca_es.cli metrics --firds-listings g0/corpus/reference/esma-firds-listings.json
```

Salidas regenerables en `g0/results/` (fuera de Git).

## Canarios G0

| Canario | Prueba |
|---------|--------|
| Almirall 2026 | misma CA, dos revisiones, ratio 55→65, supersession |
| Parlem BORME-C-2026-4914 | rights issue, Iberclear ISSUER_CSD, entitlement basis temporal |
| P3 Spain SOCIMI | record<ex, payment=ex, Euroclear France, escala 8 |
| SAN (CNMV vs IR) | conflicto explícito, ambas fuentes conservadas |

Los fixtures son **sintéticos y redistribuibles**: transcriben
exclusivamente hechos explicitados en el alcance. El corpus real
permanece `LOCAL_ONLY` (ADR-011).

## Estado G0 / G0-R

- Tests: **88 PASS**.
- Gates G0: **55 PASS / 0 FAIL / 0 INCONCLUSIVE**
  (`CNMV_CHANNEL_COVERAGE_P3` resuelto como `NOT_PROVEN`).
- Runtime del core: stdlib-only. La extracción PDF real es un extra
  opcional (`pypdf`) usado solo al ingerir documentos reales.

Validación con fuentes reales (**G0-R2**):
- MFE-MEDIAFOREUROPE `40280 → 40319`: **revisión explícita real**.
- Santander división complementaria: **reconciliación CNMV + IR**.
- P3 Spain SOCIMI: documento Portfolio real (record<ex, payment=ex,
  0,11840672 EUR, Euroclear France).
- Parlem BORME real, ESMA/FIRDS real (173 listings point-in-time),
  determinismo desde PDFs reales.
- **G0-R3 cerrado**: `EVENTO → INSTRUMENTO → FIRDS` exacto (P3:
  `PORTFOLIO-4733 → ES0105282000 → LEI + segment MIC POSE`), sin matching
  por nombre (ADR-013).
Ver `docs/G0R-FINDINGS.md`. El canario sintético Almirall 2026 queda
`RETIRED / INVALIDATED_BY_REAL_EVIDENCE`.

Informe G0: `docs/G0-FINAL-REPORT.md`.
Decisiones: `docs/decisions/`. Gates: `docs/gates/`. Fuentes: `docs/sources/`.
