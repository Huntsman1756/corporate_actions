# P17 — Securities Transaction & Settlement Feed V1: conformidad

Estado: **CLOSED** tras evidencia de verificacion.

## Contratos

| contrato | modulo | funcion |
|---|---|---|
| `CA_ES_SETTLEMENT_OBSERVATION_V1` | `settlement_observation.py` | facts MT54x / sese.023-025 -> observacion normalizada (kind INSTRUCTION/STATUS/CONFIRMATION) |
| `CA_ES_SETTLEMENT_TRANSACTION_V1` | `settlement_transaction.py` | ledger de transacciones por referencias explicitas; outcomes NEW_TRANSACTION/BOUND/EXACT_DUPLICATE/SEMANTIC_DUPLICATE/AMBIGUOUS/INSUFFICIENT_IDENTITY |
| `CA_ES_SETTLEMENT_STATUS_V1` | `settlement_status.py` | vista auditable del ciclo por tx (history + conflictos) |
| `CA_ES_SETTLEMENT_RECON_V1` | `settlement_recon.py` | instructed vs cumulative settled + conflictos; huerfanas -> INSUFFICIENT_IDENTITY |
| `CA_ES_SECURITIES_TRANSACTIONS_V1` | `settlement_export.py` | export compatible con `claim_basis` (P16) sin adaptacion |

## Invariantes verificadas

- `instruction != status != confirmation` (kind separado).
- `intended_settlement_date != actual_settlement_date`
  (98A::SETT/ESET vs SttlmDt/XpctdSttlmDt/FctvSttlmDt).
- `MATCHED != SETTLED` (25D::MTCH//MACH + 25D::SETT//PEND ->
  MATCHED; sese.024 Mtchd+Pdg -> MATCHED).
- `partial != full` (cumulative settled < instructed ->
  PARTIALLY_SETTLED; nunca dos transacciones).
- `message received != transaction authoritative` (la tx
  agrega observaciones; huerfanas conservadas, no forzadas).
- Identidad SOLO por referencias explicitas
  (acct_svcr/acct_ownr/mkt_infrstrctr/prcr/common/linked/UTI/
  pool/trade). NUNCA isin+qty+fecha.
- Duplicado exacto por `input_sha256`; duplicado semantico por
  hash del contenido normalizado (misma observacion, bytes
  distintos). Una segunda confirmacion con cantidades distintas
  NO es duplicado.
- Conflictos factual (`instructed_quantity`, `isin`, fechas)
  registrados en `conflicts`; nunca overwrite silencioso.

## Acceptance S1-S15

| gate | evidencia | estado |
|---|---|---|
| S1 sese.023 -> tx observed | `test_s1` + facts reales `sese023-instr.xml` | PASS |
| S2 MT541 mismo dominio | `test_s2` + `mt541-rece.fin` | PASS |
| S3 sese.024 pending -> PENDING | `test_s3` + `sese024-pdg.xml` | PASS |
| S4 MT548 matched/pending separados | `test_s4` + `mt548-status.fin` | PASS |
| S5 sese.025 -> SETTLED | `test_s5` + `sese025-conf.xml` | PASS |
| S6 MT545 ligada -> misma tx | `test_s6` (RELA binding) | PASS |
| S7 partial -> PARTIALLY_SETTLED | `test_s7`, `test_recon_partial_and_match` | PASS |
| S8 multi-confirmacion sin duplicar tx | `test_s8` (cumulative 400+600) | PASS |
| S9 bytes duplicados -> EXACT_DUPLICATE | `test_s9` | PASS |
| S10 mismo hecho bytes distintos -> SEMANTIC_DUPLICATE | `test_s10` | PASS |
| S11 conflicto de cantidad | `test_s11` | PASS |
| S12 sin referencia -> INSUFFICIENT_IDENTITY | `test_s12` + DAG orphan | PASS |
| S13 feed -> claim_basis sin JSON manual | `test_s13` (export -> claim_basis) | PASS |
| S14 run identico -> ids deterministas | `test_s14` + `SKIPPED_UNCHANGED` DAG | PASS |
| S15 merge de ledger conserva ciclo | `test_s15` + `test_settlement_feed_second_run_merges_ledger` | PASS |

## P7 / P3.5 / CLI

- Step `settlement_feed` (impuro, opcional) tras
  `process_inbox`; `market_claims` lo consume via
  `ctx.docs["settlement_feed"]` SOLO cuando no hay input
  `securities_transactions` declarado.
- `CA_ES_SETTLEMENT_RECON_V1` -> casos P3.5 con clave estable
  `settlement-feed|<tx|source_ref>`; OVER_SETTLED/
  QUANTITY_CONFLICT/FAILED = HIGH; NO_INSTRUCTION_BASIS/
  INSUFFICIENT_IDENTITY = MEDIUM; estados de ciclo normales
  filtrados.
- CLI: `st-observe`, `st-ledger`, `st-status`, `st-recon`,
  `st-export`.

## Verificacion real

Facts generados con el adapter JVM reconstruido sobre fixtures
reales (`mt541-rece.fin`, `mt545-conf.fin`, `mt548-status.fin`,
`sese023-instr.xml`, `sese024-pdg.xml`, `sese025-conf.xml`) —
pipeline completo observation->ledger->recon->export verificado
sobre ambas familias: MT541+548+545 -> SETTLED; sese.023+024+025
-> SETTLED, recon MATCH, export BUY/1000.

## Limites congelados

- MT536/537 (statements agregados) fuera de V1.
- MT549+ y sese.001-022/026+ fuera.
- Read-only: no se genera ISO settlement.
- `PrtlyRlsdQty` (partial release) NO se mapea a settled —
  semantica distinta.
- Binding por referencia; nunca por amount+date.
- FX sin cambios (boundary diferido).
