# P4.3 — Capacidad ISO 20022 / seev (semantic freeze)

Status: DONE
Fecha: 2026-09-17

## Alcance

Segunda capa de transporte (MX/ISO 20022) que desemboca en los
contratos de negocio ya cerrados en P1–P6. **No** se crea un segundo
modelo de corporate actions: MX es otro transporte hacia los mismos
contratos.

```text
MT transport ─┐
              ├─> existing ca-es domain contracts
MX / seev ────┘
```

## Dependencia fijada

```text
com.prowidesoftware:pw-iso20022:SRU2025-10.3.10
  jar  sha256 = 483a2a661a26602311c4fe84360eb6b35cb1dedea410fbf5bd14dbb442cf3a31
  pom  sha256 = 0a3b38af76778d9633a7e5cd58bb0dff189b0736399a8dc66f470b75d4fad328
```

Ambos checksums registrados en `gradle/verification-metadata.xml`.
La deriva de checksum falla el build (dependencia verificada).
Se mantiene `pw-swift-core:SRU2025-10.3.19` sin tocar.
Target Java 11 (la rama 10.3.x es Java 11+ — verificado en build).

## Variantes disponibles en el jar pinneado

Las cuatro parejas existen en `pw-iso20022:SRU2025-10.3.10`:

| Mensaje | Base (.001) | ISO-15022 variant (.002) |
|---|---|---|
| Notification | `seev.031.001.15` | `seev.031.002.15` |
| Instruction | `seev.033.001.13` | `seev.033.002.13` |
| Instr. status advice | `seev.034.001.15` | `seev.034.002.15` |
| Movement confirmation | `seev.036.001.16` | `seev.036.002.16` |

Estructura top-level idéntica en ambas variantes
(`NtfctnGnlInf`/`CorpActnGnlInf`/`AcctDtls`/`CorpActnDtls`/
`CorpActnOptnDtls`/`AddtlInf`); difieren en las versiones de los
component types. Los nombres de elemento que necesita el dominio
(`CorpActnEvtId`, `EvtTp`, `UndrlygScty`, `DtDtls`, `OptnTp`,
`OptnNb`, `DfltPrcgOrStgInstr`, `RspnDdln`, `RateAndAmtDtls`...)
existen con el mismo nombre en ambas.

### Decisión de variante

- **Lectura**: `.001` y `.002` para los cuatro mensajes, read-only.
  El extractor de facts es agnóstico al modelo (walk DOM del árbol
  JAXB marshalleado por Prowide); los paths semánticos son los
  nombres de elemento.
- **Escritura**: **`.002` únicamente**.
  Evidencia: la variante `002` es la designada por ISO 20022 como
  "ISO 15022 Variant" — el submodelo definido para ser semánticamente
  equivalente/interoperable con MT564/565/567/566. Toda la semántica
  probada de ca-es procede de evidencia ISO 15022 (P4–P6); escribir
  `.002` garantiza que todo lo expresable tiene correspondiente MT
  exacto y evita rellenar estructuras `.001` más ricas sin evidencia.
  Escribir `.001` exigiría elegir estructuras no demostradas — sería
  una decisión de perfil de mercado no soportada. V1 no asume ese
  perfil.

## API del modelo (verificado por `javap` sobre el jar pinneado)

- `MxSeev0NN00MVV.parse(String)` / `AbstractMX.parse(String)`
  (autodetección por namespace) / `parse(String, MxReadConfiguration)`.
- `mx.element()` → `org.w3c.dom.Element` (marshal JAXB a DOM).
- `mx.getAppHdr()` → `AppHdr` (`from()`, `to()`, `reference()`,
  `messageName()`, `serviceName()`, `duplicate()`, `creationDate()`).
- `mx.message()`/`document()`/`header()` → serialización XML
  (writer, P4.5).
- `getMxId()` → identificador `seev.NNN.VVV.VV` exacto.
- Codeset `EvtTp/Cd` (`CorporateActionEventType35Code` en `.002`):
  mismos códigos de 4 letras que `22F::CAEV` (DVCA, SPLF, BONU,
  EXRI, MRGR, …) — base de paridad MT↔MX.

## Contrato de facts

`CA_ES_SWIFT_MX_FACTS_V1` (nuevo; análogo a
`CA_ES_SWIFT_MT_FACTS_V1` pero schema separado — no debilitar el
guard de MT):

```text
schema_version        CA_ES_SWIFT_MX_FACTS_V1
standard_family       ISO20022
standard_release      SRU2025
release_state_as_of   <fecha del pin>
library               prowide-iso20022
library_version       SRU2025-10.3.10
adapter_version
generated_at
message_identifier    seev.NNN.VVV.VV exacto (del namespace)
input_sha256
parse_status          PARSE_OK | PARSE_ERROR | UNSUPPORTED_MESSAGE_TYPE
apphdr_facts          facts del Business Application Header (si hay)
facts[]
  model_path          /Document/CorpActnNtfctn/CorpActnGnlInf/... (elementos)
  value               texto del elemento hoja
  occurrence          índice entre hermanos del mismo nombre
  evidence_locator    element_path[occurrence] determinista (DOM depth-first)
  input_sha256
```

Extracción: `AbstractMX.parse` → `mx.element()` (DOM del modelo
Prowide) → walk DOM depth-first. `model_path` = local-names; la
identidad de choice queda en el path (`EvtTp/Cd` vs `EvtTp/Prtry`).
`toJson()` de Prowide queda prohibido como contrato (uso interno
solo si hiciera falta — no se usa).

`PARSE_OK` = solo parsing. **Nunca** se emite `SCHEMA_VALID`,
`NETWORK_VALID` ni `SWIFT_VALID`: Prowide OSS cubre modelo/parseo/
escritura, no validación de red.

## Seguridad XML (verificada en bytecode + tests)

`com.prowidesoftware.swift.utils.SafeXmlUtils` (pw-swift-core,
verificado por `javap -c`):

- `XMLConstants/secure-processing` = true;
- `external-general-entities` = false;
- `disallow-doctype-decl` = true;
- `XMLInputFactory`: `supportDTD` = false,
  `isSupportingExternalEntities` = false, límites de tamaño de
  entidad aplicados.

El path de parseo Prowide (`NamespaceReader`, `MxParseUtils`) usa
`SafeXmlUtils` — **no se escribe parser XML propio**. Además, en el
adapter:

- cap de input (bytes) en stdin;
- timeout del subproceso en el lado Python (igual que MT);
- XML crudo nunca en stderr/logs (solo nombres de clase de excepción);
- XML malformado / DTD / XXE / bombas → `PARSE_ERROR` fail-closed;
- facts deterministas para XML idéntico.

## UNSUPPORTED deliberados (V1)

- seev.032/035/037/038, cancelaciones, statements — fuera del scope
  mínimo de paridad.
- Perfiles de red ISO 20022 / market practice propietarios.
- Librerías comerciales de validación/traducción Prowide.
- Validación XSD de red (no disponible en OSS): solo `PARSE_OK`.
