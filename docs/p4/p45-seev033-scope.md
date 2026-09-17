# P4.5 — seev.033 instruction writer (scope preregistrado)

Status: DONE

## Frontera

```text
CA_ES_ELECTION_INSTRUCTION_V1 (READY)
+ facts de la notificacion fuente
  (CA_ES_SWIFT_MX_FACTS_V1 seev.031 | CA_ES_SWIFT_MT_FACTS_V1 MT564)
+ CA_ES_SWIFT_MX_ENVELOPE_V1 (BAH explicito)
    -> seev033_project()   -> CA_ES_SEEV033_PROJECTION_V1
    -> adapter JVM "seev033" -> modelo Prowide tipado -> XML
                             -> CA_ES_SEEV033_XML_V1
```

Variante de escritura: **`seev.033.002.13`** (la ISO 15022 variant;
ver p43-see-v-capability.md). El core nunca genera XML; el adapter JVM
construye el modelo tipado `MxSeev03300213` y serializa con Prowide
(`mx.message()` con AppHdr).

## Envelope — `CA_ES_SWIFT_MX_ENVELOPE_V1`

Campos obligatorios, sin defaults (BAH `head.001.001.02` /
`BusinessAppHdrV02`, verificado por javap):

| Campo envelope | Elemento BAH |
|---|---|
| `sender_bic` | `Fr/FIId/FinInstnId/BICFI` |
| `receiver_bic` | `To/FIId/FinInstnId/BICFI` |
| `msg_def_idr` | `MsgDefIdr` — debe ser `seev.033.002.13` |
| `biz_svc` | `BizSvc` |
| `cre_dt` | `CreDt` (ISO 8601 explicito) |

`BizMsgIdr` = `instruction_id` (derivado explicito: es la referencia
de negocio del emisor a la instrucción — el equivalente SEME; es el
valor que seev.034 cita en `InstrId/Id`, binding P4.6). No es un
campo de envelope separado ni un default.

## Elementos escritos (projection)

`CA_ES_SEEV033_PROJECTION_V1` lleva `elements[]` ordenados con
`{model_path, value, source}` — cada campo traza a instrucción,
facts fuente o envelope:

| model_path | value | source |
|---|---|---|
| `CorpActnInstr/CorpActnGnlInf/CorpActnEvtId` | CORP de la notificacion | `facts:CorpActnGnlInf/CorpActnEvtId` (MX) o `facts:GENL:20C:CORP` (MT) |
| `CorpActnInstr/CorpActnGnlInf/EvtTp/Cd` | CAEV de la notificacion | `facts:.../EvtTp/Cd` o `facts:GENL:22F:CAEV` |
| `CorpActnInstr/CorpActnGnlInf/UndrlygScty/FinInstrmId/ISIN` | isin | `instruction.isin` |
| `CorpActnInstr/AcctDtls/SfkpgAcct` | account_id | `instruction.account_id` |
| `CorpActnInstr/CorpActnInstr/OptnNb/Nb` | option_identifier | `instruction.option_identifier` |
| `CorpActnInstr/CorpActnInstr/OptnTp/Cd` | option_code_raw | `instruction.option_code_raw` |
| `CorpActnInstr/CorpActnInstr/SctiesQtyOrInstdAmt/SctiesQty/InstdQty/Qty/Unit` | requested_quantity | `instruction.requested_quantity` (BigDecimal; punto decimal) |

Nada mas: sin `BnfclOwnrDtls`, `PrtctInstr`, `AddtlInf`,
`SplmtryData`, `OthrDocId`, `EvtsLkg` (el link a la notificación lo
da `CorpActnEvtId`; el link a nivel documento se defiere: la V1 no
tiene un BizMsgIdr de notificación probado en facts con semántica
equivalente a RELA).

## Fail-closed (proyección)

- `instruction_status != READY` → NOT_SERIALIZABLE.
- schema de facts no reconocido → ValueError.
- `option_kind` ∉ {CASH, SECURITIES} → UNSUPPORTED_OPTION_KIND.
- CORP/CAEV ausentes o conflictivos en los facts fuente →
  reasons MISSING/CONFLICTING, NOT_SERIALIZABLE.
- `requested_quantity` no positivo/no Decimal → INVALID.
- `INSTRUCTION_FACTS_MISMATCH` si el `source_message_input_sha256`
  de la instrucción no iguala el `input_sha256` de los facts
  (misma regla que MT565).
- Envelope incompleto/malformado → ValueError.

`projection_status`: `SERIALIZABLE` | `NOT_SERIALIZABLE`. Solo
SERIALIZABLE llega al writer.

## Salida — `CA_ES_SEEV033_XML_V1`

```text
xml                    sobre completo (AppHdr + Document)
xml_sha256
source_projection_sha256
message_identifier     seev.033.002.13
write_status           OK | NOT_SERIALIZABLE | ADAPTER_ERROR
```

El writer rechaza projections NOT_SERIALIZABLE. `CreDt` viene del
envelope — la salida es determinista bajo inputs fijos (sin clock
interno).

## Round-trip

`seev033 XML -> MxSeev03300215 parse -> assert semantic equality`
de los campos mapeados. No se exige identidad de bytes (namespaces/
prefixes se normalizan legítimamente); sí hash determinista del
artefacto ca-es bajo inputs fijos.

## Paridad MT↔MX

Mismo `CA_ES_ELECTION_INSTRUCTION_V1` -> MT565 y seev.033 codifican:
instruction_id (SEME vs BizMsgIdr), CORP/CAEV, ISIN, account,
option (CAON/CAOP vs OptnNb/OptnTp), quantity (QINS UNIT vs
InstdQty Unit). Equivalentes en semántica probada.
