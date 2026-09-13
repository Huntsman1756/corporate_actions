# ADR-006 — Reference-data boundary / ESMA ListingResolver

Status: ACCEPTED (G0 freeze, 2026-09-13)

## Context

Ya existe una capa que extrae LEI/ISIN/MIC de ESMA/FIRDS. ca-es no debe
reconstruir un security master.

## Decision

ca-es define un contrato congelado:

```python
class ListingResolver(Protocol):
    def listings_by_isin(self, isin: str, as_of: date) -> list[Listing]: ...
    def instruments_by_lei(self, lei: str, as_of: date) -> list[InstrumentListing]: ...
```

- La resolución es **point-in-time**: se usa el conjunto válido a la
  fecha del evento, nunca el venue actual.
- `segment_mic` se conserva; no se colapsa a operating MIC.
- Un ISIN puede estar admitido en varios MIC.
- La semántica regulatoria del LEI (`NORMAL_ISSUER`, `FUND`, ...) se
  preserva.
- El adapter consume un artefacto `ESMA_FIRDS_LISTINGS_V1`; no descarga
  FIRDS.

Enriquecer con FIRDS produce facts `REFERENCE_ENRICHMENT`, nunca
`SOURCE_ASSERTION`.

Gates: `CA_CORE_DOES_NOT_OWN_FIRDS`, `LISTING_RESOLVER_CONTRACT_FROZEN`,
`VENUE_RESOLUTION_POINT_IN_TIME`, `SEGMENT_MIC_PRESERVED`,
`MULTI_VENUE_INSTRUMENT_SUPPORTED`,
`NO_CURRENT_VENUE_USED_FOR_HISTORICAL_EVENT`,
`NO_NAME_AUTO_LINK_WHEN_LEI_OR_ISIN_AVAILABLE`, `FIRDS_SEMANTICS_PRESERVED`.
