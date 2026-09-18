"""P10.5 — WEBHOOK adapter: clasificacion de status, hardening
URL/redirects/SSRF, idempotency headers, post-send -> UNKNOWN."""
from __future__ import annotations

import http.server
import json
import socket
import threading

import pytest

from ca_es.delivery.webhook_adapter import deliver
from ca_es.ops_delivery import (
    DeliveryRequest, O_FAILED_PERMANENT, O_FAILED_RETRYABLE,
    O_SUCCEEDED, O_UNKNOWN)


def _request() -> DeliveryRequest:
    payload = {"schema": "CA_ES_ALERT_DELIVERY_PAYLOAD_V1",
               "alert_key": "DEADLINE_OVERDUE|dk1",
               "category": "DEADLINE_OVERDUE"}
    return DeliveryRequest(
        delivery_key="DLV-" + "ab" * 32,
        alert_key=payload["alert_key"],
        alert_semantic_sha256="aa", alert_state="OPEN",
        adapter_type="webhook", destination_id="w1", generation=1,
        payload_schema="CA_ES_ALERT_DELIVERY_PAYLOAD_V1",
        payload=payload, created_at="2026-09-18T00:00:00Z",
        payload_bytes=json.dumps(payload).encode())


class _Recorder:
    def __init__(self):
        self.requests = []


def _serve(handler_cls, requests_sink):
    """Servidor HTTP local efimero; devuelve (url, server)."""
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), handler_cls)
    server._sink = requests_sink
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return f"http://127.0.0.1:{server.server_address[1]}/hook", server


def _cfg(url, **kw):
    cfg = {"url": url, "allow_insecure_http": True,
           "timeout_seconds": 5}
    cfg.update(kw)
    return cfg


def _handler(status=200, extra_headers=None, redirect_to=None,
             big_body=False):
    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            self.server._sink.requests.append({
                "path": self.path,
                "headers": dict(self.headers),
                "body": body})
            if redirect_to:
                self.send_response(status)
                self.send_header("Location", redirect_to)
                self.end_headers()
                return
            self.send_response(status)
            for k, v in (extra_headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if big_body:
                self.wfile.write(b"x" * 70000)
            else:
                self.wfile.write(b"{}")

        def log_message(self, *a):
            pass
    return H


@pytest.fixture
def sink():
    return _Recorder()


def test_success_200(sink):
    url, srv = _serve(_handler(200, {"X-Request-Id": "req-1"}), sink)
    try:
        res = deliver(_request(), _cfg(url))
        assert res.outcome == O_SUCCEEDED
        assert res.receipt["http_status"] == 200
        assert res.receipt["request_id"] == "req-1"
    finally:
        srv.shutdown()


def test_idempotency_and_alert_headers(sink):
    url, srv = _serve(_handler(204), sink)
    try:
        req = _request()
        deliver(req, _cfg(url))
        sent = sink.requests[0]["headers"]
        assert sent["Idempotency-Key"] == req.delivery_key
        assert sent["X-CA-ES-Delivery-Key"] == req.delivery_key
        assert sent["X-CA-ES-Alert-Key"] == req.alert_key
        assert sent["Content-Type"] == "application/json"
    finally:
        srv.shutdown()


@pytest.mark.parametrize("status", [200, 201, 202, 204])
def test_expected_statuses_success(status, sink):
    url, srv = _serve(_handler(status), sink)
    try:
        assert deliver(_request(), _cfg(url)).outcome == O_SUCCEEDED
    finally:
        srv.shutdown()


@pytest.mark.parametrize("status", [400, 401, 403, 404, 405, 410, 422])
def test_permanent_statuses(status, sink):
    url, srv = _serve(_handler(status), sink)
    try:
        res = deliver(_request(), _cfg(url))
        assert res.outcome == O_FAILED_PERMANENT
        assert res.error_code == f"HTTP_{status}"
    finally:
        srv.shutdown()


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504])
def test_retryable_statuses(status, sink):
    url, srv = _serve(_handler(status), sink)
    try:
        res = deliver(_request(), _cfg(url))
        assert res.outcome == O_FAILED_RETRYABLE
        assert res.error_code == f"HTTP_{status}"
    finally:
        srv.shutdown()


def test_retry_after_parsed(sink):
    url, srv = _serve(
        _handler(429, {"Retry-After": "120"}), sink)
    try:
        res = deliver(_request(), _cfg(url))
        assert res.outcome == O_FAILED_RETRYABLE
        assert res.retry_after_seconds == 120
    finally:
        srv.shutdown()


def test_retry_after_http_date(sink):
    url, srv = _serve(
        _handler(503, {"Retry-After":
                       "Wed, 21 Oct 2099 07:28:00 GMT"}), sink)
    try:
        res = deliver(_request(), _cfg(url))
        assert res.outcome == O_FAILED_RETRYABLE
        assert res.retry_after_seconds is not None
        assert res.retry_after_seconds > 0
    finally:
        srv.shutdown()


def test_redirect_not_followed_by_default(sink):
    url, srv = _serve(_handler(302, redirect_to="/other"), sink)
    try:
        res = deliver(_request(), _cfg(url))
        assert res.outcome == O_FAILED_PERMANENT
        assert res.error_code == "REDIRECT_NOT_FOLLOWED"
        assert len(sink.requests) == 1  # no se reemitio
    finally:
        srv.shutdown()


def test_redirect_to_file_scheme_rejected(sink):
    url, srv = _serve(
        _handler(302, redirect_to="file:///etc/passwd"), sink)
    try:
        res = deliver(_request(), _cfg(url, max_redirects=2))
        assert res.outcome == O_FAILED_PERMANENT
        assert res.error_code == "REDIRECT_UNSAFE_TARGET"
    finally:
        srv.shutdown()


def test_redirect_cross_origin_rejected(sink):
    url, srv = _serve(
        _handler(302, redirect_to="http://127.0.0.1:1/evil"), sink)
    try:
        res = deliver(_request(), _cfg(url, max_redirects=2))
        assert res.outcome == O_FAILED_PERMANENT
        assert res.error_code == "REDIRECT_CROSS_ORIGIN"
    finally:
        srv.shutdown()


def test_same_origin_redirect_followed(sink):
    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            self.server._sink.requests.append({
                "path": self.path,
                "headers": dict(self.headers), "body": body})
            if self.path == "/hook":
                self.send_response(307)
                self.send_header("Location", "/moved")
            else:
                self.send_response(404)
            self.end_headers()

        def log_message(self, *a):
            pass

    url, srv = _serve(H, sink)
    try:
        res = deliver(_request(), _cfg(url, max_redirects=2))
        assert res.error_code == "HTTP_404"
        assert len(sink.requests) == 2
        assert sink.requests[1]["path"] == "/moved"
    finally:
        srv.shutdown()


def test_oversized_response_bounded(sink):
    url, srv = _serve(_handler(200, big_body=True), sink)
    try:
        res = deliver(
            _request(), _cfg(url, max_response_bytes=1024))
        assert res.outcome == O_FAILED_PERMANENT
        assert res.error_code == "RESPONSE_TOO_LARGE"
    finally:
        srv.shutdown()


def test_http_non_localhost_rejected():
    res = deliver(_request(), {
        "url": "http://example.com/hook",
        "allow_insecure_http": True})
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "HTTP_NOT_ALLOWED"


def test_http_without_allow_insecure_rejected():
    res = deliver(_request(), {
        "url": "http://127.0.0.1:9/hook"})
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "HTTP_NOT_ALLOWED"


def test_userinfo_url_rejected():
    res = deliver(_request(), {
        "url": "http://user:pass@127.0.0.1/hook",
        "allow_insecure_http": True})
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "URL_USERINFO_REJECTED"


def test_non_http_scheme_rejected():
    for url in ("file:///etc/passwd", "ftp://h/x", "gopher://h"):
        res = deliver(_request(), {
            "url": url, "allow_insecure_http": True})
        assert res.outcome == O_FAILED_PERMANENT
        assert res.error_code == "URL_SCHEME_REJECTED"


def test_no_url_fails_closed():
    res = deliver(_request(), {})
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "WEBHOOK_NO_URL"


def test_host_allowlist(sink):
    url, srv = _serve(_handler(200), sink)
    try:
        res = deliver(_request(), _cfg(
            url, host_allowlist=["api.example.com"]))
        assert res.error_code == "HOST_NOT_ALLOWED"
        res2 = deliver(_request(), _cfg(
            url, host_allowlist=["127.0.0.1"]))
        assert res2.outcome == O_SUCCEEDED
    finally:
        srv.shutdown()


def test_token_env_missing_fails_closed(sink):
    url, srv = _serve(_handler(200), sink)
    try:
        res = deliver(_request(), _cfg(
            url, token_env="CA_ES_TEST_NO_SUCH_ENV"))
        assert res.outcome == O_FAILED_PERMANENT
        assert res.error_code == "TOKEN_ENV_MISSING"
        assert not sink.requests  # nada salio por la red
    finally:
        srv.shutdown()


def test_token_env_sends_authorization(sink, monkeypatch):
    monkeypatch.setenv("CA_ES_TEST_WH_TOK", "s3cr3t")
    url, srv = _serve(_handler(200), sink)
    try:
        res = deliver(_request(), _cfg(
            url, token_env="CA_ES_TEST_WH_TOK"))
        assert res.outcome == O_SUCCEEDED
        assert sink.requests[0]["headers"]["Authorization"] == \
            "Bearer s3cr3t"
    finally:
        srv.shutdown()


def test_extra_headers_cannot_override_auth(sink):
    url, srv = _serve(_handler(200), sink)
    try:
        res = deliver(_request(), _cfg(
            url, extra_headers={"Authorization": "Bearer evil"}))
        assert res.error_code == "HEADER_OVERRIDE_REJECTED"
    finally:
        srv.shutdown()


def test_connection_refused_retryable():
    # puerto cerrado -> pre-send -> retryable (nunca UNKNOWN:
    # sabemos que nada salio)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]  # ligado pero NO escuchando
    res = deliver(_request(), _cfg(
        f"http://127.0.0.1:{port}/x", timeout_seconds=2))
    assert res.outcome == O_FAILED_RETRYABLE
    assert res.error_code.startswith("CONNECT_")


def test_post_send_drop_is_unknown():
    """Servidor que acepta, lee la request y cierra sin responder
    -> outcome incierto, NUNCA retryable automatico."""
    ready = threading.Event()

    def dropper():
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        ready.port = port
        ready.set()
        conn, _ = srv.accept()
        conn.settimeout(5)
        try:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
        except socket.timeout:
            pass
        conn.close()
        srv.close()

    t = threading.Thread(target=dropper, daemon=True)
    t.start()
    ready.wait(5)
    res = deliver(_request(), _cfg(
        f"http://127.0.0.1:{ready.port}/x", timeout_seconds=5))
    assert res.outcome == O_UNKNOWN
    assert res.error_code.startswith("POST_SEND_")


def test_invalid_timeout_rejected():
    res = deliver(_request(), {
        "url": "http://127.0.0.1/x", "allow_insecure_http": True,
        "timeout_seconds": 0})
    assert res.error_code == "INVALID_TIMEOUT"
