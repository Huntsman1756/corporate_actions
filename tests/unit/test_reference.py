from __future__ import annotations

from datetime import date

from ca_es.reference.contracts import (
    InMemoryListingResolver,
    Listing,
    UnresolvedListingResolver,
)


def _resolver() -> InMemoryListingResolver:
    return InMemoryListingResolver(
        [
            Listing("ES0113900J37", "XMAD", "2000-01-01"),
            Listing("ES0113900J37", "MAD4", "2000-01-01", operating_mic="XMAD"),
            Listing("ES0113900J37", "XOLD", "1995-01-01", termination_date="2005-12-31"),
        ]
    )


def test_venue_resolution_point_in_time():
    resolver = _resolver()
    active = resolver.listings_by_isin("ES0113900J37", date(2026, 4, 28))
    assert {listing.segment_mic for listing in active} == {"XMAD", "MAD4"}
    assert "XOLD" not in {listing.segment_mic for listing in active}


def test_historical_venue_present_at_historical_date():
    resolver = _resolver()
    active = resolver.listings_by_isin("ES0113900J37", date(2001, 1, 1))
    assert {listing.segment_mic for listing in active} == {"XMAD", "MAD4", "XOLD"}


def test_segment_mic_preserved_not_collapsed():
    resolver = _resolver()
    active = resolver.listings_by_isin("ES0113900J37", date(2026, 4, 28))
    assert all(listing.segment_mic for listing in active)


def test_unresolved_resolver_fails_closed():
    resolver = UnresolvedListingResolver()
    assert resolver.listings_by_isin("ES0113900J37", date(2026, 4, 28)) == []
