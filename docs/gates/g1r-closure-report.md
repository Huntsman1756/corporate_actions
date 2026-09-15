# G1-R Closure Report — Corporate Actions ES

**G1-R VERDICT: FAIL**

Binding cause: `false_financial_facts = 1` en HOLDOUT virgen.

`POEX-DOC-39649` (NEXTLOG, ampliación de capital con derechos de
suscripción preferente, fuente Portfolio): el documento publica
`Precio de suscripción por acción nueva (nominal + prima) 4€ POR ACCIÓN
NUEVA` (1€ nominal + 3€ prima) y `Ratio 2 DERECHOS → 1 ACCIÓN NUEVA`.
El parser congelado emite `amount.gross_per_share = 4 EUR` — número
correcto, fact canónico incorrecto por `field_path`: en un
`CAPITAL_INCREASE` el precio de suscripción/emisión pertenece a
`amount.issue_price_per_share` (canonical-registry
`AMOUNT_ROLE.ISSUE_PRICE_PER_SHARE`, separado expresamente de
`GROSS_UNIT_AMOUNT`; precedente ADR-017 y erratum del oracle iter-1,
IP-2670 `0,37`). El slot correcto existe en el parser CNMV
(`_ISSUE_PRICE_EVENTS`) pero la fuente Portfolio no lo aplica.

Nueva clase P0 descubierta en holdout: **`AMOUNT_ROLE_MISBINDING`**
(source-specific amount-role attribution). Registrada en
`g1r/results/post-holdout-findings.jsonl` y `state.json`
(`failure_classes.discovered_in_holdout`).

El criterio estaba preregistrado (`docs/gates/g1r-preregistered.json`,
tag `g1r-protocol` = `f9ee8f8`): una sola aparición P0 en HOLDOUT es
hard-fail. Este FAIL es permanente; una fase posterior (G1-R2 u otra)
no lo reescribe.

Fecha de cierre: 2026-09-15. Último commit de adjudicación: `725da2e`.

---

## 1. Scope y freeze

| Elemento | Valor |
|---|---|
| Protocolo | `docs/gates/g1r-preregistered.json` + `g1r-execution-runbook.md`; tag `g1r-protocol` (`f9ee8f8`) |
| Semantic freeze | tag `g1r-semantic-freeze` (`cad072f`) |
| Parser freeze | tag `g1r-parser-freeze` → `a6a0674` (5/5 clases P0 DEV resueltas; holdout unseals) |
| Regression oracle | 56/56 (`dev-iter-5-g1-oracle-eval.json`, congelado) |
| DEV oracle | 0 `P0_UNRESOLVED`, 0 `REGRESSED` / `EMITTED_OTHER` / `NOW_ABSENT` |
| Corpus | 25 DEV + 15 HOLDOUT virgen (frame G1 menos 150 excluidos; split por `SHA256(CA_ES_G1R_SPLIT_V1 + frame_item_id)`) |
| Iteraciones DEV | dev-iter-1..5, una failure class abierta a la vez, firma externa por checkpoint |

`git diff g1r-parser-freeze..HEAD` tras los runs: solo `g1r/results`,
`g1r/adjudication`, `scripts/_*.py` (tooling de adjudicación) y
`.gitignore`. Cero cambios funcionales en `src/` post-freeze.

## 2. HOLDOUT virgen — ejecución

- Dos runs sobre el mismo freeze: `holdout-run-1-a6a0674`,
  `holdout-run-2-a6a0674`; `parser_commit=a6a0674`,
  `parser_commit_dirty=false`, commiteados (`aa7603f`) **antes** del
  paquete de adjudicación (`8d71539`). `seed_verdicts` del artefacto de
  run: 15 `UNADJUDICATED` — virginidad demostrada.
- Funnel: 15/15 retrieved · parsed · `event_detected` · 0 excepciones;
  `critical_facts_extracted` 8/15; `instrument_resolved` 2/15
  (medido, no binding).
- `conflicts = 1`: los 3 ISIN de `POEX-DOC-39649` (cotizables
  `ES0105969002`, derechos `ES0605969908`, acciones nuevas temporales
  `ES0105969028`) registrados como `Conflict` explícito — aceptado,
  limitación P2 de desambiguación por etiqueta.

## 3. Adjudicación humana — resultado

Missingness sobre los 6 campos críticos (90 filas, 15 docs):

| Clase | Filas |
|---|---:|
| published (CORRECT + MISSING) | 44 |
| CORRECT | 31 |
| **MISSING** (publicado, no extraído) | **13** |
| UNKNOWN (aplicable, no publicado) | 6 |
| NOT_APPLICABLE | 28 |
| NOT_REVIEWABLE_NO_TEXT_LAYER | 12 |

Los 12 campos pendientes pertenecen a `CNMV-OIR-34719` y
`POEX-DOC-15339` (PDF escaneados sin capa de texto, 0 facts emitidos).

Tabla de firma del revisor:

| Punto | Firma |
|---|---|
| `POEX-DOC-39649` amount slot | **REJECT — P0** (`gross_per_share` → `issue_price_per_share`) |
| `POEX-DOC-39649` ISIN conflict | ACCEPT — conflicto explícito / limitación P2 |
| `CNMV-IP-2683` | ACCEPT — `HUMAN_RELATION_REQUIRED` (oferta sobre acciones de Biotest AG, name-only; ADR-013 conservador correcto) |
| `CNMV-OIR-34719`, `POEX-DOC-15339` | PENDING VISUAL |
| P0 review coverage (facts emitidos) | compatible con 1.0 |
| P1 non-degradation | **INDETERMINATE** |
| Regression oracle / parser freeze | 56/56 / válido |

## 4. Hard-fail table (preregistrada)

| Hard criterion | Resultado | Estado |
|---|---:|---|
| `false_financial_facts > 0` | **1** (`AMOUNT_ROLE_MISBINDING`, POEX-DOC-39649) | **FAIL — BINDING** |
| `wrong_attribution > 0` | 0 | PASS |
| `wrong_event_type > 0` | 0 | PASS |
| `date_misbinding > 0` | 0 | PASS |
| `false_positive_event > 0` | 0 | PASS |
| `p0_review_coverage < 1.0` | 39/39 facts P0 emitidos revisados → 1.0 | PASS |
| `parser_miss_rate` (guard `missing·60 ≤ published·23`) | 780 ≤ 1012 solo excluyendo 12 filas sin excepción preregistrada; con `k` facts publicados en escaneados pasa iff `k ≤ 6` | **INDETERMINATE_PENDING_VISUAL_REVIEW** |
| `field_provenance_rate < 1.0` | 63/63 con `evidence_locator` → 1.0 | PASS |
| `silent_conflicts > 0` | 0 (el único conflicto es explícito/registrado) | PASS |
| `unproven_auto_merges > 0` | 0 | PASS |
| `human_authored_facts > 0` | 0 (adjudicación humana: solo relaciones) | PASS |
| `second_run_determinism != 1.0` | run-1 vs run-2 idénticos salvo `phase` y `batch_sha256` (derivado) → 1.0 | PASS |

El veredicto FAIL no depende del resultado visual de los dos PDF
escaneados: el P0 de `POEX-DOC-39649` ya lo determina.

## 5. Naturaleza probatoria de los valores

Distinción explícita exigida en la firma:

- **VERIFIED_COMPARATOR**: `second_run_determinism` (diff byte a byte
  de los dos artefactos de run).
- **VERIFIED_HUMAN_REVIEW**: `p0_review_coverage`, la lectura documental
  de `POEX-DOC-39649` (`holdout-text/`), el carácter explícito del
  conflicto de ISIN, `HUMAN_RELATION_REQUIRED` de `CNMV-IP-2683`.
- **GENERATED_BY_PROPOSAL** (constantes escritas por
  `_adjudicate_g1r_holdout.py`, aceptadas o corregidas por la revisión):
  `field_provenance_rate`, los cinco contadores P0 propuestos — el de
  `false_financial_facts` fue **refutado** (0 → 1).
- **DERIVED**: `parser_miss_rate` (conteos de
  `holdout-missingness-review.jsonl`; denominador incompleto).

## 6. Qué concluye y qué no concluye G1-R

```text
G1-R: las 5 clases P0 conocidas quedan corregidas y sostenidas
      (regression oracle 56/56, DEV 0 P0 abiertos) — PROVEN sobre lo conocido
G1-R: el parser congelado a6a0674 NO generaliza con seguridad operativa:
      el holdout virgen descubre AMOUNT_ROLE_MISBINDING — FALSIFIED
```

- No invalida el modelo canónico ni la disciplina evidence-first: el
  error se detectó porque cada fact cita su evidencia y la separación
  `ISSUE_PRICE_PER_SHARE`/`GROSS_UNIT_AMOUNT` ya existía en el registry.
- No demuestra nada sobre los 2 PDF escaneados: su missingness queda
  `PENDING VISUAL` y fuera del denominador preregistrado.
- `CNMV-IP-2683` demuestra que la abstención `HUMAN_RELATION_REQUIRED`
  funciona como se diseñó (ADR-013).

## 7. Next phase

- El HOLDOUT queda **gastado como evidencia** (`SPENT_EVIDENCE`):
  prohibido remediar el parser y re-ejecutar estos 15 seeds — los
  convertiría en DEV.
- La corrección `precio de suscripción → issue_price_per_share` en la
  fuente Portfolio, la desambiguación por etiqueta de los 3 ISIN y la
  revisión visual/OCR de los escaneados van a una fase nueva con
  **holdout virgen nuevo** (G1-R2 o el gate que se defina).
- Backlog: `g1r/results/post-holdout-findings.jsonl`
  (`AMOUNT_ROLE_MISBINDING` P0, `ISIN_ROLE_DISAMBIGUATION` P2,
  `SCANNED_PDF_NO_TEXT_LAYER` P1_PENDING) + `backlog_p1_p2` heredado.
- `docs/gates/g1r-preregistered.json` permanece intacto
  (`DRAFT_PENDING_APPROVAL`); la aprobación queda documentada por el
  tag `g1r-protocol` y el veredicto firmado.

---

## Artifacts (evidencia congelada)

```text
g1r/state.json                                    estado final (holdout ADJUDICATED / FAIL)
g1r/results/holdout-run-{1,2}-a6a0674-results.json (+ .sha256)   runs virgenes
g1r/results/holdout-verdict-proposal.json         proposal (ADJUDICATED_REJECTED_AS_PASS)
g1r/results/holdout-verdict.json                  veredicto firmado FAIL
g1r/results/post-holdout-findings.jsonl           findings para la fase siguiente
g1r/results/g1r-changes.jsonl                     iters 1-5
g1r/results/dev-iter-5-*-eval.json                oracles congelados (56/56)
g1r/adjudication/holdout-{seed,missingness,instrument}-review.jsonl + holdout-text/
g1r/manifests/holdout-adjudication-sha256.json    integridad del paquete revisado
docs/gates/g1r-preregistered.json                 protocolo (intacto)
```

Tags: `g1r-protocol` (`f9ee8f8`) · `g1r-semantic-freeze` ·
`g1r-parser-freeze` (`a6a0674`)
