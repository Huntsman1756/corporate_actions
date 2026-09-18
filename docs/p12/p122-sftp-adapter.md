# P12.1/P12.2 — SFTP transport adapter — preregistro

Adapter SFTP real sobre **Paramiko** (SSHv2 pure-Python, cliente y
servidor; LGPL-2.1, extra opcional `sftp`). Servidor de conformidad:
OpenSSH real (lab/CI ubuntu) + servidor Paramiko in-process en
tests (mismo wire protocol, no mock de transporte).

## Config (fail-closed)

```text
host, port                       (requeridos)
username | username_env          (requerido uno)
private_key_path                 (auth por clave; passphrase_env opc)
password_env                     (alternativa env-only; clave preferida)
known_hosts_path                 (verificación por known_hosts)
host_key_fingerprint             (SHA256 pineado; alternativa)
remote_outbox                    (requerido)
remote_receipts                  (requerido)
local_receipt_staging            (requerido — descarga local de receipts)
remote_receipt_disposition       archive|keep  (default archive)
read_back_verify                 bool (default true: re-lee y sha)
connect_timeout_seconds, operation_timeout_seconds
```

Obligatorio: host verification — `known_hosts_path` O
`host_key_fingerprint`. Sin ninguno -> config inválida.
`AutoAddPolicy`/`StrictHostKeyChecking=no` prohibidos.

## Layout remoto (protocolo de adapter, no estándar)

```text
<remote_outbox>/
    <delivery_id>.msg.tmp     upload parcial (pre-commit)
    <delivery_id>.msg         bytes finales (rename)
    <delivery_id>.meta.json   CA_ES_SEND_META_V1 — commit marker
<remote_receipts>/
    <delivery_id>.ack.json | .nak.json    (evidencia externa)
    processed/
```

## Commit remoto

```text
1. put message_text -> <did>.msg.tmp
2. stat remoto + (read_back_verify: open+read+sha256)
3. posix_rename (ext posix-rename@openssh.com; fallback rename)
   -> <did>.msg
4. put meta -> tmp -> rename -> <did>.meta.json   (COMMIT)
5. evidence REMOTE_PERSISTED en transport_metadata
```

Fase de fallo -> outcome:

```text
connect/auth/host-key           -> FAILED_RETRYABLE (auth permanente)
upload tmp falla                -> FAILED_RETRYABLE (nada comprometido)
tmp ok + sha mismatch read-back -> FAILED_PERMANENT COLLISION remota
.msg renombrado, meta falla     -> UNKNOWN (verify() resuelve)
```

## Idempotencia remota

```text
meta remoto existe + sha casa + msg verificado -> SPOOLED replay
meta/msg con sha distinto                      -> COLLISION permanente
.msg sin meta + sha casa -> completar meta     -> SPOOLED
.msg sin meta + sha distinto                   -> COLLISION
```

## verify() post-crash

Conecta y aplica la misma inspección remota ->
`SPOOLED|NOT_SPOOLED|COLLISION|UNKNOWN`.

## Receipt polling (P12.2)

`poll_receipts(dest_config)`:

```text
list remote_receipts/<did>.(ack|nak).json
    -> download a local_receipt_staging (write atómico local)
    -> core valida con el contrato P11 (schema/sha/estado)
    -> válido:   ledger + remote move a processed/ (archive)
    -> inválido: quarantine local; remoto se conserva (nunca
       se borra evidencia remota; keep/archive solo decide si
       el receipt válido se archiva tras ingestión)
```

Fallo de red durante el poll -> fallo técnico del poller, jamás
rechazo de negocio. Duplicados -> idempotente. ACK+NAK mismo
delivery -> conflicto -> quarantine.

## Seguridad (P12.11)

- Path remoto solo de config del operador; ningún campo del
  mensaje/alerta define ruta remota. `delivery_id` (nombre de
  fichero) es `SND-[0-9a-f]{64}` — seguro por construcción.
- Read-back sha por defecto ON; `max_message_bytes` respeta
  `send_policy`.
- Permisos de clave privada verificados donde el FS lo permite;
  contraseña/passphrase solo `*_env`, jamás persistidas.
- Sin traversal: nombres remotos siempre `<delivery_id>.{msg,
  meta.json,ack.json,nak.json}` bajo dirs de config; se rechaza
  cualquier entrada remota que no case el patrón.
