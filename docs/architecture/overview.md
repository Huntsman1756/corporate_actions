# Arquitectura — ca-es G0

## Principio central

Separación estricta de conceptos, ninguno colapsable:

```
SOURCE DOCUMENT
EVENT ASSERTION
EVENT CANDIDATE
CORPORATE ACTION IDENTITY
EVENT REVISION
FACT
RELATION
REFERENCE ENRICHMENT
```

## Modelo conceptual

```
ISSUER
  └── INSTRUMENT
         ├── REFERENCE DATA   (LEI, ISIN, segment MIC)   ← capa ESMA
         └── CORPORATE ACTION
                ├── source documents
                ├── assertions
                ├── identity relations
                ├── revisions
                ├── related events
                └── canonical operational view (facts + conflicts)
```

## Módulos

| Módulo | Responsabilidad |
|--------|-----------------|
| `canonical` | serialización/hashing determinista (`CA_ES_CANONICAL_JSON_V1`) |
| `numeric` | `FinancialAmount` (Decimal + raw_lexeme + escala) |
| `vocab` | estados y relaciones controladas |
| `namespaces` | UUIDv5 estables (documento, candidato, assertion, revisión) |
| `source_policy` | rol, raw_storage, redistribución por fuente |
| `sources.documents` | source documents inmutables + verificación SHA-256 |
| `sources.parsers` | doc → claims (sin decidir verdad) |
| `assertions` | claims → assertions con provenance |
| `identity` | candidate IDs, ledger append-only, resolución canónica |
| `revisions` | DAG de supersession → generaciones/revisiones |
| `temporal` | restricciones scoped; sin orden global |
| `entitlement` | entitlement basis como assertion temporal |
| `provenance` | facts, conflictos explícitos, facts derivados |
| `reference` | `ListingResolver` + adapter ESMA/FIRDS |
| `semantics` | mapping FIBO/ISO explícito (UNMAPPED permitido) |
| `iso_boundary` | límite core ↔ `iso-adapter-jvm` (Prowide) |
| `pipeline` | orquesta el run determinista |
| `metrics` | mide cobertura real sin ocultar fallos |
| `gates` | evalúa los gates preregistrados |
| `cli` | `run`, `second-run`, `gates`, `metrics`, `event`, `isin` |

## Flujo determinista

1. `load_and_parse`: verifica SHA-256 y parsea.
2. `build_identity`: relaciones deterministas + adjudicaciones → ledger →
   resolución canónica (menor `candidate_event_id`).
3. `build_revisions`: generaciones por supersession.
4. `build_event_views`: facts por revisión + enriquecimiento FIRDS
   point-in-time + conflictos.
5. `result_sha = sha256(body)` excluye `executed_at`/`run_id`.

## Límites

- ca-es **no** posee FIRDS; consume `ListingResolver`.
- ca-es **no** genera ISO; el adapter JVM está fuera del core.
- ca-es **no** ingiere Iberclear (`REFERENCE_ONLY`).
