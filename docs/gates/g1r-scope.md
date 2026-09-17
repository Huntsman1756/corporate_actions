# G1-R — Extraction Safety & Generalization (remediation)

Status: **DRAFT — PENDING APPROVAL, NOT YET TAGGED** (2026-09-14).
El tag `g1r-protocol` solo se crea tras aprobación humana del diff final.
Parent: G1 cerrado en FAIL — `docs/gates/g1-closure-report.md`
(`b1b79c1`, rama `g1-audit-review`). Parser congelado de referencia:
`c431830 / g1-parser-freeze`.

## Pregunta de G1-R

> ¿Puede `ca-es` eliminar los false financial facts y los errores de
> atribución observados en G1 y **mantener** ese comportamiento en un
> nuevo holdout virgen — **sin comprar la seguridad por abstención**?

G1 demostró feasibility (G0) y falsó generalización (G1). G1-R es la
remediación de **seguridad de extracción**, no una fase de cobertura.

## Catálogo empírico de fallos (especificación del problema)

Fuente: `g1/results/post-freeze-findings.jsonl` (30 findings).

```
FALSE FACTS / P0 — hard-fail si aparece UNA vez en holdout
  DECIMAL_SPLIT_PDF          "0. 53 euros"->53 ; "0, 47 euros"->47
  WRONG_VALUE                nominal de accion (0,01) promovido a dividendo
  WRONG_ATTRIBUTION          755M del buyback asignado al dividendo
  WRONG_EVENT_TYPE           fusion clasificada CASH_DIVIDEND
  DATE_MISBINDING            fecha de anuncio previsto capturada como ex_date
  FALSE_POSITIVE_EVENT       event_type emitido sobre un seed NOT_CA

MISSED FACTS / P1 — medidos, sujetos al NON_DEGRADATION_GUARD
  LABEL_VARIANT / UNLABELED_DATE / EURO_SYMBOL_FORMAT
  MAGNITUDE_ANCHOR_GAP / RATIO_NOT_EXTRACTED
  BOUND_AMOUNT_NOT_MAPPED / LEXEME_VARIANT_EVENT_TYPE

LIMITACIONES DE FUENTE — no son bugs
  REGISTRY_ARTIFACT_NO_LEXEME / INSTRUMENT_BINDING_ABSENT
```

## Prioridades

```
P0  false_financial_facts    -> 0   (hard-fail)
P0  wrong_attribution        -> 0   (hard-fail)
P0  wrong_event_type         -> 0   (hard-fail)
P0  date_misbinding          -> 0   (hard-fail)
P0  false_positive_event     -> 0   (hard-fail)
P1  published-but-missed     -> mejorar, SIN empeorar el baseline
P2  instrument resolution    -> subir, manteniendo ADR-013
P3  discovery recall         -> FUERA DE SCOPE (fase posterior propia)
```

**Seguridad antes que cobertura, pero no seguridad-por-abstención.**

## Guards anti-abstención (la debilidad principal del draft v1)

Un parser que devuelva `UNKNOWN` casi siempre obtendría todos los
P0=0. Por tanto se congela un hard gate separado:

```
NON_DEGRADATION_GUARD (hard-fail en holdout virgen)

  baseline G1 = 23 / 60   (fraccion exacta, no decimal redondeado)

  PASS iff:   missing * 60 <= published * 23

  display:    parser_miss_rate <= 38,33 %   (solo presentacion)

equivalentemente:

  correct_published_critical_fact_recall >= 37/60   (fraccion exacta)
```

El umbral se compara como **racional** — `0.3833` jamás entra en la
comparación, así que un parser que iguale exactamente el baseline G1
pasa el guard. P1 sigue teniendo como objetivo mejorar el 38,33 %, pero
**no se permite empeorar** para conseguir seguridad.

## Cobertura de revisión P0

G1 cayó por valores **poblados pero incorrectos**, que el missingness
clásico no veía. Por tanto, demostrar P0=0 exige revisar contra fuente
el 100 % de los facts emitidos relevantes para P0:

```
p0_relevant_emitted_facts =
  event_type + fechas de evento + amounts + ratios + currencies
  + cualquier otro fact financiero emitido

p0_review_coverage =
  reviewed_p0_relevant_emitted_facts / p0_relevant_emitted_facts

PASS requires = 1.0
```

Las anotaciones humanas pueden registrar el valor esperado y la
evidencia como **evaluation oracle**; nunca entran como facts del
producto (`human_fact_entry = FORBIDDEN` sigue intacto).

### Semántica de ejes ortogonales

`FALSE_FINANCIAL_FACT` **no** es un estado alternativo a `MISSING`:
son ejes ortogonales. Un `53` donde correspondía `0,53` es
simultáneamente `MISSING` para completeness y `FALSE_FINANCIAL_FACT`
para safety — exactamente como se adjudicó en G1.

`false_positive_event`: un seed adjudicado `NOT_CA` con `event_type`
emitido (p. ej. `CASH_DIVIDEND`) es hard-fail propio; no encaja en
ninguno de los otros cuatro P0.

## Corpus — tres conjuntos, roles distintos

```
G1 SEALED (25)     -> REGRESSION ONLY. Nunca evidencia de generalización.
G1-R DEV (25)      -> documentos nuevos para desarrollar las clases P0.
G1-R HOLDOUT (15)  -> virgen, sellado ANTES de tocar el parser.
```

### Frame y muestreo (algoritmo congelado, literal de G1)

```
parent_frame = g1/manifests/sampling-frame.json
sha256       = edc785ebbe007ad5eec000edc06abaff15b2c674698c27e726cc41253dc94188
```

Se reutiliza el **frame G1 congelado** (mismo universo temporal; sin
frame drift). Algoritmo:

```
1. eliminar del frame los 150 frame_item_id de
   g1r/manifests/excluded-g1-frame-items.json
   (DEV+HOLDOUT+ADVERSARIAL+NO_MATCH de G1;
    excluded_ids_sha256 = 74f216cda7d4de32d841386a1d99e6aefcad3bc33ac1a01b62ef2b42bbaad2b3)
   antes de cualquier hash
2. sample_score = SHA256("CA_ES_G1R_SAMPLE_V1" + stratum + frame_item_id)
3. ordenar por score y tomar 20 MAIN / 10 BMEG / 10 PORTFOLIO
4. dedup misma CA + backfill por orden de score (misma regla que G1;
   ver pre_split_dedup)
5. split_score = SHA256("CA_ES_G1R_SPLIT_V1" + frame_item_id)
6. ordenar los 40 por split_score; los 15 primeros -> HOLDOUT
7. los 25 restantes -> DEV
```

El dedup del paso 4 ocurre **antes** del split, así que está sujeto a la
misma restricción de sellado que el holdout:

```
pre_split_dedup:
  automated_only: true
  manual_document_inspection: false
  permitted_evidence:
    - structured source identifiers
    - exact official cross-references
    - already-frozen metadata
```

Si no puede determinarse automáticamente que dos seeds son la misma CA,
**ambos permanecen**: preferible un duplicado documentado que contaminar
un futuro holdout inspeccionando su contenido.

Sellado del holdout:

```
holdout_content_sealed_until = G1R_PARSER_FREEZE
no_manual_holdout_inspection = true
```

Los documentos pueden adquirirse automáticamente para fijar
`content_sha256` antes del desarrollo, pero nadie abre su contenido ni
deriva estadísticas de él antes del parser freeze.

### Sin promesa de cobertura de clases

Un muestreo hash sin cuotas de familia **no** garantiza cubrir todas las
clases P0. Un PASS será evidencia direccional, no prueba de tasa cero
verdadera: `0/n` errores con n pequeño deja un límite Wilson 95 % alto
(p. ej. `0/15` eventos → ~20 %). El informe G1-R reportará `n`
(oportunidades), errores, tasa e IC95 **por evento y por fact**.

## Regression oracle (congelado)

`g1r/manifests/g1-regression-oracle.json`
(`oracle_sha256 = 6c300cbb34c1052209b3e99c462c8b0331cfde73780c5e76be035ed5c6f55725`):

```
49 known_correct_critical_fields   (37 HOLDOUT + 12 ADVERSARIAL)
   required = REMAIN_CORRECT
   expected_claims: claims semanticos ejecutables por campo
     (p. ej. date.ex_date: "2026-07-08",
            amount.gross_per_share: {normalized: "0.08690661",
                                     currency: "EUR"})
   -> todos los expected_claims deben seguir emitidos y
      semanticamente iguales; se permiten claims adicionales,
      siempre sujetos a p0_review

7  known_p0_incorrect_fields
   required = CORRECT_OR_ABSTAIN
   forbidden_claims: los valores erroneos observados en G1
   allowed_outcomes: ABSENT o un claim-set semánticamente
     correcto definido (p. ej. gross_per_share 0,53 EUR)
   -> ningun forbidden_claim se emite; el claim-set del campo
      es vacio o igual a un allowed_outcome
```

Los valores se extrajeron re-ejecutando `c431830` sobre los manifests
sellados (mismos raw bytes), así que cada uno de los 49 registros es
ejecutable — el comparador sabe exactamente qué valor debe preservar.
“No empeorar” es una comparación mecánica contra oracle con sha256, no
una frase interpretable.

## Determinismo — definición congelada

```
RUN 1 + RUN 2 sobre:
  el MISMO commit/worktree exacto
    parser_commit RUN1 == parser_commit RUN2
    parser_commit_dirty = false
  mismo g1r-parser-freeze
  mismos raw bytes (content_sha256 fijado en manifest)
  mismo entorno
  sin cambios de código ni config entre runs
  ANTES de la adjudicación humana

comparar:
  canonical facts, statuses, relations, conflicts, result_sha

ignorar SOLO (metadata volátil preregistrada):
  executed_at, run_id,
  timestamps de adquisición ya fijados en manifest
```

`parser_commit` **no** es ignorable: como las dos corridas salen del
mismo commit exacto, debe ser idéntico en ambas — no repetimos la
ambigüedad de procedencia de G1.

`second_run_determinism = 1.0` se exige de verdad esta vez — en G1
quedó `NOT_PROVEN` para los sellados. La reproducibilidad de
re-adquisición de raws es otra métrica y no se confunde con el
determinismo del parser.

## Cambios de código — solo reglas genéricas

Prohibido condicionar comportamiento a `frame_item_id`, issuer,
URL, hash o documento concreto. Cada entrada de
`g1r/results/g1r-changes.jsonl` exige:

```
generic_rule: true
trigger_failure_class
root_cause
tests_added
commit
```

## Secuencia de ejecución (congelada)

```
1. aprobación humana de este protocolo -> tag g1r-protocol
2. construir los 40 seeds y sellar los 15 HOLDOUT (misma operación)
3. run baseline de c431830 sobre los 25 DEV
   -> congelar baseline results (evita medir "first run" después)
4. solo entonces modificar src/
5. desarrollar en DEV; cada cambio -> g1r-changes.jsonl
6. regression set (25 sealed) tras cada iteración; diff vs oracle
7. freeze parser -> tag g1r-parser-freeze
8. ejecutar HOLDOUT virgen + segunda pasada (determinism)
9. adjudicación humana: p0_review_coverage=1.0 + missingness;
   PROPOSED hasta firma
10. veredicto G1-R
```

## Invariantes heredados (hard-fail)

```
field_provenance_rate      = 1.0
silent_conflicts           = 0
unproven_auto_merges       = 0
human_authored_facts       = 0   (relaciones adjudicables, facts no)
second_run_determinism     = 1.0
```

`human_authored_facts` cubre cualquier business fact, no solo
financieros: la arquitectura permite adjudicar relaciones, no inventar
facts.

## P2 y ADR-013

La mejora de instrument resolution **no** puede relajar identidad:
name-only nunca se convierte automáticamente en binding canónico
(ADR-013). P2 se mide; nunca a costa de `unproven_auto_merges`.

## Out of scope

- discovery recall / FN del negative control (fase propia posterior).
- expansión de producto, fuentes nuevas, generación ISO.
- reescribir el veredicto G1 (FAIL permanente).

## Veredicto G1-R

```
PASS requiere, en el HOLDOUT VIRGEN:

  false_financial_facts   = 0
  wrong_attribution       = 0
  wrong_event_type        = 0
  date_misbinding         = 0
  false_positive_event    = 0
  p0_review_coverage      = 1.0
  parser_miss_rate        <= 23/60          (NON_DEGRADATION_GUARD)
  + invariantes heredados + determinism 1.0

Y en el regression oracle:

  49 correctos siguen correctos
  7 incorrectos dejan de emitirse incorrectamente
```

`source_completeness` se mide y reporta vs baseline (77,92 %) sin ser
hard-fail. `instrument_resolved` se mide (P2). Todo lo demás
(`observed_field_accuracy`, tasas por clase de fallo, IC95) es
reporte, no gate.
