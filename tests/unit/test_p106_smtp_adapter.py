"""P10.6 — SMTP adapter: transport inyectado, STARTTLS,
clasificacion de errores, Message-ID determinista, sin secretos."""
from __future__ import annotations

import json
import smtplib
import socket

from ca_es.delivery.smtp_adapter import deliver
from ca_es.ops_delivery import (
    DeliveryRequest, O_FAILED_PERMANENT, O_FAILED_RETRYABLE,
    O_SUCCEEDED, O_UNKNOWN)


def _request() -> DeliveryRequest:
    payload = {"schema": "CA_ES_ALERT_DELIVERY_PAYLOAD_V1",
               "alert_key": "DEADLINE_OVERDUE|dk1",
               "category": "DEADLINE_OVERDUE",
               "subject_key": "dk1", "state": "OPEN",
               "summary": "DEADLINE_OVERDUE dk1",
               "details": {"deadline_date": "2026-09-20"},
               "evidence_refs": ["sha:r1"]}
    return DeliveryRequest(
        delivery_key="DLV-" + "cd" * 32,
        alert_key=payload["alert_key"],
        alert_semantic_sha256="aa", alert_state="OPEN",
        adapter_type="smtp", destination_id="mail1", generation=1,
        payload_schema="CA_ES_ALERT_DELIVERY_PAYLOAD_V1",
        payload=payload, created_at="2026-09-18T00:00:00Z",
        payload_bytes=json.dumps(payload).encode())


class FakeSMTP:
    """Doble del interfaz smtplib que usa el adapter."""

    def __init__(self, **behaviour):
        self.behaviour = behaviour
        self.calls = []
        self.sent = []

    def ehlo(self):
        self.calls.append("ehlo")
        if self.behaviour.get("ehlo_fails"):
            raise smtplib.SMTPException("ehlo boom")

    def starttls(self, context=None):
        self.calls.append("starttls")
        if self.behaviour.get("starttls_fails"):
            raise smtplib.SMTPException("tls boom")

    def login(self, user, password):
        self.calls.append(("login", user))
        if self.behaviour.get("auth_fails"):
            raise smtplib.SMTPAuthenticationError(535, b"denied")

    def send_message(self, msg):
        self.calls.append("send_message")
        self.sent.append(msg)
        if self.behaviour.get("recipients_refused"):
            raise smtplib.SMTPRecipientsRefused(
                {"x@y.z": (550, b"no")})
        if self.behaviour.get("sender_refused"):
            raise smtplib.SMTPSenderRefused(553, b"no", "a@b.c")
        if self.behaviour.get("temp_fail"):
            raise smtplib.SMTPResponseException(451, b"try later")
        if self.behaviour.get("send_uncertain"):
            raise smtplib.SMTPServerDisconnected("gone")
        return self.behaviour.get("refused", {})

    def quit(self):
        self.calls.append("quit")


def _factory(smtp_obj, **kw):
    def f(host, port, timeout, security, context):
        f.args = (host, port, timeout, security)
        return smtp_obj
    f.kw = kw
    return f


def _cfg(**kw):
    cfg = {"host": "smtp.example.com", "port": 587,
           "security": "starttls",
           "from_address": "ops@ca-es.local",
           "to_addresses": ["team@ca-es.local"]}
    cfg.update(kw)
    return cfg


def test_successful_send_starttls():
    smtp = FakeSMTP()
    res = deliver(_request(), _cfg(transport_factory=_factory(smtp)))
    assert res.outcome == O_SUCCEEDED
    assert res.receipt["accepted_recipients"] == ["team@ca-es.local"]
    assert "starttls" in smtp.calls
    assert "quit" in smtp.calls
    msg = smtp.sent[0]
    assert msg["Subject"].startswith("[ca-es] DEADLINE_OVERDUE")
    assert msg["Message-ID"] == \
        f"<{_request().delivery_key}@ca-es.local>"


def test_message_id_deterministic():
    a, b = FakeSMTP(), FakeSMTP()
    deliver(_request(), _cfg(transport_factory=_factory(a)))
    deliver(_request(), _cfg(transport_factory=_factory(b)))
    assert a.sent[0]["Message-ID"] == b.sent[0]["Message-ID"]


def test_message_id_domain_configurable():
    smtp = FakeSMTP()
    deliver(_request(), _cfg(transport_factory=_factory(smtp),
                             message_id_domain="ops.example"))
    assert smtp.sent[0]["Message-ID"].endswith("@ops.example>")


def test_no_plaintext_by_default():
    res = deliver(_request(), _cfg(security="plain"))
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "PLAINTEXT_NOT_ALLOWED"


def test_plaintext_localhost_explicit():
    smtp = FakeSMTP()
    res = deliver(_request(), _cfg(
        host="localhost", security="plain",
        allow_plaintext_localhost=True,
        transport_factory=_factory(smtp)))
    assert res.outcome == O_SUCCEEDED
    assert "starttls" not in smtp.calls


def test_smtps_no_starttls_call():
    smtp = FakeSMTP()
    res = deliver(_request(), _cfg(
        security="smtps", transport_factory=_factory(smtp)))
    assert res.outcome == O_SUCCEEDED
    assert "starttls" not in smtp.calls


def test_config_incomplete_fails_closed():
    for cfg in (_cfg(host=None), _cfg(from_address=None),
                _cfg(to_addresses=[])):
        res = deliver(_request(), cfg)
        assert res.outcome == O_FAILED_PERMANENT
        assert res.error_code == "SMTP_CONFIG_INCOMPLETE"


def test_auth_env_missing_fails_closed():
    res = deliver(_request(), _cfg(
        username_env="NO_SUCH_USER_ENV",
        password_env="NO_SUCH_PASS_ENV"))
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "SMTP_ENV_MISSING"


def test_auth_failure_permanent(monkeypatch):
    monkeypatch.setenv("CA_ES_T_SMTP_U", "u1")
    monkeypatch.setenv("CA_ES_T_SMTP_P", "p1")
    smtp = FakeSMTP(auth_fails=True)
    res = deliver(_request(), _cfg(
        username_env="CA_ES_T_SMTP_U",
        password_env="CA_ES_T_SMTP_P",
        transport_factory=_factory(smtp)))
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "SMTP_AUTH_535"
    # el detalle nunca lleva la password
    assert "p1" not in (res.error_detail_safe or "")


def test_login_called_with_env_creds(monkeypatch):
    monkeypatch.setenv("CA_ES_T_SMTP_U", "env-user")
    monkeypatch.setenv("CA_ES_T_SMTP_P", "env-pass")
    smtp = FakeSMTP()
    res = deliver(_request(), _cfg(
        username_env="CA_ES_T_SMTP_U",
        password_env="CA_ES_T_SMTP_P",
        transport_factory=_factory(smtp)))
    assert res.outcome == O_SUCCEEDED
    assert ("login", "env-user") in smtp.calls


def test_recipients_refused_permanent():
    smtp = FakeSMTP(recipients_refused=True)
    res = deliver(_request(), _cfg(transport_factory=_factory(smtp)))
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "SMTP_RECIPIENTS_REFUSED"


def test_sender_refused_permanent():
    smtp = FakeSMTP(sender_refused=True)
    res = deliver(_request(), _cfg(transport_factory=_factory(smtp)))
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code.startswith("SMTP_SENDER_REFUSED")


def test_4xx_smtp_retryable():
    smtp = FakeSMTP(temp_fail=True)
    res = deliver(_request(), _cfg(transport_factory=_factory(smtp)))
    assert res.outcome == O_FAILED_RETRYABLE
    assert res.error_code == "SMTP_451"


def test_disconnect_mid_send_unknown():
    smtp = FakeSMTP(send_uncertain=True)
    res = deliver(_request(), _cfg(transport_factory=_factory(smtp)))
    assert res.outcome == O_UNKNOWN
    assert res.error_code == "SMTP_SEND_UNCERTAIN"


def test_partial_refusal_permanent_with_receipt():
    smtp = FakeSMTP(refused={"b@ca-es.local": (550, b"no")})
    res = deliver(_request(), _cfg(
        to_addresses=["a@ca-es.local", "b@ca-es.local"],
        transport_factory=_factory(smtp)))
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "SMTP_PARTIAL_REFUSED"
    assert res.receipt["accepted_recipients"] == ["a@ca-es.local"]


def test_connect_failure_retryable():
    def bad_factory(host, port, timeout, security, context):
        raise socket.timeout("timed out")
    res = deliver(_request(), _cfg(transport_factory=bad_factory))
    assert res.outcome == O_FAILED_RETRYABLE
    assert res.error_code == "SMTP_CONNECT_FAILED"


def test_starttls_failure_permanent():
    smtp = FakeSMTP(starttls_fails=True)
    res = deliver(_request(), _cfg(transport_factory=_factory(smtp)))
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "SMTP_STARTTLS_FAILED"


def test_no_credentials_in_message_or_errors(monkeypatch):
    monkeypatch.setenv("CA_ES_T_SMTP_U", "user-secret")
    monkeypatch.setenv("CA_ES_T_SMTP_P", "pass-secret")
    smtp = FakeSMTP()
    res = deliver(_request(), _cfg(
        username_env="CA_ES_T_SMTP_U",
        password_env="CA_ES_T_SMTP_P",
        transport_factory=_factory(smtp)))
    assert res.outcome == O_SUCCEEDED
    body = smtp.sent[0].get_content()
    assert "pass-secret" not in body
    assert "user-secret" not in body
    assert "pass-secret" not in str(res)
