# ADR-015 — Controles pre-DEV de G1 y capa documental

Status: ACCEPTED (2026-09-14, antes de abrir el primer DEV)

## Context

El frame G1 (`sampling-frame.json`, sha256 `9a4949…`) ya está congelado.
Antes de ingerir el primer seed DEV se cierran tres controles que evitan
contaminar la evaluación, más la disciplina de ejecución y la política de
la capa documental.

## Decisiones

### 1. Reconciliación mecánica del frame

`g1/manifests/frame-reconciliation.json` (generado por
`scripts/build_g1_frame.py`) contabiliza cada registro enumerado:

```
enumerated
= deduplicated
+ dropped_no_registration
+ dropped_out_of_window
+ dropped_duplicate_id
+ excluded_g0
+ excluded_by_rule
+ eligible
```

La build **falla si la diferencia no es cero**. Resultado actual:

```
enumerated   12.597
deduplicated       1   (duplicado en frontera de chunk mensual CNMV)
out_of_window    152   (docs Portfolio fuera de ventana / items sin fecha)
duplicate_id      28   (misma seed bajo ids equivalentes)
excluded_g0        3   (MFE OIR-40280/40319, POEX-4733; los demás casos G0
                        son de 2023, fuera de ventana)
excluded_rule 10.994   (titulización 2.616, buyback/liquidez 1.833,
                        no-match 6.545)
eligible       1.419
```

Nota de honestidad: 934/474/39 elegibles por estrato demuestra
**capacidad muestral**, no ausencia de gaps de cobertura. El universo
verdadero de corporate actions sigue siendo desconocido.

### 2. Auditoría de falsos negativos (negative control)

`g1/adjudication/no-match-audit.jsonl`: 100 registros `NO_RULE_MATCH`
seleccionados por `SHA256("CA_ES_G1_NEGCTRL_V1" + frame_item_id)`, score
ascendente. Revisión humana posterior clasifica cada uno en
`ACTUAL_CA | NOT_CA | AMBIGUOUS`. El resultado produce
`eligibility_false_negative_rate`: cuántos corporate actions reales
pierde la regla de elegibilidad. **No se rehace el frame a
posteriori**; el sesgo medido se documenta para G1 y se corrige en G2.

### 3. Registro adversarial en tres clases

`g1/manifests/adversarial-registry.json`:

```
PRESELECTED_ADVERSARIAL   criterio detectable por metadata congelada,
                          SHA256("CA_ES_G1_ADV_V1" + id), 10 menores.
                          Cuenta como evaluacion adversarial G1.
KNOWN_PRE_G1              caracteristica conocida pero no detectable por
                          metadata; regression fixture, no observacion.
DISCOVERED_ADVERSARIAL    hallado durante DEV; regression fixture futuro,
                          NO cuenta como evaluacion adversarial.
```

Criterios por metadata: `EXPLICIT_REVISION` (incluye `related` links de
CNMV), `RIGHTS_OR_OPTIONALITY`, `MERGER_OR_EXCHANGE`, `TAKEOVER`,
`CAPITAL_REDUCTION`, `EARLY_REDEMPTION`, `MULTI_VENUE` (emisor presente en
>1 grupo de venue: CNMV / BME Growth / Portfolio). Criterios que exigen
leer el documento (`HIGH_PRECISION_AMOUNT`, `NON_DEFAULT_INFRASTRUCTURE`,
`COMPLEX_ENTITLEMENT`, `MUTABLE_ENTITLEMENT`, `ISIN_CHANGE`) **no** se
preseleccionan a ciegas.

Los casos G0 (MFE, Santander, Parlem, P3, Almirall) siguen siendo
regression fixtures y nunca cuentan como adversariales nuevos.

### 4. Disciplina de ejecución — protocolo en tres fases

`first_run` significa **la misma versión del parser para los 25 DEV**, no
"la primera vez que se vio el documento". Sin baseline común, el orden de
ejecución contamina la métrica (DEV-25 recibe más aprendizaje que DEV-01).

```
FASE A — BASELINE (g1-dev-baseline)
  mismo parser commit para los 25 seeds, sin cambios entre ejecuciones
  → g1/results/first-run-results.json  (hash + commit)
  Mide: zero-shot / baseline generalization.

FASE B — DEVELOPMENT
  inspect failure → diagnose → fix GENERICO → tests → rerun afectados
  Cada fix registrado: trigger_event, failure_class, root_cause, change,
  generic_rule=true, affected_sources, tests_added, commit.
  REGLA DURA: un fix cuya condicion sea el identificador, emisor o
  documento especifico del seed que lo provoco queda RECHAZADO
  (p.ej. `if issuer == "ENDESA"` → FAIL;
   `if table_header_matches(dividend_schema)` → OK).

FASE C — DEV FINAL
  parser freeze candidate → rerun 25/25 → g1/results/final-run-results.json
  Comparacion baseline vs final = cuanto tuvo que adaptarse el sistema.
  → PARSER_FREEZE (tag g1-parser-freeze) → abrir HOLDOUT.
```

- **Sellados hasta PARSER_FREEZE**: los 15 HOLDOUT y los 10
  `PRESELECTED_ADVERSARIAL`. Prohibido abrir o inspeccionar manualmente
  su contenido documental; la metadata del frame sí es visible
  (`dev-holdout.json`: `holdout_content_sealed_until: PARSER_FREEZE`,
  `no_manual_holdout_inspection: true`;
  `adversarial-registry.json`: `sealed_until: PARSER_FREEZE` por entry).
  Si un adversarial se usara para desarrollo pasaria a clase
  `ADVERSARIAL_DEV` y dejaria de contar como evaluacion.
- **Por cada evento DEV** se conservan `first_run_result` y
  `final_run_result`.
- Tras el freeze, **ninguna decisión metodológica nueva** hasta ver los
  resultados DEV.

### 4b. Reporte del negative control

El audit `no-match-audit.jsonl` puede ejecutarse en paralelo a DEV (no
afecta al parser ni al frame). Se reportan dos tasas, ambas con Wilson
95 % CI:

```
strict_false_negative_rate   = ACTUAL_CA / reviewed
possible_false_negative_rate = (ACTUAL_CA + AMBIGUOUS) / reviewed
```

`AMBIGUOUS` nunca se coacciona a positivo ni negativo.

El registro adversarial distingue `unique_cases` de
`criterion_assignments` (un caso puede cumplir varios criterios).

### 5. Capa documental (ingesta)

El core `ca_es` sigue siendo stdlib-only; las librerías de documento son
extras opcionales importados perezosamente:

```
PDF born-digital   pypdf            (ya es extra `pdf`, BSD-3)
        ↓ insuficiente
                   pdfplumber       (extra opcional, MIT; layout/tablas,
                                      evidencia por coordenadas)
        ↓ diagnostico solamente
                   Docling          (differential/diagnostic parser;
                                      nunca parser canonico de G1)

HTML               adapter determinista existente
        ↓ si el DOM se complica
                   selectolax       (extra opcional, MIT/Lexbor Apache-2.0)
```

Se evita PyMuPDF en el core (AGPL). Docling no es parser canónico: una
actualización podría cambiar la extracción de layout aunque el documento
no cambie; se usa solo para diagnosticar fallos de los parsers
deterministas.

## Consecuencias

- El frame es reproducible y contable a cero; cualquier discrepancia
  futura rompe la build.
- La cobertura del frame tendrá una cota de sesgo medida (negative
  control) en lugar de asumida.
- La evaluación adversarial no puede inflarse retrospectivamente.
- first-pass vs final DEV dan dos métricas distintas: generalización y
  cobertura alcanzable.
