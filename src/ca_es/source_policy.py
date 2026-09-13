"""Politica de fuentes: rol, almacenamiento raw y redistribucion.

La policy es un input autoritativo del sistema. Declara, por fuente:
autoridad, rol, si el raw es LOCAL_ONLY o redistribuible, y si existe
interfaz publica de ingesta demostrada.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .canonical import strict_json_loads

POLICY_VERSION = "CA_ES_SOURCE_POLICY_V1"


@dataclass(frozen=True)
class SourcePolicy:
    source_id: str
    authority: str
    roles: tuple[str, ...]
    raw_storage: str
    redistribution: str
    ingestion_status: str
    terms_reviewed_at: str | None
    terms_source: str | None
    availability_claim: str | None = None
    notes: str | None = None

    @property
    def is_ingestible(self) -> bool:
        return self.ingestion_status == "ACTIVE"


def load_source_policy(path: Path) -> dict[str, SourcePolicy]:
    raw = strict_json_loads(path.read_text(encoding="utf-8"))
    sources = raw["sources"]
    out: dict[str, SourcePolicy] = {}
    for source_id, entry in sources.items():
        out[source_id] = SourcePolicy(
            source_id=source_id,
            authority=entry["authority"],
            roles=tuple(entry["role"]),
            raw_storage=entry["raw_storage"],
            redistribution=entry["redistribution"],
            ingestion_status=entry["ingestion_status"],
            terms_reviewed_at=entry.get("terms_reviewed_at"),
            terms_source=entry.get("terms_source"),
            availability_claim=entry.get("availability_claim"),
            notes=entry.get("notes"),
        )
    return out


def assert_ingestible(policy: dict[str, SourcePolicy], source_id: str) -> SourcePolicy:
    if source_id not in policy:
        raise KeyError(f"fuente sin policy declarada: {source_id}")
    entry = policy[source_id]
    if not entry.is_ingestible:
        raise PermissionError(
            f"fuente {source_id} no es ingerible en G0 "
            f"(ingestion_status={entry.ingestion_status})"
        )
    return entry
