from __future__ import annotations

from ca_es.gates import evaluate_gates
from ca_es.pipeline import run_pipeline
from ca_es.source_policy import load_source_policy


def test_all_documents_sha256_pinned(run_result):
    verification = run_result["body"]["verification"]
    assert verification
    assert all(row["sha256_match"] for row in verification)


def test_all_facts_have_complete_provenance(run_result):
    for fact in run_result["body"]["facts"]:
        assert fact["source_document_id"]
        assert fact["source_document_id"]
        assert fact["evidence_locator"]
        assert fact["evidence_mode"]
        assert fact["fact_origin"] in {
            "SOURCE_ASSERTION",
            "DETERMINISTIC_DERIVATION",
            "REFERENCE_ENRICHMENT",
        }


def test_second_run_is_deterministic(repo_root, resolver):
    first = run_pipeline(repo_root, resolver=resolver, run_id="a", executed_at="2026-01-01T00:00:00Z")
    second = run_pipeline(repo_root, resolver=resolver, run_id="b", executed_at="2026-06-06T12:00:00Z")
    assert first["result_sha"] == second["result_sha"]


def test_metrics_present(run_result):
    metrics = run_result["metrics"]
    for key in (
        "documents_total",
        "documents_parsed",
        "events_detected",
        "field_provenance_rate",
        "conflict_count",
        "unresolved_identity_count",
        "human_relation_adjudications",
        "publication_lag_days",
    ):
        assert key in metrics
    assert metrics["documents_total"] == metrics["documents_parsed"]


def test_gates_no_failures_and_coverage_inconclusive(repo_root, resolver, policy, run_result):
    second = run_pipeline(repo_root, resolver=resolver, run_id="b")
    report = evaluate_gates(run_result, policy=policy, second_run=second)
    statuses = {gate: entry["status"] for gate, entry in report["gates"].items()}
    assert "FAIL" not in statuses.values()
    assert statuses["CNMV_CHANNEL_COVERAGE_P3"] == "INCONCLUSIVE"
    assert statuses["RAW_SHA256_PINNED"] == "PASS"
    assert statuses["SECOND_RUN_DETERMINISTIC"] == "PASS"
    assert statuses["NO_GLOBAL_DATE_ORDER_ASSUMPTION"] == "PASS"
