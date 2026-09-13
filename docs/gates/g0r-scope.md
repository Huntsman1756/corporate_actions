# G0-R — REAL SOURCE VALIDATION (scope cerrado)

Status: OPEN (iniciado 2026-09-13). Sustituye a G1 como siguiente fase.

## Pregunta

> ¿Sobreviven las propiedades de G0 (identidad estable, provenance,
> Decimal, temporalidad, determinismo) cuando dejamos de controlar los
> fixtures y usamos documentos públicos reales?

## Scope

```
R1  Persist canonical identity                       [DONE]
R2  Real CNMV parser        → Almirall
R3  Real BORME parser       → Parlem
R4  Real Portfolio parser   → P3
R5  Real issuer/CNMV dual   → SAN
R6  Real ESMA_FIRDS_LISTINGS_V1 adapter
R7  Resolve CNMV_CHANNEL_COVERAGE_P3
R8  Full second-run from raw sources
```

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
