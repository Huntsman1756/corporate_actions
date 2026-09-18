# P10.6 — SMTP adapter

`src/ca_es/delivery/smtp_adapter.py`. Stdlib `smtplib` +
`email.message.EmailMessage` + `ssl.create_default_context()`.

## Seguridad

- `security: starttls` (defecto) | `smtps` | `plain`.
- `plain` solo con `allow_plaintext_localhost=true` Y host
  localhost → si no, `PLAINTEXT_NOT_ALLOWED`.
- Credenciales solo `username_env` + `password_env`; si falta
  cualquiera → `SMTP_ENV_MISSING` sin conectar.
- La password nunca entra en mensaje, receipt ni error_detail.

## Mensaje

```text
From: <from_address>
To: <to_addresses>
Message-ID: <<delivery_key>@<message_id_domain>>   # determinista
Subject: [ca-es] <category> <subject_key>           # <=150 chars
Body: texto plano — campos del payload minimizado + evidence_refs
```

Message-ID derivado de `delivery_key` → duplicados reconocibles
por el servidor/receptor. Sin adjuntos en V1.

## Clasificación

| fase | condición | outcome |
|---|---|---|
| connect | timeout/DNS/refused | FAILED_RETRYABLE `SMTP_CONNECT_FAILED` |
| connect | TLS | FAILED_PERMANENT `SMTP_TLS_ERROR` |
| greeting | SMTPException | FAILED_RETRYABLE `SMTP_GREETING_FAILED` |
| STARTTLS | TLS error | FAILED_PERMANENT `SMTP_TLS_ERROR` |
| STARTTLS | SMTPException | FAILED_PERMANENT `SMTP_STARTTLS_FAILED` |
| auth | SMTPAuthenticationError | FAILED_PERMANENT `SMTP_AUTH_<code>` |
| auth | otra SMTPException | FAILED_RETRYABLE `SMTP_AUTH_ERROR` |
| send | SMTPRecipientsRefused | FAILED_PERMANENT |
| send | SMTPSenderRefused | FAILED_PERMANENT |
| send | SMTPResponseException 4xx | FAILED_RETRYABLE `SMTP_<code>` |
| send | SMTPResponseException 5xx | FAILED_PERMANENT `SMTP_<code>` |
| send | otra excepción (post-DATA) | UNKNOWN `SMTP_SEND_UNCERTAIN` |
| send | refused dict parcial | FAILED_PERMANENT `SMTP_PARTIAL_REFUSED` + receipt accepted |

`client.quit()` best-effort en `finally`.

## Tests

`transport_factory` inyectable (dict key no-JSON, no forma parte
de `CONFIG_KEYS`): callable → objeto interfaz smtplib. CI nunca
abre sockets SMTP.
