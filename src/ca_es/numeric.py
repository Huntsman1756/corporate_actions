"""Precision financiera exacta.

PROHIBIDO ``float`` para valores financieros canonicos. Se preserva:

  raw lexical representation
  normalized decimal (Decimal)
  published scale
  currency

El lexema raw es la autoridad; la normalizacion solo sustituye el
separador decimal y valida, nunca redondea. Un lexema ambiguo
(p.ej. con '.' y ',' a la vez) se rechaza en vez de interpretarse.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .errors import AmbiguousLexemeError, FloatingPointProhibited

_LEXEME_RE = re.compile(r"^([+-]?)(\d+)(?:([.,])(\d+))?$")


@dataclass(frozen=True)
class FinancialAmount:
    """Importe/ratio con precision exacta y escala publicada."""

    raw_lexeme: str
    normalized: Decimal
    scale: int
    currency: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.normalized, float):  # defensa en profundidad
            raise FloatingPointProhibited("FinancialAmount.normalized no puede ser float")

    @classmethod
    def parse(cls, raw_lexeme: str, currency: str | None = None) -> "FinancialAmount":
        if not isinstance(raw_lexeme, str):
            if isinstance(raw_lexeme, float):
                raise FloatingPointProhibited(
                    f"lexema financiero float prohibido: {raw_lexeme!r}"
                )
            raise AmbiguousLexemeError(
                f"lexema financiero debe ser string, recibido {type(raw_lexeme)!r}"
            )
        raw = raw_lexeme.strip()
        match = _LEXEME_RE.match(raw)
        if not match:
            raise AmbiguousLexemeError(f"lexema financiero no interpretable: {raw!r}")
        _sign, integer, separator, fraction = match.groups()
        if separator is None:
            scale = 0
            normalized_text = integer
        else:
            scale = len(fraction)
            normalized_text = f"{integer}.{fraction}"
        sign = "-" if _sign == "-" else ""
        try:
            normalized = Decimal(f"{sign}{normalized_text}")
        except InvalidOperation as exc:  # pragma: no cover - guarda
            raise AmbiguousLexemeError(f"lexema financiero invalido: {raw!r}") from exc
        return cls(raw_lexeme=raw, normalized=normalized, scale=scale, currency=currency)

    def normalized_str(self) -> str:
        """Representacion decimal no cientifica, preservando la escala."""
        return format(self.normalized, "f")

    def to_canonical(self) -> dict:
        return {
            "raw_lexeme": self.raw_lexeme,
            "normalized": self.normalized_str(),
            "scale": self.scale,
            "currency": self.currency,
        }


def ensure_exact(value: object, field: str = "value") -> None:
    """Falla si ``value`` contiene float binario en cualquier profundidad."""
    if isinstance(value, float):
        raise FloatingPointProhibited(f"float prohibido en fact financiero ({field})")
    if isinstance(value, FinancialAmount):
        return
    if isinstance(value, dict):
        for key, item in value.items():
            ensure_exact(item, f"{field}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            ensure_exact(item, f"{field}[{index}]")
