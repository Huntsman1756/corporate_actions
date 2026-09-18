# P12.7 — SWIFT Messaging API — assessment

Investigación del repo público oficial `swiftinc/api-sample-code`
(monorepo de ejemplos: java/spring-boot, quarkus, dotnet, nodejs,
python) y del contrato público de la Messaging API
(`developer.swift.com`).

## Hallazgos

| dimensión | estado |
|---|---|
| contrato público | OpenAPI spec publicado (Messaging API v2.x) |
| sandbox | sí — freely accessible con app del developer portal |
| autenticación | OAuth2 client credentials + mTLS (cert self-signed del sandbox) |
| endpoint submission | sí — embebe mensaje FIN/ISO 20022 en llamada REST sobre Alliance Cloud |
| delivery/status | sí — endpoints de status/delivery en la spec |
| idempotencia/correlación | identificadores de correlación en la spec; semántica exacta requiere validación contra sandbox |
| FIN y/o ISO 20022 | ambos (embed de mensajes) |

## Clasificación

```text
IMPLEMENTABLE_BUT_REQUIRES_CREDENTIALS
```

El contrato público existe y es sustancial, pero:

1. la licencia del sample code es propietaria SWIFT
   (`LICENSE.pdf`), no OSS — no se copia código;
2. probar un adapter exige cuenta del developer portal +
   consumer key/secret + certificado de cliente — credenciales que
   no existen en este entorno;
3. sin sandbox real no se puede validar la semántica de
   correlación/entrega, y un adapter no verificado contra el
   contrato real sería exactamente el tipo de "integración
   inventada" que el proyecto prohíbe.

## Decisión P12

```text
NO ADAPTER en P12 — REFERENCE_ONLY.
```

Una fase futura con credenciales sandbox podría implementar un
adapter conforme al contrato P11/P12 (mismos estados: handoff =
`SPOOLED`, respuesta del API = evidencia L3, ACK/NAK FIN = L4).
El sample code sirve como referencia de endpoints/flujos OAuth,
nunca como código base.

Los tests de ese adapter futuro deberían combinar un servidor de
contrato local (OpenAPI mock) + sandbox real opt-in — mismo patrón
que el MQ lab.
