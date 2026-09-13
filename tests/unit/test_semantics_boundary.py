from __future__ import annotations

from ca_es.iso_boundary import (
    ISO_ADAPTER_BOUNDARY,
    projection_enabled_in_core,
    validate_projection_metadata,
)
from ca_es.semantics import FIBO_RELEASE_PIN, mapping_table


def test_fibo_release_pinned():
    assert FIBO_RELEASE_PIN


def test_unmapped_semantics_allowed():
    table = mapping_table()
    assert any(entry["mapping_status"] == "UNMAPPED" for entry in table.values())


def test_no_forced_iso_mapping():
    for entry in mapping_table().values():
        if entry["mapping_status"] == "UNMAPPED":
            assert entry["iso15022_caev"] is None


def test_iso_projection_metadata_required():
    missing = validate_projection_metadata({"standard_family": "ISO15022"})
    assert "release_state_as_of" in missing
    complete = {
        "standard_family": "ISO15022",
        "standard_release": "SRU2026",
        "release_state_as_of": "2026-09-13",
        "library": "Prowide",
        "library_version": "1.0.0",
        "message_identifier": "MT564",
        "schema_version": "1",
        "generated_at": "2026-09-13T00:00:00Z",
    }
    assert validate_projection_metadata(complete) == []


def test_iso_adapter_outside_core():
    assert projection_enabled_in_core() is False
    assert "iso-adapter-jvm" in ISO_ADAPTER_BOUNDARY["adapter_location"]
