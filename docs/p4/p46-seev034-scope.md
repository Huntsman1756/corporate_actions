# P4.6 — seev.034 instruction status (scope preregistrado)

Status: DONE

## Frontera

```text
seev.034 XML -> CA_ES_SWIFT_MX_FACTS_V1
    + CA_ES_ELECTION_INSTRUCTION_V1 (target)
        -> bind_mx_instruction_status()
        -> CA_ES_ELECTION_INSTRUCTION_STATUS_V1
```

Mismo contrato que P5.6 (`CA_ES_ELECTION_INSTRUCTION_STATUS_V1` es
transport-neutral: `instruction_id`, `instruction_binding_status`,
`statuses[]`, `normalized_status`, provenance). Nunca muta
`CA_ES_ELECTION_INSTRUCTION_V1`; custodian status != workflow status.

Entrada aceptada: `message_identifier` ∈
{`seev.034.001.15`, `seev.034.002.15`}, `parse_status=PARSE_OK`.
Otro mensaje → `EXPECTED_SEEV034` (ValueError), igual que
`EXPECTED_MT567` en P5.6.

## Binding (determinista, sin fuzzy)

Equivalente MX del `GENL/LINK 20C::PREV`:

```text
/Document/CorpActnInstrStsAdvc/InstrId/Id  ==  instruction_id
```

`InstrId` (DocumentIdentification17) es "identificacion del
documento de instruccion relacionado" — el valor que P4.5 emitio en
`BizMsgIdr`. Reglas identicas a P5.6:

- unico InstrId == instruction_id → `BOUND`;
- ausente → `INSUFFICIENT_IDENTITY`;
- != instruction_id → `NO_MATCH`;
- multiples InstrId distintos aunque contenga el id → `AMBIGUOUS`.

`CorpActnInstrStsAdvc` tambien lleva `CorpActnGnlInf/CorpActnEvtId` —
se captura como contexto, nunca como clave de binding (igual que en
MT567 no se usaba 20C::CORP).

## Status normalization (whitelist preregistrada)

El status seev.034 es **estructural** — la eleccion dentro de
`InstrPrcgSts[k]` (`InstructionProcessingStatus58Choice`,
verificado por javap):

| Choice element | normalized_status | MT567 equivalente |
|---|---|---|
| `AccptdForFrthrPrcg` | ACCEPTED | 25D::IPRC//PACK |
| `Rjctd` | REJECTED | IPRC//REJT |
| `Pdg` | PENDING | IPRC//PEND |
| `DfltActn` | DEFAULT_ACTION_APPLIED | IPRC//DFLA |
| `Canc`, `Fwdd`, `Rtrd`, `StgInstr`, `PrtrySts`, `RcvdByIssrOrOfferr` | UNSUPPORTED | — (sin equivalente MT567 whitelist) |

`status_code_raw` = nombre del choice element (p.ej. `Rjctd`) +
cualquier codigo interno (`.../RsnCd/...`, `NoSpcfdRsn`) preservado
raw. Razones: leaf facts bajo la ocurrencia `InstrPrcgSts[k]` cuyo
path contiene `Rsn`/`AddtlRsnInf`/`NoSpcfdRsn` se agrupan
posicionalmente como `reason_code_raw`/`reason_narrative` (misma
idea que el windowing REAS por tag index en MT567; aqui por el
indice del ancestor en `evidence_locator`).

`message_function` = el `message_identifier` (seev.034 no lleva
23G — la propia clase de mensaje es la funcion).

## Paridad MT↔MX

MT567 `IPRC//PACK` y seev.034 `InstrPrcgSts/AccptdForFrthrPrcg`
producen `normalized_status=ACCEPTED` sobre el mismo
`instruction_id` — escenario 4/5 del conformance matrix (P4.8).
