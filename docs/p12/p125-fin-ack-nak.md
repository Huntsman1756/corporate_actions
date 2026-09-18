# P12.5 — FIN service ACK/NAK (service id 21) — preregistro

Objetivo: evidencia de red SWIFT real (L4) sobre el send ledger P11,
sin implementar un parser FIN en Python y sin fingir correlación.

Pipeline:

```text
FIN service message (bytes)
    -> adapter JVM modo `finsvc` (Prowide pinneado)
    -> CA_ES_FIN_SERVICE_RECEIPT_V1 (campos extraídos, sin decidir)
    -> correlación determinista en el core (ops_fin.py)
    -> SWIFT_ACKED | SWIFT_NAKED en el send ledger
```

## Modelo Prowide (verificado contra docs + javadoc SRU2025)

- ACK/NAK = service id **21** en block1 (`{1:F21<LT><sess><seq>}`).
- `SwiftMessage.isServiceMessage21()`, `isAck()`, `isNack()`.
- Block4 del service message: `{177:dateTime}`, `{451:0|1}`
  (0=ACK, 1=NAK), `{405:<error>}` en NAK, `{108:<MUR>}` opcional.
- Identificación del original (según la interfaz SWIFT):
  1. **copia completa del mensaje original** como unparsed text
     (formato SAA AFT) → `getUnparsedTexts().getAsFINString()`;
  2. **MUR** — `SwiftMessage.getMUR()` / field 108;
  3. **UUID** en el texto no parseado.
- Prowide NO correla — la aplicación decide.

## Contrato del adapter JVM (`finsvc`)

stdin: bytes crudos del service message. stdout: siempre JSON.

```json
{
  "schema": "CA_ES_FIN_SERVICE_RECEIPT_V1",
  "input_sha256": "<sha256 del service message>",
  "parse_status": "OK | PARSE_ERROR | NOT_SERVICE_MESSAGE_21",
  "service_id": "21",
  "is_ack": true,
  "is_nack": false,
  "field_177": "1104180901",
  "field_451": "0",
  "field_405": null,
  "field_108": null,
  "mur": null,
  "embedded_copy": {
    "present": true,
    "sha256": "<sha256 de la copia embebida>",
    "mir_lt": "LITEBEBBAXXX",
    "mir_session": "0066",
    "mir_sequence": "000079",
    "message_type": "565",
    "seme": "INSTR-0001",
    "block4_sha256": "<sha256 del block4 normalizado>"
  }
}
```

El adapter extrae, nunca decide la correlación. Diagnósticos a
stderr sin contenido FIN (invariante ADR-010).

## Correlación en el core (determinista, fail-closed)

Del mensaje original embebido se usa su **MIR**
(`LT + session + sequence` de block1) — el identificador de red del
mensaje input. Los sends almacenan `message_text`; el MIR se
extrae de su block1 en el core (regex estructural `{1:F01LT SESS SEQ}`,
no parseo semántico).

```text
candidatos = sends con MIR == MIR de la copia embebida
    0 -> NO_MATCH (receipt -> quarantine, send intocado)
    1 -> si copia presente: cross-check SEME == message_reference
         mismatch -> CONFLICTING (quarantine)
         match    -> SWIFT_ACKED | SWIFT_NAKED
   >1 -> desambiguar por block4_sha256 == sha del block4
         del message_text almacenado
         único  -> transición;   resto -> AMBIGUOUS (quarantine)
```

Solo-MUR o solo-UUID (sin copia embebida): nuestros MT565 no llevan
MUR propio (block2 input sin field 108) → `NO_CORRELATION_EVIDENCE`,
quarantine honesto. Si una fase futura añade MUR al envelope, la
correlación MUR se activa sin cambiar el ledger.

Transiciones permitidas:

```text
SPOOLED / GATEWAY_ACCEPTED | GATEWAY_REJECTED
        -> SWIFT_ACKED | SWIFT_NAKED   (terminal)
```

Conflictos: send ya `SWIFT_ACKED` y llega NAK (o al revés) →
receipt registrado `CONFLICTING` + quarantine; el send conserva su
primera evidencia de red. Duplicado byte-idéntico → idempotente.

`send_receipts.status` nuevos valores: `SWIFT_ACK`, `SWIFT_NAK`,
`CONFLICTING` (además de los existentes). `external_receipt_json`
del send guarda el resumen del service message (sin payload FIN
completo; sha256 + campos de correlación + `source`).

## Trust source

`send-ingest-fin <file>` produce receipts con `source: FILE_INGEST`
— ejerce parseo+correlación reales pero documenta que los bytes
llegaron por fichero, no por la red. Un ingestor de red futuro
emitiría `NETWORK_FIN`.
