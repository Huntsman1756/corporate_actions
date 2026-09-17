from __future__ import annotations

from datetime import date

import pytest

from ca_es.reference.esma_firds import load_firds_listings
from ca_es.reference.instrument_binding import load_instrument_bindings

pytestmark = pytest.mark.private_corpus("g0")


def _p3_event(result: dict) -> dict:
    return next(e for e in result["body"]["events"] if e["isin"] == "ES0105282000")


def _p3_facts(result: dict, event: dict) -> list[dict]:
    return [
        f for f in result["body"]["facts"] if f["event_id"] == event["canonical_event_id"]
    ]


def test_r3_1_real_event_to_isin_exact_without_name(repo_root, real_run):
    index = load_instrument_bindings(
        repo_root / "g0/corpus/reference/portfolio-instruments.json"
    )
    # Relacion estructurada documento->instrumento de la propia fuente.
    assert index.document_bindings["PORTFOLIO-4733"] == "ES0105282000"
    reference = index.instrument_by_isin["ES0105282000"]
    assert reference.product_id == "5"
    assert reference.nif == "A87558953"

    event = _p3_event(real_run)
    assert event["instrument_binding"]["evidence_mode"] == "SOURCE_CARRIED_INSTRUMENT_BINDING"
    binding = next(
        f
        for f in _p3_facts(real_run, event)
        if f["field_path"] == "affected_instrument.isin"
    )
    assert binding["value"] == "ES0105282000"
    assert binding["evidence_mode"] == "SOURCE_CARRIED_INSTRUMENT_BINDING"
    # La evidencia enlaza con la ruta canonica/product_id, no con el nombre.
    assert "product_id=5" in binding["evidence_locator"]


def test_r3_2_isin_to_firds_exact(repo_root, real_run):
    resolver = load_firds_listings(
        repo_root / "g0/corpus/reference/esma-firds-listings-real.json"
    )
    listings = resolver.listings_by_isin("ES0105282000", date(2025, 7, 24))
    assert listings
    assert {listing.lei for listing in listings} == {"959800GS3VF3X7V7QR11"}
    event = _p3_event(real_run)
    lei = next(
        f
        for f in _p3_facts(real_run, event)
        if f["field_path"] == "affected_instrument.lei"
    )
    assert lei["value"] == "959800GS3VF3X7V7QR11"
    assert lei["evidence_mode"] == "REFERENCE_ENRICHMENT"


def test_r3_3_point_in_time_mic_resolution(repo_root, real_run):
    resolver = load_firds_listings(
        repo_root / "g0/corpus/reference/esma-firds-listings-real.json"
    )
    # A la fecha del evento (ex-date 2025-07-24): solo POSE.
    event = _p3_event(real_run)
    segment = {
        f["value"]
        for f in _p3_facts(real_run, event)
        if f["field_path"] == "affected_venue.segment_mic"
    }
    assert segment == {"POSE"}
    # Historicamente (2021) P3 no estaba en POSE: la resolucion es point-in-time.
    historical = {
        listing.segment_mic
        for listing in resolver.listings_by_isin("ES0105282000", date(2021, 1, 1))
    }
    assert historical == {"GROW", "LEUE"}


def test_r3_4_second_run_deterministic_with_bindings(repo_root, real_resolver):
    from ca_es.pipeline import run_pipeline

    kwargs = dict(
        manifest_relpath="g0/manifests/real-corpus.json",
        adjudications_relpath="g0/manifests/adjudications-real.json",
        instrument_bindings_relpath="g0/corpus/reference/portfolio-instruments.json",
        resolver=real_resolver,
    )
    first = run_pipeline(repo_root, run_id="a", executed_at="2026-01-01T00:00:00Z", **kwargs)
    second = run_pipeline(repo_root, run_id="b", executed_at="2026-06-06T00:00:00Z", **kwargs)
    assert first["result_sha"] == second["result_sha"]
