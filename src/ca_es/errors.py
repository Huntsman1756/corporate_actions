"""Errores del dominio ca-es.

Se separan errores de *programa* (invariante violada) de errores de
*dato* (fuente ambigua/incompleta). Los segundos nunca deben resolverse
con una suposicion silenciosa.
"""
from __future__ import annotations


class CaEsError(Exception):
    """Base de todos los errores de ca-es."""


class InvariantViolation(CaEsError):
    """Un invariante del dominio se ha violado (fail-closed)."""


class UnprovenIdentityError(CaEsError):
    """Se ha intentado fusionar identidades sin evidencia suficiente."""


class FinancialPrecisionError(CaEsError):
    """Se ha intentado usar precision financiera no exacta (float)."""


class FloatingPointProhibited(FinancialPrecisionError):
    """Float binario prohibido para facts financieros canonicos."""


class AmbiguousLexemeError(FinancialPrecisionError):
    """Un lexema numerico no puede interpretarse sin suposiciones."""


class SilentOverrideProhibited(CaEsError):
    """Una fuente intento sobrescribir silenciosamente a otra."""


class AdjudicationBoundaryError(CaEsError):
    """Una adjudicacion humana intento escribir un fact financiero."""


class ContractViolation(CaEsError):
    """Un contrato desacoplado (p.ej. ListingResolver) fue violado."""
