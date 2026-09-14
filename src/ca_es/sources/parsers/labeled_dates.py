"""Extraccion generica de fechas etiquetadas en avisos de corporate actions.

Cubre las variantes observadas en CNMV y Portfolio Stock Exchange:

- Etiquetas en ingles o espanol: ``Ex-Date``, ``record date``,
  ``payment date``, ``fecha de pago``, ``fecha valor``, ``fecha devengo``,
  ``last trading date``, ``ultimo dia de negociacion``...
- Fechas en formato numerico (``03/07/2026``, ``03 / 07 / 2026``) o
  espanol (``22 de julio de 2026``, ``se concreta en el dia 23 de junio de
  2025``).

Cada fecha promovida conserva el fragmento que la justifica; la funcion
devuelve el lexema y el offset para que el parser construya la evidencia.
"""
from __future__ import annotations

import re

from .html_text import spanish_date_to_iso

_NUMERIC = r"\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{4}"
_SPANISH = r"\d{1,2}\s+de\s+\w+\s+de\s+\d{4}"
ANY_DATE = rf"(?:{_NUMERIC}|{_SPANISH})"

_LABELS: dict[str, tuple[str, ...]] = {
    "EX_DATE": (
        r"\bex\s*[-–—]?\s*date\b",
        r"\bexdate\b",
        r"negociar[aá]n?\s+sin\s+derecho",
        r"fecha\s+(?:a\s+partir\s+de\s+la\s+cual[^.]{0,60}?)?ex\b",
    ),
    "RECORD_DATE": (
        r"\brecord\s*[-–—]?\s*date\b",
        r"fecha\s+de\s+registro\b",
        r"titulares\s+inscritos",
    ),
    "PAYMENT_DATE": (
        r"\bpayment\s*[-–—]?\s*date\b",
        r"fecha\s+de\s+pago\b",
        r"fecha\s+valor\b",
        r"fecha\s+devengo\b",
    ),
    "LAST_TRADING_DATE": (
        r"\blast\s+trading\s+date\b",
        r"[uú]ltim[ao]\s+(?:d[ií]a|fecha)\s+de\s+(?:negociaci[oó]n|contrataci[oó]n)",
    ),
}


def _to_iso(lexeme: str) -> str | None:
    numeric = re.match(r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})", lexeme.strip())
    if numeric:
        day, month, year = numeric.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return spanish_date_to_iso(lexeme)


def find_labeled_date(text: str, date_kind: str) -> dict | None:
    """Primera fecha que siga a una etiqueta del tipo pedido (<220 chars).

    El hueco permite la forma "Fecha de pago: 25 dias siguientes ... (se
    concreta en el dia 23 de junio de 2025)" sin cruzar a la etiqueta
    siguiente: se toma siempre la primera fecha tras la etiqueta.
    """
    for label in _LABELS.get(date_kind, ()):
        match = re.search(rf"{label}.{{0,220}}?({ANY_DATE})", text, re.I | re.S)
        if match:
            iso = _to_iso(match.group(1))
            if iso:
                return {
                    "value": match.group(1),
                    "iso": iso,
                    "matched": match.group(0),
                    "offset": match.start(),
                }
    return None
