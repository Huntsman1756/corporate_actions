"""P15.4 — CA_ES_TAX_RECOVERY_DOCUMENT_SET_V1.

Checklist documental por claim: los documentos exigidos por la
regla recovery + los aportados de forma explicita. P15 NO genera
certificados ni formularios legales: registra presencia y
referencia con provenance.

Fuentes de referencias soportadas:
- facts FIN: `20C:TARE` -> RECLAIM_DOCUMENTATION_REFERENCE,
  `20C:BORE` -> BENEFICIAL_OWNER_REFERENCE (qualifiers ya emitidos
  por el extractor generico del adapter; en MX son campos SR2026
  fuera del pin SRU2025 — se aceptan via provided_documents).
- provided_documents: manifiesto explicito
  [{doc_type, reference, source}].

Completeness: COMPLETE solo si TODOS los required_documents de la
regla tienen status PRESENT. UNCLAIMED (documento aportado sin
claim asociado) se preserva con reason, nunca se descarta.
"""

from __future__ import annotations

from .tax_recovery_rules import DOC_TYPES

DOCSET_SCHEMA = "CA_ES_TAX_RECOVERY_DOCUMENT_SET_V1"

PRESENT = "PRESENT"
MISSING = "MISSING"
COMPLETE = "COMPLETE"
INCOMPLETE = "INCOMPLETE"

# qualifier FIN -> doc_type interno
_FIN_QUALIFIER_DOCS = {
    "TARE": "RECLAIM_DOCUMENTATION_REFERENCE",
    "BORE": "BENEFICIAL_OWNER_REFERENCE",
}


def _fin_document_refs(facts_docs):
    """Referencias documentales de facts FIN (20C:TARE/BORE)."""
    out = []
    for doc in facts_docs or []:
        for f in doc.get("facts") or []:
            doc_type = _FIN_QUALIFIER_DOCS.get(
                f.get("source_qualifier"))
            if doc_type is None or f.get("source_tag") != "20C":
                continue
            out.append({
                "doc_type": doc_type,
                "reference": f.get("value"),
                "source": "FIN_QUALIFIER",
                "provenance": [{
                    "field_path": f.get("field_path"),
                    "evidence_locator": f.get("evidence_locator"),
                    "raw": f.get("value"),
                    "source_tag": f.get("source_tag"),
                    "source_qualifier": f.get("source_qualifier"),
                }],
            })
    return out


def document_set(claim: dict, rule: dict | None,
                 provided_documents: list[dict] | None = None,
                 facts_docs: list[dict] | None = None,
                 now: str | None = None) -> dict:
    """Checklist documental de un claim.

    provided_documents: [{doc_type, reference, source?, provenance?}]
    facts_docs: facts FIN/MX crudos para extraer TARE/BORE.
    """
    required = list((rule or {}).get("required_documents") or [])
    provided = []
    for d in provided_documents or []:
        dt = d.get("doc_type")
        provided.append({
            "doc_type": dt if dt in DOC_TYPES else "OTHER",
            "reference": d.get("reference"),
            "source": d.get("source") or "MANUAL",
            "provenance": list(d.get("provenance") or []),
        })
    provided.extend(_fin_document_refs(facts_docs))

    by_type: dict[str, list] = {}
    for p in provided:
        by_type.setdefault(p["doc_type"], []).append(p)

    items = []
    for doc_type in required:
        hits = by_type.get(doc_type) or []
        if hits:
            for h in hits:
                items.append({
                    "doc_type": doc_type,
                    "required": True,
                    "status": PRESENT,
                    "reference": h.get("reference"),
                    "source": h.get("source"),
                    "provenance": h.get("provenance") or [],
                })
        else:
            items.append({
                "doc_type": doc_type,
                "required": True,
                "status": MISSING,
                "reference": None,
                "source": None,
                "provenance": [],
            })

    unclaimed = []
    for doc_type, hits in by_type.items():
        if doc_type in required:
            continue
        for h in hits:
            unclaimed.append({
                "doc_type": doc_type,
                "required": False,
                "status": "UNCLAIMED",
                "reason": "DOC_NOT_REQUIRED_BY_RULE",
                "reference": h.get("reference"),
                "source": h.get("source"),
                "provenance": h.get("provenance") or [],
            })

    set_status = COMPLETE if all(
        i["status"] == PRESENT for i in items) else INCOMPLETE
    return {
        "schema": DOCSET_SCHEMA,
        "generated_at": now,
        "claim_id": claim.get("claim_id"),
        "canonical_event_id": claim.get("canonical_event_id"),
        "rule_id": (rule or {}).get("rule_id"),
        "set_status": set_status,
        "items": items + unclaimed,
    }


def document_sets(cases_doc: dict, ruleset_doc: dict | None,
                  provided_documents: list[dict] | None = None,
                  facts_docs: list[dict] | None = None,
                  now: str | None = None) -> dict:
    """Doc sets para todos los claims del doc (indice por claim)."""
    rules = {r.get("rule_id"): r
             for r in (ruleset_doc or {}).get("rules") or []}
    sets = {}
    for claim in cases_doc.get("claims") or []:
        ds = document_set(claim, rules.get(claim.get("rule_id")),
                          provided_documents, facts_docs, now=now)
        sets[claim["claim_id"]] = ds
    return {
        "schema": DOCSET_SCHEMA,
        "generated_at": now,
        "canonical_event_id": cases_doc.get("canonical_event_id"),
        "kind": "INDEX",
        "sets": sets,
    }
