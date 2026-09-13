"""Identidad de corporate actions: ledger append-only y resolucion canonica."""

from .engine import (
    CanonicalResolution,
    aliases,
    group_by_canonical,
    resolve_canonical,
)
from .ledger import (
    LEDGER_VERSION,
    IdentityLedger,
    IdentityRelation,
    load_adjudications,
    load_identity_ledger,
)

__all__ = [
    "CanonicalResolution",
    "IdentityLedger",
    "IdentityRelation",
    "LEDGER_VERSION",
    "aliases",
    "group_by_canonical",
    "load_adjudications",
    "load_identity_ledger",
    "resolve_canonical",
]
