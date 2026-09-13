from __future__ import annotations

from datetime import date
from pathlib import Path

from ca_es.reference.esma_firds import load_firds_listings

ARTIFACT = "g0/corpus/reference/esma-firds-listings-real.json"


def _resolver(repo_root: Path):
    return load_firds_listings(repo_root / ARTIFACT)


def test_real_firds_artifact_loads(repo_root):
    resolver = _resolver(repo_root)
    active = resolver.listings_by_isin("ES0105282000", date(2026, 5, 20))
    assert active


def test_p3_point_in_time_current_venue(repo_root):
    # En 2026 P3 solo cotiza en POSE (Portfolio); GROW/LEUE ya terminaron.
    active = _resolver(repo_root).listings_by_isin("ES0105282000", date(2026, 5, 20))
    assert {listing.segment_mic for listing in active} == {"POSE"}


def test_p3_point_in_time_historical_venue(repo_root):
    active = _resolver(repo_root).listings_by_isin("ES0105282000", date(2021, 1, 1))
    assert {listing.segment_mic for listing in active} == {"GROW", "LEUE"}
    assert "POSE" not in {listing.segment_mic for listing in active}


def test_san_multi_venue_and_segment_mic_preserved(repo_root):
    active = _resolver(repo_root).listings_by_isin("ES0113900J37", date(2026, 4, 28))
    mics = {listing.segment_mic for listing in active}
    assert len(mics) > 1
    assert "XMAD" in mics
    # segment MIC no se colapsa a operating MIC
    grow = [
        listing
        for listing in _resolver(repo_root).listings_by_isin(
            "ES0105282000", date(2021, 1, 1)
        )
        if listing.segment_mic == "GROW"
    ]
    assert grow and grow[0].operating_mic == "POSE"
