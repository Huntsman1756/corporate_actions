"""Pipeline G0: corpus -> assertions -> identidad -> revisiones -> facts.

La misma combinacion (raw corpus, config, identity ledger, adjudication
ledger) produce la misma resolucion canonica y el mismo ``result_sha``.
``executed_at`` y ``run_id`` quedan fuera del hash logico para que una
segunda ejecucion sea determinista.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

from .assertions import Assertion, build_assertions
from .canonical import sha256_hex, sha256_text, strict_json_loads
from .entitlement import validate_entitlement_basis
from .identity import (
    IdentityLedger,
    IdentityRelation,
    aliases,
    group_by_canonical,
    load_adjudications,
    load_identity_ledger,
    resolve_canonical,
)
from .metrics import compute_metrics
from .namespaces import candidate_event_id
from .provenance import Fact, build_facts, detect_conflicts
from .reference.contracts import ListingResolver, UnresolvedListingResolver
from .reference.instrument_binding import (
    InstrumentBindingIndex,
    load_instrument_bindings,
    resolve_event_instrument,
)
from .revisions import MemberDocument, build_revisions
from .source_policy import SourcePolicy, load_source_policy
from .sources.documents import (
    CorpusManifest,
    SourceDocument,
    load_corpus_manifest,
    load_raw_bytes,
    verify_document,
)
from .sources.registry import PARSERS, PARSER_VERSION
from .sources.parsers.base import DocumentReference, ParsedDocument
from .temporal import RULESET_VERSION, check as temporal_check
from .vocab import AUTO_LINK_RELATIONS, DecisionBasis, FactOrigin, RelationType

EVENT_SCOPE_REVISION = "EVENT_SCOPE"
PIPELINE_VERSION = "CA_ES_PIPELINE_V1"

_DEFAULT_POLICY_RELPATH = "docs/sources/source-policy.json"


@dataclass
class ParsedCorpus:
    manifest: CorpusManifest
    policy: dict[str, SourcePolicy]
    documents: dict[str, SourceDocument]
    parsed: dict[str, ParsedDocument]
    raw_records: dict[str, dict]
    verification: list[dict]
    parse_errors: dict[str, str] = field(default_factory=dict)


def load_and_parse(
    corpus_root: Path, manifest_path: Path, policy_path: Path
) -> ParsedCorpus:
    policy = load_source_policy(policy_path)
    manifest = load_corpus_manifest(manifest_path, policy)
    return parse_manifest_corpus(corpus_root, manifest, policy)


def parse_manifest_corpus(
    corpus_root: Path,
    manifest: CorpusManifest,
    policy: dict[str, SourcePolicy],
) -> ParsedCorpus:
    """Parsea un manifest ya construido (fichero o en memoria — P9
    canon refresh). Identica semantica a ``load_and_parse``."""
    documents: dict[str, SourceDocument] = {}
    parsed: dict[str, ParsedDocument] = {}
    raw_records: dict[str, dict] = {}
    verification: list[dict] = []
    parse_errors: dict[str, str] = {}
    for document in manifest.documents:
        documents[document.document_id] = document
        result = verify_document(corpus_root, document)
        verification.append(result)
        if document.retrieval_status != "OK":
            continue
        if not result.get("sha256_match"):
            raise ValueError(
                f"SHA-256 no coincide para {document.document_id}: "
                f"expected={result.get('expected_sha256')} "
                f"observed={result.get('observed_sha256')}"
            )
        parser = PARSERS.get(document.source_id)
        if parser is None:
            parse_errors[document.document_id] = f"NO_PARSER:{document.source_id}"
            continue
        payload = load_raw_bytes(corpus_root, document)
        parsed_doc = parser(payload, document, policy)
        parsed_doc = _merge_manifest_relations(parsed_doc, document)
        parsed[document.document_id] = parsed_doc
        raw_records[document.document_id] = parsed_doc.raw_record
    return ParsedCorpus(
        manifest=manifest,
        policy=policy,
        documents=documents,
        parsed=parsed,
        raw_records=raw_records,
        verification=verification,
        parse_errors=parse_errors,
    )


def _merge_manifest_relations(
    parsed_doc: ParsedDocument, document: SourceDocument
) -> ParsedDocument:
    """Anade relaciones oficiales declaradas en el registro de la fuente."""
    if not document.relations:
        return parsed_doc
    existing = {
        (r.relation, r.target_source_id, r.target_official_document_id)
        for r in parsed_doc.references
    }
    references = list(parsed_doc.references)
    for entry in document.relations:
        key = (
            entry["relation"],
            entry.get("target_source_id"),
            entry.get("target_official_document_id"),
        )
        if key in existing:
            continue
        existing.add(key)
        references.append(
            DocumentReference(
                relation=entry["relation"],
                target_official_document_id=entry.get("target_official_document_id"),
                target_source_id=entry.get("target_source_id"),
                evidence_locator=entry.get("evidence_locator", document.official_document_id),
                target_publication_date=entry.get("target_publication_date"),
            )
        )
    return replace(parsed_doc, references=tuple(references))


def _documented_candidates(corpus: ParsedCorpus) -> dict[tuple[str, str], str]:
    mapping: dict[tuple[str, str], str] = {}
    for document in corpus.parsed.values():
        mapping[
            (document.document.source_id, document.document.official_document_id)
        ] = candidate_event_id(
            document.document.source_id, document.document.official_document_id
        )
    return mapping


def build_identity(
    corpus: ParsedCorpus,
    seed_ledger: IdentityLedger | None = None,
    adjudications_path: Path | None = None,
) -> tuple[IdentityLedger, dict]:
    ledger = seed_ledger or IdentityLedger()
    documented = _documented_candidates(corpus)
    deterministic: list[IdentityRelation] = []
    for document_id, parsed_doc in sorted(corpus.parsed.items()):
        source_id = parsed_doc.document.source_id
        own_candidate = candidate_event_id(
            source_id, parsed_doc.document.official_document_id
        )
        for reference in parsed_doc.references:
            if reference.relation not in {r.value for r in AUTO_LINK_RELATIONS}:
                continue
            target_source = reference.target_source_id or source_id
            target = documented.get(
                (target_source, reference.target_official_document_id or "")
            )
            if target is None or target == own_candidate:
                continue
            deterministic.append(
                IdentityRelation(
                    relation=RelationType.SAME_CORPORATE_ACTION.value,
                    a=own_candidate,
                    b=target,
                    decision_basis=DecisionBasis.DETERMINISTIC.value,
                    evidence=(reference.evidence_locator,),
                )
            )
    ledger = ledger.extend(deterministic)
    manual_count = 0
    if adjudications_path is not None:
        manual = load_adjudications(adjudications_path)
        manual_count = len(manual)
        ledger = ledger.extend(manual)

    candidate_ids = sorted(
        candidate_event_id(d.source_id, d.official_document_id)
        for d in corpus.documents.values()
        if d.retrieval_status == "OK"
    )
    pinned = ledger.bindings()
    resolutions = resolve_canonical(candidate_ids, ledger, pinned=pinned)
    groups = group_by_canonical(resolutions)
    # Persistir el canonical resuelto: estable ante futuros candidatos.
    ledger = ledger.with_bindings(
        {r.candidate_id: r.canonical_event_id for r in resolutions}
    )
    identity = {
        "ledger": ledger.to_canonical(),
        "resolutions": [
            {
                "candidate_id": r.candidate_id,
                "canonical_event_id": r.canonical_event_id,
                "state": r.state,
                "linked": r.linked,
            }
            for r in resolutions
        ],
        "aliases": aliases(resolutions),
        "canonical_events": sorted(groups),
        "manual_relation_adjudications": manual_count,
    }
    return ledger, identity


def _event_as_of(parsed_docs: list[ParsedDocument]) -> str | None:
    """Fecha point-in-time del evento: ex > record > payment > earliest claim."""
    for kind in ("EX_DATE", "RECORD_DATE", "PAYMENT_DATE"):
        found = sorted(
            claim.value
            for doc in parsed_docs
            for claim in doc.claims
            if claim.date_kind == kind and isinstance(claim.value, str)
        )
        if found:
            return found[0]
    date_values = sorted(
        claim.value
        for doc in parsed_docs
        for claim in doc.claims
        if claim.date_kind is not None and isinstance(claim.value, str)
    )
    return date_values[0] if date_values else None


def _isin(parsed_docs: list[ParsedDocument]) -> str | None:
    values = sorted({doc.isin for doc in parsed_docs if doc.isin})
    return values[0] if len(values) == 1 else None


def _lei(parsed_docs: list[ParsedDocument]) -> str | None:
    values = sorted({doc.lei for doc in parsed_docs if doc.lei})
    return values[0] if len(values) == 1 else None


def _event_type(facts: list[Fact]) -> tuple[str, str | None, str]:
    explicit = [
        f
        for f in facts
        if f.field_path == "event_type"
        and f.fact_origin == FactOrigin.SOURCE_ASSERTION.value
    ]
    distinct = sorted({str(f.value) for f in explicit if str(f.value) != "UNKNOWN"})
    if len(distinct) == 1:
        locator = next(
            f.evidence_locator
            for f in explicit
            if str(f.value) == distinct[0] and f.evidence_locator
        )
        return distinct[0], locator, "EXPLICIT"
    if not distinct:
        return "UNKNOWN", None, "UNKNOWN"
    return "UNKNOWN", None, "CONFLICTING"


def _binding_facts(canonical_event_id: str, resolution) -> list[Fact]:
    if resolution.isin is None:
        return []
    return [
        Fact(
            event_id=canonical_event_id,
            revision_id=EVENT_SCOPE_REVISION,
            assertion_id=f"binding:{canonical_event_id}:{resolution.isin}",
            field_path="affected_instrument.isin",
            value=resolution.isin,
            source_document_id=resolution.source_document_id or "INSTRUMENT_BINDING",
            source_id="PORTFOLIO_STOCK_EXCHANGE"
            if resolution.source_document_id
            else "INSTRUMENT_BINDING",
            evidence_locator=resolution.evidence_locator or "instrument binding",
            raw_pointer="/instrument_bindings",
            evidence_mode=resolution.evidence_mode or "UNKNOWN",
            fact_origin=FactOrigin.SOURCE_ASSERTION.value,
        )
    ]


def _reference_facts(
    resolver: ListingResolver,
    canonical_event_id: str,
    isin: str | None,
    as_of: str | None,
) -> list[Fact]:
    if isin is None or as_of is None:
        return []
    listings = resolver.listings_by_isin(isin, date.fromisoformat(as_of))
    facts: list[Fact] = []
    seen_lei: set[str] = set()
    evidence = f"ESMA/FIRDS listings as_of={as_of} ISIN={isin}"

    def base(assertion_suffix: str, field_path: str, value: object) -> Fact:
        return Fact(
            event_id=canonical_event_id,
            revision_id=EVENT_SCOPE_REVISION,
            assertion_id=f"reference:{canonical_event_id}:{assertion_suffix}",
            field_path=field_path,
            value=value,
            source_document_id="ESMA_FIRDS",
            source_id="ESMA_FIRDS",
            evidence_locator=evidence,
            raw_pointer=f"/listings/{isin}/{assertion_suffix}",
            evidence_mode="REFERENCE_ENRICHMENT",
            fact_origin=FactOrigin.REFERENCE_ENRICHMENT.value,
        )

    for index, listing in enumerate(listings):
        if listing.lei and listing.lei not in seen_lei:
            seen_lei.add(listing.lei)
            facts.append(base(f"lei:{listing.lei}", "affected_instrument.lei", listing.lei))
        facts.append(
            base(
                f"{listing.segment_mic}:{index}",
                "affected_venue.segment_mic",
                listing.segment_mic,
            )
        )
        facts.append(
            base(
                f"{listing.segment_mic}:{index}:admission",
                "affected_venue.admission_date",
                listing.admission_date,
            )
        )
        if listing.termination_date:
            facts.append(
                base(
                    f"{listing.segment_mic}:{index}:termination",
                    "affected_venue.termination_date",
                    listing.termination_date,
                )
            )
    return facts


def build_event_views(
    corpus: ParsedCorpus,
    identity: dict,
    resolver: ListingResolver,
    instrument_index: InstrumentBindingIndex | None = None,
) -> tuple[list[dict], list[Fact], list[dict]]:
    groups = _groups_from_identity(identity)

    # assertions por documento
    assertions_by_document: dict[str, list[Assertion]] = {}
    for document_id, parsed_doc in corpus.parsed.items():
        if parsed_doc.entitlement_basis is not None:
            validate_entitlement_basis(parsed_doc.entitlement_basis)
        assertions_by_document[document_id] = build_assertions(parsed_doc)

    all_facts: list[Fact] = []
    events: list[dict] = []
    all_conflicts: list[dict] = []
    for canonical_id, candidates in groups.items():
        member_docs: list[ParsedDocument] = []
        members: list[MemberDocument] = []
        references_by_document: dict[str, list] = {}
        for candidate in candidates:
            parsed_doc = _parsed_for_candidate(corpus, candidate)
            if parsed_doc is None:
                continue
            member_docs.append(parsed_doc)
            members.append(
                MemberDocument(
                    candidate_id=candidate,
                    document_id=parsed_doc.document.document_id,
                    source_id=parsed_doc.document.source_id,
                    official_document_id=parsed_doc.document.official_document_id,
                )
            )
            references_by_document[parsed_doc.document.document_id] = list(
                parsed_doc.references
            )
        revisions = build_revisions(canonical_id, members, references_by_document)
        revision_facts: list[Fact] = []
        for revision in revisions:
            for document_id in revision.document_ids:
                revision_facts.extend(
                    build_facts(
                        assertions_by_document[document_id], canonical_id, revision.revision_id
                    )
                )
        instrument = resolve_event_instrument(member_docs, instrument_index)
        event_isin = instrument.isin or _isin(member_docs)
        binding_facts = _binding_facts(canonical_id, instrument)
        reference_facts = _reference_facts(
            resolver, canonical_id, event_isin, _event_as_of(member_docs)
        )
        event_facts = revision_facts + binding_facts + reference_facts
        report = detect_conflicts(event_facts)
        all_facts.extend(report.facts)
        all_conflicts.extend(c.to_canonical() for c in report.conflicts)
        event_type, event_type_locator, event_type_status = _event_type(list(report.facts))

        temporal_dates: dict[str, str] = {}
        for fact in report.facts:
            if fact.date_kind and isinstance(fact.value, str) and fact.evidence_mode != "DERIVED_BY_DEFINITION":
                temporal_dates.setdefault(fact.date_kind, fact.value)
        source_for_temporal = member_docs[0].document.source_id if member_docs else None
        temporal_violations = temporal_check(temporal_dates, source_for_temporal, event_type)

        events.append(
            {
                "canonical_event_id": canonical_id,
                "candidate_ids": candidates,
                "event_type": event_type,
                "event_type_status": event_type_status,
                "event_type_evidence_locator": event_type_locator,
                "isin": event_isin,
                "instrument_binding": {
                    "evidence_mode": instrument.evidence_mode,
                    "evidence_locator": instrument.evidence_locator,
                    "source_document_id": instrument.source_document_id,
                },
                "lei": _lei(member_docs),
                "issuer_name": _issuer(member_docs),
                "revisions": [r.to_canonical() for r in revisions],
                "temporal": {
                    "dates": temporal_dates,
                    "ruleset_version": RULESET_VERSION,
                    "violations": temporal_violations,
                },
                "fact_count": len(report.facts),
                "conflict_count": len(report.conflicts),
            }
        )
    events.sort(key=lambda item: item["canonical_event_id"])
    return events, all_facts, all_conflicts


def _groups_from_identity(identity: dict) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for resolution in identity["resolutions"]:
        groups.setdefault(resolution["canonical_event_id"], []).append(
            resolution["candidate_id"]
        )
    return {key: sorted(value) for key, value in sorted(groups.items())}


def _parsed_for_candidate(corpus: ParsedCorpus, candidate: str) -> ParsedDocument | None:
    for document in corpus.parsed.values():
        if (
            candidate_event_id(
                document.document.source_id, document.document.official_document_id
            )
            == candidate
        ):
            return document
    return None


def _issuer(member_docs: list[ParsedDocument]) -> str | None:
    values = sorted({doc.issuer_name for doc in member_docs if doc.issuer_name})
    return values[0] if len(values) == 1 else None


def run_pipeline(
    repo_root: Path,
    *,
    manifest_relpath: str = "g0/manifests/canary-corpus.json",
    policy_relpath: str = _DEFAULT_POLICY_RELPATH,
    identity_ledger_relpath: str | None = None,
    adjudications_relpath: str | None = None,
    instrument_bindings_relpath: str | None = None,
    resolver: ListingResolver | None = None,
    run_id: str = "run-001",
    executed_at: str = "1970-01-01T00:00:00Z",
) -> dict:
    policy_path = repo_root / policy_relpath
    manifest_path = repo_root / manifest_relpath
    corpus = load_and_parse(repo_root, manifest_path, policy_path)

    seed_ledger = None
    ledger_source_sha = None
    if identity_ledger_relpath:
        seed_ledger, _ = load_identity_ledger(repo_root / identity_ledger_relpath)
        ledger_source_sha = sha256_text(
            (repo_root / identity_ledger_relpath).read_text(encoding="utf-8")
        )

    instrument_index = (
        load_instrument_bindings(repo_root / instrument_bindings_relpath)
        if instrument_bindings_relpath
        else None
    )
    result = pipeline_body(
        corpus,
        seed_ledger=seed_ledger,
        adjudications_path=(
            repo_root / adjudications_relpath
            if adjudications_relpath
            else None
        ),
        resolver=resolver,
        instrument_index=instrument_index,
    )
    return {
        "run": {
            "run_id": run_id,
            "executed_at": executed_at,
            "corpus_id": corpus.manifest.corpus_id,
            "manifest_sha256": sha256_text(manifest_path.read_text(encoding="utf-8")),
            "policy_sha256": sha256_text(policy_path.read_text(encoding="utf-8")),
            "identity_ledger_sha256": ledger_source_sha,
            "pipeline_version": PIPELINE_VERSION,
        },
        "body": result["body"],
        "metrics": result["metrics"],
        "result_sha": result["result_sha"],
    }


def pipeline_body(
    corpus: ParsedCorpus,
    *,
    seed_ledger: IdentityLedger | None = None,
    adjudications_path: Path | None = None,
    resolver: ListingResolver | None = None,
    instrument_index: InstrumentBindingIndex | None = None,
) -> dict:
    """Cuerpo canonico del pipeline sobre un corpus ya parseado.

    Misma composicion que ``run_pipeline`` (identidad -> event views
    -> assertions -> body -> result_sha), reutilizada por el canon
    refresh P9 sin duplicar semantica.
    """
    _, identity = build_identity(corpus, seed_ledger, adjudications_path)

    effective_resolver = resolver or UnresolvedListingResolver()
    events, facts, conflicts = build_event_views(
        corpus, identity, effective_resolver, instrument_index
    )

    assertions = [
        assertion.to_canonical()
        for document_id in sorted(corpus.parsed)
        for assertion in build_assertions(corpus.parsed[document_id])
    ]

    body = {
        "documents": [
            corpus.documents[document_id].to_canonical()
            for document_id in sorted(corpus.documents)
        ],
        "verification": sorted(corpus.verification, key=lambda item: item["document_id"]),
        "assertions": assertions,
        "identity": identity,
        "events": events,
        "facts": [fact.to_canonical() for fact in facts],
        "conflicts": conflicts,
        "parse_errors": corpus.parse_errors,
        "contracts": {
            "canonical_profile": "CA_ES_CANONICAL_JSON_V1",
            "pipeline_version": PIPELINE_VERSION,
            "parser_version": PARSER_VERSION,
            "temporal_ruleset": RULESET_VERSION,
        },
    }
    metrics = compute_metrics(body)
    result_sha = sha256_hex(body)
    return {
        "body": body,
        "metrics": metrics,
        "result_sha": result_sha,
    }
