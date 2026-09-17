# P4.7 — seev.036 movement confirmation (scope preregistrado)

Status: DONE

## Frontera

```text
seev.036 XML -> CA_ES_SWIFT_MX_FACTS_V1
    -> project_mx_message + bind_event (BOUND requerido)
    -> CA_ES_SWIFT_CASH_CANDIDATE_V1          (mx_cash_candidate)
    -> CA_ES_SWIFT_SECURITY_MOVEMENT_CANDIDATE_V1
                                            (mx_security_movement_candidate)
    -> pipelines P3/P6 existentes, sin cambios
```

Entrada: `seev.036.001.16` / `seev.036.002.16`, `parse_status=PARSE_OK`.
`project_mx_message` se extiende aditivamente: `supported_mids`
parametrizable (default = SUPPORTED_031, comportamiento P4.4 intacto)
y sufijo ISIN alternativo `CorpActnGnlInf/FinInstrmId/ISIN` (en
seev.036 el underlying va directo en `CorpActnGnlInf`, sin
`UndrlygScty`; verificado por javap en
`CorporateActionGeneralInformation190`).

## Mapping seev.036 ↔ MT566 (verificado javap SRU2025-10.3.10)

```text
CorpActnMvmntConf/
  MvmntConfId                    ≈ 20C::SEME (referencia del mensaje)
  InstrId/Id                     ≈ link a instruccion (no binding key)
  CorpActnGnlInf/CorpActnEvtId   ≈ 20C::CORP
  CorpActnGnlInf/EvtTp/Cd        ≈ 22F::CAEV
  CorpActnGnlInf/FinInstrmId/ISIN≈ 35B underlying (binding)
  AcctDtls/SfkpgAcct             ≈ 97A::SAFE
  CorpActnConfDtls/OptnNb/Nb     ≈ 13A::CAON   (caon doc-level)
  CorpActnConfDtls/OptnTp/Cd     ≈ 22F::CAOP   (caop doc-level)
```

## Cash movement (`CshMvmntDtls[k]`, CashOption110)

| Elemento | Semantica | Equiv. MT566 |
|---|---|---|
| `AmtDtls/PstngAmt` (+`@Ccy`) | importe abonado, basis no declarado | `19B::PSTA` → UNKNOWN |
| `AmtDtls/NetAmt` | neto explicito | `19B::NETO` → NET |
| `AmtDtls/GrssAmt` | bruto explicito | `19B::GRSS` → GROSS |
| `CdtDbtInd` | CRDT/DBIT explicito (raw preservado) | `22H::CRDB` (no proyectado en P4.2) |
| `DtDtls/PstngDt/Dt` o `PmtDt` | value date informativa | `98A::VALU`/`PAYD` |

Misma prioridad determinista que P4.2: `PstngAmt` → `NetAmt` →
`GrssAmt`. Basis nunca inferida: `PstngAmt` es UNKNOWN porque el
elemento no declara gross/net (igual que PSTA). Multiples
`CshMvmntDtls[k]` → `MULTIPLE_CASH_MOVEMENTS` (INDETERMINATE), nunca
agregacion. UNKNOWN sigue siendo PROJECTABLE (P3.1 lo trata
honestamente). `direction` se preserva raw en el movement emitido
(campo aditivo, P3 no lo requiere).

## Security movement (`SctiesMvmntDtls[k]`, SecuritiesOption115)

| Elemento | Semantica | Equiv. MT566 |
|---|---|---|
| `CdtDbtInd` | `CRDT`→RECEIPT, `DBIT`→DELIVERY | `22H::CRDB//CRED`/`DEBT` |
| `FinInstrmId/ISIN` | instrumento movido | `35B` del SECMOVE |
| `PstngQty/Qty/Unit` | cantidad en unidades | `36B::PSTA//UNIT` |
| `DtDtls/PstngDt/Dt` (`/DtTm` raw si no hay `Dt`) | posting date | `98A::POST` |

Un candidato por ocurrencia `SctiesMvmntDtls[k]` (indice del
evidence_locator, analogo a las ventanas SECMOVE por tag index).
`PstngQty/Qty` con otro choice (`FceAmt`, `AmtsdVal`...) →
`UNSUPPORTED_QUANTITY_TYPE`. Direccion solo desde `CdtDbtInd`
explicito — nunca del signo ni del CAEV. Sin `CdtDbtInd` →
`MISSING_DIRECTION`; codigo distinto → `UNSUPPORTED_DIRECTION_CODE`.
Sin agregacion entre ocurrencias.

## Paridad

Escenario MT566 (fixture `mt566-secmove.fin`, split 10:1) y seev.036
equivalente deben producir el mismo outcome de dominio: candidato
PROJECTABLE con RECEIPT 1000 UNIT ES0113900J37 sobre la misma cuenta
y evento canonico.
