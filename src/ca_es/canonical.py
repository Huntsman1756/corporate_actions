"""CA_ES_CANONICAL_JSON_V1 — serializacion determinista y hashing.

Perfil propio (no RFC 8785 / JCS; no se afirma compatibilidad JCS).

ALLOWED
  object, array, string, integer, boolean, null
FORBIDDEN
  float, NaN, Infinity, claves duplicadas
DATES/TIMESTAMPS
  strings ISO-8601
SERIALIZATION
  UTF-8, claves ordenadas, sin whitespace insignificante, preservacion
  exacta de Unicode (sin normalizacion NFC/NFKC).

Los valores financieros con Decimal se serializan primero a su forma
canonica (string) mediante el contrato `to_canonical()` de ca_es.numeric;
este modulo nunca acepta Decimal directamente para forzar que la escala
se explicite en el artefacto.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

_PROFILE = "CA_ES_CANONICAL_JSON_V1"
_MAX_SAFE_INT = 2**53 - 1
MAX_SAFE_INT = _MAX_SAFE_INT


def canonical_json(obj: object) -> str:
    """Serializa ``obj`` bajo CA_ES_CANONICAL_JSON_V1."""
    _assert_allowed_types(obj)
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_bytes(obj: object) -> bytes:
    return canonical_json(obj).encode("utf-8")


def sha256_hex(obj: object) -> str:
    """SHA-256 hex del contenido canonico de ``obj``."""
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def strict_json_loads(text: str) -> object:
    """Carga JSON rechazando floats, NaN/Infinity y claves duplicadas."""

    def _object_pairs_hook(pairs: list[tuple[str, object]]) -> dict:
        seen: set[str] = set()
        for key, _ in pairs:
            if key in seen:
                raise ValueError(f"clave duplicada en JSON: {key!r}")
            seen.add(key)
        return dict(pairs)

    def _reject_float(value: str) -> object:
        raise ValueError(f"float prohibido en datos G0: {value!r}")

    def _reject_constant(value: str) -> object:
        raise ValueError(f"constante no finita prohibida en datos G0: {value!r}")

    return json.loads(
        text,
        object_pairs_hook=_object_pairs_hook,
        parse_float=_reject_float,
        parse_constant=_reject_constant,
    )


def load_strict_json_object(path: str | Path) -> dict:
    obj = strict_json_loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(
            f"se requiere un objeto JSON como raiz, no {type(obj).__name__}"
        )
    return obj


def _assert_allowed_types(obj: object) -> None:
    if obj is None or isinstance(obj, (str, bool)):
        return
    if isinstance(obj, int):
        if not (-_MAX_SAFE_INT - 1 <= obj <= _MAX_SAFE_INT):
            raise ValueError(f"integer fuera del rango seguro: {obj}")
        return
    if isinstance(obj, float):
        raise ValueError(
            "float prohibido en CA_ES_CANONICAL_JSON_V1 "
            "(usar enteros o FinancialAmount.to_canonical)"
        )
    if isinstance(obj, list):
        for item in obj:
            _assert_allowed_types(item)
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise ValueError("claves no-string prohibidas en CA_ES_CANONICAL_JSON_V1")
            _assert_allowed_types(value)
        return
    raise TypeError(f"tipo no soportado en CA_ES_CANONICAL_JSON_V1: {type(obj)!r}")


CANONICAL_PROFILE = _PROFILE
