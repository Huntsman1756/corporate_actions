# P11.1 — Send contracts (preregistro)

Contratos nuevos; ninguno toca `CA_ES_ELECTION_INSTRUCTION_V1`,
`CA_ES_MT565_FIN_V1`, `CA_ES_SEEV033_XML_V1` ni
`CA_ES_ELECTION_INSTRUCTION_STATUS_V1` (lifecycle de negocio).

## CA_ES_INSTRUCTION_SEND_V1 (ledger row)

```text
delivery_id            PK: "SND-" + sha256(
                          "CA_ES_INSTRUCTION_SEND_V1|" +
                          instruction_id + "|" +
                          content_sha256 + "|" +
                          destination_id + "|" +
                          send_policy_version )
instruction_id         identidad de negocio (caller-provided)
message_reference      MT565 20C::SEME / seev.033 BizMsgIdr
message_schema         CA_ES_MT565_FIN_V1 | CA_ES_SEEV033_XML_V1
message_text           bytes exactos (UTF-8) — persistidos en
                       derivación, nunca reconstruidos
content_sha256         sha256(message_text bytes)
destination_id
adapter_type           filespool (V1)
generation             count(sends de (instruction_id,dest)) + 1
status                 PREPARED|SPOOLED|SPOOL_FAILED_RETRYABLE|
                       SPOOL_FAILED_PERMANENT|GATEWAY_ACCEPTED|
                       GATEWAY_REJECTED|UNKNOWN_OUTCOME|ABANDONED
transport_reference    NULL hasta que un receipt lo aporte
attempt_count / first_prepared_at / spooled_at /
last_attempt_at / next_attempt_after
```

`message_text` se persiste en la fila (los bytes son la evidencia;
la instrucción puede no estar en el state store).

## CA_ES_TRANSPORT_RECEIPT_V1

Esquema versionado para acknowledgements externos depositados en
`receipts/` por un consumidor externo:

```json
{
  "schema": "CA_ES_TRANSPORT_RECEIPT_V1",
  "delivery_id": "SND-...",
  "content_sha256": "<sha256 hex>",
  "status": "ACCEPTED | REJECTED",
  "gateway_reference": null | "<ref del gateway>",
  "received_at": "<ISO8601>",
  "reason": null | "<texto seguro <=300>"
}
```

- El nombre de fichero es `<delivery_id>.ack.json` (espera
  `status=ACCEPTED`) o `<delivery_id>.nak.json` (`REJECTED`).
- La convención de directorio es **protocolo de adapter ca-es**,
  no estándar SWIFT. Documentado como tal.
- `content_sha256` debe igualar el del send: un receipt que cita
  otros bytes → QUARANTINED HASH_MISMATCH.
- Receipt para delivery inexistente, JSON malformado, status
  inconsistente con el sufijo, ambos `.ack` y `.nak`, o receipt
  para send no-SPOOLED → QUARANTINED (movido a `quarantine/`,
  registrado en `send_receipts`, nunca borrado).
- Receipt válido → transición `SPOOLED → GATEWAY_ACCEPTED |
  GATEWAY_REJECTED`, `transport_reference=gateway_reference`,
  fichero movido a `receipts/processed/`.
- Un receipt local de test ejercita la máquina de estados pero
  nunca constituye evidencia de aceptación real: GATEWAY_* en
  producción requiere artefacto creado por consumidor externo.

## CA_ES_SEND_ATTEMPT_V1 (ledger row)

```text
attempt_id          = "SNA-" + delivery_id + "-" + attempt_number
delivery_id         FK
attempt_number      1..n append-only
started_at / completed_at
status              STARTED | SUCCEEDED | FAILED | UNKNOWN
retryable
error_code          corto estable (SPOOL_MKDIR_FAILED,
                    DELIVERY_ID_COLLISION, ...)
error_detail_safe   <=200 chars
transport_metadata  JSON seguro (path, sha256, bytes)
```

## CA_ES_SEND_RESULT_V1 (doc del dispatcher)

```text
schema = CA_ES_SEND_RESULT_V1
generated_at
status                 SUCCESS | PARTIAL | UNCHANGED | DISABLED
receipts_ingested / receipts_quarantined
sends_prepared?  (n/a — prepare es comando aparte)
attempted / spooled / failed_retryable / failed_permanent /
unknown / skipped_terminal
orphan_attempts_recovered / orphan_attempts_marked_unknown
per_destination: [{destination_id, adapter, attempted, spooled,
                   failed_retryable, failed_permanent, unknown}]
```

## CA_ES_SEND_STATUS_V1

```text
prepared / spooled / gateway_accepted / gateway_rejected /
failed_retryable / failed_permanent / unknown_outcome / abandoned
oldest_spooled_at            (edad del spool pendiente de receipt)
destinations[]
attempt counts
status                     HEALTHY|DEGRADED|FAILED|DISABLED
```

## Clasificación de outcomes del adapter

```text
SPOOLED            → attempt SUCCEEDED, send SPOOLED
FAILED_RETRYABLE   → attempt FAILED retryable, send
                     SPOOL_FAILED_RETRYABLE (+next_attempt_after)
FAILED_PERMANENT   → attempt FAILED, send SPOOL_FAILED_PERMANENT
UNKNOWN            → attempt UNKNOWN, send UNKNOWN_OUTCOME
```
