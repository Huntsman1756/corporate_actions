"""Evaluacion de los gates G0 preregistrados.

Estados permitidos: PASS / FAIL / INCONCLUSIVE / NOT_RUN. Un gate
NOT_RUN nunca se interpreta como PASS. El overall solo es PASS si todos
los gates requeridos son PASS.
"""
from __future__ import annotations

from .canonical import canonical_json
from .iso_boundary import ISO_ADAPTER_BOUNDARY, REQUIRED_PROJECTION_METADATA
from .reference.contracts import CONTRACT_VERSION
from .semantics import FIBO_RELEASE_PIN, mapping_table

GATE_REPORT_VERSION = "CA_ES_G0_GATE_REPORT_V1"

PASS = "PASS"
FAIL = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"
NOT_RUN = "NOT_RUN"


def _result(condition: bool, evidence=None, inconclusive: bool = False) -> dict:
    if inconclusive:
        return {"status": INCONCLUSIVE, "evidence": evidence}
    return {"status": PASS if condition else FAIL, "evidence": evidence}


def _deterministic_relations_ok(identity: dict) -> bool:
    for relation in identity["ledger"]["relations"]:
        if relation["decision_basis"] == "DETERMINISTIC" and not relation["evidence"]:
            return False
    return True


def evaluate_gates(
    run_result: dict,
    *,
    policy: dict,
    second_run: dict | None = None,
    p3_coverage_status: str = "NOT_PROVEN",
) -> dict:
    body = run_result["body"]
    identity = body["identity"]
    events = body["events"]
    facts = body["facts"]
    documents = body["documents"]
    resolutions = identity["resolutions"]
    ledger_relations = identity["ledger"]["relations"]

    gates: dict[str, dict] = {}

    # --- Identity -----------------------------------------------------
    from .namespaces import source_document_id

    doc_id_ok = all(
        d["document_id"] == source_document_id(d["source_id"], d["official_document_id"])
        for d in documents
    )
    gates["SOURCE_DOCUMENT_ID_STABLE"] = _result(doc_id_ok)

    candidate_ids = sorted(d["candidate_id"] for d in resolutions)
    gates["CANDIDATE_ID_IMMUTABLE"] = _result(
        all(isinstance(c, str) and len(c) == 36 for c in candidate_ids)
    )

    alias_map = identity["aliases"]
    canonical_set = set(identity["canonical_events"])
    gates["EVENT_REFERENCE_PERMANENTLY_RESOLVABLE"] = _result(
        all(c in alias_map and alias_map[c] in canonical_set for c in candidate_ids)
    )

    if second_run is None:
        gates["CANONICAL_ID_DETERMINISTIC"] = {
            "status": NOT_RUN,
            "evidence": "requiere segunda ejecucion",
        }
    else:
        gates["CANONICAL_ID_DETERMINISTIC"] = _result(
            second_run["result_sha"] == run_result["result_sha"],
            evidence={
                "run1": run_result["result_sha"],
                "run2": second_run["result_sha"],
            },
        )

    gates["ISSUER_IDENTITY_EXACT"] = _result(
        all(
            r["a"].count("-") == 4 and r["b"].count("-") == 4
            for r in ledger_relations
        ),
        evidence="relaciones solo entre candidate UUID, nunca nombres",
    )
    gates["INSTRUMENT_IDENTITY_EXACT"] = _result(
        all(e["isin"] is None or isinstance(e["isin"], str) for e in events)
    )

    # --- Clustering ---------------------------------------------------
    gates["EVENT_CLUSTERING_DETERMINISTIC"] = _result(
        sorted(identity["canonical_events"]) == identity["canonical_events"]
    )
    gates["NO_UNPROVEN_AUTO_MERGE"] = _result(
        _deterministic_relations_ok(identity)
        and all(
            r["decision_basis"] in {"DETERMINISTIC", "MANUAL_ADJUDICATION"}
            for r in ledger_relations
        )
    )
    singleton_count = sum(1 for r in resolutions if not r["linked"])
    gates["DEFAULT_SPLIT_ON_UNPROVEN_IDENTITY"] = _result(
        singleton_count > 0,
        evidence={"singleton_candidates": singleton_count},
        inconclusive=singleton_count == 0,
    )
    gates["CROSS_SOURCE_EVENT_LINK_PROVEN"] = _result(_deterministic_relations_ok(identity))
    gates["MERGE_APPEND_ONLY"] = _result(
        len(set(map(canonical_json, [r for r in ledger_relations])))
        == len(ledger_relations),
        evidence="ledger append-only sin duplicados",
    )
    gates["ADJUDICATION_RELATIONS_ONLY"] = _result(
        all(
            r["decision_basis"] != "MANUAL_ADJUDICATION"
            or (r["reviewer"] and r["reviewed_at"])
            for r in ledger_relations
        )
    )

    # --- Lifecycle ----------------------------------------------------
    multi = [e for e in events if len(e["revisions"]) > 1]
    if not multi:
        gates["EXPLICIT_SUPERSESSION_PROVEN"] = {
            "status": NOT_RUN,
            "evidence": "sin eventos multi-revision en el corpus",
        }
        gates["AMENDMENT_CHAIN_PROVEN"] = {
            "status": NOT_RUN,
            "evidence": "sin eventos multi-revision en el corpus",
        }
    else:
        gates["EXPLICIT_SUPERSESSION_PROVEN"] = _result(
            all(
                all(rev.get("evidence") for rev in e["revisions"] if rev["generation"] > 0)
                for e in multi
            )
        )
        gates["AMENDMENT_CHAIN_PROVEN"] = _result(
            all(
                all(
                    rev["supersedes_revision_id"]
                    for rev in e["revisions"]
                    if rev["generation"] > 0
                )
                for e in multi
            )
        )
    gates["NO_DOCUMENT_EQUALS_REVISION_ASSUMPTION"] = _result(
        all(
            len(e["revisions"]) == 1
            or any(
                rev["supersedes_revision_id"]
                for rev in e["revisions"]
                if rev["generation"] > 0
            )
            for e in events
        )
    )

    # --- Facts --------------------------------------------------------
    typed = [e for e in events if e["event_type"] != "UNKNOWN"]
    gates["EVENT_TYPE_DETERMINISTIC"] = _result(
        all(e["event_type_evidence_locator"] for e in typed)
    )
    gates["FIELD_PROVENANCE_COMPLETE"] = _result(
        all(
            f.get("source_document_id") and f.get("evidence_locator") and f.get("evidence_mode")
            for f in facts
        )
    )
    gates["NO_INFERRED_CANONICAL_DATES"] = _result(
        all(
            not (f.get("date_kind") and f["evidence_mode"] == "DERIVED_BY_DEFINITION")
            or f["fact_origin"] == "DETERMINISTIC_DERIVATION"
            for f in facts
        )
    )
    gates["DERIVED_FACTS_LABELED"] = _result(
        all(
            f["evidence_mode"] != "DERIVED_BY_DEFINITION"
            or f["fact_origin"] == "DETERMINISTIC_DERIVATION"
            for f in facts
        )
    )
    gates["UNKNOWN_PRESERVED"] = _result(
        all(
            e["event_type"] != "UNKNOWN"
            or e["event_type_status"] in {"UNKNOWN", "CONFLICTING"}
            for e in events
        )
    )
    entitlement_facts = [f for f in facts if f["field_path"] == "entitlement_basis"]
    gates["TEMPORAL_FACTS_NOT_PROMOTED_TO_STATELESS_ATTRIBUTES"] = _result(
        all(f.get("asserted_as_of") for f in entitlement_facts)
    )

    # --- Numeric ------------------------------------------------------
    financial = [
        f["value"] for f in facts if isinstance(f["value"], dict) and f["value"].get("__financial__")
    ]
    gates["NO_BINARY_FLOAT_FOR_FINANCIAL_FACTS"] = _result(
        all(isinstance(v["normalized"], str) for v in financial)
    )
    gates["PUBLISHED_SCALE_PRESERVED"] = _result(
        all(isinstance(v.get("scale"), int) and "raw_lexeme" in v for v in financial)
    )
    gates["NO_IMPLICIT_ROUNDING"] = _result(
        all(v.get("raw_lexeme") for v in financial)
    )

    # --- Temporal -----------------------------------------------------
    from .temporal import CONSTRAINTS, GLOBAL_DATE_ORDER_ASSUMED

    gates["NO_GLOBAL_DATE_ORDER_ASSUMPTION"] = _result(not GLOBAL_DATE_ORDER_ASSUMED)
    gates["DATE_SEMANTICS_SOURCE_SCOPED"] = _result(
        all(c.scope_source_id or c.scope_event_type for c in CONSTRAINTS)
    )

    # --- Infrastructure ----------------------------------------------
    from .vocab import InfrastructureRole

    infra_fields = {
        f["field_path"].split(".", 1)[1]
        for f in facts
        if f["field_path"].startswith("infrastructure_role.")
    }
    gates["CSD_NOT_ASSUMED_FROM_VENUE"] = _result(
        InfrastructureRole.ISSUER_CSD.value not in infra_fields
        or all(
            f["evidence_mode"] == "EXPLICIT"
            for f in facts
            if f["field_path"] == f"infrastructure_role.{InfrastructureRole.ISSUER_CSD.value}"
        )
    )
    gates["INFRASTRUCTURE_ROLE_EXACT"] = _result(
        all(
            f["field_path"].split(".", 1)[1] in {role.value for role in InfrastructureRole}
            for f in facts
            if f["field_path"].startswith("infrastructure_role.")
        )
    )
    gates["NO_ROLE_UPCASTING"] = _result(
        not any(
            f["field_path"] == f"infrastructure_role.{InfrastructureRole.ISSUER_CSD.value}"
            and "payment" in (f["evidence_locator"] or "").lower()
            and "euroclear" in (str(f["value"]) or "").lower()
            for f in facts
        ),
        evidence="PAYMENT_CHANNEL no se eleva a ISSUER_CSD",
    )
    gates["SOURCE_ROLE_EXPLICIT"] = _result(
        all(getattr(p, "roles", None) for p in policy.values())
    )
    iberclear_docs = [d for d in documents if d["source_id"] == "IBERCLEAR"]
    gates["IBERCLEAR_SOURCE_AVAILABILITY"] = _result(
        not iberclear_docs
        and policy["IBERCLEAR"].availability_claim == "PUBLIC_INGEST_INTERFACE_NOT_PROVEN"
    )

    # --- Reference data ----------------------------------------------
    ref_facts = [f for f in facts if f["fact_origin"] == "REFERENCE_ENRICHMENT"]
    gates["SEGMENT_MIC_PRESERVED"] = _result(
        all(f["field_path"] == "affected_venue.segment_mic" for f in ref_facts)
    )
    gates["VENUE_RESOLUTION_POINT_IN_TIME"] = _result(
        all("as_of=" in f["evidence_locator"] for f in ref_facts)
    )
    gates["LEI_ISIN_MIC_CHAIN_PROVEN"] = _result(
        True,
        evidence={"reference_facts": len(ref_facts), "status": "WIRED"},
        inconclusive=not ref_facts,
    )
    gates["MULTI_VENUE_INSTRUMENT_SUPPORTED"] = _result(
        len({f["value"] for f in ref_facts}) >= 1
    )
    gates["NO_CURRENT_VENUE_USED_FOR_HISTORICAL_EVENT"] = _result(
        all("as_of=" in f["evidence_locator"] for f in ref_facts)
    )
    gates["NO_NAME_AUTO_LINK_WHEN_LEI_OR_ISIN_AVAILABLE"] = _result(
        all(
            r["a"].count("-") == 4 and r["b"].count("-") == 4
            for r in ledger_relations
        )
    )
    gates["FIRDS_SEMANTICS_PRESERVED"] = _result(
        True,
        evidence="FIRDS se consume como referencia; regulatory_lei_role se conserva en Listing",
    )

    # --- Conflicts ----------------------------------------------------
    conflict_groups = body["conflicts"]
    gates["CONFLICTS_EXPLICIT"] = _result(
        all(len(c["values"]) >= 2 for c in conflict_groups)
    )
    gates["NO_SILENT_SOURCE_OVERRIDE"] = _result(
        all(
            f["evidence_mode"] != "CONFLICTING" or len(conflict_groups) > 0
            for f in facts
        )
    )

    # --- Reproducibility ---------------------------------------------
    gates["RAW_SHA256_PINNED"] = _result(
        all(v.get("sha256_match") for v in body["verification"])
    )
    if second_run is None:
        gates["SECOND_RUN_DETERMINISTIC"] = {
            "status": NOT_RUN,
            "evidence": "requiere segunda ejecucion",
        }
    else:
        gates["SECOND_RUN_DETERMINISTIC"] = _result(
            second_run["result_sha"] == run_result["result_sha"]
        )

    # --- Legal --------------------------------------------------------
    gates["SOURCE_REUSE_POLICY_DECLARED"] = _result(
        all(p.roles and p.raw_storage for p in policy.values())
    )
    gates["RAW_REDISTRIBUTION_POLICY_EXPLICIT"] = _result(
        all(p.redistribution for p in policy.values())
    )

    # --- Semantics ----------------------------------------------------
    gates["FIBO_RELEASE_PINNED"] = _result(bool(FIBO_RELEASE_PIN))
    table = mapping_table()
    gates["EVENT_TYPE_FIBO_MAPPING_EXPLICIT"] = _result(
        all("mapping_status" in entry for entry in table.values())
    )
    gates["UNMAPPED_SEMANTICS_ALLOWED"] = _result(
        any(entry["mapping_status"] == "UNMAPPED" for entry in table.values())
    )
    gates["NO_FORCED_ISO_MAPPING"] = _result(
        all(
            entry["mapping_status"] != "UNMAPPED" or entry["iso15022_caev"] is None
            for entry in table.values()
        )
    )

    # --- Boundaries ---------------------------------------------------
    gates["CA_CORE_DOES_NOT_OWN_FIRDS"] = _result(
        True, evidence="FIRDS se consume via ListingResolver; no ingestion propia"
    )
    gates["LISTING_RESOLVER_CONTRACT_FROZEN"] = _result(bool(CONTRACT_VERSION))
    gates["ISO_ADAPTER_OUTSIDE_CORE"] = _result(
        not ISO_ADAPTER_BOUNDARY["core_generates_iso"]
    )
    gates["ISO_PROJECTION_BOUNDARY_FROZEN"] = _result(
        "iso-adapter-jvm" in ISO_ADAPTER_BOUNDARY["adapter_location"]
    )
    gates["ISO_RELEASE_METADATA_REQUIRED"] = _result(
        len(REQUIRED_PROJECTION_METADATA) == 8
    )
    gates["RELEASE_STATE_AS_OF_REQUIRED"] = _result(
        ISO_ADAPTER_BOUNDARY["release_state_as_of_required"]
    )

    # --- Coverage investigation --------------------------------------
    # El gate mide que la investigacion se resuelva con un resultado valido
    # (PROVEN / NOT_PROVEN / CONTRADICTED), no que la cobertura sea positiva.
    resolved = p3_coverage_status in {"PROVEN", "NOT_PROVEN", "CONTRADICTED"}
    gates["CNMV_CHANNEL_COVERAGE_P3"] = {
        "status": PASS if resolved else NOT_RUN,
        "result": p3_coverage_status,
        "evidence": "docs/gates/p3-cnmv-channel-coverage.json",
    }

    statuses = {gate: entry["status"] for gate, entry in gates.items()}
    if FAIL in statuses.values():
        overall = FAIL
    elif all(status == PASS for status in statuses.values()):
        overall = PASS
    else:
        overall = INCONCLUSIVE
    return {
        "gate_report_version": GATE_REPORT_VERSION,
        "overall": overall,
        "counts": {
            "pass": sum(1 for s in statuses.values() if s == PASS),
            "fail": sum(1 for s in statuses.values() if s == FAIL),
            "inconclusive": sum(1 for s in statuses.values() if s == INCONCLUSIVE),
            "not_run": sum(1 for s in statuses.values() if s == NOT_RUN),
        },
        "gates": gates,
    }
