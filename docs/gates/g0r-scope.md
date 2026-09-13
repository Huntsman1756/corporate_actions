# G0-R — REAL SOURCE VALIDATION (scope cerrado)

Status: OPEN (iniciado 2026-09-13). Sustituye a G1 como siguiente fase.

## Pregunta

> ¿Sobreviven las propiedades de G0 (identidad estable, provenance,
> Decimal, temporalidad, determinismo) cuando dejamos de controlar los
> fixtures y usamos documentos públicos reales?

## Scope

```
R1  Persist canonical identity                       [PASS]
R2  Real CNMV parser        → Almirall               [INCONCLUSIVE: sin correccion real]
R3  Real BORME parser       → Parlem                 [PASS]
R4  Real Portfolio parser   → P3                     [BLOCKED: Portfolio HTTP 500]
R5  Real issuer/CNMV dual   → SAN                    [BLOCKED: falta pareja IR]
R6  Real ESMA_FIRDS_LISTINGS_V1 adapter              [PASS]
R7  Resolve CNMV_CHANNEL_COVERAGE_P3                 [PASS: NOT_PROVEN]
R8  Full second-run from raw sources                 [PASS en corpus real disponible]
```

Detalle de resultados y hallazgos: `docs/G0R-FINDINGS.md`.

## Hallazgo de R3 (validación real)

`BORME-C-2026-4914` real adquirido (`https://www.boe.es/buscar/doc.php?id=BORME-C-2026-4914`,
SHA-256 `94c6571d50a97785990411abf2fbe2e84ab9c157089caf188d25ed7ac48fce4e`,
LOCAL_ONLY). El parser real (`borme_html`) extrae, contra el documento:

- `RIGHTS_ISSUE` (aumento de capital con derecho de suscripción preferente)
- `ratio.terms = {new_shares: 20, old_shares: 39}` (enteros exactos)
- `amount.issue_price_per_share = 0,80 EUR` (lexema raw, escala 2, sin float)
- nominal 0,01; prima 0,79; nominal máx 99.375,00; prima máx 7.850.625,00
- `entitlement_basis` con `asserted_as_of=2026-08-31`: elegibles 19.378.125;
  componentes registradas 19.865.753, autocartera 209.745, renuncia 277.883
- `ISSUER_CSD=IBERCLEAR` (registro contable explícito)
- `TRADING_VENUE="BME Growth"` (venue name; el `segment_mic` es de ESMA/FIRDS)

**Divergencia detectada frente al fixture sintético:** el fixture G0 usaba
ratio `2` y fechas inventadas. El documento real usa 20:39 y **no publica
fechas ex/record/payment explícitas** (periodo relativo a la publicación).
El parser real las deja ausentes: no se inventan fechas. Esto es
exactamente lo que G0-R debía descubrir.

## Criterio de cierre

```
real documents only
4 canaries PASS
raw SHA-256 reproducible
0 human-authored facts
0 silent conflicts
0 unproven merges
canonical IDs stable after new candidates
LEI/ISIN/MIC from actual FIRDS evidence
second-run deterministic
55/55 gates resolved
```

## Reglas

- Los originales permanecen `LOCAL_ONLY`; en Git solo van manifest,
  URL/identificador oficial, SHA-256, metadata de adquisición y
  expectativas permitidas (ADR-011).
- No se inventan facts. Si un documento no demuestra un campo, el campo
  es `UNKNOWN`.
- El `venue_name` de una source assertion (p.ej. "BME Growth") no se
  convierte en MIC. El `segment_mic` lo aporta la capa ESMA/FIRDS por
  separado (ADR-006); no se codifican equivalencias a mano.

## Estado R1 (cerrado)

Implementado en `ca_es/identity`:

- `candidate_id`: determinista e inmutable (sin cambios).
- `canonical_event_id`: fijado en la creación y persistido en
  `canonical_bindings`; no cambia por un candidato menor (ADR-012).
- `aliases`: append-only.

Evidencia: tests `test_canonical_stable_after_new_smaller_candidate`,
`test_pinned_binding_is_immutable`, `test_component_membership_is_order_independent`,
`test_canonical_resolution_deterministic_for_same_ledger`,
`test_canonical_bindings_round_trip`.

## Pendiente de corpus real

R2–R8 requieren los documentos reales. Ver
`docs/sources/real-corpus-acquisition.md`.
