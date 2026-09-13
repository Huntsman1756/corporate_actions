# ADR-001 — Event identity and candidate IDs

Status: ACCEPTED (G0 freeze, 2026-09-13)

## Context

El primer documento ingerido no debe definir la identidad del evento:
el orden de ingestión no es una propiedad del hecho financiero y puede
cambiar entre runs.

## Decision

Cada documento origina una identidad inmutable:

```
candidate_event_id = UUIDv5(CA_ES_CANDIDATE_NAMESPACE, source_id + ":" + official_document_id)
```

`candidate_event_id` es determinista, append-only e independiente del
orden de ingestión. Nunca se deriva de fecha, importe, ratio, ticker ni
nombre normalizado. La identidad canónica se resuelve aparte (ADR-002).

## Consequences

- Reordenar la ingesta no cambia ninguna identidad.
- Una corrección de importe no cambia la identidad del candidato.
- `source_document_id` y `candidate_event_id` usan namespaces distintos.

Gates: `SOURCE_DOCUMENT_ID_STABLE`, `CANDIDATE_ID_IMMUTABLE`,
`CANONICAL_ID_DETERMINISTIC`.
