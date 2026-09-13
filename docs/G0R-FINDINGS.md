# G0-R — Real source validation: hallazgos

Fecha: 2026-09-13. Fase final: **G0-R2**.
Verdict: `G0 REAL-DATA` = **STRONG** (un gate INCONCLUSIVE: ISIN en el
pipeline real). Arquitectura validada con documentos reales.

## Cierre por gate

| Gate | Estado | Evidencia real |
|------|--------|----------------|
| R1 canonical persistente | PASS | ADR-012 |
| R2 revisión explícita real | PASS | MFE `40280 → 40319` |
| R3 Parlem BORME | PASS | `BORME-C-2026-4914` |
| R4-A P3 documento real | PASS | Portfolio doc 4733 |
| R4-B adaptador Portfolio | PASS | `api.portfolio.exchange/poex/document/{id}` |
| R5 CNMV + IR dual | PASS | Santander dividendo 2025 |
| R6 FIRDS real | PASS | 173 listings |
| R7 cobertura CNMV P3 | PASS | `NOT_PROVEN` |
| R8 second-run desde raw | PASS | `20c233f4…` idéntico |
| Integridad (0 facts humanos, 0 conflictos silenciados, 0 merges no probados) | PASS | — |
| LEI/ISIN/MIC en el pipeline real | INCONCLUSIVE | docs reales sin ISIN |

## Los tres casos nuevos

### R2 — MFE-MEDIAFOREUROPE: revisión explícita real
- `CNMV-OIR-40280` (15/04/2026): dividendo 0,22 EUR; pago **29/07/2026**
  (ex 27/07, record 28/07).
- `CNMV-OIR-40319` (17/04/2026): *"se dan a conocer las **nuevas fechas**
  relativas a la distribución del dividendo ordinario bruto"* → pago
  **22/07/2026** (ex 20/07, record 21/07).
- Resultado: misma corporate action, relación explícita, **modificación
  parcial** (solo fechas), dos revisiones, la anterior retenida, importe
  0,22 EUR no reescrito. Sustituye al canario Almirall falsado.

### R5 — Santander: reconciliación CNMV + IR
- `CNMV-SAN-DIV-2026`: 12,50 céntimos/acción, pago **05/05/2026**, ex
  **30/04**, record **04/05** (ex/record sin año → derivadas, etiquetadas).
- `SAN-IR-REMUNERATION`: *"final cash dividend of €12.50 cents per share
  against H2 2025 results, paid in May 2026"*.
- Enlace por **adjudicación humana registrada** (`SAME_CORPORATE_ACTION`,
  sin identificador común). Ambas dan **0,125 EUR** (céntimos→EUR,
  `DERIVED_BY_DEFINITION`); CNMV **suplementa** las fechas. **0 conflictos,
  0 revisiones**.

### R4 — P3 Spain SOCIMI: documento Portfolio real
- `api.portfolio.exchange/poex/document/4733` (08/07/2025): record
  **23/07/2025** < ex **24/07/2025**, payment **= ex**, importe bruto
  **0,11840672 EUR** (8 decimales), pago vía **Euroclear France**.
- `www.portfolioexchange.com` devolvía HTTP 500, pero la API de documentos
  responde 200 de forma estable: R4-A (documento) y R4-B (adaptador) PASS.

## Hallazgos que cambian decisiones

- El fixture sintético de Parlem divergía de la realidad (ratio 2 vs 20:39;
  fechas inventadas).
- **El canario Almirall 2026 (55→65) no existe** en CNMV: **retirado**
  (`g0/manifests/retired-canaries.json`, `INVALIDATED_BY_REAL_EVIDENCE`).
- **CNMV no cubre P3** por las consultas hechas (`NOT_PROVEN`).
- `venue_name` (BME Growth) no se convierte en MIC; el `segment_mic`
  (`GROW`) lo aporta FIRDS por separado.
- El "12,50 céntimos" de Santander se normaliza a 0,125 EUR marcado
  `DERIVED_BY_DEFINITION`; la escala y el lexema se conservan.

## Único gate abierto

`CLOSURE_LEI_ISIN_MIC_FIRDS` sigue **INCONCLUSIVE**: la capa FIRDS real
existe y resuelve point-in-time, pero los documentos reales ingeridos
(BORME Parlem, CNMV/IR Santander) **no publican ISIN**, por lo que el
evento no enlaza todavía con `ListingResolver` en el pipeline. Para
cerrarlo: un documento real que publique ISIN, o una regla determinista
de adopción de ISIN desde una fuente portadora (con evidencia).

## Decisión

`G0 CORE` = **PASS** (55/55 gates).
`G0 REAL-DATA` = **STRONG** (arquitectura validada; 1 gate abierto).
`NEXT` = cerrar el enlace ISIN↔evento; después **G1**.
