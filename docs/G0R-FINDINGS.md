# G0-R — Real source validation: hallazgos

Fecha: 2026-09-13. Verdict: **G0-R INCONCLUSIVE** (no fallo; validación
parcial con evidencia real).

## Cierre por gate

| Gate | Estado | Evidencia |
|------|--------|-----------|
| R1 canonical persistente | PASS | ADR-012; 5 tests |
| R2 Almirall CNMV real | INCONCLUSIVE | parser PDF real OK; sin corrección/supersesión real |
| R3 Parlem BORME real | PASS | `BORME-C-2026-4914` |
| R4 P3 Portfolio real | NOT_RUN | Portfolio HTTP 500 |
| R5 SAN dual real | NOT_RUN | falta pareja IR real |
| R6 FIRDS real | PASS | 173 listings reales |
| R7 cobertura CNMV P3 | PASS | resultado NOT_PROVEN |
| R8 second-run desde raw | PASS | determinista con PDFs reales |

## Lo que se demostró con documentos reales

1. **Parlem / BORME-C-2026-4914** (`SHA-256 94c6571d…`): rights issue con
   ratio real **20:39**, precio **0,80 EUR** (lexema raw, escala 2),
   entitlement basis temporal (`as_of 2026-08-31`), `ISSUER_CSD=IBERCLEAR`,
   `TRADING_VENUE="BME Growth"` y **cero fechas ex/record/payment
   inventadas**.
2. **ESMA/FIRDS** (`esma_registers_firds`): 173 listings reales para SAN,
   Almirall, P3 y Parlem. Point-in-time: P3 → `POSE` en 2026 y
   `GROW`/`LEUE` en 2021; SAN multi-venue con `XMAD`; `segment_mic`
   preservado (GROW con operating POSE).
3. **Almirall / CNMV PDF** (`CNMV-IP-1884/1885`): parser PDF real,
   importe **199.999.992,6** (Decimal exacto, escala 1), 24.390.243
   acciones, clustering por `EXACT_OFFICIAL_CROSS_REFERENCE` y **conflicto
   de fecha explícito** entre las dos comunicaciones.
4. **Determinismo**: `run_pipeline` sobre el corpus real (BORME + PDFs)
   produce el mismo `result_sha` en dos ejecuciones.

## Hallazgos que cambian decisiones

- El fixture sintético de Parlem divergía de la realidad (ratio 2 vs 20:39;
  fechas inventadas). Validar con fuente real era necesario.
- **El canario Almirall 2026 (55→65) no existe en el canal CNMV**: el
  último hecho relevante de Almirall es de 2023. El evento real disponible
  es un aumento de capital con exclusión de preferentes (ABB), no una
  corrección de ratio. `EXPLICIT_SUPERSESSION` sobre datos reales de
  Almirall queda `NOT_PROVEN`.
- **CNMV no cubre P3** por las consultas realizadas (OIR por LEI y por
  denominación → 0). Resultado `NOT_PROVEN`; no se afirma inexistencia.
- **Portfolio Stock Exchange devuelve HTTP 500**; R4 queda bloqueado sin
  documento.
- `venue_name` ("BME Growth") no se convierte en MIC; el `segment_mic`
  (`GROW`) lo aporta FIRDS por separado.

## Qué falta para cerrar G0-R

1. Documento real de P3 (Portfolio cuando esté disponible, o canal del
   emisor / archivo web) y su parser.
2. Pareja CNMV + IR real para SAN y su reconciliación.
3. Un caso real de corrección/supersesión (el Almirall 2026 no existe;
   buscar otro emisor con rectificación publicada).
4. Enriquecer el pipeline real con el `ListingResolver` FIRDS una vez los
   eventos reales tengan ISIN (Almirall/P3/SAN lo tienen; el BORME de
   Parlem no publica ISIN).

## Decisión

`G0 ENGINEERING CORE` = **PASS** (55/55 gates).
`G0 REAL-DATA VALIDATION` = **PARCIAL / INCONCLUSIVE**.
`NEXT` = completar R2/R4/R5 con documentos reales; **NO** pasar a G1.
