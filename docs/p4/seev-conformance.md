# P4.8 — Conformance matrix MT ↔ ISO 20022 (seev)

Status: DONE — `tests/unit/test_p48_conformance.py` (12 escenarios).

```text
Business concept            MT       ISO 20022      Destino comun
---------------------------------------------------------------
Notification                MT564    seev.031      CA_ES_SWIFT_CA_MESSAGE_V1
                                                  + binding + election
Instruction                 MT565    seev.033      CA_ES_ELECTION_INSTRUCTION_V1
Instruction status          MT567    seev.034      CA_ES_ELECTION_INSTRUCTION_STATUS_V1
Movement confirmation       MT566    seev.036      CA_ES_SWIFT_CASH_CANDIDATE_V1
                                                  / CA_ES_SWIFT_SECURITY_
                                                    MOVEMENT_CANDIDATE_V1
```

## Escenarios (resultados)

| # | Escenario | MT | MX | Resultado |
|---|---|---|---|---|
| 1 | Cash dividend notification | MT564 fixture real | seev.031.002.15 fixture real | `event_type`, ISIN, fechas, gross, currency, CORP ref identicos tras proyeccion |
| 2 | Voluntary/elective option | MT564 e2e | seev.031 e2e | mismo `CA_ES_ELECTION_OPPORTUNITY_V1`: option_code, default_status, RspnDdln |
| 3 | Election instruction | MT565 | seev.033.002.13 | mismo intent `CA_ES_ELECTION_INSTRUCTION_V1`; XML round-trip real Prowide |
| 4 | Instruction accepted | `25D::IPRC//PACK` | `AccptdForFrthrPrcg` | `normalized_status=ACCEPTED`, BOUND |
| 5 | Instruction rejected | `IPRC//REJT` | `Rjctd` | `REJECTED` |
| 6 | Cash movement GROSS | `19B::GRSS` | `AmtDtls/GrssAmt` | `amount_basis=GROSS`, amount/currency equivalentes (Decimal) |
| 7 | Cash movement basis desconocida | `19B::PSTA` | `AmtDtls/PstngAmt` | `UNKNOWN` + `UNKNOWN_AMOUNT_BASIS`, PROJECTABLE |
| 8 | Security receipt | `22H::CRDB//CRED` | `CdtDbtInd=CRDT` | `RECEIPT`, qty/fecha/cuenta identicas |
| 9 | Security delivery | `CRDB//DEBT` | `CdtDbtInd=DBIT` | `DELIVERY` |
| 10 | Valor conflictivo deliberado | 2× `19B::GRSS` | 2× `GrssAmt` | `CONFLICTING_AMOUNT`, INDETERMINATE en ambos |
| 11 | Codigo unsupported raw | `IPRC//XXYY` | `PrtrySts` | `UNSUPPORTED` con raw preservado en ambos |
| 12 | Identidad ambigua | 2× `20C::PREV` | 2× `InstrId/Id` | `AMBIGUOUS` en ambos |

## Diferencias legitimas documentadas (no son fallos de paridad)

- **`message_function`**: MT lleva `23G` (NEWM/CAST/INST); seev no tiene
  equivalente — la clase de mensaje es la funcion. En MX el campo se
  rellena con el `message_identifier`.
- **Direccion cash**: seev.036 expone `CdtDbtInd` por movimiento y el
  candidato MX lo preserva (`direction` raw); el candidato MT566 (P4.2)
  no lo proyecta — campo aditivo, no requerido por P3.
- **Lexema de importe**: MT `125,` → `125`; MX `125.00` → `125.00`.
  `raw_lexeme`+scale preservados; igualdad verificada por `Decimal`,
  nunca por string.
- **Binding de instruccion**: MT567 correlaciona por `20C::PREV`;
  seev.034 por `InstrId/Id`. Ambos explicitos y deterministas;
  `CorpActnEvtId`/`20C::CORP` son contexto, nunca clave.
- **`message_identifier`** y `input_sha256` difieren siempre entre
  transportes — se excluyen de la comparacion por construccion.
- **Provenance**: `source_tag`/`sequence`/`block4.tag[i]` (MT) vs
  `model_path`/`element:...` (MX) — misma funcion, distinta forma.

## Semantica deliberadamente NO soportada (igual en ambos)

- Status seev.034 fuera de la whitelist (`Canc`, `Fwdd`, `Rtrd`,
  `StgInstr`, `PrtrySts`, `RcvdByIssrOrOfferr`) → `UNSUPPORTED` raw.
- `PstngQty` en `FceAmt`/otros choices → `UNSUPPORTED_QUANTITY_TYPE`.
- Basis de importe nunca inferida: `PstngAmt`/`PSTA` = UNKNOWN.
- Sin schema/network/SWIFT validation: `PARSE_OK` es solo parsing.

## Deferido en V1

seev.032/035/037/038, cancelaciones, statements, perfiles de red,
market practice propietaria, librerias comerciales de validacion o
traduccion.
