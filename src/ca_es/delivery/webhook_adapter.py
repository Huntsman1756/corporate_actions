"""P10.5 — WEBHOOK delivery adapter (HTTPS generico, stdlib).

`http.client` en vez de urllib: permite distinguir la fase del fallo
— conexion/pre-send -> FAILED_RETRYABLE; tras bytes enviados ->
UNKNOWN (nunca se asume que el servidor no recibio).

Hardening: HTTPS por defecto (http solo localhost explicito), sin
userinfo, sin redirects por defecto, redirects same-origin limitados,
timeouts, cap de respuesta, Retry-After parseado como recomendacion
(el core no duerme), credenciales solo via *_env, TLS verify ON.
"""
from __future__ import annotations

import http.client
import os
import socket
import ssl
from urllib.parse import urljoin, urlparse

from ..ops_delivery import (
    AdapterResult, O_FAILED_PERMANENT, O_FAILED_RETRYABLE,
    O_SUCCEEDED, O_UNKNOWN)

CONFIG_KEYS = {
    "url", "url_env", "token_env", "timeout_seconds",
    "max_response_bytes", "expected_statuses", "max_redirects",
    "host_allowlist", "allow_insecure_http", "extra_headers",
}

_DEFAULT_TIMEOUT = 10
_DEFAULT_MAX_RESPONSE = 16384
_DEFAULT_EXPECTED = (200, 201, 202, 204)
_MAX_REDIRECTS_CAP = 3

RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
PERMANENT_STATUSES = frozenset({400, 401, 403, 404, 405, 410, 422})


class _ConfigError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _resolve_url(dest_config: dict) -> str:
    url = dest_config.get("url")
    if not url:
        env_name = dest_config.get("url_env")
        if env_name:
            url = os.environ.get(env_name)
    if not url:
        raise _ConfigError("WEBHOOK_NO_URL")
    return url


def _validate_url(url: str, allow_insecure: bool) -> tuple:
    """Devuelve (scheme, host, port, path_query). Fail-closed."""
    parsed = urlparse(url)
    if parsed.username or parsed.password:
        raise _ConfigError("URL_USERINFO_REJECTED")
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if scheme not in ("http", "https") or not host:
        raise _ConfigError("URL_SCHEME_REJECTED")
    if scheme == "http":
        localhost = host in ("localhost", "127.0.0.1", "::1")
        if not (allow_insecure and localhost):
            raise _ConfigError("HTTP_NOT_ALLOWED")
    port = parsed.port or (443 if scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return scheme, host, port, path


def _check_host_allowlist(host: str, allowlist) -> None:
    if allowlist and host not in {
            h.lower() for h in allowlist}:
        raise _ConfigError("HOST_NOT_ALLOWED")


def _parse_retry_after(value: str | None) -> int | None:
    """Retry-After en segundos o HTTP-date; None si no parseable."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        seconds = int(value)
        return min(seconds, 86400)
    from email.utils import parsedate_to_datetime
    from datetime import UTC, datetime
    try:
        target = parsedate_to_datetime(value)
        delta = (target - datetime.now(UTC)).total_seconds()
        return max(0, min(int(delta), 86400))
    except (TypeError, ValueError, OverflowError):
        return None


def _connection(scheme: str, host: str, port: int, timeout: float,
                context: ssl.SSLContext | None):
    if scheme == "https":
        return http.client.HTTPSConnection(
            host, port, timeout=timeout, context=context)
    return http.client.HTTPConnection(host, port, timeout=timeout)


def _safe_error(exc: BaseException) -> str:
    """Clase+codigo corto; nunca mensaje con URL/headers/body."""
    return exc.__class__.__name__


def _post_once(url_parts, headers: dict, body: bytes, timeout: float,
               context: ssl.SSLContext | None,
               max_response_bytes: int) -> tuple[int, dict, str | None]:
    """Un POST. Devuelve (status, receipt_headers, error_marker).

    error_marker: None | "RETRYABLE" | "UNKNOWN" | "PERMANENT:<code>"
    — distingue fase pre-send vs post-send.
    """
    scheme, host, port, path = url_parts
    conn = _connection(scheme, host, port, timeout, context)
    try:
        conn.request("POST", path, body=body, headers=headers)
    except (ConnectionRefusedError, socket.gaierror,
            socket.timeout, TimeoutError) as exc:
        return 0, {}, f"RETRYABLE:{_safe_error(exc)}"
    except ssl.SSLError as exc:
        return 0, {}, f"PERMANENT:TLS_ERROR:{_safe_error(exc)}"
    except (BrokenPipeError, ConnectionResetError,
            ConnectionAbortedError, OSError) as exc:
        # bytes pueden haber salido -> outcome incierto
        return 0, {}, f"UNKNOWN:{_safe_error(exc)}"
    try:
        try:
            resp = conn.getresponse()
        except ssl.SSLError as exc:
            return 0, {}, f"PERMANENT:TLS_ERROR:{_safe_error(exc)}"
        except (socket.timeout, TimeoutError, ConnectionError,
                http.client.HTTPException, OSError) as exc:
            # request enviado; respuesta perdida -> UNKNOWN
            return 0, {}, f"UNKNOWN:{_safe_error(exc)}"
        try:
            body_bytes = resp.read(max_response_bytes + 1)
        except (socket.timeout, TimeoutError, ConnectionError,
                http.client.HTTPException, OSError) as exc:
            return 0, {}, f"UNKNOWN:{_safe_error(exc)}"
    finally:
        conn.close()
    if len(body_bytes) > max_response_bytes:
        return resp.status, {}, "PERMANENT:RESPONSE_TOO_LARGE"
    receipt = {"http_status": resp.status}
    request_id = resp.getheader("X-Request-Id") or \
        resp.getheader("x-request-id")
    if request_id:
        receipt["request_id"] = str(request_id)[:128]
    retry_after = _parse_retry_after(resp.getheader("Retry-After"))
    location = resp.getheader("Location")
    if location:
        receipt["_location"] = location  # interno, no persistir
    if retry_after is not None:
        receipt["retry_after_seconds"] = retry_after
    return resp.status, receipt, None


def deliver(request, dest_config: dict) -> AdapterResult:
    try:
        url = _resolve_url(dest_config)
        allow_insecure = bool(dest_config.get("allow_insecure_http"))
        parts = _validate_url(url, allow_insecure)
        _check_host_allowlist(
            parts[1], dest_config.get("host_allowlist"))
    except _ConfigError as exc:
        return AdapterResult(
            O_FAILED_PERMANENT, error_code=exc.code)

    timeout = float(dest_config.get(
        "timeout_seconds", _DEFAULT_TIMEOUT))
    if timeout <= 0:
        return AdapterResult(
            O_FAILED_PERMANENT, error_code="INVALID_TIMEOUT")
    max_response = int(dest_config.get(
        "max_response_bytes", _DEFAULT_MAX_RESPONSE))
    expected = set(dest_config.get(
        "expected_statuses") or _DEFAULT_EXPECTED)
    max_redirects = min(int(dest_config.get("max_redirects", 0)),
                        _MAX_REDIRECTS_CAP)

    headers = {
        "Content-Type": "application/json",
        "Idempotency-Key": request.delivery_key,
        "X-CA-ES-Alert-Key": request.alert_key[:256],
        "X-CA-ES-Delivery-Key": request.delivery_key,
    }
    token_env = dest_config.get("token_env")
    if token_env:
        token = os.environ.get(token_env)
        if not token:
            return AdapterResult(
                O_FAILED_PERMANENT, error_code="TOKEN_ENV_MISSING")
        headers["Authorization"] = f"Bearer {token}"
    for name, value in (dest_config.get("extra_headers") or {}).items(
    ):
        if name.lower() in ("authorization", "content-type",
                            "host", "content-length"):
            return AdapterResult(
                O_FAILED_PERMANENT,
                error_code="HEADER_OVERRIDE_REJECTED")
        headers[str(name)] = str(value)

    context = ssl.create_default_context()
    body = request.payload_bytes
    current_parts = parts
    redirects = 0
    while True:
        status, receipt, marker = _post_once(
            current_parts, headers, body, timeout, context,
            max_response)
        if marker is not None:
            kind, _, detail = marker.partition(":")
            if kind == "RETRYABLE":
                return AdapterResult(
                    O_FAILED_RETRYABLE,
                    error_code=f"CONNECT_{detail}",
                    error_detail_safe=detail)
            if kind == "UNKNOWN":
                return AdapterResult(
                    O_UNKNOWN, error_code=f"POST_SEND_{detail}",
                    error_detail_safe=detail)
            return AdapterResult(
                O_FAILED_PERMANENT, error_code=detail,
                error_detail_safe=detail)

        location = receipt.pop("_location", None)
        retry_after = receipt.pop("retry_after_seconds", None)
        if status in expected:
            return AdapterResult(O_SUCCEEDED, receipt=receipt)
        if 300 <= status < 400:
            if redirects >= max_redirects or not location:
                return AdapterResult(
                    O_FAILED_PERMANENT,
                    error_code="REDIRECT_NOT_FOLLOWED",
                    error_detail_safe=f"HTTP_{status}",
                    receipt={"http_status": status})
            new_url = urljoin(url, location)
            try:
                new_parts = _validate_url(new_url, allow_insecure)
            except _ConfigError:
                return AdapterResult(
                    O_FAILED_PERMANENT,
                    error_code="REDIRECT_UNSAFE_TARGET")
            _same_origin = (
                new_parts[0] == current_parts[0]
                and new_parts[1] == current_parts[1]
                and new_parts[2] == current_parts[2])
            if not _same_origin:
                return AdapterResult(
                    O_FAILED_PERMANENT,
                    error_code="REDIRECT_CROSS_ORIGIN")
            try:
                _check_host_allowlist(
                    new_parts[1], dest_config.get("host_allowlist"))
            except _ConfigError:
                return AdapterResult(
                    O_FAILED_PERMANENT,
                    error_code="REDIRECT_HOST_NOT_ALLOWED")
            current_parts = new_parts
            url = new_url
            redirects += 1
            continue
        if status in RETRYABLE_STATUSES:
            return AdapterResult(
                O_FAILED_RETRYABLE, error_code=f"HTTP_{status}",
                error_detail_safe=f"HTTP_{status}",
                retry_after_seconds=retry_after,
                receipt=receipt)
        if status in PERMANENT_STATUSES or 400 <= status < 500:
            return AdapterResult(
                O_FAILED_PERMANENT, error_code=f"HTTP_{status}",
                error_detail_safe=f"HTTP_{status}",
                receipt=receipt)
        # 5xx no listados -> retryable conservador; 1xx raro -> permanente
        if 500 <= status < 600:
            return AdapterResult(
                O_FAILED_RETRYABLE, error_code=f"HTTP_{status}",
                error_detail_safe=f"HTTP_{status}",
                retry_after_seconds=retry_after,
                receipt=receipt)
        return AdapterResult(
            O_FAILED_PERMANENT, error_code=f"HTTP_{status}",
            error_detail_safe=f"HTTP_{status}", receipt=receipt)
