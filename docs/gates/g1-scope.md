# G1 — Coverage, completeness, operational usefulness

Status: **PROTOCOL FROZEN before ingestion** (2026-09-13).
Parent: G0 cerrado en `4931593 / g0r3`.

## Pregunta de G1

> ¿Qué porcentaje del universo real de corporate actions podemos
> descubrir, reconstruir y mantener con calidad suficiente para ser útil
> operacionalmente, y a qué coste en intervención y latencia?

G0 respondió *¿podemos hacerlo?* (feasibility). G1 responde *¿con qué
frecuencia, con cuánta información y a qué coste?*.

## Ventana temporal (fijada antes de mirar resultados)

```
2025-01-01 → 2026-09-13
```

Se puede acortar la ventana para controlar volumen, pero **no** se amplía
selectivamente por conveniencia.

## Marco de muestreo y estratos (objetivo 40–50)

```
20  mercado principal / emisores grandes
10  BME Growth / MTF
10  Portfolio Stock Exchange
10  adversariales / otros casos públicos
```

Reglas:

- Selección por **regla determinista** (calendario oficial / registros de
  la ventana, ordenados por identificador oficial), nunca por conveniencia.
- **No se fuerzan cuotas** de tipos ni de estrato que no aparezcan. Si no
  hay casos suficientes, eso **es** un resultado de cobertura.

## Familias mínimas

```
CASH_DIVIDEND
SCRIP_DIVIDEND / RIGHTS_ISSUE
CAPITAL_INCREASE
CAPITAL_REDUCTION
SPLIT / REVERSE_SPLIT        si aparece en la ventana
MERGER / TENDER / REDEMPTION si aparece en la ventana
```

## Dev / holdout

```
G1 corpus = 50  (o 40-50)
  35 development
  15 holdout
```

- El holdout se **congela antes** de ajustar parsers a los documentos.
- Si aparece un fallo en holdout, se puede corregir, pero se conserva:
  `first_run_result`, `final_run_result`, `reason_for_change`.
- Los canarios G0 (MFE, Santander, Parlem, P3) son **regression fixtures**,
  excluidos de las métricas de G1.

## `UNKNOWN` ≠ `MISSING`

Distinción obligatoria:

```
UNKNOWN
  la fuente se proceso correctamente,
  pero el dato no estaba publicado        -> limitacion de la fuente

MISSING
  el pipeline no consiguio extraer/resolver
  algo que SI estaba publicado            -> bug de ca-es
```

Esto separa "el problema es la fuente" de "el problema somos nosotros".

## Intervención humana

```
human_relation_adjudication  ALLOWED   (solo relaciones, auditable)
human_fact_entry             FORBIDDEN
```

Métrica obligatoria:

```
manual_adjudication_rate = manual_adjudications / events
```

Si G1 necesita intervención en ~40 % de las corporate actions, el modelo
puede seguir siendo correcto pero el producto **no** escala
operacionalmente. Eso debe quedar visible.

## Criterios duros (G1 FAIL si alguno)

```
field_provenance_rate        < 1.0
silent_conflicts             > 0
unproven_auto_merges         > 0
human_authored_financial_facts > 0
financial_precision_loss     > 0
second_run_determinism       != 1.0
```

Las métricas de cobertura y completitud **se miden primero y se decide
después**: G1 debe descubrir qué ofrecen las fuentes, no validar umbrales
inventados.

## Métricas G1

Ver `docs/gates/g1-preregistered.json` (máquina-legible). Categorías:

```
DISCOVERY        events_discovered, events_ingested, source_document_retrieval_rate
IDENTITY         issuer_identity_exact_rate, instrument_identity_exact_rate,
                 event_identity_resolved_rate, manual_adjudication_rate
FACT COMPLETENESS event_type_rate, ex_date_rate, record_date_rate,
                 payment_date_rate, amount_or_ratio_rate, currency_rate
QUALITY          field_provenance_rate, unknown_rate, missing_rate,
                 conflict_rate, revision_detection_rate, unresolved_identity_rate
REFERENCE DATA   isin_binding_rate, lei_resolution_rate, mic_resolution_rate,
                 point_in_time_mic_rate
OPERATIONS       publication_lag, source_to_canonical_latency
REPRODUCIBILITY  second_run_determinism, raw_retrieval_reproducibility
```

## Disciplina de ejecución

1. Congelar este protocolo (este commit / tag).
2. Construir el marco de muestreo determinista.
3. Ingerir dev (35) sin tocar holdout.
4. Ajustar parsers solo con dev; registrar cambios.
5. Ejecutar holdout (15) en frío; conservar first/final/reason.
6. Informar métricas por estrato y globales; declarar cobertura y huecos.
7. G1 no se declara PASS por "los tests pasan", sino por las métricas.

## Addendum 2026-09-14 — fuentes del frame y muestreo (cerrado)

Decisión tomada **antes** de generar el manifiesto; no se reabre tras la
construcción del frame. El SHA-256 del frame es el nuevo punto de
congelación de G1. Versión máquina-legible:
`docs/gates/g1-sampling-preregistered.json`.

### Fuentes por estrato

```
MAIN_MARKET      CNMV OIR ∪ CNMV Información Privilegiada
BME_GROWTH_MTF   Tabla oficial "Operaciones financieras" de BME Growth
                 (fuente declarada: emisora; raw LOCAL_ONLY por licencia BME)
PORTFOLIO        Índice oficial de productos → documentos de cada producto
ADVERSARIAL      Registro purposive separado (sin frame probabilístico);
                 nunca entra en tasas globales
```

**Benchmark externo (no forma parte del frame):** BME Exchange Corporate
Actions (SIBE) sirve para medir la captura del MAIN_FRAME:

```
bme_reference_events_matched_in_cnmv_frame / bme_reference_events_eligible
```

Limitación registrada: BME Exchange solo publica ~último año (splits
~último mes). `bme_reference_events_eligible` queda acotado a lo que la
fuente sirve en la fecha de adquisición.

### Unidad de muestreo

El frame contiene **seeds de documento/noticia oficial**, no corporate
actions: la identidad del evento la resuelve el propio pipeline
(`seed → event candidate → corporate action`). No se usa la salida del
sistema para construir su evaluación.

### Selección y split deterministas

```
sample_score = SHA256("CA_ES_G1_SAMPLE_V1" + stratum + frame_item_id)
→ sort(sample_score) → take N por estrato

split_score  = SHA256("CA_ES_G1_SPLIT_V1" + frame_item_id)
→ sort sobre los seleccionados → primeros 15 = HOLDOUT
```

Los canarios G0 se excluyen **antes** del hashing y quedan en
`excluded-known-cases.json` con motivo `G0_REGRESSION_FIXTURE`.

Deduplicación post-selección: si dos seeds resultan ser la misma CA por
evidencia determinista → conservar el de mejor `sample_score`, rellenar
con el siguiente del frame, registrar la operación. Nada a dedo.

### UNKNOWN vs MISSING — procedimiento

`g1/adjudication/missingness-review.jsonl`: para cada campo crítico
aplicable no poblado, revisión humana del documento fuente:

```
PUBLISHED     + pipeline vacío → MISSING   (bug de ca-es)
NOT_PUBLISHED                  → UNKNOWN   (límite de la fuente)
AMBIGUOUS                      → UNKNOWN / SOURCE_AMBIGUOUS
```

El revisor determina solo si el dato estaba publicado; **nunca introduce
el valor**. `human_fact_entry` sigue FORBIDDEN.

### Denominadores y reporte

`g1/manifests/metric-applicability.json` fija, por `family × field`:
`APPLICABLE | NOT_APPLICABLE | CONDITIONAL`. Las tasas se calculan solo
sobre el universo aplicable. Reporte obligatorio `n/N`, rate, Wilson 95 %
CI. Con N≈10 por estrato, las estimaciones son **direccionales, no
poblacionales**.

### Controles pre-DEV (ADR-015)

- `g1/manifests/frame-reconciliation.json`: cada registro enumerado queda
  contabilizado; la build falla si la invariancia no cierra a cero.
- `g1/adjudication/no-match-audit.jsonl`: muestra determinista de 100
  `NO_RULE_MATCH` para auditar falsos negativos de elegibilidad.
- Adversarial en tres clases (`PRESELECTED_ADVERSARIAL`,
  `KNOWN_PRE_G1`, `DISCOVERED_ADVERSARIAL`); solo la primera cuenta como
  evaluación G1.
- **Sellados hasta PARSER_FREEZE**: los 15 HOLDOUT y los 10
  `PRESELECTED_ADVERSARIAL`. Prohibido inspeccionar su contenido
  documental antes del parser freeze.
- Ejecución en tres fases: baseline (mismo parser commit, 25/25) →
  desarrollo (solo fixes genéricos, registrados) → DEV final. Detalle en
  ADR-015 §4.
- Por cada DEV se conservan `first_run_result` y `final_run_result`.
- Capa documental: `pypdf` → `pdfplumber` (extra) → Docling (solo
  diagnóstico); HTML: adapter actual → `selectolax` si hace falta. Sin
  PyMuPDF (AGPL).
