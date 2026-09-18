"""Capa HTTP de adquisicion publica (P9).

Explicita y acotada: UA declarado, timeouts, retries solo para fallos
tecnicos transitorios (timeout, reset, 5xx seleccionados), byte cap,
redirects validados a http(s) y mismo esquema esperado. Nunca reintenta
fallos semanticos. ``fetcher`` inyectable para tests offline.
"""
from __future__ import annotations

import http.cookiejar
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

USER_AGENT = (
    "ca-es-source-refresh/1.0 "
    "(+https://github.com/corporate-actions; public-source-acquisition)"
)

DEFAULT_MAX_BYTES = 64 * 1024 * 1024  # 64 MiB cap pre-store


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int
    content: bytes
    media_type: str
    error: str | None = None


@dataclass
class FetchError(Exception):  # type: ignore[misc]
    # NO frozen: Python asigna __traceback__/__context__ en raise —
    # una excepcion frozen rompe la propagacion (FrozenInstanceError).
    url: str
    reason: str
    status: int | None = None
    transient: bool = False

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"FETCH_ERROR:{self.reason}:{self.url}:{self.status}"


def _redirect_ok(url: str) -> bool:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    """Solo http(s); bloquea file://, data:, esquemas raros."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _redirect_ok(newurl):
            raise urllib.error.HTTPError(
                req.full_url, code, f"REDIRECT_REJECTED:{newurl[:80]}",
                headers, fp)
        return super().redirect_request(
            req, fp, code, msg, headers, newurl)


def build_opener(base_url: str | None = None,
                 timeout: int = 30) -> urllib.request.OpenerDirector:
    """Opener con cookiejar (WebForms CNMV lo exige) y redirect
    guardado. ``base_url`` inicial calienta la sesion."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar), _GuardedRedirect)
    if base_url:
        opener.open(
            urllib.request.Request(
                base_url, headers={"User-Agent": USER_AGENT}),
            timeout=timeout).read()
    return opener


def make_fetcher(opener: urllib.request.OpenerDirector | None = None,
                 *, timeout: int = 90, retries: int = 3,
                 politeness: float = 0.35,
                 max_bytes: int = DEFAULT_MAX_BYTES,
                 user_agent: str = USER_AGENT):
    """Devuelve fetch(url, referer=None) -> FetchResult.

    Retries acotados solo ante errores transitorios. Politeness sleep
    antes de cada request (la fuente no es un benchmark).
    ``user_agent`` es por fuente: algunos endpoints probados (p.ej.
    la API de documentos Portfolio) rechazan UAs no-browser — el
    adapter usa alli el header probado por G1-R2, no un bypass nuevo.
    """
    opener = opener or build_opener()

    def fetch(url: str, referer: str | None = None) -> FetchResult:
        headers = {"User-Agent": user_agent}
        if referer:
            headers["Referer"] = referer
        last_exc: Exception | None = None
        for attempt in range(max(1, retries)):
            time.sleep(politeness)
            try:
                request = urllib.request.Request(url, headers=headers)
                with opener.open(request, timeout=timeout) as resp:
                    status = getattr(resp, "status", 200) or 200
                    media = resp.headers.get("Content-Type", "")
                    content = resp.read(max_bytes + 1)
                if len(content) > max_bytes:
                    raise FetchError(url, "RESPONSE_TOO_LARGE",
                                     status=status)
                return FetchResult(
                    url=url, status=status, content=content,
                    media_type=media)
            except urllib.error.HTTPError as exc:
                last_exc = exc
                if 500 <= exc.code < 600 and attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise FetchError(
                    url, "HTTP_STATUS", status=exc.code,
                    transient=500 <= exc.code < 600) from exc
            except (urllib.error.URLError, TimeoutError,
                    ConnectionError, OSError) as exc:
                last_exc = exc
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise FetchError(
                    url, "TRANSIENT", transient=True) from exc
        raise FetchError(url, "EXHAUSTED", transient=True) from last_exc

    return fetch
