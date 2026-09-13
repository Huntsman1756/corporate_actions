# ADR-003 — Assertions vs canonical facts

Status: ACCEPTED (G0 freeze, 2026-09-13)

## Context

Un documento afirma hechos; la "verdad" operativa es una reconciliación.
Colapsarlos pierde provenance y oculta conflictos.

## Decision

Separación estricta:

```
SOURCE DOCUMENT -> ASSERTION -> (reconciliación) -> FACT
```

- Un `Fact` solo procede de `SOURCE_ASSERTION`,
  `DETERMINISTIC_DERIVATION` o `REFERENCE_ENRICHMENT`.
- Todo fact conserva `source_document_id`, `evidence_locator`,
  `raw_pointer` y `evidence_mode`.
- Si dos fuentes discrepan, ambos facts se conservan con
  `evidence_mode=CONFLICTING` y se emite un `Conflict`. Nunca hay
  override silencioso.

Gates: `FIELD_PROVENANCE_COMPLETE`, `CONFLICTS_EXPLICIT`,
`NO_SILENT_SOURCE_OVERRIDE`, `DERIVED_FACTS_LABELED`.
