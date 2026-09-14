# G1-R — Extraction Safety & Generalization (remediation)

Status: **PROTOCOL FROZEN before any parser change** (2026-09-14).
Parent: G1 cerrado en FAIL — `docs/gates/g1-closure-report.md`
(`b1b79c1`, rama `g1-audit-review`). Parser congelado de referencia:
`c431830 / g1-parser-freeze`.

## Pregunta de G1-R

> ¿Puede `ca-es` eliminar los false financial facts y los errores de
> atribución observados en G1 y **mantener** ese comportamiento en un
> nuevo holdout virgen?

G1 demostró feasibility (G0) y falsó generalización (G1). G1-R no es
una fase de cobertura: es la remediación de **seguridad de extracción**.

## Lo que G1 falsó — catálogo empírico de fallos

Fuente: `g1/results/post-freeze-findings.jsonl` (30 findings).
Este catálogo es la especificación del problema, no una lista
hipotética:

```
FALSE FACTS (P0)
  DECIMAL_SPLIT_PDF          "0. 53 euros"->53 ; "0, 47 euros"->47
  WRONG_VALUE                nominal de accion (0,01) promovido a dividendo
  WRONG_ATTRIBUTION          755M del buyback asignado al dividendo
  WRONG_EVENT_TYPE           fusion clasificada CASH_DIVIDEND
  DATE_MISBINDING            fecha de anuncio previsto capturada como ex_date

MISSED FACTS (P1)
  LABEL_VARIANT              "Fecha ex date", "Fecha Ex-Date", "ex -date"
  UNLABELED_DATE             "a satisfacer en efectivo el", "con fecha de efectos"
  EURO_SYMBOL_FORMAT         "EUR 0,15", "100.000 EUR"
  MAGNITUDE_ANCHOR_GAP       "por un importe total de N millones de euros"
  RATIO_NOT_EXTRACTED        "19,916 acciones por cada (1) accion"
  BOUND_AMOUNT_NOT_MAPPED    "hasta 29.678.964,75 EUR" (precio/cotas)
  LEXEME_VARIANT_EVENT_TYPE  "oferta publica voluntaria de adquisicion",
                             avisos de calendario POEX

LIMITACIONES DE FUENTE/ARTEFACTO (no son bugs)
  REGISTRY_ARTIFACT_NO_LEXEME   paginas derechos de voto/capital
  INSTRUMENT_BINDING_ABSENT     ISIN no publicado en el documento
```

## Prioridades (orden estricto)

```
P0  false financial value      -> 0   (hard-fail)
P0  wrong attribution          -> 0   (hard-fail)
P0  wrong event type           -> 0   (hard-fail)
P0  date misbinding            -> 0   (hard-fail)
P1  published-but-missed facts -> bajar (medido, sin umbral duro)
P2  instrument resolution      -> subir (medido)
P3  discovery recall           -> FUERA DE SCOPE (fase posterior propia)
```

**Seguridad antes que cobertura.** Un `53 EUR` donde la fuente decía
`0,53 EUR` es peor que un `UNKNOWN`. El `11 %` de FN del negative
control NO se aborda en G1-R.

## Dirección arquitectónica (a evaluar en DEV, no preregistrada como diseño)

El cambio de fondo que G1-R debe explorar:

```
ANTES (G1):     text -> regex -> canonical fact

G1-R:           document
                -> evidence spans / blocks
                -> candidate facts
                -> semantic attribution + validation
                -> canonical facts
```

Principio: ningún fact financiero se emite sin (a) evidencia textual
acotada al enunciado del evento, (b) validación de consistencia
(rango, unidad, rol semántico del importe), (c) atribución demostrada
al evento correcto. La capa exacta la decide el desarrollo; lo que se
congela es el **criterio de aceptación**, no la implementación.

## Corpus — tres conjuntos, roles distintos

```
G1 SEALED (25)     -> REGRESSION ONLY
                      sirven para verificar que la remediación corrige
                      los fallos conocidos; NUNCA cuentan como evidencia
                      de generalización

G1-R DEV           -> documentos NUEVOS para desarrollar las clases
                      de fallo del catálogo

G1-R HOLDOUT       -> completamente virgen, congelado ANTES de tocar
                      el parser; es la única evidencia de generalización
```

Reglas de muestreo G1-R (deterministas, mismo esquema que G1):

```
sample_score = SHA256("CA_ES_G1R_SAMPLE_V1" + stratum + frame_item_id)
split_score  = SHA256("CA_ES_G1R_SPLIT_V1"  + frame_item_id)
```

- Mismos estratos que G1 (MAIN_MARKET, BME_GROWTH_MTF, PORTFOLIO).
- **Excluidos de la selección**: todos los `frame_item_id` ya usados en
  el corpus G1 (DEV, HOLDOUT, ADVERSARIAL, NO_MATCH).
- Tamaños objetivo: **25 DEV + 15 HOLDOUT** (suficiente para cubrir las
  clases P0 con margen).
- Sin cuotas forzadas de familia; la composición es lo que es.
- Set adversarial: opcional, misma mecánica `PRESELECTED_ADVERSARIAL`;
  si se usa, reportado separado, nunca combinado.

## Veredicto G1-R

```
G1-R PASS requiere, EN EL HOLDOUT VIRGEN:

  false_financial_facts   = 0
  wrong_attribution       = 0
  wrong_event_type        = 0
  date_misbinding         = 0

Y además (invariantes heredados, se miden de verdad):

  field_provenance_rate   = 1.0
  silent_conflicts        = 0
  unproven_auto_merges    = 0
  human_authored_facts    = 0
  second_run_determinism  = 1.0   <- esta vez SE EJECUTA el re-run

Y en el regression set (25 sellados G1):

  los fallos P0 conocidos quedan corregidos o reclasificados
  documentalmente; no se permite empeorar lo que ya era correcto
  (regression guard sobre los 37 campos correctos).
```

`parser_miss_rate` y `source_completeness` se **miden** en el holdout
virgen y se reportan contra el baseline G1 (38,33 % / 77,92 %); no son
hard-fail en G1-R porque la prioridad congelada es seguridad.

## Disciplina de ejecución

1. Congelar este protocolo + `g1r-preregistered.json` (commit/tag
   `g1r-protocol`) **antes** de modificar `src/`.
2. Construir G1-R DEV y congelar G1-R HOLDOUT en la misma operación.
3. Desarrollar la capa de extracción/atribución en DEV; cada cambio
   queda en `g1r/results/g1r-changes.jsonl` con `reason_for_change`.
4. Ejecutar el regression set (25 sellados) tras cada iteración;
   publicar diff de facts.
5. Al congelar el parser G1-R: tag `g1r-parser-freeze`, ejecutar
   holdout virgen + segunda pasada completa (determinism).
6. Adjudicación humana: mismas reglas que G1 — veredictos,
   missingness, `PROPOSED` hasta firma.
7. `human_fact_entry` sigue FORBIDDEN.
8. El FAIL de G1 no se reescribe nunca; G1-R produce su propio
   veredicto.
