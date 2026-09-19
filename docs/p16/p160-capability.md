# P16.0 — capability audit: Market Claims seev.050-053 en pin SRU2025

Jar auditado: `pw-iso20022-SRU2025-10.3.10.jar` (pin de
`adapters/iso-adapter-jvm/build.gradle.kts`, verification-metadata
sha256). Metodo: `unzip -l` + `javap` sobre clases `MxSeev05*`
y `dic.*` reales.

## Mensajes presentes en el pin

| mensaje | ISO function | versiones en pin | catalogo ISO actual |
|---|---|---|---|
| seev.050 | MarketClaimCreation | .001.01 / .001.02 / .001.03 | .001.04 |
| seev.051 | MarketClaimCancellationRequest | .001.01 / .001.02 | .001.02 |
| seev.052 | MarketClaimStatusAdvice | .001.01 / .001.02 / .001.03 | .001.04 |
| seev.053 | MarketClaimCxlReqStatusAdvice | .001.01 / .001.02 / .001.03 | .001.04 |

El pin esta una variante por detras del catalogo ISO en
050/052/053. ISO recuerda que publicar una version no obliga a
adoptarla: P16 soporta lo que el jar demuestra, no la numeracion
mas alta.

## Campos verificados (javap)

**seev.050 `MarketClaimCreationV03`**: `TxRef`
(`AcctSvcrTxId`/`MktInfrstrctrTxId`/`PrcrTxId` — referencias de
la claim), `CorpActnGnlInf` (`CorpActnEvtId`,
`OffclCorpActnEvtId`, `EvtTp`, `FinInstrmId`),
`RltdSttlmInstrDtls` (`RltdSttlmInstrId`, `RltdSttlmQty`,
`TrfOfPrcdsTpInd`, `PrcdsQtyBrkdwn`), `AcctDtls`, `CorpActnDtls`,
`MktClmTp` (`MarketClaimType1Code`: **MKTC** market claim,
**RVMC** reverse market claim), `MktClmDtls`
(`CorporateActionOption234`: `OptnNb`, `OptnTp`,
`SctiesMvmntDtls`, `CshMvmntDtls`), `DlvrgSttlmPties`,
`RcvgSttlmPties`.

**seev.051 `MarketClaimCancellationRequestV02`**: `MktClmCreId`
(ref a la seev.050), `TxRef`, `CorpActnGnlInf`, `AcctDtls`.

**seev.052 `MarketClaimStatusAdviceV03`**: `MktClmCreId`,
`TxRef`, `CorpActnGnlInf`, `AcctDtls`, `MktClmPrcgSts`
(choice: `Canc`, `AccptdForFrthrPrcg`, `Rjctd`, `Pdg`,
`MtchgSts`, `PrtrySts`), `MktClmDtls`.

**seev.053 `MarketClaimCancellationRequestStatusAdviceV03`**:
`MktClmCxlReqId`, `TxRef`, `CorpActnGnlInf`, `MktClmCxlReqSts`
(choice: `CxlCmpltd`, `Accptd`, `Rjctd`, `PdgCxl`, `PrtrySts`),
`MktClmDtls`.

`TransferOfProceedsType1Code`: **CLFT** (full transfer of
proceeds), **CLPT** (partial), **CLNT** (no transfer) —
indicador de direccion del traspaso economico en la
instruccion de settlement relacionada.

## Buyer Protection (seev.060-067) — DOC-ONLY

**Ausente del pin.** `unzip -l` no contiene ninguna clase
`MxSeev06*`. La familia Buyer Protection (instruction, status,
cancellation, allegement, report) es una incorporacion del
catalogo 2026. Soportarla exigiria migrar a un pin SRU2026 +
regresion P4-P15: se deja como entrada de roadmap, sin
implementacion por arrastre.

## SR2026 forward-compat — NO soportado, documentado

SR2026 anade a seev.050 un indicador que distingue claims
creadas solo para deteccion de claims creadas para settlement.
Ese campo **no existe en .001.01-.03**: P16 nunca lo proyecta;
si un mensaje futuro lo trajera, quedaria como fact sin
proyeccion semantica (preservado, no interpretado).

## Adapter

`MxFactsAdapter` es un walker DOM generico: bastan las entradas
`SUPPORTED` para emitir `CA_ES_SWIFT_MX_FACTS_V1` de
seev.050-053. Sin parsers nuevos, sin cambio de contrato de
facts.

## FIN / ISO 15022

No existe mensaje MT dedicado de market claim equivalente a
seev.050-053; la liquidacion de la claim viaja como movimiento
cash/security ordinario (MT566/camt) que P4.2/P6.3/P13 ya
observan. P16 liga esos movimientos al claim SOLO por
referencia explicita.

## Reutilizacion (sin nuevo settlement engine)

- P4 MX facts (whitelist nueva), P4.2/P6.3 movement candidates
- P8 economic entitlement (basis del importe esperado)
- P13 custody positions/cash observations
- P3/P6.4 recon, P3.5 cases, P7 DAG/cache, P11 send boundary
