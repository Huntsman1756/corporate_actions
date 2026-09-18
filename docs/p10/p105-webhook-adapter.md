# P10.5 — WEBHOOK adapter

`src/ca_es/delivery/webhook_adapter.py`. POST HTTPS genérico con
`http.client` (no urllib): permite distinguir la fase del fallo.

## Fases y clasificación

```text
connect/request falla (pre-send)   → FAILED_RETRYABLE  CONNECT_*
TLS error (cualquier fase)         → FAILED_PERMANENT  TLS_ERROR:*
bytes enviados, respuesta perdida  → UNKNOWN_OUTCOME   POST_SEND_*
respuesta recibida                 → por status HTTP
```

El cierre de conexión es `finally`-garantizado en todos los caminos.

## Request

```text
POST <path+query> HTTP/1.1
Content-Type: application/json
Idempotency-Key: <delivery_key>
X-CA-ES-Alert-Key: <alert_key truncado 256>
X-CA-ES-Delivery-Key: <delivery_key>
Authorization: Bearer <env>        # solo si token_env configurado
```

`extra_headers` permitido pero no puede sobreescribir
`Authorization`, `Content-Type`, `Host` ni `Content-Length`
(`HEADER_OVERRIDE_REJECTED`).

## Clasificación de status

| status | outcome |
|---|---|
| expected (defecto 200/201/202/204) | SUCCEEDED |
| 408, 425, 429, 500, 502, 503, 504 | FAILED_RETRYABLE |
| 400, 401, 403, 404, 405, 410, 422 | FAILED_PERMANENT |
| otro 4xx | FAILED_PERMANENT (conservador) |
| otro 5xx | FAILED_RETRYABLE (conservador) |
| 3xx | redirect handling (abajo) |

`Retry-After` (segundos u HTTP-date, cap 86400) se parsea y se
devuelve como `retry_after_seconds` — recomendación al dispatcher;
el core nunca duerme.

## Redirects

`max_redirects` por defecto **0** (`REDIRECT_NOT_FOLLOWED`,
cap 3). Si se habilita:

- destino se revalida con `_validate_url` (esquema http/https,
  sin userinfo) → `REDIRECT_UNSAFE_TARGET`;
- solo same-origin (scheme+host+port) → `REDIRECT_CROSS_ORIGIN`;
- host_allowlist se reaplica → `REDIRECT_HOST_NOT_ALLOWED`.

`file://`, `ftp://`, userinfo embebido: rechazados siempre.

## Hardening

- HTTPS por defecto; `http://` solo con
  `allow_insecure_http=true` Y host localhost/127.0.0.1/::1.
- `ssl.create_default_context()` — verificación TLS siempre ON;
  no existe equivalente a `verify=False`.
- `timeout_seconds` (connect+read), `max_response_bytes`
  (defecto 16 KiB — body truncado, nunca persistido).
- `host_allowlist` opcional.
- `url` o `url_env`; credenciales solo `token_env`.
- Errores seguros: solo clase de excepción + código; nunca URL,
  query, headers ni body en `error_detail_safe`.

## Config

```json
{"adapter": "webhook", "config": {
  "url_env": "CA_ES_WEBHOOK_URL",
  "token_env": "CA_ES_WEBHOOK_TOKEN",
  "timeout_seconds": 10,
  "expected_statuses": [200, 202],
  "max_redirects": 0,
  "host_allowlist": ["hooks.example.com"]}}
```
