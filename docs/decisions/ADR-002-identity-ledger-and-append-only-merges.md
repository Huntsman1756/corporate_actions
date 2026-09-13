# ADR-002 — Identity ledger and append-only merges

Status: ACCEPTED (G0 freeze, 2026-09-13)

## Context

Dos documentos pueden describir la misma corporate action. La fusión de
identidades no puede ser probabilística ni destructiva.

## Decision

- Solo fusionan relaciones `SAME_CORPORATE_ACTION`.
- El ledger es append-only: nunca elimina ni reescribe candidatos.
- El canonical de un componente es el menor `candidate_event_id`
  (orden lexicográfico), función determinista del conjunto de inputs.
- En ausencia de evidencia suficiente, cada candidato es su propio
  canonical (`DEFAULT_SPLIT_ON_UNPROVEN_IDENTITY`).
- Las referencias antiguas resuelven siempre (a un canonical, que puede
  cambiar si entra un id menor en el componente).

## Evidencia que autoriza clustering automático

`EXPLICIT_PREDECESSOR_REFERENCE`, `EXACT_EXTERNAL_EVENT_ID`,
`EXACT_OFFICIAL_CROSS_REFERENCE`. Se añade `SUPERSEDES` porque implica una
referencia explícita al predecesor. Nunca same issuer + same type + fechas
aproximadas.

Gates: `MERGE_APPEND_ONLY`, `NO_UNPROVEN_AUTO_MERGE`,
`EVENT_REFERENCE_PERMANENTLY_RESOLVABLE`, `CROSS_SOURCE_EVENT_LINK_PROVEN`.

## Human adjudication

Una adjudicación humana solo puede escribir relaciones (`SAME_`,
`DISTINCT_`, `RELATED_CORPORATE_ACTION`) con `reviewer` y `reviewed_at`.
El loader rechaza cualquier campo financiero.
