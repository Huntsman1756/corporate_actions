"""Contrato ListingResolver — limite congelado con la capa ESMA/FIRDS.

ca-es NO reconstruye FIRDS ni posee un security master. Consume LEI ->
ISIN -> segment MIC mediante este contrato desacoplado. La resolucion es
point-in-time: nunca se usa el venue actual para enriquecer un evento
historico.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

from ..vocab import IdentityState

CONTRACT_VERSION = "CA_ES_LISTING_RESOLVER_V1"


@dataclass(frozen=True)
class Listing:
    isin: str
    segment_mic: str
    admission_date: str
    termination_date: str | None = None
    operating_mic: str | None = None
    venue_name: str | None = None
    lei: str | None = None
    regulatory_lei_role: str | None = None

    def to_canonical(self) -> dict:
        return {
            "isin": self.isin,
            "segment_mic": self.segment_mic,
            "operating_mic": self.operating_mic,
            "venue_name": self.venue_name,
            "lei": self.lei,
            "regulatory_lei_role": self.regulatory_lei_role,
            "admission_date": self.admission_date,
            "termination_date": self.termination_date,
        }


@dataclass(frozen=True)
class InstrumentListing:
    lei: str
    isin: str
    segment_mic: str
    admission_date: str
    termination_date: str | None = None
    operating_mic: str | None = None
    regulatory_lei_role: str | None = None

    def to_canonical(self) -> dict:
        return {
            "lei": self.lei,
            "isin": self.isin,
            "segment_mic": self.segment_mic,
            "operating_mic": self.operating_mic,
            "regulatory_lei_role": self.regulatory_lei_role,
            "admission_date": self.admission_date,
            "termination_date": self.termination_date,
        }


@runtime_checkable
class ListingResolver(Protocol):
    def listings_by_isin(self, isin: str, as_of: date) -> list[Listing]:
        ...

    def instruments_by_lei(self, lei: str, as_of: date) -> list[InstrumentListing]:
        ...


def _active(admission: str, termination: str | None, as_of: date) -> bool:
    admitted = date.fromisoformat(admission)
    if admitted > as_of:
        return False
    if termination is None:
        return True
    return date.fromisoformat(termination) >= as_of


class InMemoryListingResolver:
    """Resolver determinista para tests y fixtures."""

    def __init__(self, listings: list[Listing]) -> None:
        self._listings = tuple(listings)

    def listings_by_isin(self, isin: str, as_of: date) -> list[Listing]:
        matched = [
            listing
            for listing in self._listings
            if listing.isin == isin
            and _active(listing.admission_date, listing.termination_date, as_of)
        ]
        return sorted(matched, key=lambda item: (item.segment_mic, item.admission_date))

    def instruments_by_lei(self, lei: str, as_of: date) -> list[InstrumentListing]:
        instruments = [
            InstrumentListing(
                lei=listing.lei or "",
                isin=listing.isin,
                segment_mic=listing.segment_mic,
                admission_date=listing.admission_date,
                termination_date=listing.termination_date,
                operating_mic=listing.operating_mic,
                regulatory_lei_role=listing.regulatory_lei_role,
            )
            for listing in self.listings_by_isin_any(lei)
            if _active(listing.admission_date, listing.termination_date, as_of)
        ]
        return sorted(instruments, key=lambda item: (item.isin, item.segment_mic))

    def listings_by_isin_any(self, lei: str) -> list[Listing]:
        return [listing for listing in self._listings if listing.lei == lei]


class UnresolvedListingResolver:
    """Resolver fail-closed: nunca inventa un venue."""

    def listings_by_isin(self, isin: str, as_of: date) -> list[Listing]:
        return []

    def instruments_by_lei(self, lei: str, as_of: date) -> list[InstrumentListing]:
        return []


def instrument_identity_state(listings: list[Listing]) -> str:
    if not listings:
        return IdentityState.UNRESOLVED.value
    isins = {listing.isin for listing in listings}
    if len(isins) > 1:
        return IdentityState.CONFLICTING.value
    return IdentityState.EXACT.value
