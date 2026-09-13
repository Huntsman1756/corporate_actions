# ADR-014 — G1 sampling preregistration and MISSING vs UNKNOWN

Status: ACCEPTED (G1 protocol freeze, 2026-09-13)

## Context

G0 demostró feasibility con pocos casos profundamente auditados. El riesgo
de G1 ya no es arquitectónico sino de **selection bias**: construir
"40 casos que sabemos que funcionan" no mide nada. G1 debe medir
cobertura, completitud, calidad, latencia e intervención sobre un corpus
no escogido por conveniencia.

## Decision

1. **Preregistrar antes de ingerir**: marco de muestreo, ventana temporal,
   estratos, familias, split dev/holdout, criterios duros y catálogo de
   métricas se congelan **antes** de descargar el primer documento de G1
   (`docs/gates/g1-preregistered.json`).
2. **Muestreo determinista** por calendario/registro oficial en la ventana,
   ordenado por identificador oficial. Sin selección por conveniencia.
3. **No forzar cuotas** de tipos que no aparezcan: la ausencia es un
   resultado de cobertura.
4. **Holdout congelado** antes de tocar parsers; todo cambio sobre holdout
   conserva `first_run_result`, `final_run_result`, `reason_for_change`.
5. **Canarios G0 excluidos** de las métricas G1 (son regression fixtures).

## `MISSING` ≠ `UNKNOWN`

```
UNKNOWN  la fuente se proceso; el dato no estaba publicado  (fuente)
MISSING  el pipeline no extrajo/resolvio algo publicado      (ca-es)
```

Se modelan por separado para saber si el fallo es de la fuente o del
sistema. `missing_rate` es una métrica de calidad de ca-es;
`unknown_rate` mide lo que las fuentes no publican.

## Intervención humana

- `human_relation_adjudication`: permitido, auditable, se mide.
- `human_fact_entry`: prohibido (ADR-002/003).
- `manual_adjudication_rate` es una métrica operativa de primer orden: el
  modelo puede ser correcto y aun así no escalar.

## Criterios duros

G1 FAIL si `field_provenance_rate < 1.0` o hay conflictos silenciados,
merges no probados, facts financieros de origen humano, pérdida de
precisión financiera o determinismo < 1.0. Las métricas de cobertura y
completitud se miden primero; sus umbrales no se preregistran.
