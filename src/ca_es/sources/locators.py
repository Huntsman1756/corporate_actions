"""Resolucion de locators de fuente a URLs absolutas.

Los frames pueden contener locators relativos del portal (p.ej.
``../otra-informacion-regulada-corporativa/....aspx?Nif=...`` en filas
CNMV). La resolucion es determinista y ocurre antes de la adquisicion:
solo normaliza la forma de la URL, nunca decide contenido.
"""
from __future__ import annotations

from urllib.parse import urljoin, urlparse

_PORTAL_BASE = {
    "CNMV_OIR": "https://www.cnmv.es/portal/Otra-Informacion-Relevante/Consulta-OIR.aspx",
    "CNMV_IP": "https://www.cnmv.es/portal/Informacion-Privilegiada/Consulta-IP.aspx",
    "CNMV": "https://www.cnmv.es/portal/home.aspx",
}


def resolve_locator(source: str, locator: str | None) -> str | None:
    """Devuelve una URL absoluta o ``None`` si no es resoluble."""
    if not locator:
        return None
    locator = locator.strip()
    parsed = urlparse(locator)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return locator
    base = _PORTAL_BASE.get(source) or _PORTAL_BASE.get(source.split("_")[0])
    if base is None:
        return None
    resolved = urljoin(base, locator)
    parsed = urlparse(resolved)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return resolved
