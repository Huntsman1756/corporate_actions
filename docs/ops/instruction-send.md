# Instruction Send — guía de operador (P11)

Envío de mensajes CA serializados (MT565 FIN / seev.033 XML,
producidos por el adapter JVM — ADR-010) hacia un **integration
boundary** por transport adapter. V1 implementa
`FileSpoolTransport` como adapter productivo de referencia.

## Semántica fundamental

```text
SPOOLED             ≠  submission a SWIFT
GATEWAY_ACCEPTED    ≠  INSTRUCTION_ACCEPTED (MT567/seev.034)
transport ACK       ≠  status de negocio
```

- `PREPARED` — mensaje construido y validado localmente.
- `SPOOLED` — bytes entregados **durable y atómicamente** al
  boundary filesystem configurado. Es el máximo estado alcanzable
  sin consumidor externo. **Nunca** significa enviado a SWIFT.
- `GATEWAY_ACCEPTED / GATEWAY_REJECTED` — solo cuando un
  consumidor externo real deposita un receipt válido en
  `receipts/`.
- `SWIFT_ACKED / SWIFT_NAKED` — solo cuando un service message
  FIN 21 real se parsea por Prowide (`send-ingest-fin`) y
  correlaciona determinísticamente (MIR + SEME). Es evidencia de
  **red** (L4), no de negocio.
- `MT567 / seev.034` (status de instrucción de negocio) vive en
  P5.6 — lifecycle separado, jamás modelado como ACK de
  transporte.

## Referencias (separadas)

```text
delivery_id          SND-<sha256>  identidad interna + idempotencia
message_reference    MT565 20C::SEME / seev.033 BizMsgIdr
transport_reference  NULL hasta que un receipt externo lo aporte
content_sha256       digest de los bytes exactos transmitidos
```

## Setup

```json
"send": {
  "enabled": true,
  "destinations": [{
    "destination_id": "gw-file-1",
    "adapter": "filespool",
    "enabled": true,
    "message_schemas": ["*"],
    "config": {"spool_directory": "/var/lib/ca-es/send/spool"}
  }],
  "retry": {"max_attempts": 5, "base_delay_seconds": 300,
            "max_delay_seconds": 3600, "backoff_factor": 2.0},
  "send_policy": {"max_message_bytes": 65536}
}
```

`message_schemas` admite `"*"` o
`CA_ES_MT565_FIN_V1`/`CA_ES_SEEV033_XML_V1` exactos. Sin routing
oculto; adapter desconocido → config rechazada (fail-closed).

## Layout del spool

```text
<spool>/
  outbox/<delivery_id>.msg        bytes exactos
        <delivery_id>.meta.json   CA_ES_SEND_META_V1
  receipts/<delivery_id>.ack.json | .nak.json   (externos)
          processed/
  quarantine/
```

Escritura transaccional: tmp en el mismo directorio →
flush+fsync → `os.replace` atómico → `.msg` primero, `.meta`
después (meta = commit) → fsync del directorio.

**Precisión de "durable"**: en POSIX, `fsync(fichero)` + rename
atómico + `fsync(dir)` persisten el rename ante fallo de sistema.
En Windows el fsync de directorio no está expuesto (best-effort);
la durabilidad del rename es la que el SO/filesystem garantice
para `os.replace`. No se afirma más garantía de la que cada
plataforma proporciona.

La convención `receipts/*.ack.json|*.nak.json` es **protocolo de
adapter ca-es**, no un estándar SWIFT. Un gateway real traduciría
su respuesta nativa a `CA_ES_TRANSPORT_RECEIPT_V1`.

## Idempotencia

```text
delivery_id inexistente                  → crear
delivery_id existente + mismo sha256     → replay no-op
delivery_id existente + sha256 distinto  → FAIL CLOSED
                                           (DELIVERY_ID_COLLISION)
```

Nunca overwrite silencioso. `.msg` huérfano sin `.meta` (crash
entre commits) → verify() = NOT_SPOOLED → el reintento completa
el meta (mismo sha) o falla cerrado (sha distinto).

## Receipts (evidencia externa)

```json
{"schema": "CA_ES_TRANSPORT_RECEIPT_V1",
 "delivery_id": "SND-...", "content_sha256": "<sha>",
 "status": "ACCEPTED|REJECTED",
 "gateway_reference": null, "received_at": "<ISO>", "reason": null}
```

Válido → `SPOOLED → GATEWAY_*` + `transport_reference` + fichero
a `receipts/processed/`. Malformado, schema incorrecto,
delivery_id desconocido, hash distinto, sufijo/status
inconsistente, ambos ack+nak, o receipt para send no-SPOOLED →
`quarantine/` + fila `QUARANTINED` en `send_receipts` (nunca
borrado). Receipt byte-idéntico re-depositado tras GATEWAY_* →
consumo idempotente sin transición.

**Un receipt local de test ejercita la máquina de estados pero
nunca constituye evidencia de aceptación SWIFT real.**

### Trust boundary del receipt

El software demuestra validez + binding `delivery_id` +
`content_sha256` + correlación. No demuestra **quién** depositó
el fichero — eso lo garantiza el trust boundary operacional:

```text
Receipt local/test        → evidencia de state machine
Receipt en producción
  + ACL / identidad de servicio separada / consumidor externo
                          → evidencia de gateway
ACK/NAK FIN real          → evidencia de red SWIFT
```

`GATEWAY_*` pesa como evidencia solo si el despliegue controla
quién escribe en `receipts/` (ACL, servicio separado).

## Comandos

```bash
ca-es send-prepare  --state <dir> --config ops.json \
    --message mt565-doc.json --instruction-id INS-0001
ca-es send-dispatch --state <dir> --config ops.json \
    [--delivery-id SND-...]
ca-es send-status   --state <dir> [--config ops.json]
ca-es send-show     --state <dir> --delivery-id SND-...
ca-es send-retry    --state <dir> --delivery-id SND-... \
    [--force-unknown] [--actor <quien>]
ca-es send-abandon  --state <dir> --delivery-id SND-... \
    [--actor <quien>] [--note "..."]

# P12: transportes reales + polling + evidencia de red
ca-es send-poll     --state <dir> --config ops.json
ca-es send-ingest-fin --state <dir> --fin <service-message.fin>
```

`send-prepare` y `send-dispatch` son pasos separados: preparar
registra PREPARED por destino routed (idempotente por
`delivery_id`); despachar ejecuta orphan recovery → receipt
ingestion → dispatch de elegibles, con `STARTED` durable
(checkpoint) antes de cada side effect.

## Recuperación y retry

- Crash tras `STARTED` → la siguiente pasada llama
  `adapter.verify()`: `SPOOLED` (recovered), `NOT_SPOOLED`
  (reintento seguro), `COLLISION` (permanente), `UNKNOWN`
  (→ `UNKNOWN_OUTCOME`, sin auto-retry).
- `SPOOL_FAILED_RETRYABLE` → backoff
  `min(base·factor^(n-1), cap)`; `max_attempts` → permanente.
- `UNKNOWN_OUTCOME` → solo `send-retry --force-unknown` o
  `send-abandon` (auditoría append-only).

## Limitaciones deliberadas

- Adapters: `filespool`, `sftp` (Paramiko, extra `sftp`), `mq`
  (ibmmq, extra `mq` — requiere cliente IBM MQ C instalado).
  Ambos opcionales y lazy; sin la dependencia → fail-closed.
  REST/SWIFT API: sin adapter (contrato público insuficiente
  sin sandbox — ver docs/p12/p127).
- `send-poll` ingiere receipts filespool locales y receipts
  remotos SFTP (staging local → mismo validador → archive
  remoto solo si la ingesta fue válida; `disposition=keep`
  deja el remoto intacto). Una pasada, idempotente, nunca un
  daemon.
- `send-ingest-fin` parsea un service message FIN 21 vía el
  adapter JVM/Prowide y correlaciona MIR+SEME → SWIFT_ACKED/
  SWIFT_NAKED. `source=FILE_INGEST`: ejerce la máquina de
  estados con parseo/correlación reales; la fuerza de la
  evidencia depende del canal por el que llegó el fichero.
- At-least-once; no exactly-once.
- `send-prepare` acepta docs `CA_ES_MT565_FIN_V1` /
  `CA_ES_SEEV033_XML_V1` con `write_status=OK` y binding
  `message_reference` por contención conservadora
  (`:20C::SEME//<id>` / `<id>` en XML).
