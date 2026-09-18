# P13.0 — Input capability matrix (custody feeds)

Audit preregistrado sobre los jars **pinneados** (no "latest"):

- `pw-swift-core` = `SRU2025-10.3.19`
- `pw-iso20022` = `SRU2025-10.3.10`

Verificación empírica: `unzip -l` + `javap` sobre los jars
resueltos por Gradle con verification-metadata. Las clases citadas
existen en el pin; las capacidades de negocio se confirman por TDD
con fixtures sintéticos (P13.15) antes de declarar SUPPORTED.

## Whitelist de versiones (additive a los adapters existentes)

| mensaje | versiones whitelist | criterio |
|---|---|---|
| MT535 | n/a (FIN no versiona) | SRU2025 |
| MT940 | n/a | SRU2025 |
| MT950 | n/a | SRU2025 |
| semt.002 | `semt.002.001.12`, `semt.002.002.11` | última .001 (ISO 20022) + última .002 (variante ISO-15022) del jar |
| camt.053 | `camt.053.001.13` | última del jar pinneado |
| camt.054 | `camt.054.001.13` | última del jar pinneado |

Versiones más antiguas presentes en el jar (semt.002.001.01–11,
.002.03–10, camt.053.001.01–12, camt.054.001.01–12) NO se
whitelistean: sin fixtures reales por versión no hay evidencia de
equivalencia de mapping → `UNSUPPORTED_MESSAGE_TYPE` (fail-closed),
extensible por profile si una entidad lo requiere.

## SECURITIES POSITIONS

### MT535 — Statement of Holdings → `SUPPORTED_V1`

Clase `MT535` presente. Semántica estándar (SWIFT MRG cat.5):
informa holdings en cuenta de custodia a una fecha, para
reconciliación entre account owner y account servicer.

| requisito | campo/estructura | estado |
|---|---|---|
| safekeeping account | `97A::SAFE//` (GENL) | explícito |
| statement identity | `20C::SEME//` (GENL) | explícito |
| as-of | `98A/C/E::STAT//` (GENL) | explícito (A=date, C=datetime, E=? se acepta A/C) |
| instrument | `35B` ISIN en seq FIN | explícito; ISIN ausente → position con `isin=null` (fail-closed en mapping si se requiere) |
| quantity | `93B::AGGR//` + sub-balances `93B/C::AVAI/NAVI/LOAN/BLOK/…` en SUBBAL | explícito (qualifier + quantity type UNIT/FAMT/AMOR) |
| quantity type/basis | componente quantity type de `93B/C` | explícito |
| availability/sub-position | qualifiers de `93B/C` en SUBBAL (AVAI, NAVI, BLOK, PLED, LOAN, …) | explícito cuando presente |
| completeness/continuation | `28E` page + continuation indicator (`ONLY`/`MORE`/`LAST`) | explícito → assembly multi-página obligatorio |
| actividad | `17B::ACTI//N` → statement sin movimiento; seq B ausente → statement sin holdings | explícito |
| frecuencia/tipo | `22F` qualifiers (SFRE, CODE) | facts preservados; no requeridos |

### semt.002 — SecuritiesBalanceCustodyReport → `SUPPORTED_V1`

`MxSemt00200112` y `MxSemt00200211` presentes. Equivalente MX de
MT535: `StmtGnlDtls` (StmtNb/StmtDtTm/UpdTp/ActvtyInd/StmtBsis),
`SfkpgAcct`, `BalForAcct[]` (FinInstrmId + QtyForAcct/SubBal).
Completeness: `UpdTp` (e.g. COMP/DELT) + `StmtNb` paginación —
la equivalencia exacta con `28E` se fija por fixture + test de
paridad; si `UpdTp` no distingue "última página", las reglas de
completeness se documentan en `p131-position-observation.md` y el
resultado puede quedar `INDETERMINATE` (nunca COMPLETE inventado).

## CASH MOVEMENTS (account observations)

### camt.054 — BankToCustomerDebitCreditNotification → `SUPPORTED_V1`

`MxCamt05400113` presente. Notificación débito/crédito por entry:
`Ntfctn.Id`, `Acct`, `Ntry[]` (`NtryRef`, `Amt`+`Ccy`, `CdtDbtInd`,
`Sts`=BOOK/PDNG/INFO, `BookgDt`, `ValDt`, `AcctSvcrRef`, `RvslInd`,
`NtryDtls/TxDtls/Refs` con EndToEndId/TxId/InstrId/PmtInfId/Prtry,
`RmtInf`). Binding CA solo si referencias explícitas.

### camt.053 — BankToCustomerStatement → `SUPPORTED_V1`

`MxCamt05300113` presente. Statement completo: `Stmt.Id`,
`ElctrncSeqNb` (sequencing), `FrToDt`, `Acct`, `Bal[]`
(OPBD/CLBD/ITBD…), mismas `Ntry[]` que camt.054.

### MT940 — Customer Statement Message → `SUPPORTED_V1` (observación)

`MT940` + `Field61`/`Field86` presentes. `20` ref, `25` cuenta,
`28C` statement/sequence number, `60a/62a` balances (F/M),
`61` línea (value date, entry date, D/C+R reversal, amount,
transaction type, owner ref, servicer ref, supplementary),
`64` disponible, `86` narrativa → **evidencia acotada, nunca
semántica** (profile requerido para interpretarla).

### MT950 — Statement Message → `SUPPORTED_V1` (observación)

`MT950` presente. Mismo esqueleto que MT940 sin `86`. Interbancario:
produce observación de cash account con menos contexto; el binding
solo via servicer/owner references.

## Clasificación final preregistrada

| formato | clase | notas |
|---|---|---|
| MT535 | SUPPORTED_V1 | completeness vía 28E obligatoria |
| semt.002.001.12 | SUPPORTED_V1 | paridad MT535 sujeta a test |
| semt.002.002.11 | SUPPORTED_V1 | variante ISO-15022, misma proyección |
| camt.054.001.13 | SUPPORTED_V1 | binding explícito requerido |
| camt.053.001.13 | SUPPORTED_V1 | idem + statement sequencing |
| MT940 | SUPPORTED_V1 (obs) | field 86 = evidencia, nunca semántica genérica |
| MT950 | SUPPORTED_V1 (obs) | sin field 86 |
| field 86 bank narratives | PROFILE_REQUIRED | sin parseo genérico |
| otras versiones MX | UNSUPPORTED | hasta evidencia de equivalencia |

## Lo que NINGÚN formato demuestra por sí solo

- Correlación cash↔corporate-action por importe/fecha: **ningún
  formato la autoriza**; solo referencias explícitas (EndToEndId,
  InstrId, owner/servicer refs mapeadas por ledger o profile).
- Account identity global: todos reportan el identificador que el
  servicer usa; el mapping `account_id_raw → account_id` es
  configuración explícita (P13.18 profile / mapping table).
