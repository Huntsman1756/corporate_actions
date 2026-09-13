# G0 scope — Corporate Actions ES (`ca-es`)

Status: FROZEN before implementation (2026-09-13).

## Pregunta de G0

> ¿Podemos reconstruir corporate actions reales con identidad estable,
> revisiones correctas, facts exactos y provenance completa sin permitir
> que heuristicas o humanos inventen el estado economico del evento?

## Dentro de alcance

- Capa inmutable de source documents con `source_document_id` estable y
  `content_sha256` fijado.
- Extraccion document → assertions, separada de assertions → reconciliacion.
- `candidate_event_id` determinista (UUIDv5) y `canonical_event_id` resuelto
  por identity ledger append-only.
- Relaciones de identidad y alias permanentes; adjudicacion humana
  limitada a relaciones.
- Revisions/supersession con evidencia explicita.
- Facts con provenance a nivel de campo y conflictos explicitos.
- Numeros financieros con `Decimal`, lexema raw y escala publicada.
- Semantica temporal source/infrastructure/event-type scoped sin orden global.
- Entitlement basis como assertion temporal (`asserted_as_of`).
- Contrato `ListingResolver` consumiendo la capa ESMA/FIRDS existente.
- Gates, metricas y CLI minima.

## Fuera de alcance (G0)

- Generacion ISO 15022 / 20022 (queda tras el limite `iso-adapter-jvm`).
- Un security master propio (FIRDS pertenece a la capa ESMA).
- Scraping masivo o corpus raw redistribuible de terceros.
- Clustering probabilistico o fuzzy matching.
- Funcionalidad "util despues" no exigida por los gates.

## Corpus previsto

Periodo 2025–2026. Emisores SAN, BBVA, IBE, ITX, REP. Familias
CASH_DIVIDEND, SCRIP/RIGHTS, CAPITAL_INCREASE, CAPITAL_REDUCTION. No se
amplia scope automaticamente.

## Canarios

- **Almirall 2026** — correccion explicita 55 → 65 derechos/accion nueva;
  misma corporate action, nueva revision, supersession.
- **Parlem BORME-C-2026-4914** — rights issue, BME Growth, rol de registro
  Iberclear explicito, entitlement basis mutable.
- **P3 Spain SOCIMI** — record date < ex date, payment date = ex date,
  Euroclear France como payment channel, alta precision decimal, semantica
  temporal no-Iberclear.

## Desviacion declarada

Las fuentes reales (CNMV/BORME/Portfolio) no se redistribuyen en este
repo. Los canarios se ejecutan sobre fixtures minimos, marcados como
`synthetic`, que codifican exclusivamente los hechos explicitados en el
enunciado del proyecto. Por tanto la cobertura de corpus real es
`INCONCLUSIVE` en G0; la maquinaria de auditabilidad si se demuestra.
