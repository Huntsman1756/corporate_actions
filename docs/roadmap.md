# Roadmap de producto — Corporate Actions Operations Workbench

Post-G3 (ciclo de gates G0–G3 cerrado). El canon
`CA_ES_OPERATIONAL_CANON_V1` y la superficie `CA_ES_OPERATIONAL_SURFACE_V1`
están probados; a partir de aquí el proyecto crece verticalmente en
valor operativo, no horizontalmente en parsers ni en gates.

```text
CNMV / BME / BORME / Portfolio
             │
             ▼
      ca-es canonical core       ← PROBADO (G2)
             │
     ┌───────┼───────────┐
     ▼       ▼           ▼
 Ops Desk  Entitlements  Messaging
 / Brief   / Recon       MT / MX  (seev.*)
     │       │
     ▼       ▼
 Deadlines  Exceptions
 Evidence   Expected vs actual
 Conflicts  Payment / instruction
```

## Regla build vs adopt

Si una pieza genérica existe madura en OSS, se integra; ca-es solo
construye la lógica diferencial española, la provenance y el workflow
operacional. Sin reinventar piezas básicas.

## Adopciones OSS decididas

| Pieza | Proyecto | Decisión |
|---|---|---|
| Cockpit operativo | Textual | ADOPT |
| Web/API instantáneo del canon | Datasette + SQLite | ADOPT |
| SWIFT MT564/565/566/567/568 | Prowide Core | ADOPT (adapter, no generador propio) |
| ISO 20022 seev.* | Prowide ISO20022 | ADOPT (adapter) |
| Cálculos CA / TERP / ajustes | vn-corporate-actions (MIT) | PORT selectivo de fórmulas + tests; Decimal-only, nunca float |
| Reconciliación cash entitlement | corp_action_recon_cash (MIT) | REFERENCIA + ampliar |
| Lifecycle financiero | FINOS CDM | REFERENCE / mapping, sin dependencia runtime |
| ISIN validation | python-stdnum | ADOPT como utility de validación (no fuente de identidad) |
| Calendarios/deadlines | pandas_market_calendars | ADOPT como utility, no fuente autoritativa |
| Lineage externo | OpenLineage | LATER / adapter |
| Desktop financiero | FDC3 | LATER / interop |
| Diseño de CA desk | CA Alpha Dashboard | BENCHMARK de producto (dataset sintético; nuestro diferencial = canon evidence-first) |

## Fases

```text
P1  Ops Desk
    P1.0 morning brief (ca-es brief --as-of ...)        DONE
    P1.1 snapshot delta (--previous-canon,             DONE
         NEW/CHANGED/REMOVED_*, conflictos, UNSUPPORTED)
    P1.2 Textual Ops Desk (ca-es desk, read-only        DONE
         sobre brief(); extra `desk`)                    — P1 CLOSED
    deadline queue

P2  Entitlements
    P2.0 cash dividend entitlement                      DONE
         (ca-es entitlement --event <id> --positions p.json
          CA_ES_POSITIONS_V1 / CA_ES_ENTITLEMENT_V1;
          POSITION_AT_RECORD_DATE; INDETERMINATE nunca estima)
    split / stock dividend / rights issue
    Decimal-only; fórmulas portadas y testeadas desde vn-corporate-actions

P3  Reconciliation / Exceptions
    expected entitlement vs actual cash
    MATCH / EXCEPTION / MISSING; CSV in/out
    ca-es reconcile --event <id> --positions p.csv --actual c.csv

P4  SWIFT / ISO adapters
    Prowide MT564/565/566/567/568
    Prowide seev.031 / seev.* (ISO 20022)
    adapter ca-es -> Prowide, no parser SWIFT propio

P5  Elections / deadlines
    business-day awareness via pandas_market_calendars
    ACTION_REQUIRED status por días restantes

P6  Positions / impact

P7  Automation / alerts
    OpenLineage adapter, FDC3 interop
```

## Prioridad actual

P1 → P2 → P3 → P4. Cada fase se implementa con tests; sin nuevos gates
formales (G4+ no existen).
