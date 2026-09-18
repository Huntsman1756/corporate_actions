# P13.16 — custody feed conformance (cross-transport parity)

Comparación SOLO sobre semántica común probada. Las diferencias
genuinas de cada formato se documentan, nunca se normalizan.

## Posiciones: MT535 ↔ semt.002.001.12 / .002.11

| semantica | MT535 | semt.002 | parity |
|---|---|---|---|
| cuenta | `97A::SAFE` | `SfkpgAcct/Id` | ✔ verbatim raw id |
| statement ref | `20C::SEME` | `StmtGnlDtls/StmtId` | ✔ |
| as_of | `98A/C::STAT` | `StmtGnlDtls/StmtDtTm` | ✔ fecha; MX permite DtTm |
| ISIN | `35B` | `BalForAcct/FinInstrmId/ISIN` | ✔ |
| cantidad | `93B::AGGR` | `BalForAcct/AggtBal` | ✔ Decimal |
| quantity type | componente 93B | `Unit/FaceAmt/AmtsdVal` | ✔ UNIT↔Unit, FAMT↔FaceAmt, AMOR↔AmtsdVal |
| disponible | `93B::AVAI` | `AvlblBal` | ✔ availability |
| bloqueada | `93B::BLOK` | `NotAvlblBal` | parcial — MX tiene subtipos de no-disponibilidad más ricos |
| paginación | `28E` page/ONLY-MORE-LAST | `Pgntn/PgNb`+`LastPgInd` | ✔ completitud |
| delta/completo | — (MT535 siempre snapshot) | `UpdTp/Cd` COMP/DELT | diferencia genuina: DELT nunca es snapshot completo |

`semt.002.002.11` (variante ISO-15022) usa el mismo árbol
`BalForAcct`; se acepta con el mismo mapping — la equivalencia está
demostrada por el modelo, no por normalización.

Test: `test_p13_custody_position.py::test_parity_with_mt535` y
`test_snapshot_semantic_hash_parity` — MT535 y semt.002 con el
mismo contenido producen el mismo semantic hash de posiciones
(`isin, quantity, quantity_type`) tras quitar provenance de
transporte.

## Cash: MT940/950 ↔ camt.053.001.13 / camt.054.001.13

| semantica | MT940/950 | camt.053/054 | parity |
|---|---|---|---|
| cuenta | `25` | `Acct/Id/IBAN|Othr/Id` | ✔ raw id (namespaces distintos: account-id vs IBAN — el mapping es del profile) |
| statement ref | `20` (o `28C` stmt/seq) | `Stmt/Id` / `Ntfctn/Id` | ✔ |
| entry id | 61 `reference for the account owner` | `NtryRef`/`AcctSvcrRef` | ✔ |
| D/C | 61 mark (C/D + RC/RD reversal) | `CdtDbtInd` + `RvslInd` | ✔ reversal explícito en ambos |
| amount | 61 amount `,` decimal | `Amt`+`@Ccy` | ✔ Decimal; ccy MT via 60/62 |
| value date | 61 value date | `ValDt` | ✔ |
| booking date | 61 entry date MMDD → DERIVED (mismo año que value date) | `BookgDt` | parcial — MT no lleva año; DERIVED_BY_DEFINITION documentado |
| status | — (no existe) | `Sts/Cd` BOOK/PDNG/INFO | diferencia genuina: MT no expone booked/pending |
| CA/tx refs | 61 owner/servicer refs; `86` narrativa | `TxDtls/Refs/*` | MT: refs estructuradas en 61; `86` = evidencia verbatim, PROFILE_REQUIRED |
| saldos | `60F/M`, `62F/M`, `64`, `65` | `Bal` typed | ✔ ambos preservados en `balances` |

## Matriz de soporte final

| formato | vertical | estado |
|---|---|---|
| MT535 | positions | SUPPORTED_V1 |
| semt.002.001.12 | positions | SUPPORTED_V1 |
| semt.002.002.11 | positions | SUPPORTED_V1 (mismo mapping, variante ISO-15022) |
| MT940 | cash observation | SUPPORTED_V1 (field 86 = evidencia verbatim) |
| MT950 | cash observation | SUPPORTED_V1 |
| camt.054.001.13 | cash observation | SUPPORTED_V1 |
| camt.053.001.13 | cash observation | SUPPORTED_V1 |
| field 86 → semántica CA | binding | PROFILE_REQUIRED |
| Iberclear reporting | positions/cash | REFERENCE_ONLY |
| narrativas bancarias propietarias | binding | PROFILE_REQUIRED (CA_ES_CUSTODY_PROFILE_V1) |

No soportado a propósito: binding por amount/date/currency
(diagnóstico solamente), agregación implícita de posiciones,
instrumento por nombre/ticker, cualquier statement no-COMPLETE
como input autoritativo.
