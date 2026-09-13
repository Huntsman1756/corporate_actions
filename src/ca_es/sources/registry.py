"""Registro de parsers por fuente.

Un parser transforma bytes de un source document en un ``ParsedDocument``
(claims observados + referencias + roles), sin decidir todavia la verdad
global. Los parsers de G0 operan sobre fixtures estructurados que son
transcripciones de los documentos; la provenance incluye un puntero JSON
verificable ademas de la cita humana.
"""
from __future__ import annotations

from collections.abc import Callable

from .parsers.base import PARSER_VERSION, parse_structured
from .parsers.borme import parse as parse_borme
from .parsers.cnmv import parse as parse_cnmv
from .parsers.issuer import parse as parse_issuer
from .parsers.portfolio import parse as parse_portfolio

ParserFn = Callable[..., object]

PARSERS: dict[str, ParserFn] = {
    "CNMV": parse_cnmv,
    "BOE_BORME": parse_borme,
    "PORTFOLIO_STOCK_EXCHANGE": parse_portfolio,
    "ISSUER_IR": parse_issuer,
}

__all__ = ["PARSERS", "PARSER_VERSION", "parse_structured"]
