# P13.1–P13.4 — position observation & snapshots

```text
CA_ES_SWIFT_MT_FACTS_V1 (MT535)
CA_ES_SWIFT_MX_FACTS_V1 (semt.002.001.12 / .002.11)
        │
        ▼
CA_ES_POSITION_OBSERVATION_V1     ← transport facts, sin semantica de dominio
        │
        ▼  agrupa por (account_id_raw, statement_reference), prueba completitud
CA_ES_POSITION_SNAPSHOT_V1        ← COMPLETE / PARTIAL / INDETERMINATE / CONFLICTING
        │
        ▼  account_map explicito (profile) — nunca inferido
CA_ES_POSITIONS_V1                ← el contrato existente, intocado
```

`CA_ES_POSITION_OBSERVATION_V1` NO sustituye a `CA_ES_POSITIONS_V1`:
preserva lo que el mensaje prueba (statement ref, paginación,
balances con qualifier) antes de cualquier mapping.

## Contrato de observación

```json
{
 "schema": "CA_ES_POSITION_OBSERVATION_V1",
 "source_standard": "ISO15022|ISO20022",
 "source_message_identifier": "MT535|semt.002.001.12",
 "input_sha256": "...",
 "statement_reference": "SEME o StmtId",
 "statement_as_of": "YYYY-MM-DD",
 "account_id_raw": "id verbatim del servicer",
 "pagination": {"page": 1, "continuation": "ONLY|MORE|LAST|null",
                "last_page": true|false|null,
                "update_type": "COMP|DELT|null"},
 "positions": [{
   "instrument_index": 0,
   "isin": "ES…|null",
   "balances": [{"qualifier": "AGGR|AVAI|BLOK|…",
                 "availability_type": "…",
                 "quantity_type": "UNIT|FAMT|AMOR",
                 "quantity_raw": "12500,", "quantity": "12500"}],
   "quantity": "canonica = AGGR unico, nunca agregada",
   "quantity_type": "UNIT",
   "availability": {"AVAI": "…", "BLOK": "…"},
   "reasons": []}],
 "parse_status": "OK|UNSUPPORTED|PARSE_ERROR",
 "reasons": []
}
```

## Mapping MT535 (SRU2025, via Prowide facts)

| semantica | campo | notas |
|---|---|---|
| statement ref | `20C::SEME` GENL | |
| as_of | `98A::STAT` GENL (98C datetime como fallback) | |
| cuenta | `97A::SAFE` GENL | verbatim → `account_id_raw` |
| paginación | `28E` page + continuation (`ONLY`/`MORE`/`LAST`) | |
| actividad | `17B::ACTI` | N + sin seq B → EMPTY_STATEMENT |
| instrumento | `35B` ISIN en seq `SUBSAFE/FIN`, occurrence=N | description preservada, nunca identidad |
| balances | `93B/C` qualifiers en `SUBSAFE/FIN/SUBBAL`, occurrence=N | occurrence enlaza con `35B[N]` |
| cantidad | componente `balance` de 93B | decimal SWIFT `,` normalizado a Decimal |
| quantity type | componente `quantity type code` | `UNIT`/`FAMT`/`AMOR` |

## Mapping semt.002 (.001.12 / .002.11)

| semantica | elemento | notas |
|---|---|---|
| statement ref | `StmtGnlDtls/StmtId` | |
| as_of | `StmtGnlDtls/StmtDtTm/Dt|DtTm` | |
| cuenta | `SfkpgAcct/Id` | |
| paginación | `Pgntn/PgNb` + `Pgntn/LastPgInd` | |
| update type | `StmtGnlDtls/UpdTp/Cd` | `COMP` completo / `DELT` delta → nunca COMPLETE |
| instrumento | `BalForAcct[k]/FinInstrmId/ISIN` | k via `evidence_locator` indexado |
| cantidad | `BalForAcct[k]/AggtBal/Qty/Qty/Qty/Unit|FaceAmt|AmtsdVal` | → `AGGR` balance |
| disponible | `BalForAcct[k]/AvlblBal/Qty/Qty/Unit` | → `AVAI` |
| no disponible | `BalForAcct[k]/NotAvlblBal/Qty/…` | → `NAVAI` |

## Completitud de statement

Decidida en `custody_snapshot.completeness` por evidencia:

- `COMPLETE`: página única `ONLY`/`LAST`, o páginas `1..N` contiguas
  con `LAST` presente; semt.002 exige `UpdTp=COMP` + `LastPgInd`.
- `PARTIAL`: falta una página (`MISSING_PAGES`), no hay página LAST,
  o `UpdTp=DELT` (statement delta — nunca snapshot completo).
- `INDETERMINATE`: sin marcador terminal, sin `Pgntn`, o páginas
  con contenido conflictivo (`CONFLICTING_PAGE_CONTENT`).
- `CONFLICTING_POSITION_SNAPSHOTS`: dos statements COMPLETE para el
  mismo `(account, as_of)` con posiciones distintas — fail-closed,
  ninguno gana. Mismo contenido con refs distintas NO es conflicto
  (`DUPLICATE_STATEMENT_AGREEING`).

Páginas duplicadas por entrega (mismo número, mismo contenido,
bytes distintos o transporte distinto) se colapsan conservando
todos los `input_sha256` en `pages`/`source_refs`.

## Snapshot identity

`snapshot_id = PSNAP-<semantic_sha256(account, ref, as_of,
positions)>[:16]`. Replay idéntico → mismo id. Cada snapshot se
persiste como artifact content-addressed; los statements
anteriores nunca se mutan.

## Proyección a CA_ES_POSITIONS_V1

Solo snapshots `COMPLETE`. `account_map` explícito del profile;
cuentas sin mapping → `_skipped_accounts`, posiciones sin ISIN o
sin cantidad → `_dropped_positions` con reason. Orden determinista
(account, isin). Nada de ticker/nombre/aggregación.
