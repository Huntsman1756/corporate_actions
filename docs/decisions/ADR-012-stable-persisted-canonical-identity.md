# ADR-012 — Stable persisted canonical identity

Status: ACCEPTED (G0-R, 2026-09-13). Supersede la selección de canonical
de ADR-002.

## Context

En G0 el canonical de un componente era el menor `candidate_event_id`,
recalculado en cada run. El alias antiguo seguía resolviendo, pero el
`canonical_event_id` podía **cambiar** si más tarde entraba un candidato
con id menor. Para un producto operativo eso no es aceptable: "canonical"
debe ser históricamente estable.

## Decision

```text
candidate_id        determinista + inmutable
canonical_event_id  determinista en la creación + persistente
aliases             append-only
```

Reglas:

1. Se procesan las relaciones `SAME_CORPORATE_ACTION` en orden de ledger
   (append-only). Al crear un componente, si ambos lados son nuevos se
   elige el menor id; a partir de ahí queda **fijado**.
2. Si un lado ya tiene canonical (por un merge anterior o un binding
   persistido), **gana el canonical establecido**, con independencia de
   que el candidato entrante tenga un id menor.
3. El canonical resuelto se persiste en el identity ledger como
   `canonical_bindings` (candidate → canonical). Los bindings persistidos
   se aplican primero y son inmutables.
4. Caso canónico:

```text
A SAME_CA B         → canonical A
llega 0000 (< A)
0000 SAME_CA A      → 0000 → A   (NO cambia a 0000)
```

## Consequences

- `canonical_event_id` es estable frente a nuevos candidatos.
- La resolución depende del orden del ledger (parte de los inputs
  autoritativos), no del orden de ingestión de los documentos.
- La PERTENENCIA al componente sigue siendo independiente del orden.
- Reproducibilidad: mismos inputs (raw, config, ledger, adjudicación) →
  mismo canonical.

Gates: `CANONICAL_ID_DETERMINISTIC` (G0) + `CANONICAL_ID_STABLE` (G0-R).
