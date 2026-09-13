# ADR-009 — FIBO semantic alignment

Status: ACCEPTED (G0 freeze, 2026-09-13)

## Context

Antes de inventar una taxonomía propia conviene reutilizar semántica
existente (EDM Council FIBO CAE, Open Investment Model). Pero una
referencia semántica no es autoridad factual.

## Decision

- FIBO se usa como referencia semántica, **nunca** como autoridad de
  hechos.
- La release se fija: `FIBO_RELEASE_PIN = FIBO-2024Q4`.
- Cada `event_type` declara un mapping explícito y versionado en
  `semantics.py`.
- Cuando no hay extracto de estándar verificado, `mapping_status =
  UNMAPPED`. G0 deliberadamente no certifica equivalencias FIBO/ISO.
- Nunca se fuerza una equivalencia (`NO_FORCED_ISO_MAPPING`).

Gates: `FIBO_RELEASE_PINNED`, `EVENT_TYPE_FIBO_MAPPING_EXPLICIT`,
`UNMAPPED_SEMANTICS_ALLOWED`, `NO_FORCED_ISO_MAPPING`.

## Open Investment Model

Se usa como referencia de alineación conceptual operativa; no introduce
runtime en G0.
