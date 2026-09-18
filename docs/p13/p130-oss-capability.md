# P13.0 — OSS survey: custody position & cash feeds

Survey obligatorio antes de implementar P13. Política del proyecto:
**ADOPT / WRAP / REFERENCE / REJECT OSS probado antes que construir
infraestructura genérica**. Nada de código se copia sin verificar
licencia; nada propietario se vendoriza.

Estado: PREREGISTRADO — las decisiones se confirman al cerrar P13.

## Pregunta del survey

Los feeds de custodia (MT535, semt.002, MT940/950, camt.053/054) deben
terminar proyectando a `CA_ES_POSITIONS_V1` y
`CA_ES_CASH_MOVEMENTS_V2` **sin parsers propios y sin modelos de
dominio paralelos**. ¿Quién ofrece el modelo de mensaje?

## Tabla de decisiones

| repo / fuente | licencia | decisión | rol en ca-es |
|---|---|---|---|
| prowide/prowide-core (`pw-swift-core` SRU2025-10.3.19) | Apache-2.0 | ADOPT (ya pinneado) | modelo+parseo MT535, MT940, MT950 vía adapter JVM |
| prowide/prowide-core-examples | Apache-2.0 | REFERENCE | patrones de API MT535 (sequences 16R/16S), sin copiar código |
| prowide/prowide-iso20022 (`pw-iso20022` SRU2025-10.3.10) | Apache-2.0 | ADOPT (ya pinneado) | modelo+parseo semt.002, camt.053, camt.054 |
| prowide/prowide-iso20022-examples | Apache-2.0 | REFERENCE | patrones `AbstractMX.parse`/`MxId`, sin copiar código |
| ISO 20022 message definitions (iso20022.org) | © ISO, uso informativo | REFERENCE | semántica oficial semt.002/camt.053/camt.054; nada se redistribuye |
| SWIFT Standards MT reference (us5mb_20220722) | © SWIFT | REFERENCE | semántica campos MT535/MT940/MT950; nada se redistribuye |
| FINOS CDM (finos/common-domain-model) | Apache-2.0 / CSL | REFERENCE (semántico) | vocabulario de reconciliación; sin modelo paralelo |
| wolph/mt940 (`mt-940`) | BSD-3-Clause | REFERENCE | validación de semántica field 61/86; NO se adopta (Prowide ya cubre MT940 y el core es stdlib-only) |
| qoomon/banking-swift-messages-java | MIT | REJECT | subset MT940/MT942 redundante con Prowide |
| tahzeer/x940 | GPL-3.0 | REJECT | licencia incompatible (GPL), inmaduro |

## Fichas

### 1. prowide/prowide-core (ADOPT)

- **Pin**: `SRU2025-10.3.19` (gradle verification-metadata sha256).
- **Cobertura verificada en el jar pinneado** (javap/unzip):
  `MT535`, `MT940`, `MT950` en `com.prowidesoftware.swift.model.mt.*`;
  `Field61` con accessors `getValueDate/getEntryDate/
  getDebitCreditMark/getAmount/getTransactionType/
  getReferenceForTheAccountOwner/
  getReferenceOfTheAccountServicingInstitution/
  getSupplementaryDetails`; `Field28E` con
  `getPageNumber/getContinuationIndicator`; `Field93B` con
  `getQualifier/getDataSourceScheme` + componentes cantidad;
  `MT535.getSequenceBList/getSequenceFINList/getSequenceSUBBALList`.
- **Reuse**: el extractor genérico `IsoAdapter.extractFacts` ya emite
  facts por componente con sequence path (16R/16S) y occurrence;
  P13 solo amplía la whitelist `SUPPORTED`.
- **NOT reuse**: no se usa `MT535.getSequenceBList()` para lógica de
  negocio en Java — la proyección semántica vive en el core Python
  sobre facts (consistencia con P4).
- **Decision**: ADOPT.

### 2. prowide/prowide-iso20022 (ADOPT)

- **Pin**: `SRU2025-10.3.10`.
- **Cobertura verificada en el jar**:
  `MxSemt00200101`–`MxSemt00200112` (variante .001) y
  `MxSemt00200203`–`MxSemt00200211` (variante ISO-15022 .002);
  `MxCamt05300101`–`MxCamt05300113`;
  `MxCamt05400101`–`MxCamt05400113`.
- **Reuse**: `MxFactsAdapter` hace DOM-walk genérico del modelo
  marshalleado; P13 amplía la whitelist `SUPPORTED` a las versiones
  documentadas en `p130-capability.md`.
- **NOT reuse**: no se instancian los beans tipados para lógica de
  negocio en Java — la proyección vive en Python sobre `model_path`
  facts (consistencia con P4.3).
- **Decision**: ADOPT.

### 3. prowide examples repos (REFERENCE)

Ambos (`prowide-core-examples`, `prowide-iso20022-examples`) son
Apache-2.0 y activos. Se usan como referencia de API (p.ej. cómo
navegar sequences 16R/16S de MT535, `AbstractMX.parse` con
autodetección por namespace). **No se copia código** ni fixtures:
los fixtures P13 son sintéticos generados por el propio adapter.

### 4. ISO 20022 message definitions (REFERENCE)

`semt.002` = *SecuritiesBalanceCustodyReport* — posiciones en cuenta
de custodia a una fecha; `camt.053` = *BankToCustomerStatement*;
`camt.054` = *BankToCustomerDebitCreditNotification*. Catálogo
oficial consultado para semántica de campos; nada del catálogo se
redistribuye. Versiones soportadas = las que el jar pinneado modela.

### 5. SWIFT Standards MT reference (REFERENCE)

MT535 = *Statement of Holdings*: informa cantidades/instrumentos en
cuenta de custodia a una fecha para reconciliación; soporta
paginación (`28E` page/continuation). MT940 = customer statement con
`61`/`86`; MT950 = statement interbancario sin `86`. Semántica
consultada; fixtures sintéticos propios.

### 6. FINOS CDM (REFERENCE semántico)

Vocabulario de reconciliación de posiciones (custodian vs internal).
No se adopta el modelo: `CA_ES_POSITION_RECON_V1` es aditivo y
mínimo; CDM queda como referencia terminológica.

### 7. wolph/mt940 (REFERENCE)

`mt-940` (BSD-3, activo, stdlib-only, ~100% coverage contra fixtures
bancarios reales). Es el parser MT940 Python más maduro. **No se
adopta**: Prowide ya modela MT940 con Field61/Field86 completos y el
core es stdlib-only; añadirlo duplicaría parseo en dos boundaries.
Se usa como referencia para validar la semántica de field 61
(value date, entry date, D/C mark, transaction type, referencias).

### 8. qoomon/banking-swift-messages-java (REJECT)

Subset MT940/MT942; redundante con Prowide ya pinneado.

### 9. tahzeer/x940 (REJECT)

GPL-3.0 (incompatible con la política de dependencias del core) e
inmaduro.

## Lo que NO se construye

- Parser MT535 / MT940 / MT950 en Python.
- Parser XML o modelo ISO 20022 propio.
- Parser genérico de field 86 (narrativa bancaria = PROFILE_REQUIRED).
- Modelo paralelo de posiciones/cash: se proyecta a los contratos
  existentes.
