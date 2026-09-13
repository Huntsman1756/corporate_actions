# G0 — Informe final

Fecha: 2026-09-13. Runtime: stdlib-only, offline.

## 1. Estado inicial encontrado

`F:\_Proyectos\corporate_actions` estaba **vacío** (greenfield), sin Git
inicializado. No existe capa ESMA/FIRDS instrument-level localizable en
`F:\_Proyectos`: la única capa existente es
`esdata-profesional/apps/workers/worker_esma_firds.py`, que carga
**metadata de ficheros DLTINS**, no extrae LEI/ISIN/MIC a nivel listing.
Se tomó como referencia de estilo `finreg-es` (stdlib-only, canonical
JSON, provenance, fail-closed) y se documentó la discrepancia (ver §10).

## 2. Decisiones tomadas

- Identidad canónica determinista por menor `candidate_event_id`; merges
  append-only; clustering solo por evidencia explícita (ADR-001/002).
- Assertions separadas de facts; conflictos explícitos, sin override
  silencioso (ADR-003).
- Revisiones solo por `SUPERSEDES`/`EXPLICIT_PREDECESSOR_REFERENCE`;
  generaciones por camino más largo en el DAG (ADR-004).
- Sin orden global de fechas; restricciones source-scoped (ADR-005).
- `ListingResolver` congelado; adapter consume artefacto
  `ESMA_FIRDS_LISTINGS_V1`; point-in-time; `segment_mic` preservado
  (ADR-006).
- Iberclear `REFERENCE_ONLY` / `PUBLIC_INGEST_INTERFACE_NOT_PROVEN`;
  `PAYMENT_CHANNEL ≠ ISSUER_CSD` (ADR-007).
- `Decimal` + `raw_lexeme` + escala; float prohibido (ADR-008).
- FIBO pin `FIBO-2024Q4`, mappings explícitos **UNMAPPED** (no se
  certifica equivalencia sin extracto) (ADR-009).
- ISO 15022/20022 fuera del core; Prowide JVM; metadata de release
  obligatoria (ADR-010).
- Corpus raw `LOCAL_ONLY`; fixtures sintéticos redistribuibles (ADR-011).

## 3. Archivos creados

```
pyproject.toml, README.md, AGENTS.md, .gitignore
src/ca_es/{__init__,__main__,canonical,numeric,errors,vocab,namespaces,
  source_policy,assertions,provenance,revisions,temporal,entitlement,
  semantics,iso_boundary,metrics,gates,pipeline,cli}.py
src/ca_es/identity/{__init__,ledger,engine}.py
src/ca_es/reference/{__init__,contracts,esma_firds}.py
src/ca_es/sources/{__init__,documents,registry}.py
src/ca_es/sources/parsers/{__init__,base,cnmv,borme,portfolio,issuer}.py
schemas/{source-document,assertion,fact,financial-amount,event,
  identity-ledger}.schema.json
tests/conftest.py + tests/unit/* + tests/integration/* + tests/canaries/*
docs/architecture/overview.md
docs/decisions/ADR-001..011
docs/gates/{g0-gates-preregistered.json,g0-scope.md,
  p3-cnmv-channel-coverage.json}
docs/sources/{README.md,source-policy.json}
docs/G0-FINAL-REPORT.md
g0/manifests/canary-corpus.json
g0/corpus/synthetic/*.json (6)
g0/corpus/reference/esma-firds-listings.json
```

## 4. ADRs

ADR-001 identidad y candidate IDs · ADR-002 ledger append-only ·
ADR-003 assertions vs facts · ADR-004 revisiones/supersession ·
ADR-005 temporal sin orden global · ADR-006 límite ESMA/ListingResolver ·
ADR-007 roles de fuente e Iberclear · ADR-008 Decimal/escala ·
ADR-009 FIBO · ADR-010 límite ISO/Prowide · ADR-011 redistribución raw.

## 5. Gates preregistrados

`docs/gates/g0-gates-preregistered.json` (`CA_ES_G0_GATES_V1`), con los
55 gates de §23 agrupados en Identity, Clustering, Lifecycle, Facts,
Numeric, Temporal, Infrastructure, Reference data, Conflicts,
Reproducibility, Legal, Semantics, Boundaries y Coverage investigation.
Registrados **antes** de adaptar la implementación.

## 6. Tests ejecutados

```
python -m pytest   →  53 passed
```

Cubren: same input→same UUID; orden A,B==B,A; merge manual no borra;
alias antiguo resuelve; adjudicación humana no escribe fact; conflicto
explícito; fecha UNKNOWN preservada; derivada etiquetada; P3
record<ex/payment==ex aceptado; Parlem entitlement con `as_of`; P3
0,11840672 exacto; float rechazado; venue histórico point-in-time;
multi-MIC preservado; name-only no auto-link; Iberclear REFERENCE_ONLY;
documento `SUPPORTS` ≠ revisión; corrección explícita → revisión.

## 7. Resultados exactos

| Métrica | Valor |
|---------|-------|
| documents_total / parsed | 6 / 6 |
| events_detected | 4 |
| event_type_coverage | 4/4 = 1.000000 |
| ex_date_explicit_rate | 0.500000 |
| record_date_explicit_rate | 0.250000 |
| payment_date_explicit_rate | 0.250000 |
| amount_ratio_coverage | 1.000000 |
| field_provenance_rate | 1.000000 |
| amendment_chain_proven_rate | 1.000000 |
| conflict_count | 1 |
| unresolved_identity_count | 2 (Parlem, P3 sin identificador de instrumento) |
| human_relation_adjudications | 0 |
| publication_lag_days | min 8 / max 165 (6 muestras) |
| result_sha | `79d8015800359e78a1aa07014030656f4b1f75247a1587c10fd3af22a38d11e4` |
| second run | `deterministic: true` |
| gates | 54 PASS / 0 FAIL / 1 INCONCLUSIVE |

Gate INCONCLUSIVE: `CNMV_CHANNEL_COVERAGE_P3` (ver §9). **Overall:
INCONCLUSIVE**, no PASS, porque un gate requerido no está resuelto.

## 8. Canarios cubiertos

- **Almirall 2026**: una corporate action, dos revisiones, ratio
  55→65, supersession explícita. PASS.
- **Parlem BORME-C-2026-4914**: rights issue, `ISSUER_CSD=IBERCLEAR`
  explícito, `TRADING_VENUE=BME_GROWTH`, entitlement basis con
  `asserted_as_of=2026-08-31` y componentes (autocartera, renuncias),
  sin upcasting a CSD. PASS.
- **P3 Spain SOCIMI**: `RECORD_DATE < EX_DATE`, `PAYMENT_DATE ==
  EX_DATE`, `PAYMENT_CHANNEL=EUROCLEAR_FRANCE`, importe
  `0,11840672` escala 8. PASS.
- **SAN (CNMV vs IR)**: conflicto explícito en `amount.gross_per_share`,
  ambas fuentes conservadas con `CONFLICTING`. PASS.

## 9. Problemas encontrados

- `CNMV_CHANNEL_COVERAGE_P3`: no investigable offline → `INCONCLUSIVE`.
  No se convierte "no encontrado en el corpus" en "no existe".
- La capa ESMA existente no expone LEI/ISIN/MIC a nivel listing; se
  definió el contrato y un adapter de artefacto normalizado, dejando
  explícito que la extracción pertenece a la capa ESMA (ver §10).
- `float` en las tasas de métricas rompía la serialización canónica; se
  corrigió a strings decimales.
- El cálculo de tasas de fecha se hacía tras eliminar la vista temporal;
  corregido.

## 10. Desviaciones respecto al prompt

- **Corpus real no disponible**: G0 se ejecuta sobre fixtures
  **sintéticos redistribuibles** que transcriben exclusivamente los
  hechos explicitados. Fechas concretas de P3 y SAN son ilustrativas y
  están marcadas; importe P3 y ratio Almirall sí son los exigidos.
- **Capa ESMA inexistente a nivel instrumento**: se implementó el
  contrato + adapter a un artefacto `ESMA_FIRDS_LISTINGS_V1`, no un
  reconstruido de FIRDS. Discrepancia documentada.
- **FIBO/ISO mappings**: deliberadamente `UNMAPPED` (no hay extracto de
  estándar verificado offline). Es una elección conservadora, no un
  fallo.

## 11. Riesgos abiertos

- Cobertura real de corpus no demostrada (sintético).
- `CNMV_CHANNEL_COVERAGE_P3` sin resolver.
- Resolución canónica puede cambiar si entra un `candidate_event_id`
  menor en un componente ya mergeado (sigue siendo resoluble, pero no
  congelado); si se exige estabilidad histórica del canonical habría que
  persistir decisiones en el ledger (nuevo input autoritativo).
- Parsers de G0 operan sobre fixtures estructurados; falta parser
  HTML/PDF real por fuente.
- Sin Git inicializado: no hay historia ni commit.

## 12. Commit SHA

Repositorio inicializado y publicado con autorización del usuario.

- Commit inicial: `64980af` — "Initial ca-es G0: deterministic,
  evidence-first corporate actions core".
- Repositorio: `https://github.com/Huntsman1756/corporate_actions.git`
  (rama `main`).
- Push realizado por HTTPS con el credential helper de `gh`; las claves
  SSH disponibles no cubrían GitHub.
- Este informe se actualiza en un commit posterior; el código de G0
  corresponde al commit inicial `64980af`.
