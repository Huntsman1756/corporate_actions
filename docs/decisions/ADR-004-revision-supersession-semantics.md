# ADR-004 — Revision/supersession semantics

Status: ACCEPTED (G0 freeze, 2026-09-13)

## Context

BORME, CNMV, IR y venues publican documentos paralelos sobre la misma
operación. No todo documento nuevo es una revisión.

## Decision

- Documentos que solo `SUPPORTS`/`SUPPLEMENTS` el mismo evento no crean
  revisión.
- Solo `SUPERSEDES` / `EXPLICIT_PREDECESSOR_REFERENCE` crean una nueva
  generación.
- La generación es la longitud del camino más largo desde una raíz en el
  DAG de supersession (independiente del orden de ingestión).
- `revision_id = UUIDv5(..., canonical_event_id + ":gen:" + generation)`.
- La cadena de enmiendas queda explícita (`supersedes_revision_id`) con
  evidencia.

Caso canario: Almirall 2026 V1 (55 derechos/acción nueva) → V2
(65), misma corporate action, dos revisiones, supersession explícita.

Gates: `EXPLICIT_SUPERSESSION_PROVEN`, `AMENDMENT_CHAIN_PROVEN`,
`NO_DOCUMENT_EQUALS_REVISION_ASSUMPTION`.
