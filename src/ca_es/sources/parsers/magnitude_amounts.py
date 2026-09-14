"""Normalizacion determinista de magnitudes monetarias verbales.

Cubre lexemas del tipo "255 millones de euros", "1,2 millones de euros",
"500 thousand euros" o "EUR 325.000.000" cuando van precedidos de un
ancla semantica que indica que representan el importe del evento
("importe ... de", "por un importe nominal maximo de", "en circulacion
es de"...).

El importe esta publicado de forma explicita: esto es una normalizacion
de representacion (coeficiente x magnitud), no una derivacion. Los
qualifiers ("aproximadamente", "hasta", "mas de", "menos de",
"alrededor de", "up to", "approximately"...) impiden la promocion:
un importe acotado/aproximado no es un amount exacto.
"""
from __future__ import annotations

import re
from decimal import Decimal

from ...numeric import FinancialAmount

_MAGNITUDES = {
    "mil": Decimal(1_000),
    "millón": Decimal(1_000_000),
    "millon": Decimal(1_000_000),
    "millones": Decimal(1_000_000),
    "million": Decimal(1_000_000),
    "millions": Decimal(1_000_000),
    "thousand": Decimal(1_000),
}

_ANCHORS: tuple[tuple[str, str], ...] = (
    (r"en circulaci[oó]n[^.]{0,60}?(?:es de|asciende a)\s*", "amount.outstanding"),
    (r"(?:por un\s+)?importe\s+(?:nominal\s+)?m[aá]ximo\s+de\s*", "amount.max_total"),
    (r"importe\s+(?:nominal\s+)?(?:de la emisi[oó]n\s+)?(?:es de|de|asciende a|ascendente a)\s*", "amount.issue_total"),
    (r"por un importe(?:\s+nominal)?\s+de\s*", "amount.stated_amount"),
    (r"por un total de\s*", "amount.stated_amount"),
)

_NUMBER = r"(\d[\d.,]*)"
_MAGNITUDE = r"(mill[oó]n(?:es)?|millones|mil|millions?|thousand)\s+(?:de\s+)?(euros?|€)"
_QUALIFIERS = re.compile(
    r"(?:aproximadamente|hasta|m[aá]s\s+de|menos\s+de|alrededor\s+de|cerca\s+de"
    r"|superior\s+a|inferior\s+a|no\s+superior|approximately|up\s+to"
    r"|at\s+least|maximum\s+of|minimum\s+of)\s+(?:(?:un|una|el|la|los|las|a|the|an)\s+)*$",
    re.I,
)


def _normalized(coefficient: str, magnitude_word: str) -> tuple[Decimal, int] | None:
    try:
        coef = FinancialAmount.parse_localized(coefficient)
    except Exception:
        return None
    magnitude = _MAGNITUDES.get(magnitude_word.lower())
    if magnitude is None:
        return None
    value = (coef.normalized * magnitude).normalize()
    scale = max(0, -value.as_tuple().exponent)
    return value, scale


def find_magnitude_amounts(text: str) -> list[dict]:
    """Importes con magnitud verbal precedidos de ancla semantica.

    Devuelve dicts {field_path, amount, matched, offset, raw_lexeme}.
    """
    found: list[dict] = []
    for anchor, field_path in _ANCHORS:
        for match in re.finditer(
            anchor + _NUMBER + r"\s+" + _MAGNITUDE, text, re.I
        ):
            before = text[max(0, match.start() - 40):match.start()]
            if _QUALIFIERS.search(before):
                continue
            full = match.group(0)
            lexeme = full[full.find(match.group(1)):]
            norm = _normalized(match.group(1), match.group(2))
            if norm is None:
                continue
            value, scale = norm
            found.append(
                {
                    "field_path": field_path,
                    "amount": FinancialAmount(
                        raw_lexeme=lexeme,
                        normalized=value,
                        scale=scale,
                        currency="EUR",
                    ),
                    "matched": match.group(0),
                    "offset": match.start(),
                }
            )
    return found
