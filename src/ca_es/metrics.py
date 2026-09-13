"""Metricas G0: miden lo que las fuentes permiten, sin ocultar fallos."""
from __future__ import annotations

from datetime import date


def _rate(numerator: int, denominator: int) -> str | None:
    # Ratas como string decimal: nunca float binario en artefactos canonicos.
    if denominator == 0:
        return None
    return f"{numerator / denominator:.6f}"


def _events(body: dict) -> list[dict]:
    return body["events"]


def _facts(body: dict) -> list[dict]:
    return body["facts"]


def _explicit_date(events: list[dict], field_path: str) -> int:
    count = 0
    for event in events:
        for fact in event.get("_facts", []):
            if fact["field_path"] == field_path and fact["evidence_mode"] == "EXPLICIT":
                count += 1
                break
    return count


def compute_metrics(body: dict) -> dict:
    events = _events(body)
    facts = _facts(body)
    documents = body["documents"]
    resolutions = body["identity"]["resolutions"]

    # Se materializa una vista de facts por evento para las tasas de fecha.
    facts_by_event: dict[str, list[dict]] = {}
    for fact in facts:
        facts_by_event.setdefault(fact["event_id"], []).append(fact)
    for event in events:
        event["_facts"] = facts_by_event.get(event["canonical_event_id"], [])

    events_with_isin = sum(1 for e in events if e.get("isin"))
    events_with_lei = sum(1 for e in events if e.get("lei"))
    typed_events = [e for e in events if e.get("event_type") != "UNKNOWN"]
    event_types: dict[str, int] = {}
    for event in events:
        event_types[event["event_type"]] = event_types.get(event["event_type"], 0) + 1

    financial_events = sum(
        1
        for event in events
        if any(
            isinstance(fact["value"], dict) and fact["value"].get("__financial__")
            for fact in event["_facts"]
        )
    )
    facts_with_provenance = sum(
        1
        for fact in facts
        if fact.get("source_document_id")
        and fact.get("evidence_locator")
        and fact.get("evidence_mode")
    )

    multi_revision_events = [e for e in events if len(e["revisions"]) > 1]
    amendment_proven = sum(
        1
        for event in multi_revision_events
        if all(
            revision.get("supersedes_revision_id")
            for revision in event["revisions"]
            if revision["generation"] > 0
        )
        and any(revision.get("evidence") for revision in event["revisions"])
    )

    lags: list[int] = []
    for document in documents:
        publication = document.get("publication_date")
        retrieved = document.get("retrieved_at")
        if not publication or not retrieved:
            continue
        try:
            lags.append(
                (date.fromisoformat(retrieved[:10]) - date.fromisoformat(publication)).days
            )
        except ValueError:
            continue

    ex_explicit = _rate(_explicit_date(events, "date.ex_date"), len(events))
    record_explicit = _rate(_explicit_date(events, "date.record_date"), len(events))
    payment_explicit = _rate(_explicit_date(events, "date.payment_date"), len(events))

    for event in events:
        event.pop("_facts", None)

    return {
        "documents_total": len(documents),
        "documents_parsed": len({a["document_id"] for a in body["assertions"]}),
        "events_detected": len(events),
        "issuer_identity_exact_rate": _rate(events_with_lei, len(events)),
        "instrument_identity_exact_rate": _rate(events_with_isin, len(events)),
        "event_type_coverage": {
            "typed_events": len(typed_events),
            "total_events": len(events),
            "rate": _rate(len(typed_events), len(events)),
            "by_type": dict(sorted(event_types.items())),
        },
        "ex_date_explicit_rate": ex_explicit,
        "record_date_explicit_rate": record_explicit,
        "payment_date_explicit_rate": payment_explicit,
        "amount_ratio_coverage": _rate(financial_events, len(events)),
        "field_provenance_rate": _rate(facts_with_provenance, len(facts)),
        "amendment_chain_proven_rate": _rate(amendment_proven, len(multi_revision_events)),
        "unresolved_identity_count": sum(
            1 for resolution in resolutions if resolution["state"] == "UNRESOLVED"
        ),
        "conflict_count": len(body["conflicts"]),
        "human_relation_adjudications": body["identity"][
            "manual_relation_adjudications"
        ],
        "publication_lag_days": {
            "samples": len(lags),
            "min": min(lags) if lags else None,
            "max": max(lags) if lags else None,
        },
    }
