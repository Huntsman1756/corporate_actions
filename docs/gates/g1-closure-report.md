# G1 Closure Report — Corporate Actions ES

**G1 VERDICT: FAIL**

Binding cause: `financial_precision_loss > 0`.

Dos casos HOLDOUT produjeron importes financieros silenciosamente
erróneos por `DECIMAL_SPLIT_PDF`: `0. 53 euros` → `53` (CNMV-OIR-38190,
Amadeus) y `0, 47 euros` → `47` (CNMV-OIR-41467, CIE). El criterio estaba
preregistrado antes de abrir HOLDOUT (`docs/gates/g1-scope.md`). No se
aceptó ninguna remediación antes del veredicto y este FAIL es permanente:
una eventual remediación G1-R no lo reescribe.

Fecha de cierre: 2026-09-14. Rama de auditoría: `g1-audit-review`
(último commit de adjudicación: `9f8fe5c`).

---

## 1. Scope y freeze

| Elemento | Valor |
|---|---|
| G0 parent | `4931593` / tag `g0r3` (CERRADO) |
| G1 protocol | tag `g1-protocol`, `docs/gates/g1-scope.md` + `g1-sampling-preregistered.json` |
| DEV baseline | tag `g1-dev-baseline` |
| Parser freeze | `c431830de42acef3d108525edb575ed83be4fc13` (tag `g1-parser-freeze`) |
| `src/` tras apertura de sellados | **sin modificar** — diff vacío vs `c431830` |
| Ventana de muestreo | 2025-01-01 → 2026-09-13 |
| Corpus | 25 DEV + 15 HOLDOUT + 10 ADVERSARIAL + 100 NO_MATCH |
| ADVERSARIAL | `PRESELECTED_ADVERSARIAL`, **nunca combinado** con tasas globales |

Los sellados se ejecutaron en la misma corrida sobre `src/` byte-idéntico
a `c431830`. Los resultados registran `parser_commit=1ac372e` (HEAD del
runner `--set`, commit de infraestructura); `src/` es idéntico al freeze —
documentado en `post-freeze-findings.jsonl` (`PROVENANCE_NOTE`).

## 2. Sampling / discovery

- Frame construido determinísticamente
  (`sample_score = SHA256("CA_ES_G1_SAMPLE_V1" + stratum + frame_item_id)`),
  split DEV/HOLDOUT congelado antes de desarrollo del parser.
- **DEV frame precision: 22/25 = 88 %** (3 `NOT_CA` confirmados: M&A de
  la compañía sin efecto sobre su instrumento).
- **Negative control (100 `NO_MATCH`, adjudicación humana con lectura
  documental): 11 `ACTUAL_CA` / 89 `NOT_CA`.**
- **`false_negative_rate = 11/100 = 11,0 %`, Wilson 95 % [6,3 %, 18,6 %]**
  (strict = possible; 0 `AMBIGUOUS` tras revisión documental).
- Alcance: FN del *frame de descubrimiento* frente al alcance
  operacional amplio de G1 — no "11 % de dividendos perdidos". Los misses
  concentran CAs enterradas en resoluciones de junta, colocaciones
  aceleradas cuyo título no dice "aumento de capital", contraprestaciones
  en acciones nuevas, admisiones/listings y ajustes derivados de CA.
- **Conclusión: el filtrado por título/categoría no es suficiente como
  discovery layer.**

## 3. DEV (25 seeds) — referencia, no medida de generalización

- 22 `ACTUAL_CA` + 3 `NOT_CA`, todos CONFIRMED.
- Campos críticos sobre `ACTUAL_CA`: 97 published/populated, 0 MISSING,
  18 UNKNOWN, 15 N/A, 1 AMBIGUOUS.
- `parser_miss_rate = 0/97 = 0 %`
- `source_completeness = 97/116 = 83,62 %`
- `source_completeness_resolved = 97/115 = 84,35 %`
- Clean-run probado sobre `c431830` limpio: `parser_commit_dirty=false`,
  batch `8ea825031f71ba15…`, diffs por seed = solo el campo `parser_commit`.

**DEV se usó para desarrollar el parser; su 0 % no mide generalización.**
Era el diseño del experimento.

## 4. HOLDOUT (15 seeds) — resultado principal

- Veredictos: **15/15 `ACTUAL_CA`** (CONFIRMED).
- Pipeline: 15/15 retrieved · parsed · event_detected · **0 excepciones**.
- Funnel: `critical_facts_extracted` 10/15 · `instrument_resolved` 7/15
  (el funnel no es la métrica; los denominadores vienen de la
  adjudicación).

Missingness sobre los 6 campos críticos (`event_type`, `ex_date`,
`record_date`, `payment_date`, `amount_or_ratio`, `currency`):

| Clase | Campos |
|---|---:|
| published (correctly populated + MISSING) | 60 |
| correctly populated | 37 |
| **MISSING** (publicado, no correctamente extraído) | **23** |
| UNKNOWN (aplicable, no publicado) | 16 |
| NOT_APPLICABLE | 13 |
| AMBIGUOUS | 1 |

- **`parser_miss_rate = 23/60 = 38,33 %`**
- `source_completeness = 60/77 = 77,92 %`
- `source_completeness_resolved = 60/76 = 78,95 %`

## 5. False extractions en HOLDOUT — el finding más peligroso

Separadas de `MISSING`: son facts emitidos con provenance perfecta y
valor erróneo. Operacionalmente peores que `UNKNOWN`.

| Seed | Campo | Publicado | Emitido | Clase |
|---|---|---|---|---|
| CNMV-OIR-38190 Amadeus | `amount_or_ratio` | `0. 53 euros` | `53` | `DECIMAL_SPLIT_PDF` |
| CNMV-OIR-41467 CIE | `amount_or_ratio` | `0, 47 euros` | `47` | `DECIMAL_SPLIT_PDF` |
| CNMV-IP-2594 Sabadell | `amount_or_ratio` | `12,44 céntimos` | `755 M€` del programa de recompra | `WRONG_ATTRIBUTION` |
| CNMV-OIR-36680 Árima | `event_type` | fusión por absorción | `CASH_DIVIDEND` | `WRONG_EVENT_TYPE` |

Diagnóstico post-freeze (**no es gate preregistrado**):

```text
observed_field_accuracy HOLDOUT = 37/41 = 90,24 %
```

Todos los campos incorrectos están también contabilizados como
`MISSING` (publicado y no correctamente extraído) en la revisión.

## 6. ADVERSARIAL (10 seeds) — reportado separado

Veredictos tras corrección firmada:

- **9 `ACTUAL_CA` · 1 `NOT_CA`** — el `NOT_CA` es **CNMV-OIR-33825
  Bankinter** (fusión intragrupo de filiales integrales: sin canje ni
  efecto sobre holders).
- `CNMV-OIR-42668` Azkoyen = `ACTUAL_CA` / `REGISTRATION` (modificación
  sustancial del objeto social con derecho de separación a 9,38 €/acc;
  evento fuera de las 10 familias canónicas → `event_type` AMBIGUOUS).
- `selection_class` + `adversarial_criteria` preservados por seed.

| Métrica | Valor |
|---|---|
| published / populated / MISSING / UNKNOWN / N/A / AMBIG | 21 / 12 / 9 / 13 / 15 / 3 |
| `parser_miss_rate` | **9/21 = 42,86 %** |
| `source_completeness` | 21/37 = 56,76 % |
| `source_completeness_resolved` | 21/34 = 61,76 % |
| `observed_field_accuracy` (diagnóstico) | 12/15 = 80,00 % |
| `instrument_resolved` | **0/10** |

El 0/10 de resolución de instrumento **no demuestra por sí solo un fallo
del resolver**: varios documentos no publican ISIN (páginas de registro,
OPAs con términos pendientes) o el instrumento afectado es de un tercero
(AEDAS en 37252). Queda como finding para evaluación G1-R.

Relación criterio→fallo: los `MISSING` adversariales no se concentran en
el criterio hostil de selección; son las mismas clases genéricas vistas
en HOLDOUT (formato `€`, ancla de magnitud, variante de lexema).

## 7. Hard-fail table (preregistrada)

| Hard criterion | Resultado | Estado |
|---|---:|---|
| `field_provenance_rate < 1.0` | 130/130 facts con `evidence_locator`/`raw_pointer` → 1.0 | **PASS** |
| `silent_conflicts > 0` | 0 (1 `Conflict` explícito registrado: ISINs clase A/B de Grifols) | **PASS** |
| `unproven_auto_merges > 0` | 0 (identity UNRESOLVED en todos los seeds; sin merges) | **PASS** |
| `human_authored_financial_facts > 0` | 0 | **PASS** |
| `financial_precision_loss > 0` | **2** (`DECIMAL_SPLIT_PDF` 38190, 41467) | **FAIL — BINDING** |
| `second_run_determinism != 1.0` | HOLDOUT+ADVERSARIAL ejecutados una sola pasada | **NOT_PROVEN** |

`raw_retrieval_reproducibility`: 25/25 raws re-descargados con
`content_sha256` idéntico al manifest sellado → demostrado.
`second_run_determinism` queda `NOT_PROVEN` para los sellados: el
clean-run de DEV demostró determinismo sobre esa población, que es
distinta. No se convierte en PASS por analogía.

## 8. Interpretación técnica

```text
G0: architecture / source feasibility — PROVEN
G1: current deterministic extraction strategy
    does NOT generalize with operational safety — FALSIFIED
```

Tres findings distintos, sin mezclar:

```text
DISCOVERY   11 % FN en negative control (frame de título/categoría)
SOURCE      ~78 % completeness en HOLDOUT (lo que las fuentes publican)
PARSER      38,33 % miss rate + false extractions silenciosas
```

El contraste DEV→HOLDOUT (`0 % → 38,33 %` miss, `0 → 4` false
extractions en 15 seeds) indica sobreajuste del extractor a los seeds
de desarrollo, no un defecto del modelo canónico ni de la disciplina
evidence-first: la provenance se mantuvo 1.0 y los errores son
detectables exactamente porque cada fact cita su evidencia.

## 9. Qué NO concluye G1

- No demuestra que las fuentes públicas sean inviables (completeness
  ~78 % es un suelo útil).
- No invalida la arquitectura identity/provenance/revision — al
  contrario: permitió auditar cada fallo hasta el lexema fuente.
- No demuestra que `ListingResolver` sea el problema (0/10 adversarial
  es mayormente ausencia de ISIN en el documento).
- No demuestra que un enfoque determinista sea imposible.
- **Sí demuestra que este parser congelado (`c431830`) y su atribución
  de contexto actual no son aptos para uso operativo.**

## 10. Next phase — G1-R: Extraction Safety & Generalization

Objetivo acotado, seguridad antes que cobertura:

```text
false financial facts → 0   (DECIMAL_SPLIT_PDF, nominal→dividendo)
wrong attribution       → 0   (importes ajenos al enunciado del evento)
wrong event type        → 0   (prioridad de lexemas estructurales)
then reduce MISSING         (label variants, € format, magnitude anchors,
                             canje ratios, bound amounts, OPA lexemes)
```

Restricciones metodológicas:

- Los 25 sellados pasan a ser **regression set conocido**, nunca nuevo
  holdout.
- G1-R requiere un **nuevo holdout virgen** para demostrar que no se
  vuelve a sobreajustar.
- `post-freeze-findings.jsonl` (30 findings) es el backlog semilla de
  G1-R; ninguno modifica el resultado G1.

---

## Artifacts (evidencia congelada)

```text
g1/manifests/                    sampling-frame, dev-holdout, adversarial-registry,
                                 eligibility-rules, metric-applicability, no-match lists
g1/adjudication/seed-verdicts.jsonl                    DEV 25 CONFIRMED
g1/adjudication/missingness-review.jsonl               DEV 52 CONFIRMED
g1/adjudication/no-match-audit.jsonl                   100 CONFIRMED
g1/adjudication/holdout-seed-verdicts.jsonl            15 CONFIRMED
g1/adjudication/holdout-missingness-review.jsonl       53 CONFIRMED
g1/adjudication/adversarial-seed-verdicts.jsonl        10 CONFIRMED
g1/adjudication/adversarial-missingness-review.jsonl   46 (verificado mecánicamente)
g1/results/first-run-results.json / final-run-results.json   DEV
g1/results/holdout-results.json / adversarial-results.json   sellados
g1/results/dev-changes.jsonl                           7 cambios DEV con commit refs
g1/results/post-freeze-findings.jsonl                  30 findings G1-R backlog
g1/results/sealed-field-accuracy.json                  diagnóstico (no gate)
```

Tags: `g0r3` · `g1-protocol` · `g1-dev-baseline` ·
`g1-parser-freeze` (= `c431830`) · `g1-parser-freeze-candidate-2`
