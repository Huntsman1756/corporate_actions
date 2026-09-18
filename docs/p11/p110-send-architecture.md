# P11 — Send Ledger / Transport Boundary (arquitectura)

P11 convierte mensajes CA ya serializados (MT565 FIN / seev.033
XML, producidos exclusivamente por el adapter JVM, ADR-010) en
envíos durables, idempotentes y auditables hacia un boundary de
integración.

P11 **no** es un gateway de mensajería. No implementa SWIFT, no
serializa mensajes y no interpreta status de negocio.

```text
CA_ES_ELECTION_INSTRUCTION_V1   (P5.4, instruction_id = SEME)
        ↓
MT565 FIN / seev.033 XML        (adapter JVM — bytes ya fijos)
        ↓
P11 send ledger (SQLite, schema v4)
        ↓
TRANSPORT ADAPTER               (V1: FileSpoolTransport)
        ↓
boundary (spool dir)
        ↓
external consumer -> receipt (ca-transport-receipt)
        ↓
GATEWAY_ACCEPTED / GATEWAY_REJECTED   (solo evidencia externa)
        ↓
MT567 / seev.034 = BUSINESS instruction status (P5.6, lifecycle
separado — nunca transport)
```

## Separación de niveles (regla de la fase)

```text
PREPARED           mensaje validado localmente, fila en ledger
SPOOLED            bytes persistidos durable+atómicamente en el
                   boundary configurado — NADA MÁS. No es
                   submission a SWIFT ni aceptación de gateway.
GATEWAY_ACCEPTED   solo si un consumidor externo real deposita
GATEWAY_REJECTED   un receipt válido en el boundary
SWIFT_ACKED/NAKED  solo si se ingiere ACK/NAK FIN real — DEFERRED
                   (no hay ingestión FIN ACK en V1)
BUSINESS_STATUS    MT567/seev.034 vía P5.6 — lifecycle aparte
```

`TRANSPORT_ACCEPTED != INSTRUCTION_ACCEPTED`. Un ACK de transporte
no es `PACK` de MT567.

## Referencias (separadas, siempre)

```text
delivery_id         identidad interna inmutable del envío lógico;
                    clave de idempotencia; determinista
message_reference   MT565 20C::SEME / seev.033 BizMsgIdr
                    (= instruction_id en V1, binding explícito)
transport_reference la devuelve el gateway cuando exista;
                    NULL hasta entonces
content_sha256      digest inmutable de los bytes exactos
```

## delivery_id

```text
delivery_id = "SND-" + sha256(
    "CA_ES_INSTRUCTION_SEND_V1|" +
    instruction_id + "|" +
    content_sha256 + "|" +
    destination_id + "|" +
    send_policy_version )
```

Mismo instruction + mismos bytes + mismo destino → mismo
delivery_id → dedup. Bytes distintos → nuevo delivery_id → nueva
generación por (instruction_id, destination_id). Sin números de
intento en la identidad.

## Estados del send

```text
PREPARED                  derivado, sin bytes en boundary
SPOOLED                   handoff durable verificado
SPOOL_FAILED_RETRYABLE    error transitorio FS → retry
SPOOL_FAILED_PERMANENT    colisión/config → sin auto-retry
GATEWAY_ACCEPTED          receipt externo ACCEPTED válido
GATEWAY_REJECTED          receipt externo REJECTED válido
UNKNOWN_OUTCOME           crash tras STARTED sin poder verificar
ABANDONED                 decisión operadora terminal
```

Terminales: GATEWAY_ACCEPTED, GATEWAY_REJECTED, ABANDONED.
SPOOLED espera receipt (no terminal de lifecycle).

## Crash recovery verificable

El side effect de FileSpool es comprobable (¿existe
`<delivery_id>.msg` con el content_sha256 del ledger?). Orphan
STARTED → `adapter.verify()`:

- msg+meta existen y hash coincide → SPOOLED (recovery real)
- incompletos/ausentes → retry seguro (el rename nunca ocurrió)
- bytes distintos bajo mismo delivery_id → permanente
  DELIVERY_ID_COLLISION (fail closed)

Para transportes futuros sin verify (MQ), orphan STARTED queda
UNKNOWN_OUTCOME — el contrato lo soporta.

## V1 scope

- FileSpoolTransport único adapter.
- MQ (pymqi), SFTP, REST: plugins futuros conformes al mismo
  send-ledger contract. NO se implementan sin endpoint/protocolo
  real contra el que validar.
- SWIFT_ACKED/NAKED: estados del contrato, sin ingestor en V1.
- Receipt directory convention = protocolo de adapter NUESTRO,
  no estándar SWIFT asumido.
