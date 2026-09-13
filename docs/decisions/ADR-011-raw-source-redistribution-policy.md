# ADR-011 — Raw-source redistribution policy

Status: ACCEPTED (G0 freeze, 2026-09-13)

## Context

El repositorio OSS debe poder publicarse sin redistribuir corpus raw de
terceros cuando los términos no lo permitan.

## Decision

- Se publican preferentemente: código, schemas, parsers, tests, reglas de
  mapping, maquinaria de provenance, fixtures sintéticos/mínimos
  redistribuibles, documentación.
- Cada fuente declara `raw_storage` y `redistribution` en
  `docs/sources/source-policy.json`.
- `raw/` y `g0/corpus/raw/*` permanecen fuera de Git cuando aplica.
- Los hashes y metadata sí pueden conservarse.
- Los fixtures de canario de G0 son **sintéticos** y redistribuibles;
  transcriben solo hechos explicitados en el alcance, y los originales
  reales permanecen `LOCAL_ONLY`.

Política por fuente:

| Fuente | raw_storage | redistribution |
|--------|-------------|----------------|
| CNMV | LOCAL_ONLY | NOT_REDISTRIBUTED |
| BOE_BORME | LOCAL_ONLY | HASH_AND_METADATA_ONLY |
| PORTFOLIO_STOCK_EXCHANGE | LOCAL_ONLY | NOT_REDISTRIBUTED |
| ISSUER_IR | LOCAL_ONLY | NOT_REDISTRIBUTED |
| ESMA_FIRDS | LOCAL_ONLY | HASH_AND_METADATA_ONLY |
| IBERCLEAR | NOT_INGESTED | NOT_REDISTRIBUTED |

Gates: `SOURCE_REUSE_POLICY_DECLARED`,
`RAW_REDISTRIBUTION_POLICY_EXPLICIT`.
