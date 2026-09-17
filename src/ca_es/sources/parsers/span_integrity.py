"""Integridad de spans numericos extraidos de PDF.

La extraccion de texto puede insertar whitespace dentro de un lexema
decimal ("0. 53", "0, 47"): la cola del importe apareceria como un
entero falso ("53", "47"). `interrupted_decimal` detecta la fractura;
la decision de abstenerse o reconstruir es del parser (nunca se
normaliza la cola como si fuera un valor completo).
"""
from __future__ import annotations

import re

_INTERRUPTED_TAIL = re.compile(r"\d[.,]\s*$")


def interrupted_decimal(text: str, pos: int) -> bool:
    """True si `pos` inicia digitos que continuan un numero roto.

    El lexema inmediatamente anterior termina en "<digito><. ó ,>
    <whitespace>", es decir, los digitos que empiezan en `pos` son la
    parte fraccionaria de un decimal partido por la extraccion, no un
    importe independiente.
    """
    return bool(_INTERRUPTED_TAIL.search(text[max(0, pos - 8):pos]))
