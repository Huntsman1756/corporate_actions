# P12.3/P12.4 — IBM MQ adapter + lab opt-in — preregistro

Adapter real contra IBM MQ vía el binding oficial `ibmmq`
(mq-mqi-python, sucesor de PyMQI). Extra opcional `mq`; import
lazy; el core sigue stdlib-only. NUNCA se implementa el wire
protocol.

## Config (fail-closed, secretos solo env)

```text
queue_manager        (requerido)
channel              (requerido, p.ej. DEV.APP.SVRCONN)
connection_name      "host(puerto)" o CCDT url
request_queue        (requerido)
reply_queue          (opcional — polling de receipts futuro)
username_env         (opcional)
password_env         (opcional)
ssl_cipher_spec      (opcional — TLS explícito)
key_repository       (opcional — keystore TLS)
connect_timeout      (segundos)
```

Sin credenciales embebidas ni en el ledger ni en excepciones
persistidas (`error_detail_safe` truncado, sin password).

## Identidad MQ

- `CorrelId` determinista = `"CAES" + sha256(delivery_id)[:20]`
  (24 bytes) — permite dedup/idempotencia y verify() por browse.
- `MsgId` lo asigna el queue manager; se persiste como evidencia
  (hex) tras el commit.
- Sin headers SWIFT-propietarios ni RFH2 inventados. Un perfil
  Alliance/MQ concreto sería un adapter/profile aparte.

## Semántica

```text
deliver():
    browse por CorrelId -> ya existe + sha casa  -> MQ_PUT_CONFIRMED (replay)
                         -> sha distinto       -> COLLISION permanente
    MQPUT bajo MQPMO_SYNCPOINT -> commit -> MQ_PUT_CONFIRMED
    error pre-commit según MQRC -> FAILED_RETRYABLE | FAILED_PERMANENT
    error en/durante commit    -> UNKNOWN (verify() resuelve)

verify():
    browse por CorrelId + sha payload ->
        SPOOLED | COLLISION | NOT_SPOOLED | UNKNOWN
```

`MQ_PUT_CONFIRMED` prueba: el queue manager confirmó el put bajo
transacción. NO prueba consumo por gateway ni aceptación SWIFT.

### Clasificación MQRC (semántica oficial IBM)

| reason | nombre | clase |
|---|---|---|
| 2035 | MQRC_NOT_AUTHORIZED | permanente |
| 2058 | MQRC_Q_MGR_NAME_ERROR | permanente |
| 2085 | MQRC_UNKNOWN_OBJECT_NAME | permanente |
| 2087 | MQRC_UNKNOWN_REMOTE_Q_MGR | permanente |
| 2009 | MQRC_CONNECTION_BROKEN | UNKNOWN si post-put / retryable si pre-put |
| 2059 | MQRC_Q_MGR_NOT_AVAILABLE | retryable |
| 2161/2162 | MQRC_Q_MGR_QUIESCING / MQRC_Q_MGR_STOPPING | retryable |
| 2053 | MQRC_Q_FULL | retryable |
| 2051 | MQRC_PUT_INHIBITED | retryable |
| otros | — | permanente conservador |

Reason numérico persistido en `transport_metadata_json`.

Sin reconnect infinito: el dispatcher P11 ya hace backoff; el
adapter no reintenta internamente.

## Lab opt-in (P12.4)

`scripts/p12_mq_lab.py` — solo local, nunca CI pública:

```text
IBM MQ Advanced for Developers (icr.io/ibm-messaging/mq)
LICENSE=accept lo pone el OPERADOR (licencia IBM, no
redistribuible, uso restringido a máquina de desarrollo)

P12_MQ_LIVE=1 + cliente ibmmq instalado + imagen arrancada
    -> MQPUT -> consumer independiente lee bytes exactos
    -> sha idéntico -> replay idempotente -> escenarios de corte
```

CI normal: adapter con MQI fake inyectado (misma superficie
`connect/Queue/put/browse/commit`, MQMIError con reason codes).
