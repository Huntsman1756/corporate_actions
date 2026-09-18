"""P7.0 — CA_ES_SEMANTIC_HASH_V1: hashing semantico canonico.

Unica implementacion de hashing semantico del runtime. Ningun otro
modulo borra claves ad-hoc para comparar artefactos.

Politica (docs/p7/p70-runtime-model.md):

- excluye solo claves execution-only, por nombre, a cualquier
  profundidad: generated_at, executed_at, started_at, completed_at,
  run_id;
- nunca excluye claves business (as_of, instructed_at, resolved_at,
  first_seen_at, last_seen_at, retrieved_at, reviewed_at, actor,
  source_*, fechas efectivas/de publicacion);
- el orden de las listas es semantico y se preserva;
- serializacion determinista cross-platform: UTF-8, sort_keys,
  separadores fijos, ensure_ascii.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

SEMANTIC_HASH_POLICY = "CA_ES_SEMANTIC_HASH_V1"

# nombres que en ca-es solo existen como metadatos de ejecucion
EXCLUDED_KEYS = frozenset({
    "generated_at",
    "executed_at",
    "started_at",
    "completed_at",
    "run_id",
})


def canonicalize(obj: Any) -> Any:
    """Elimina claves execution-only recursivamente.

    No muta el input.
    """
    if isinstance(obj, dict):
        return {
            k: canonicalize(v)
            for k, v in obj.items()
            if k not in EXCLUDED_KEYS
        }
    if isinstance(obj, list):
        return [canonicalize(v) for v in obj]
    return obj


def canonical_json(obj: Any) -> str:
    """JSON canonico determinista (identico en Windows/Linux)."""
    return json.dumps(
        canonicalize(obj),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def semantic_sha256(obj: Any) -> str:
    """SHA-256 del JSON canonico del artefacto."""
    return hashlib.sha256(
        canonical_json(obj).encode("utf-8")
    ).hexdigest()


def byte_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
