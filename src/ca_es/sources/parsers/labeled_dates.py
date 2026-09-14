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

# (patron, es_nombre_de_campo): los nombres de campo pueden aparecer como
# referencia descriptiva ("en la fecha de pago") y requieren el filtro de
# prefijo; las frases de contexto ("los titulares inscritos") no.
_LABELS: dict[str, tuple[tuple[str, bool], ...]] = {
    "EX_DATE": (
        (r"\bex\s*[-–—]?\s*date\b", True),
        (r"\bexdate\b", True),
        (r"negociar[aá]n?\s+sin\s+derecho", False),
    ),
    "RECORD_DATE": (
        (r"\brecord\s*[-–—]?\s*date\b", True),
        (r"fecha\s+de\s+registro\b", True),
        (r"titulares\s+inscritos", False),
    ),
    "PAYMENT_DATE": (
        (r"\bpayment\s*[-–—]?\s*date\b", True),
        (r"fecha\s+de\s+pago\b", True),
        (r"fecha\s+valor\b", True),
    ),
    "LAST_TRADING_DATE": (
        (r"\blast\s+trading\s+date\b", True),
        (r"[uú]ltim[ao]\s+(?:d[ií]a|fecha)\s+de\s+(?:negociaci[oó]n|contrataci[oó]n)", False),
    ),
}


def _to_iso(lexeme: str) -> str | None:
    lexeme = re.sub(r"\s+", " ", lexeme.strip())
    numeric = re.match(r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})", lexeme)
    if numeric:
        day, month, year = numeric.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return spanish_date_to_iso(lexeme)


# Uso descriptivo de la etiqueta ("en la fecha de pago", "la fecha de
# reparto"): cuando el nombre del campo se menciona como concepto y no
# introduce un valor, la siguiente fecha del documento no le pertenece.
_DESCRIPTIVE_PREFIX = re.compile(
    r"(?:en|a|de|desde|por|para|hasta|del|la|el|los|las)\s+(?:la\s+|el\s+)?$",
    re.I,
)


_FIELD_NAME_PATTERNS = tuple(
    pattern
    for entries in _LABELS.values()
    for pattern, is_field_name in entries
    if is_field_name
)
_ANY_FIELD_NAME = re.compile("|".join(_FIELD_NAME_PATTERNS), re.I)


def find_labeled_date(text: str, date_kind: str) -> dict | None:
    """Primera fecha publicada tras una etiqueta del tipo pedido.

    - Se prueban todas las ocurrencias de cada etiqueta (la primera puede
      ser una mencion delegada sin fecha, p.ej. "(payment date)").
    - El hueco de hasta 220 caracteres permite la forma "Fecha de pago:
      25 dias siguientes ... (se concreta en el dia 23 de junio de 2025)".
    - Una etiqueta precedida de articulo o preposicion ("en la fecha de
      pago", "comunicara la fecha de reparto") se considera referencia
      descriptiva y se descarta: promoveria una fecha ajena al campo.
    """
    for label, is_field_name in _LABELS.get(date_kind, ()):
        for label_match in re.finditer(label, text, re.I):
            if is_field_name and _DESCRIPTIVE_PREFIX.search(
                text[max(0, label_match.start() - 12):label_match.start()]
            ):
                continue
            window = text[label_match.end():label_match.end() + 240]
            date_match = re.search(ANY_DATE, window)
            if not date_match:
                continue
            # La fecha pertenece a esta etiqueta solo si no hay otra
            # etiqueta de campo interpuesta ("record date: X" entre
            # "ex date" y la fecha significaria captura cruzada).
            if _ANY_FIELD_NAME.search(window[: date_match.start()]):
                continue
            iso = _to_iso(date_match.group(0))
            if iso:
                matched = text[label_match.start():label_match.end() + date_match.end()]
                return {
                    "value": date_match.group(0),
                    "iso": iso,
                    "matched": matched,
                    "offset": label_match.start(),
                }
    return None
