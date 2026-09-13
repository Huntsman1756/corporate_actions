"""Parser CNMV (fixture estructurado)."""
from __future__ import annotations

from ...canonical import strict_json_loads
from ...source_policy import SourcePolicy
from ..documents import SourceDocument
from .base import ParsedDocument, parse_structured

SOURCE_ID = "CNMV"


def parse(
    payload: bytes, document: SourceDocument, policy: dict[str, SourcePolicy]
) -> ParsedDocument:
    if document.source_id != SOURCE_ID:
        raise ValueError(f"parser CNMV recibio fuente {document.source_id}")
    raw = strict_json_loads(payload.decode("utf-8"))
    return parse_structured(raw, document, policy, parser_name="cnmv")
