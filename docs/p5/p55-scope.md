# P5.5 — MT565 Projection / Serialization

Status: **FROZEN — PENDING IMPLEMENTATION**.
Parent: P5.4 Election Instruction Intent DONE.

Pregunta única:

> ¿Qué FIN MT565 corresponde exactamente a una instrucción READY, con
> cada campo trazable a una fuente explícita?

ADR-010 sigue vigente: el core Python no genera SWIFT. El writer vive
en `adapters/iso-adapter-jvm` sobre la dependencia pinneada
`pw-swift-core:SRU2025-10.3.19`.

```text
CA_ES_ELECTION_INSTRUCTION_V1  (READY)
+ CA_ES_SWIFT_MT_FACTS_V1      (el MT564 fuente; input_sha256 liga)
+ CA_ES_SWIFT_MT565_ENVELOPE_V1 (transporte, todo explícito)
        ↓ mt565_project()      [core, Python]
CA_ES_MT565_PROJECTION_V1      (SERIALIZABLE | NOT_SERIALIZABLE)
        ↓ write565()           [JVM, iso-adapter modo "mt565"]
CA_ES_MT565_FIN_V1             (fin + fin_sha256)
```

Solo `SERIALIZABLE` puede llegar al writer JVM.

## Envelope (CA_ES_SWIFT_MT565_ENVELOPE_V1)

Todo dato de transporte/cabecera que no es hecho de negocio ya probado
por la instrucción/opportunity viaja aquí, explícito y sin defaults:

```text
sender_bic        BIC8 o BIC11  (-> bic11; LT12 = bic11 + "X")
receiver_bic      BIC8 o BIC11  (idem)
session_number    4 dígitos
sequence_number   6 dígitos
priority          N | S | U
```

Envelope malformado -> `ValueError` (fail closed: es configuración, no
evidencia). Sin BICs por defecto, sin cuenta por defecto.

## Binding fail-closed

```text
instruction.source_message_input_sha256 == facts.input_sha256
```

Mismatch -> `ValueError(INSTRUCTION_FACTS_MISMATCH)`.

## Mapping preregistrado (evidenciado en pw-swift-core
## SRU2025-10.3.19: MT565.java tag SRU2025-10.3.19 + UHB ISO 15022)

Secuencias del modelo pinneado: GENL, LINK(A1), USECU(B), FIA(B1),
ACCTINFO(B2), BENODET(C), CAINST(D), ADDINFO(E). En CAINST el número de
opción viaja en `13A::CAON` (no `22F::CAON` como en el MT564).

`fields[]` del projection doc = lista ordenada de tags block4; el JVM
solo ensambla:

```text
tag   value                                  source
16R   GENL                                   constant
20C   :SEME//<instruction_id>                instruction.instruction_id
20C   :CORP//<corp>                          facts GENL 20C::CORP
23G   NEWM                                   constant
22F   :CAEV//<caev>                          facts GENL 22F::CAEV
16R   LINK                                   constant
13A   :LINK//564                             constant
20C   :RELA//<seme del MT564>                facts GENL 20C::SEME
16S   LINK                                   constant
16S   GENL                                   constant
16R   USECU                                  constant
35B   ISIN <isin>                            instruction.isin
16R   ACCTINFO                               constant
97A   :SAFE//<account_id>                    instruction.account_id
16S   ACCTINFO                               constant
16S   USECU                                  constant
16R   CAINST                                 constant
13A   :CAON//<option_identifier>             instruction.option_identifier
22F   :CAOP//<option_code_raw>               instruction.option_code_raw
36B   :QINS//UNIT/<qty coma>                 instruction.requested_quantity
16S   CAINST                                 constant
```

Cantidad SWIFT: `format(Decimal,'f')` con `.` -> `,`
(`12500` -> `12500,`; `12500.5` -> `12500,5`). Nunca float.

No se emiten: CAMV (no existe en GENL de MT565), BENODET, ADDINFO,
PREP, porcentajes, importes, narrativa — nada inferido ni inventado.

## projection_status

```text
SERIALIZABLE       sin reasons
NOT_SERIALIZABLE   con reasons:
  INSTRUCTION_NOT_READY          instruction_status != READY
  UNSUPPORTED_MESSAGE_TYPE       facts no es MT564
  UNSUPPORTED_OPTION_KIND        option_kind fuera de CASH/SECURITIES
  MISSING_CORP_REFERENCE         GENL sin 20C::CORP
  CONFLICTING_CORP_REFERENCE     >1 CORP distintos
  MISSING_SOURCE_SEME            GENL sin 20C::SEME
  CONFLICTING_SOURCE_SEME        >1 SEME distintos
  MISSING_CAEV                   GENL sin 22F::CAEV
  CONFLICTING_CAEV               >1 CAEV distintos
  MISSING_INSTRUCTION_FIELD:<n>  isin/account_id/option_identifier/
                                 option_code_raw/requested_quantity
  INVALID_REQUESTED_QUANTITY     no Decimal / <=0
```

Un fact ausente nunca se sustituye por un default.

## Contrato de artifacts

```text
CA_ES_MT565_PROJECTION_V1
  schema, generated_at
  source_instruction_id
  source_canon_logical_sha256          (de la instrucción)
  source_positions_logical_sha256
  source_message_input_sha256
  canonical_event_id
  projection_status
  reasons[]
  envelope {sender_lt, receiver_lt, session_number,
            sequence_number, priority}   (LT12 ya normalizados)
  fields[]  {tag, value, source}

CA_ES_MT565_FIN_V1  (emitido por el JVM)
  schema, generated_at
  fin                      (texto FIN completo)
  fin_sha256
  source_projection_sha256 (sha256 del doc de entrada)
  adapter_version, library_version
  write_status             OK | INPUT_ERROR | ADAPTER_ERROR
```

## JVM adapter

Nuevo modo por argv: `java -jar iso-adapter.jar mt565`
(sin argv = parse, contrato P4.0 intacto).

* stdin = doc CA_ES_MT565_PROJECTION_V1;
* stdout = doc CA_ES_MT565_FIN_V1 siempre JSON;
* exit codes: 0 OK / 2 INPUT_ERROR / 4 ADAPTER_ERROR;
* `projection_status != SERIALIZABLE` o schema distinto -> exit 2;
* construye SwiftMessage con Prowide (SwiftBlock1/SwiftBlock2Input/
  SwiftBlock4+Tag) y serializa `message()`;
* FIN y datos de instrucción nunca a stderr/logs (solo clase de
  excepción en detail).

## Tests preregistrados

Python (`test_p55_mt565.py`):

1. READY + facts completos -> SERIALIZABLE con fields exactos.
2. INSTRUCTION_NOT_READY.
3. INSTRUCTION_FACTS_MISMATCH -> fail closed.
4. facts no MT564 -> UNSUPPORTED_MESSAGE_TYPE.
5. option UNSUPPORTED -> UNSUPPORTED_OPTION_KIND.
6. CORP/SEME/CAEV ausentes y conflictivos.
7. Envelope inválido -> ValueError.
8. Cantidad -> coma SWIFT.
9. Determinismo con --now fijo; inputs no mutados.
10. e2e con jar: project -> write -> fin contiene los tags
    preregistrados y fin_sha256 determinista.

JVM (`Mt565WriterTest`):

1. write565 -> FIN; MT565.parse verifica CAON/CAOP/QINS en CAINST,
   SEME/CORP/CAEV en GENL, RELA en LINK, ISIN+SAFE en USECU/ACCTINFO.
2. FIN determinista para el mismo projection.
3. projection != SERIALIZABLE -> exit 2.
4. JSON inválido -> exit 2; schema distinto -> exit 2.
5. Nada de contenido FIN/instrucción en stderr.

## Fuera de alcance

* partial elections, mínimos/múltiplos/ratios;
* BENODET, ADDINFO, narrative 70E;
* oversubscription (:22H::CAOP//OVER);
* cancelaciones (23G:CANC);
* envío real SWIFT / transporte;
* MT567 (P5.6); ISO 20022.
