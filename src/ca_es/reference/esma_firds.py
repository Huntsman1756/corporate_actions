"""Adapter a la capa ESMA/FIRDS existente.

ca-es consume un artefacto normalizado de listings producido por la capa
ESMA externa. No descarga ni reconstruye FIRDS. El artefacto declara su
version y no expone semantica propia mas alla de lo que FIRDS publica.
"""
from __future__ import annotations

from pathlib import Path

from ..canonical import strict_json_loads
from .contracts import InMemoryListingResolver, Listing

ARTIFACT_VERSION = "ESMA_FIRDS_LISTINGS_V1"


def load_firds_listings(path: Path) -> InMemoryListingResolver:
    raw = strict_json_loads(path.read_text(encoding="utf-8"))
    if raw.get("artifact_version") != ARTIFACT_VERSION:
        raise ValueError(
            f"artifact_version inesperada: {raw.get('artifact_version')!r}"
        )
    listings = [
        Listing(
            isin=entry["isin"],
            segment_mic=entry["segment_mic"],
            admission_date=entry["admission_date"],
            termination_date=entry.get("termination_date"),
            operating_mic=entry.get("operating_mic"),
            venue_name=entry.get("venue_name"),
            lei=entry.get("lei"),
            regulatory_lei_role=entry.get("regulatory_lei_role"),
        )
        for entry in raw["listings"]
    ]
    return InMemoryListingResolver(listings)
