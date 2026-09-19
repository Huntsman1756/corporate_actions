# P17.0 — capability audit: Securities Transaction & Settlement Feed

Audit realizado contra los jars **efectivamente pinneados** del
adapter (`pw-swift-core-SRU2025-10.3.19`, `pw-iso20022-
SRU2025-10.3.10`), no contra el catalogo ISO vigente. Verificado
con `jar tf` + `javap`.

## MT (Prowide Core — extractor generico por tag/qualifier)

Clases presentes en `com.prowidesoftware.swift.model.mt.mt5xx`:

| mensaje | rol | V1 |
|---|---|---|
| MT540 | Receive Free instruction | SI |
| MT541 | Receive Against Payment instruction | SI |
| MT542 | Deliver Free instruction | SI |
| MT543 | Deliver Against Payment instruction | SI |
| MT544 | Receive Free confirmation | SI |
| MT545 | Receive Against Payment confirmation | SI |
| MT546 | Deliver Free confirmation | SI |
| MT547 | Deliver Against Payment confirmation | SI |
| MT548 | Settlement status / processing advice | SI |
| MT536 | Statement of Transactions | auditado, NO V1 (agregado a nivel statement, no lifecycle por transaccion) |
| MT537 | Statement of Pending Transactions | auditado, NO V1 (idem) |
| MT535 | Statement of Holdings | ya soportado (P13) |

El extractor MT es qualifier-agnostico (P14/P15): 20C::SEME/RELA/
TRRF/COMM/CORP/POOL/MITI/PCTI/PREV/CLTR, 23G::NEWM/CANC/REPL/PREA,
22F::SETR, 22H::REDE, 22H::PAYM, 98A::TRAD, 98A::SETT, 98A::ESET,
36B::SETT/PSTA, 19A::SETT/ESTT/PSTA, 35B, 97A::SAFE, 95P/Q/R
parties, 25D::MTCH/SETT/IPRC/CPRC, 24B reasons, 70D/70E salen
como facts sin tocar el parser. Solo se extiende la whitelist
`IsoAdapter.SUPPORTED` con `540..548`.

## MX sese (pw-iso20022 — extractor generico de DOM)

Presentes en el pin:

| familia | versiones .001 | versiones .002 |
|---|---|---|
| sese.023 SctiesSttlmTxInstr | .001.01–.11 | .002.01–.11 |
| sese.024 SctiesSttlmTxStsAdvc | .001.01–.13 | .002.01–.12 |
| sese.025 SctiesSttlmTxConf | .001.01–.12 | .002.01–.11 |

Las variantes `.002` son el track SMPG restricted del mismo
message set. V1 soporta ambas familias en el boundary de facts;
la proyeccion se verifica con fixtures `.001` (ultimo del pin:
023.001.11 / 024.001.13 / 025.001.12). Paridad de proyeccion
`.002` se verifica con al menos un fixture; si los paths no
comparten nombres, `.002` queda facts-only documentado.

## Modelo real verificado (javap)

**sese.023** `SecuritiesSettlementTransactionInstructionV11`:
`TxId` (String acct-servicer tx id), `SttlmTpAndAddtlParams`
(SctiesMvmntTp RECE|DELI + Pmt FREE|APMT|… + CmonId +
CorpActnEvtId + RcncltnInd + collateral ids), `NbCounts`,
`Lnkgs` (PrcgPos/MsgNb/Ref/LkdQty/RefOwnr), `TradDtls`
(TradId[]!, TradDt, SttlmDt=intended, LateDlvryDt, MtchgSts,
AffirmSts), `FinInstrmId/ISIN`, `QtyAndAcctDtls` (SttlmQty,
AcctOwnr, SfkpgAcct, CshAcct), `SttlmParams`, `Dlvrg/RcvgSttlmPties`,
`SttlmAmt`, `OthrAmts`.

**sese.024** `SecuritiesSettlementTransactionStatusAdviceV13`:
`TxId` = TransactionIdentifications47 {AcctOwnrTxId,
AcctSvcrTxId, MktInfrstrctrTxId, CtrPtyMktInfrstrctrTxId,
PrcrTxId, CmonId, NetgSvcPrvdrId}, `Lnkgs` (Linkages41 con
SctiesSttlmTxId), `PrcgSts` (AckdAccptd/PdgPrcg/Rjctd/Rpr/Canc/
PdgCxl/Prtry/CxlReqd/ModReqd), `IfrdMtchgSts`, `MtchgSts`
(Mtchd/Umtchd/Prtry), `SttlmSts` (Pdg/Flng/Prtry), `TxDtls`.

**sese.025** `SecuritiesSettlementTransactionConfirmationV12`:
`TxIdDtls` = SettlementTypeAndIdentification29 (todos los refs +
SctiesMvmntTp + Pmt + CmonId + PoolId + **CorpActnEvtId** +
NonceId), `TradDtls` = SecuritiesTradeDetails143 (TradId,
**UnqTxIdr = UTI**, TradDt, SttlmDt, **FctvSttlmDt = actual
settlement date**), `FinInstrmId/ISIN`, `QtyAndAcctDtls`
(**SttldQty, PrevslySttldQty, RmngToBeSttldQty**,
PrevslySttldAmt, RmngToBeSttldAmt — semantica cumulative
explicita), `AcctOwnr/SfkpgAcct`, `SttldAmt`.

## Decisiones de scope

- **En V1**: MT540-548 + sese.023/024/025 (todas las versiones
  del pin en whitelist de facts; proyeccion verificada .001).
- **Fuera V1**: MT536/537 (statement aggregates; documentado
  para fase posterior si un feed real lo justifica); MT549
  (matching statement?); MT530/538/558+; sese.001-022,
  sese.026+ (allegement/OTC/ETC familias); Buyer Protection
  seev.060-067 (P18).
- **Sin generacion ISO** (ADR-010): solo lectura/observacion.
- **SR2026**: versiones posteriores a las del pin fuera; no se
  persigue numeracion.

## Whitelist additions

`IsoAdapter.SUPPORTED`: + `540,541,542,543,544,545,546,547,548`.
`MxFactsAdapter.SUPPORTED`: + sese.023.001.01-11 + .002.01-11,
sese.024.001.01-13 + .002.01-12, sese.025.001.01-12 + .002.01-11.
