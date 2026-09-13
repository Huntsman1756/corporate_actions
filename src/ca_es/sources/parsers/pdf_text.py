"""Extraccion de texto de PDF (dependencia opcional).

El core de ca-es es stdlib-only. La extraccion PDF solo se usa al
ingerir documentos reales de fuentes que publican PDF (CNMV); se importa
de forma perezosa y, si no esta instalada, falla de forma explicita en
vez de degradar silenciosamente.

Dependencia: pypdf (BSD-3-Clause), extra opcional `ca-es[pdf]`.
Motivo: no existe extractor PDF en la stdlib; pypdf es mantenido y de
licencia permisiva. Estrategia de salida: el parser real consume
`ParsedDocument`; sustituir pypdf por otro extractor no toca el core.
"""
from __future__ import annotations

import io

from ...errors import CaEsError


class PdfSupportUnavailable(CaEsError):
    """No hay backend de extraccion PDF instalado."""


def extract_text(payload: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise PdfSupportUnavailable(
            "extraccion PDF requiere pypdf: instalar ca-es[pdf]"
        ) from exc
    reader = PdfReader(io.BytesIO(payload))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def normalize_text(text: str) -> str:
    """Colapsa espacios pero conserva saltos de linea significativos."""
    import re

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)
