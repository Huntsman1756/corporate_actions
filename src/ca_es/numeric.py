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
        if isinstance(self.normalized, Decimal) and not self.normalized.is_finite():
            raise AmbiguousLexemeError("FinancialAmount.normalized debe ser finito")

    @classmethod
    def parse_localized(
        cls,
        raw_lexeme: str,
        currency: str | None = None,
        decimal_sep: str = ",",
        thousands_sep: str = ".",
    ) -> "FinancialAmount":
        """Interpreta un numero localizado sin ambiguedad ni redondeo.

        Exige agrupacion de miles valida (grupos de 3). Preserva el
        ``raw_lexeme`` original y normaliza solo el separador decimal.
        """
        if not isinstance(raw_lexeme, str):
            if isinstance(raw_lexeme, float):
                raise FloatingPointProhibited(
                    f"lexema financiero float prohibido: {raw_lexeme!r}"
                )
            raise AmbiguousLexemeError("lexema financiero debe ser string")
        raw = raw_lexeme.strip()
        if not raw:
            raise AmbiguousLexemeError("lexema financiero vacio")
        sign = ""
        if raw[0] in "+-":
            sign, raw = ("-" if raw[0] == "-" else ""), raw[1:]
        if decimal_sep in raw:
            int_part, _, frac = raw.partition(decimal_sep)
        else:
            int_part, frac = raw, None
        groups = (
            int_part.split(thousands_sep)
            if thousands_sep and thousands_sep in int_part
            else [int_part]
        )
        if not all(group.isdigit() for group in groups) or not groups:
            raise AmbiguousLexemeError(f"lexema financiero no interpretable: {raw_lexeme!r}")
        if len(groups) > 1 and (len(groups[0]) > 3 or any(len(g) != 3 for g in groups[1:])):
            raise AmbiguousLexemeError(
                f"agrupacion de miles invalida: {raw_lexeme!r}"
            )
        if frac is not None and not frac.isdigit():
            raise AmbiguousLexemeError(f"parte decimal invalida: {raw_lexeme!r}")
        integer = "".join(groups)
        scale = len(frac) if frac else 0
        normalized_text = f"{integer}.{frac}" if frac else integer
        normalized = Decimal(f"{sign}{normalized_text}")
        return cls(raw_lexeme=raw_lexeme.strip(), normalized=normalized, scale=scale, currency=currency)

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

    @classmethod
    def from_cents(
        cls,
        raw_lexeme: str,
        currency: str = "EUR",
        cents_per_unit: int = 100,
        decimal_sep: str = ",",
        thousands_sep: str | None = ".",
    ) -> "FinancialAmount":
        """Convierte un importe publicado en centimos a la unidad (EUR).

        Es una derivacion por definicion (1 EUR = 100 centimos). Se
        preserva el lexema publicado y la escala resultante
        (escala_publicada + log10(cents_per_unit)).
        """
        published = cls.parse_localized(
            raw_lexeme,
            currency=currency,
            decimal_sep=decimal_sep,
            thousands_sep=thousands_sep,
        )
        factor = Decimal(cents_per_unit)
        exponent = factor.adjusted()
        if factor == Decimal((0, (1,), exponent)):
            parts = published.normalized.as_tuple()
            normalized = Decimal(
                (parts.sign, parts.digits, parts.exponent - exponent)
            )
        else:
            normalized = published.normalized / factor
        return cls(
            raw_lexeme=published.raw_lexeme,
            normalized=normalized,
            scale=published.scale + exponent,
            currency=currency,
        )

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
