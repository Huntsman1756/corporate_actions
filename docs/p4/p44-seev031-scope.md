# P4.4 — seev.031 → dominio existente (scope preregistrado)

Status: DONE

## Contratos reutilizados (sin nuevos)

Auditoría de transport-neutralidad:

- `CA_ES_SWIFT_CA_MESSAGE_V1` — es la proyección semántica de un
  mensaje CA; ningún campo es estructuralmente MT-específico
  (`caev`, `event_type`, `fields{isin,ex_date,record_date,
  payment_date,gross_per_share,currency,message_function,
  processing_status}`, `message_identifier`). Se reutiliza tal cual:
  `message_identifier` distingue `MT564` de `seev.031.002.15`; la
  provenance de cada campo pasa a llevar `model_path` en vez de
  `source_tag`/`sequence` (dict libre, misma forma).
- `CA_ES_SWIFT_EVENT_BINDING_V1` — binding canon por
  `event_type`+ISIN+comparación de fechas/importe: ya es agnóstico
  al transporte. `bind_event()` se reutiliza **sin modificar**;
  el guard de schema sigue siendo `CA_ES_SWIFT_CA_MESSAGE_V1`.
- `CA_ES_ELECTION_OPPORTUNITY_V1` — sus campos
  (`option_identifier`, `option_code_raw`, `option_kind`,
  `default_status`, `source_response_deadline`, `terms`,
  `operational_deadlines`) son transport-neutrales. Se reutiliza.

No se debilita ningún guard existente: lo que cambia es *quién*
emite el doc, no el contrato.

## Entrada aceptada

`CA_ES_SWIFT_MX_FACTS_V1` con `message_identifier` ∈
{`seev.031.001.15`, `seev.031.002.15`} y `parse_status=PARSE_OK`.
Otro mensaje → `status=UNSUPPORTED_MESSAGE_TYPE`.

## Mapping seev.031 → CA_ES_SWIFT_CA_MESSAGE_V1

Verificado contra el modelo `MxSeev03100215`/`MxSeev03100115` del
jar pinneado (javap). Solo elementos explícitos:

| Campo dominio | model_path (sufijo) | Notas |
|---|---|---|
| `caev` | `CorpActnGnlInf/EvtTp/Cd` | mismo codeset 4-letras que 22F::CAEV (enum `CorporateActionEventType35Code`); `EvtTp/Prtry` no mapea → UNSUPPORTED_CA_EVENT |
| `event_type` | derivado vía `CAEV_MAP` | DVCA→CASH_DIVIDEND, SPLF→SPLIT |
| `corporate_action_reference` | `CorpActnGnlInf/CorpActnEvtId` | equivalente a 20C::CORP |
| `isin` (binding) | `CorpActnGnlInf/UndrlygScty/FinInstrmId/ISIN` | underlying, nunca instrumento movido |
| `ex_date` | `CorpActnDtls/DtDtls/ExDvddDt/Dt` | DateFormat41Choice.Dt = LocalDate |
| `record_date` | `CorpActnDtls/DtDtls/RcrdDt/Dt` | idem |
| `payment_date` | `CorpActnDtls/DtDtls/PmtDt/Dt` | idem |
| `gross_per_share` | `CorpActnOptnDtls/RateAndAmtDtls/GrssDstrbtnRate/Amt` | GrossDividendRateFormat41Choice.Amt; todas las ocurrencias se agregan por valor único (CONFLICTING si difieren) — nunca se elige una opción arbitraria |
| `currency` | `.../GrssDstrbtnRate/Amt/@Ccy` | atributo de la misma Amt |
| `message_function` | `NtfctnGnlInf/NtfctnTp` | NEWM/RPLC/… |
| `processing_status` | `CorpActnGnlInf/EvtPrcgTp/Cd` | |
| `related_reference` | — | sin mapping V1 (ABSENT) |

`NetDstrbtnRate` **no** se mapea a `gross_per_share` (semántica
neta, distinta). `DtCd` (date code) nunca se interpreta como fecha.

## Mapping seev.031 → CA_ES_ELECTION_OPPORTUNITY_V1

`project_mx_election()` paralelo a `project_election()`:

- una opción por ocurrencia de `CorpActnOptnDtls` (agrupado por el
  índice `[k]` del ancestor en `evidence_locator`);
- `option_identifier` ← `OptnNb` (ancla; su ausencia →
  MISSING_OPTION_IDENTITY);
- `option_code_raw` ← `OptnTp/Cd` → whitelist cerrada
  `OPTION_KIND` (CASH→CASH, SECU→SECURITIES; otro → UNSUPPORTED);
  `OptnTp/Prtry` → UNSUPPORTED con raw preservado;
- `default_status` ← `DfltPrcgOrStgInstr/DfltOptnInd`:
  `true`→DEFAULT, `false`→NOT_DEFAULT, ausente→UNKNOWN.
  `StgInstrInd` **no** es un indicador de default → UNKNOWN;
- `source_response_deadline` ← `DtDtls/RspnDdln/Dt/Dt` (LocalDate)
  o `Dt/DtTm` (raw ISO preservado); `DtCd`/`DtCdAndTm` nunca
  interpretados → quedan como term provenance;
- `terms` ← todos los demás facts de la ocurrencia (provenance);
- sin CAOPTN equivale a sin `CorpActnOptnDtls` →
  `NO_OPTION_EVIDENCE` → INDETERMINATE (nunca NON_ELECTIVE);
- binding canon/queue: mismas reglas P5.2 (`bind_event` reutilizado,
  queue binding por `deadline_types`, `QUEUE_CANON_MISMATCH` raise).

## Paridad MT↔MX

Fixture `seev031-002.xml` vs `mt564-valid.fin`: mismo escenario
DVCA/MAND (mismo ISIN, mismas fechas, mismo bruto). Tras proyección,
`event_type`/`isin`/fechas/`gross_per_share`+`currency` deben ser
equivalentes; difieren solo `message_identifier`, provenance e
`input_sha256`.

## Fail-closed

- CAEV ausente/no mapeado → UNSUPPORTED_CA_EVENT (igual que MT).
- Sin binding → oportunidad INDETERMINATE con `EVENT_NOT_BOUND`.
- ISIN múltiple/conflictivo → CONFLICTING vía `_field`.
