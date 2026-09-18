# P8.6 — Integración de familias de valores en el DAG P7

## Scope

Conectar la cadena P8 (terms → securities entitlement → position
impact → security recon → P3.5 cases) al runtime P7 como step
`securities_events`, alimentado por los facts MT564/MT566 que
`process_inbox` ya persiste en `inbox_messages`.

## Diseño

Step impuro (lee `inbox_messages` mutable), opcional, después de
`process_inbox`:

```
inbox_messages PROCESSED ──> artifact_refs ──> facts docs
        │ pasada 1: MT566
        ▼
security_movement_candidate (BOUND/NO_MATCH) ──> artifacts
        │ pasada 2: MT564 (solo familias soportadas)
        ▼
project_ca_message ──> bind_event ──> build_event_terms
        ──> compute_securities_entitlements(elections)
        ──> compute_security_impact
        ──> reconcile_security_movements(candidates BOUND)
        ──> build_cases_doc(previous=último run OK)
        ▼
CA_ES_OPS_INDEX_V1 kind=CA_ES_SECURITIES_EVENT_V1
```

- Dos pasadas: MT566 primero (los candidatos existen antes de que el
  recon los consuma, independientemente del orden de llegada).
- Solo `binding_status == BOUND` entra como actual; NO_MATCH se
  persiste como candidate pero no reconcilia (fail-closed).
- `elections`: input opcional del config
  `{canonical_event_id: {account_id: qty|"CASH"|"SECU"}}` —
  explícito, nunca DFLT.
- Casos mergeados con los del último run exitoso por evento
  (`_previous_security_cases`), conservando `first_seen_at`.
- `alert_outbox` deriva `EXCEPTION_CASE` también de los casos de
  valores.
- Inbox sin mensajes de valores → index con `items` vacío
  (SUCCEEDED); canon/positions ausentes → `None` → BLOCKED
  (consistente con `entitlements`).

## Fuera de scope

- Proyección de posiciones dentro del DAG (impact queda persistido
  como artefacto; `projected_positions` sigue siendo operación de
  superficie).
- MX/seev.036: el boundary JVM ya emite facts MX idénticos; el step
  consume `CA_ES_SWIFT_MT_FACTS_V1` indistintamente del transporte.

## Tests

`tests/unit/test_p86_dag_securities.py` — 5 tests:
step presente y SUCCEEDED sin inbox; cadena SPLF completa
(terms PROVEN → entitlement 12500→125000 → impact DELIVERY+RECEIPT
→ recon MISSING → 2 casos); MT566 NO_MATCH persistido sin romper
recon; casos → alertas EXCEPTION_CASE; merge de casos entre runs
sin duplicar.
