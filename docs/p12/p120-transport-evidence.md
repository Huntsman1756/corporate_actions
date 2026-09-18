# P12.0 — Transport evidence model + trust ladder

Modelo de evidencia de transporte para P12. No es un workflow
lineal — es una **taxonomía de evidencia**: cada capa responde una
pregunta distinta, puede no aparecer, y ninguna promoción entre
capas es automática.

P11 congelado define el lifecycle del send:

```text
PREPARED -> SPOOLED -> GATEWAY_ACCEPTED | GATEWAY_REJECTED
                      (SWIFT_ACKED | SWIFT_NAKED reservados)
```

P12 mantiene esos estados intactos y añade:

1. **evidencia de transporte** por attempt (typed metadata, no
   estados nuevos del send): lo que el adapter puede probar sobre
   el handoff físico;
2. **SWIFT_ACKED / SWIFT_NAKED** como estados reales del send,
   alcanzables solo con evidencia de un service message FIN 21
   parseado por el adapter JVM/Prowide.

## Taxonomía (L0–L5)

```text
L0 PREPARED
   bytes serializados existen localmente (ledger row)
   produce: ca-es              prueba: mensaje construido/validado
   NO prueba: entrega de ningún tipo

L1 LOCAL_COMMITTED
   commit local duradero (FileSpool: .msg+.meta tras fsync+rename)
   produce: ca-es              prueba: handoff al boundary local
   NO prueba: salida del host, lectura externa

L2 TRANSPORT_COMMITTED
   el protocolo real confirma commit en el boundary remoto:
     SFTP  -> REMOTE_PERSISTED      (rename remoto + stat/read-back)
     MQ    -> MQ_PUT_CONFIRMED      (MQPUT bajo syncpoint + commit)
   produce: adapter + protocolo real (OpenSSH / IBM MQ)
   prueba: el mensaje exacto quedó persistido/encolado en el
           sistema remoto alcanzado
   NO prueba: consumo por gateway, aceptación, red SWIFT

L3 GATEWAY_EVIDENCE
   receipt externo correlado (CA_ES_TRANSPORT_RECEIPT_V1)
   produce: consumidor externo real; confianza = boundary
            operacional (ACL / identidad de servicio separada)
   prueba: el gateway autorizado recibió/rechazó la ingestión
   NO prueba: entrada a la red SWIFT

L4 NETWORK_EVIDENCE
   service message FIN 21 (ACK/NAK) real parseado por Prowide
   produce: la red/interfaz SWIFT (evidencia a nivel red)
   prueba: la interfaz SWIFT aceptó (ACK) o rechazó (NAK) el
           mensaje concreto identificado por MIR/copia/MUR
   NO prueba: entrega al receptor final ni aceptación de negocio

L5 BUSINESS_STATUS
   MT567 / seev.034 (P5.6) — lifecycle separado
   produce: el custodio/mercado
   responde: ¿estado de la INSTRUCCIÓN de negocio?
   NO es "un ACK más fuerte"; otra pregunta, otro lifecycle
```

Reglas duras:

```text
SFTP upload success          != GATEWAY_RECEIVED != SWIFT_ACKED
MQPUT commit                 != GATEWAY_RECEIVED != SWIFT_ACKED
remote file exists           != instruction accepted
SWIFT ACK                    != MT567 / seev.034 accepted
L5                           != "stronger ACK" — otra pregunta
```

Sin promoción automática entre capas. `SPOOLED` en el ledger sigue
significando "commit del adapter completado" — para sftp/mq el
adapter solo devuelve `O_SPOOLED` cuando su evidencia L2 es real
(rename remoto verificado / MQ commit).

## Estados del send (extensión aditiva P12)

```text
PREPARED -> SPOOLED -> GATEWAY_ACCEPTED | GATEWAY_REJECTED
          SPOOLED / GATEWAY_* -> SWIFT_ACKED | SWIFT_NAKED
```

- `SWIFT_ACKED` / `SWIFT_NAKED`: terminales. Solo desde un service
  message FIN 21 correlado determinísticamente.
- Evidencia conflictiva (ACK y NAK para el mismo delivery) se
  preserva completa: segunda evidencia contraria -> QUARANTINED +
  send inmutable en su primer estado SWIFT_*. Sin precedencia
  inventada.
- Un receipt local de test NUNCA se etiqueta como evidencia SWIFT:
  `send-ingest-fin` exige bytes FIN parseados por el adapter JVM;
  la trust source queda registrada (`source: FILE_INGEST` vs un
  futuro ingestor de red).

## Evidencia de transporte por attempt

`send_attempts.transport_metadata_json` (ya existe, aditivo):

```json
{
  "transport_evidence": "REMOTE_PERSISTED",
  "remote_path": "outbox/SND-....msg",
  "remote_size": 1234,
  "read_back_sha256": "...",
  "server": "SSH-2.0-OpenSSH_9.6"
}
```

```json
{
  "transport_evidence": "MQ_PUT_CONFIRMED",
  "queue_manager": "QM1",
  "queue": "CA.OUT",
  "msg_id_hex": "...",
  "correl_id_hex": "..."
}
```

Cada adapter declara su evidencia; el core la persiste verbatim
(segura, truncada) sin reinterpretarla.

## Trust source registrado

Todo receipt lleva la fuente que lo produjo:

```text
FILE_INGEST      operador depositó un fichero (state-machine/lab)
REMOTE_POLL      adapter descargó de un boundary remoto controlado
NETWORK_FIN      service message FIN 21 parseado por Prowide
```

Un `FILE_INGEST` de un FIN ACK ejerce el state machine completo
(parseo real Prowide + correlación real) pero documenta que los
bytes llegaron por fichero — la fuerza de la evidencia depende del
canal, no solo del contenido.
