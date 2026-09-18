# P12.0 — OSS survey: transport adapters & conformance lab

Survey obligatorio de repos públicos antes de implementar P12.
Política del proyecto: **ADOPT / WRAP / PORT OSS probado antes que
construir infraestructura genérica**. Nada de código se copia sin
verificar licencia; nada propietario se vendoriza ni se redistribuye.

Estado: PREREGISTRADO (cierre al final de P12 con decisiones
confirmadas en `oss-provenance.md`).

## Tabla de decisiones

| repo | licencia | decisión | rol en ca-es |
|---|---|---|---|
| prowide/prowide-core (`pw-swift-core` SRU2025-10.3.19) | Apache-2.0 | ADOPT (ya pinneado) | parseo FIN service 21 ACK/NAK en adapter JVM |
| openssh/openssh-portable | BSD-style (SSH) | ADOPT (test server) | servidor SFTP real en lab/CI |
| paramiko/paramiko | LGPL-2.1 | ADOPT (extra `sftp`) | cliente SFTP + servidor in-process en tests |
| ibm-messaging/mq-mqi-python (`ibmmq`) | Python-2.0 | ADOPT (extra `mq`, lazy) | adapter IBM MQ real |
| ibm-messaging/mq-dev-patterns | Apache-2.0 | REFERENCE | patrones syncpoint/correlación, sin copiar código |
| ibm-messaging/mq-container | Apache-2.0 scripts / producto IBM | REFERENCE (lab opt-in) | queue manager developer local; NUNCA en CI normal |
| swiftinc/api-sample-code | SWIFT (LICENSE.pdf) | REFERENCE_ONLY | contrato Messaging API; sin adapter sin credenciales |
| apache/qpid-proton | Apache-2.0 | DEFERRED_NO_TARGET_PROFILE | AMQP sin boundary real que lo requiera |
| pysftp | BSD | REJECT | wrapper no mantenido sobre paramiko |
| OpenSSH `sftp` CLI como cliente | BSD | REJECT (cliente) | batch frágil, outcomes no estructurados |

## Fichas

### 1. prowide/prowide-core

- **Owner**: Prowide Software (open source).
- **Purpose**: modelo y parser completo FIN MT/ISO 15022; incluye
  service messages (block1 service id 21 = ACK/NAK) vía
  `SwiftMessage.isServiceMessage21()/isAck()/isNack()`,
  `ServiceMessage21` (`getField451` 0=ACK/1=NAK, `getField405` error
  code, `getField177` datetime, `getField108` MUR),
  `getUnparsedTexts()` (copia embebida del original),
  `AckMessageComparator`.
- **License**: Apache-2.0.
- **Activity**: activo, releases SRU anuales; pin actual
  `SRU2025-10.3.19` con gradle verification-metadata sha256.
- **Security**: nada de contenido FIN a stderr/logs (invariante del
  adapter ya implementado).
- **Dependency cost**: cero — ya pinneado (ADR-010).
- **Reuse**: todo el parseo ACK/NAK y extracción de campos de
  correlación. NUNCA se implementa parser FIN en Python.
- **NOT reuse**: correlación ACK↔original (Prowide la deja
  explícitamente a la aplicación); `AckMessageComparator` se evalúa
  pero la correlación vive en el core Python sobre campos extraídos.
- **Decision**: ADOPT (ya adoptado; se extiende su uso).

### 2. openssh/openssh-portable

- **Owner**: OpenBSD / OpenSSH team.
- **Purpose**: implementación de referencia SSH/SFTP (servidor `sshd`
  + subsistema `sftp-server`).
- **License**: BSD-style (SSH license / ISC variants).
- **Activity**: activo, estándar de facto.
- **Dependency cost**: paquete del sistema; no se vendoriza.
- **Reuse**: servidor SFTP real del conformance lab (CI ubuntu y
  local). Cliente `sftp` NO se usa como transporte (ver pysftp).
- **NOT reuse**: el CLI `sftp` como cliente del adapter — outcomes de
  batch no estructurados, atomicidad de rename no controlable,
  host-key handling externo.
- **Decision**: ADOPT como test server; REJECT como cliente.

### 3. paramiko/paramiko

- **Owner**: Jeff Forcier / paramiko org.
- **Purpose**: implementación SSHv2 pure-Python — cliente Y servidor;
  SFTP client completo (`SFTPClient`, `posix_rename`, `stat`,
  `listdir`, channels).
- **License**: LGPL-2.1 — usable como dependencia opcional sin
  copyleft sobre ca-es (no se copia código; es un extra opcional,
  no un requisito del core).
- **Activity**: maduro y mantenido; Python >= 3.9.
- **Security**: host-key verification obligatoria — se configura
  `RejectPolicy` + `load_host_keys` o fingerprint pineado;
  `AutoAddPolicy` prohibido en producción.
- **Dependency cost**: `paramiko` + `cryptography` (wheels para
  win/linux). Extra `sftp`, no requisito del core.
- **Reuse**: `SSHClient`, `Transport`, `SFTPClient`, y las clases
  server-side (`ServerInterface`, `SFTPServerInterface`,
  `SFTPServer`) para levantar un servidor SSH/SFTP REAL in-process
  en tests — mismo wire protocol, sin mocks de transporte.
- **NOT reuse**: `AutoAddPolicy`, `WarningPolicy`.
- **Decision**: ADOPT como extra `sftp`.

### 4. ibm-messaging/mq-mqi-python (`ibmmq`)

- **Owner**: IBM MQ Development (repo oficial ibm-messaging).
- **Purpose**: binding Python oficial del MQI — sucesor mantenido de
  `pymqi`, API-compatible (`import ibmmq as pymqi` en migración).
- **License**: Python-2.0 (per setup.py).
- **Activity**: paquete nuevo (2025) activamente mantenido por IBM;
  PyMQI previo con décadas de uso bancario.
- **Dependency cost**: extensión C — requiere IBM MQ C client
  runtime+SDK >= 9.1 instalado (o MQ Redistributable Client). NO
  instala limpio sin cliente → extra `mq` opcional, import lazy,
  tests con MQI fake inyectado; nunca requisito de CI normal.
- **Reuse**: `connect_with_options`, `Queue` (browse/put/get),
  `MQMD`/`PMO`/`GMO` (syncpoint, matching por CorrelId),
  `MQMIError` con reason codes oficiales.
- **NOT reuse**: nada propietario redistribuible; no se inventan
  headers SWIFT-on-MQ específicos de un perfil bancario.
- **Decision**: ADOPT como extra `mq` opcional.

### 5. ibm-messaging/mq-dev-patterns

- **License**: Apache-2.0.
- **Reuse**: patrones conceptuales — put bajo `MQPMO_SYNCPOINT` +
  commit, correlación por `CorrelId`, clasificación de MQRC.
- **NOT reuse**: código de aplicación.
- **Decision**: REFERENCE.

### 6. ibm-messaging/mq-container

- **License**: scripts Apache-2.0; el producto IBM MQ dentro de la
  imagen bajo *IBM MQ Advanced for Developers* (International
  License Agreement for Non-Warranted Programs) — **no permite
  redistribución; uso restringido a máquina de desarrollo**.
- **Reuse**: lab opt-in local (`P12_MQ_LIVE=1` + `LICENSE=accept`
  explícito del operador) vía `icr.io/ibm-messaging/mq` o build
  propio desde el repo.
- **NOT reuse**: vendorizar la imagen; requerirla en CI pública;
  aceptar la licencia en nombre del operador.
- **Decision**: REFERENCE — lab opt-in documentado, jamás CI normal.

### 7. swiftinc/api-sample-code

- **License**: SWIFT proprietary sample license (`LICENSE.pdf`) —
  no OSS estándar.
- **Purpose**: ejemplos oficiales de Messaging API v2.x — REST sobre
  Alliance Cloud que embebe mensajes FIN/ISO 20022 en llamadas API;
  OAuth2 + certificado de cliente; sandbox público del developer
  portal (`developer.swift.com`) con OpenAPI spec publicado.
- **Reuse**: referencia del contrato público para una futura fase;
  assessment en `p127-swift-api-assessment.md`.
- **NOT reuse**: copiar código (licencia); implementar un adapter
  sin credenciales sandbox verificables.
- **Decision**: REFERENCE_ONLY /
  IMPLEMENTABLE_BUT_REQUIRES_CREDENTIALS (ver p127).

### 8. apache/qpid-proton

- **License**: Apache-2.0. AMQP 1.0 maduro.
- **Reuse**: ninguna — no existe boundary concreto que hable AMQP.
- **Decision**: DEFERRED_NO_TARGET_PROFILE (YAGNI, P12.8).

### 9. pysftp

- **License**: BSD. Wrapper de paramiko sin mantenimiento activo.
- **Decision**: REJECT — paramiko directo da control fino de
  host-key policy, rename y errores.

## Reglas del survey

1. Ningún adapter nuevo redefine el contrato P11; se registra en
   `adapter_registry()` bajo el mismo `SendRequest/SendAdapterResult`.
2. Dependencias opcionales con import lazy; core stdlib-only intacto.
3. Productos propietarios (IBM MQ) jamás en CI pública ni
   redistribuidos.
4. Nada de código copiado de repos no-Apache/BSD compatibles.
