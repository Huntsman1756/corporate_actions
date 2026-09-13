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
