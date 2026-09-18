"""P10.6 — SMTP delivery adapter (stdlib smtplib + ssl).

STARTTLS por defecto; SMTPS si ``security="smtps"``; plaintext solo
localhost explicito. Credenciales solo via ``username_env`` /
``password_env``. Message-ID determinista desde delivery_key.

``transport_factory`` inyectable para tests: callable que devuelve
un objeto con la interfaz smtplib (ehlo/starttls/login/send_message/
quit). Sin servidor SMTP real en CI.
"""
from __future__ import annotations

import json
import os
import smtplib
import socket
import ssl
from email.message import EmailMessage
from email.utils import format_datetime
from datetime import UTC, datetime

from ..ops_delivery import (
    AdapterResult, O_FAILED_PERMANENT, O_FAILED_RETRYABLE,
    O_SUCCEEDED, O_UNKNOWN)

CONFIG_KEYS = {
    "host", "port", "security", "username_env", "password_env",
    "from_address", "to_addresses", "message_id_domain",
    "timeout_seconds", "allow_plaintext_localhost",
}


def _safe_error(exc: BaseException) -> str:
    return exc.__class__.__name__


def _default_transport(host: str, port: int, timeout: float,
                       security: str, context: ssl.SSLContext):
    if security == "smtps":
        return smtplib.SMTP_SSL(
            host, port, timeout=timeout, context=context)
    return smtplib.SMTP(host, port, timeout=timeout)


def _build_message(request, from_addr: str, to_addrs: list[str],
                   msg_domain: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg["Date"] = format_datetime(datetime.now(UTC))
    msg["Message-ID"] = f"<{request.delivery_key}@{msg_domain}>"
    subject = f"[ca-es] {request.payload.get('category')} " \
              f"{request.payload.get('subject_key')}"
    msg["Subject"] = subject[:150]
    lines = [
        "ca-es alert delivery",
        "",
        f"alert_key: {request.alert_key}",
        f"delivery_key: {request.delivery_key}",
        f"category: {request.payload.get('category')}",
        f"state: {request.payload.get('state')}",
        f"summary: {request.payload.get('summary')}",
        "",
        "details:",
        json.dumps(request.payload.get("details") or {},
                   indent=2, sort_keys=True, ensure_ascii=True),
        "",
        "evidence_refs:",
        json.dumps(request.payload.get("evidence_refs") or [],
                   indent=2, sort_keys=True, ensure_ascii=True),
        "",
        "--",
        "Este aviso es operativo; no contiene datos de posiciones "
        "ni mensajes MT/MX.",
    ]
    msg.set_content("\n".join(lines))
    return msg


def deliver(request, dest_config: dict) -> AdapterResult:
    host = dest_config.get("host")
    port = int(dest_config.get("port") or 587)
    security = (dest_config.get("security") or "starttls").lower()
    from_addr = dest_config.get("from_address")
    to_addrs = dest_config.get("to_addresses") or []
    allow_plain = bool(dest_config.get("allow_plaintext_localhost"))

    if not host or not from_addr or not to_addrs:
        return AdapterResult(
            O_FAILED_PERMANENT, error_code="SMTP_CONFIG_INCOMPLETE")
    if security not in ("starttls", "smtps", "plain"):
        return AdapterResult(
            O_FAILED_PERMANENT, error_code="SMTP_SECURITY_UNKNOWN")
    if security == "plain":
        localhost = host.lower() in ("localhost", "127.0.0.1", "::1")
        if not (allow_plain and localhost):
            return AdapterResult(
                O_FAILED_PERMANENT, error_code="PLAINTEXT_NOT_ALLOWED")

    username = password = None
    user_env = dest_config.get("username_env")
    if user_env:
        username = os.environ.get(user_env)
        pass_env = dest_config.get("password_env")
        password = os.environ.get(pass_env) if pass_env else None
        if not username or not password:
            return AdapterResult(
                O_FAILED_PERMANENT, error_code="SMTP_ENV_MISSING")

    timeout = float(dest_config.get("timeout_seconds") or 10)
    msg_domain = dest_config.get("message_id_domain") or \
        from_addr.split("@")[-1]
    msg = _build_message(request, from_addr, to_addrs, msg_domain)

    factory = dest_config.get("transport_factory")
    context = ssl.create_default_context()
    client = None
    try:
        client = (factory or _default_transport)(
            host, port, timeout, security, context)
    except (socket.timeout, TimeoutError, ConnectionError,
            socket.gaierror, OSError) as exc:
        return AdapterResult(
            O_FAILED_RETRYABLE, error_code="SMTP_CONNECT_FAILED",
            error_detail_safe=_safe_error(exc))
    except ssl.SSLError as exc:
        return AdapterResult(
            O_FAILED_PERMANENT, error_code="SMTP_TLS_ERROR",
            error_detail_safe=_safe_error(exc))
    except smtplib.SMTPException as exc:
        return AdapterResult(
            O_FAILED_RETRYABLE, error_code="SMTP_GREETING_FAILED",
            error_detail_safe=_safe_error(exc))

    try:
        try:
            if security == "starttls":
                client.ehlo()
                client.starttls(context=context)
                client.ehlo()
        except ssl.SSLError as exc:
            return AdapterResult(
                O_FAILED_PERMANENT, error_code="SMTP_TLS_ERROR",
                error_detail_safe=_safe_error(exc))
        except smtplib.SMTPException as exc:
            return AdapterResult(
                O_FAILED_PERMANENT,
                error_code="SMTP_STARTTLS_FAILED",
                error_detail_safe=_safe_error(exc))
        if username:
            try:
                client.login(username, password)
            except smtplib.SMTPAuthenticationError as exc:
                return AdapterResult(
                    O_FAILED_PERMANENT,
                    error_code=f"SMTP_AUTH_{exc.smtp_code}",
                    error_detail_safe="authentication failed")
            except smtplib.SMTPException as exc:
                return AdapterResult(
                    O_FAILED_RETRYABLE, error_code="SMTP_AUTH_ERROR",
                    error_detail_safe=_safe_error(exc))
        try:
            refused = client.send_message(msg)
        except smtplib.SMTPRecipientsRefused as exc:
            return AdapterResult(
                O_FAILED_PERMANENT,
                error_code="SMTP_RECIPIENTS_REFUSED",
                error_detail_safe=_safe_error(exc))
        except smtplib.SMTPSenderRefused as exc:
            return AdapterResult(
                O_FAILED_PERMANENT,
                error_code=f"SMTP_SENDER_REFUSED_{exc.smtp_code}",
                error_detail_safe="sender refused")
        except smtplib.SMTPResponseException as exc:
            if 400 <= exc.smtp_code < 500:
                return AdapterResult(
                    O_FAILED_RETRYABLE,
                    error_code=f"SMTP_{exc.smtp_code}",
                    error_detail_safe=_safe_error(exc))
            return AdapterResult(
                O_FAILED_PERMANENT, error_code=f"SMTP_{exc.smtp_code}",
                error_detail_safe=_safe_error(exc))
        except smtplib.SMTPException as exc:
            # DATA enviado parcial o respuesta perdida -> incierto
            return AdapterResult(
                O_UNKNOWN, error_code="SMTP_SEND_UNCERTAIN",
                error_detail_safe=_safe_error(exc))
        except (socket.timeout, TimeoutError, ConnectionError,
                OSError) as exc:
            return AdapterResult(
                O_UNKNOWN, error_code="SMTP_SEND_UNCERTAIN",
                error_detail_safe=_safe_error(exc))
    finally:
        try:
            if client is not None:
                client.quit()
        except Exception:  # noqa: BLE001 — quit best-effort
            pass

    if refused:
        # aceptacion parcial: entrega ocurrida para un subconjunto
        return AdapterResult(
            O_FAILED_PERMANENT,
            error_code="SMTP_PARTIAL_REFUSED",
            error_detail_safe=(
                f"refused:{sorted(refused)}")[:200],
            receipt={"accepted_recipients": sorted(
                set(to_addrs) - set(refused))})
    return AdapterResult(
        O_SUCCEEDED,
        receipt={"accepted_recipients": list(to_addrs)})
