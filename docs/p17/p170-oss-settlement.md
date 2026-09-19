# P17.0 — OSS / fuentes publicas: settlement transaction feed

## Prowide (pin actual — sin migracion)

- **pw-swift-core-SRU2025-10.3.19**: modelos `MT536`-`MT549`
  presentes; el extractor de facts FIN es qualifier-agnostico
  (verificado P14/P15 con TARE/BORE/TXRC). Ningun parser nuevo:
  solo whitelist.
- **pw-iso20022-SRU2025-10.3.10**: `MxSese023/024/025` en todas
  las versiones `.001`/`.002` del SRU2025. El extractor MX
  (`AbstractMX.parse` + walk DOM -> facts con local-name paths +
  evidence locators) las consume sin cambios de codigo.
- No se actualiza Prowide: las clases necesarias ya estan en el
  pin; SR2026 no aporta nada requerido para este lifecycle V1.

## ISO 20022 (catalogo publico)

- `sese.023` SecuritiesSettlementTransactionInstruction:
  instruccion RECE/DELI con o sin pago (SctiesMvmntTp + Pmt).
- `sese.024` SecuritiesSettlementTransactionStatusAdvice:
  transporta transaction IDs, matching/settlement status,
  processing status — estados, nunca confirmacion economica.
- `sese.025` SecuritiesSettlementTransactionConfirmation:
  confirmacion con SttldQty/PrevslySttldQty/RmngToBeSttldQty —
  la semantica de partial settlement es **cumulative** en el
  propio modelo (previously-settled explicito).
- MT540-543 = instrucciones (540/541 RECE free|apmt; 542/543
  DELI free|apmt). MT544-547 = confirmaciones espejo. MT548 =
  status (25D::MTCH/SETT/IPRC/CPRC + 24B reasons).
- Publicar version nueva no obliga a adoptarla (politica ISO).

## SWIFT MT (handbook publico)

- Referencias de cadena: `20C::SEME` (sender ref = acct-servicer
  tx id), `20C::RELA` (related/prev), `20C::TRRF` (trade ref),
  `20C::COMM` (common/cmonId), `20C::CORP` (CA event),
  `20C::POOL`, `20C::MITI` (market infra), `20C::PCTI`
  (processor), `20C::CLTR` (client collateral), `20C::PREV`.
- `23G`: NEWM/CANC/REPL/PREA — funcion del mensaje (CANC/REPL
  modifican el ciclo de la observacion, no crean transaccion
  nueva).
- Direccion economica: `22H::REDE//RECE|DELI` + `22H::PAYM//
  FREE|APMT` — equivalencia MT540-543 <-> sese.023.
- Fechas: `98A::TRAD` trade date, `98A::SETT` intended
  settlement (instrucciones) / actual settlement
  (confirmaciones) — la semantica depende del tipo de mensaje,
  no del qualifier. `98A::ESET` donde aplica.
- Cantidades: `36B::SETT` (instructed), `36B::PSTA` (previously
  settled en confirmaciones/537); `19A::SETT`, `19A::ESTT`,
  `19A::PSTA` amounts.
- MT548 status: `25D::MTCH//MACH|NMAT`, `25D::SETT//PEND|PENF`,
  `25D::IPRC//PACK|REPR|PPRC|CANC|...`, `25D::CPRC`,
  `24B::PEND|PENF|...` + rsn codes; `70D/70E` narrativa
  (preservada, nunca clasificada semanticamente).

## Equivalencia de dominio (S2/S6)

```
MT540/541 RECE instr  ~ sese.023 SctiesMvmntTp=RECE Pmt=FREE|APMT
MT542/543 DELI instr  ~ sese.023 DELI
MT544/545 RECE conf   ~ sese.025 RECE
MT546/547 DELI conf   ~ sese.025 DELI
MT548 status          ~ sese.024
```

La proyeccion normaliza a UN modelo de observacion; el dominio
economico queda transport-neutral (misma invariante que P14/P16).

## Identidad — por que referencias y nunca ISIN+qty+fecha

Los modelos dan una cadena de referencias explícita:
`acctSvcrTxId` (SEME), `acctOwnrTxId`, `mktInfrstrctrTxId`
(MITI), `ctrPtyMktInfrstrctrTxId`, `prcrTxId` (PCTI), `cmonId`
(COMM), `poolId` (POOL), `tradId` (TRRF), `unqTxIdr` (UTI en
sese.025), `corpActnEvtId` (CORP), linkages RELA/PREV.
`SfkpgAcct`/`AcctOwnr` cierran la cuenta. Ningun campo de
contenido (ISIN/qty/fecha) participa en la identidad — eso es
exactamente el invariante "no identity merge sin evidencia
determinista" de AGENTS.md.

## Fuentes descartadas

- Open-source settlement engines completos (p.ej. motores de
  reconciliacion genericos): reinventarian lo que el core ya
  tiene; fuera de scope "read-only boundary + ledger".
- MT536/537 como driver de transacciones V1: son statements
  agregados; si un feed real los usa como fuente primaria se
  abre una subfase dedicada.
