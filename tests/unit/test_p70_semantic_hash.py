"""P7.0 — CA_ES_SEMANTIC_HASH_V1 (docs/p7/p70-runtime-model.md)."""
from __future__ import annotations

import copy

from ca_es.semantic_hash import (
    EXCLUDED_KEYS,
    canonical_json,
    canonicalize,
    semantic_sha256,
)

BASE = {
    "schema": "CA_ES_ACTION_QUEUE_V1",
    "generated_at": "2026-09-18T08:00:00Z",
    "as_of": "2026-09-18",
    "items": [
        {"event_id": "E1", "deadline": "2026-09-20"},
    ],
    "steps": [
        {"step_id": "compute", "started_at": "t1",
         "completed_at": "t2", "run_id": "r-1"},
    ],
    "source": {"retrieved_at": "2026-09-17T10:00:00Z"},
}


def test_generated_at_change_same_hash():
    a = copy.deepcopy(BASE)
    b = copy.deepcopy(BASE)
    b["generated_at"] = "2030-01-01T00:00:00Z"
    assert semantic_sha256(a) == semantic_sha256(b)


def test_nested_execution_keys_same_hash():
    a = copy.deepcopy(BASE)
    b = copy.deepcopy(BASE)
    b["steps"][0]["started_at"] = "x"
    b["steps"][0]["completed_at"] = "y"
    b["steps"][0]["run_id"] = "r-999"
    assert semantic_sha256(a) == semantic_sha256(b)


def test_as_of_change_different_hash():
    a = copy.deepcopy(BASE)
    b = copy.deepcopy(BASE)
    b["as_of"] = "2026-09-19"
    assert semantic_sha256(a) != semantic_sha256(b)


def test_evidence_change_different_hash():
    a = copy.deepcopy(BASE)
    b = copy.deepcopy(BASE)
    b["items"][0]["deadline"] = "2026-09-21"
    assert semantic_sha256(a) != semantic_sha256(b)


def test_business_timestamps_preserved():
    a = copy.deepcopy(BASE)
    b = copy.deepcopy(BASE)
    b["source"]["retrieved_at"] = "2026-09-18T00:00:00Z"
    assert semantic_sha256(a) != semantic_sha256(b)


def test_instructed_at_preserved():
    a = {"instructed_at": "2026-09-18T09:00:00Z",
         "generated_at": "t0"}
    b = {"instructed_at": "2026-09-18T09:00:01Z",
         "generated_at": "t0"}
    assert semantic_sha256(a) != semantic_sha256(b)


def test_case_lifecycle_timestamps_preserved():
    a = {"first_seen_at": "t1", "resolved_at": "t2"}
    b = {"first_seen_at": "t1", "resolved_at": "t3"}
    assert semantic_sha256(a) != semantic_sha256(b)


def test_key_named_timestamp_never_stripped():
    obj = {"timestamp": "2026-01-01"}
    assert "timestamp" in canonicalize(obj)
    assert "timestamp" not in EXCLUDED_KEYS


def test_list_order_is_semantic():
    assert semantic_sha256([1, 2]) != semantic_sha256([2, 1])


def test_deterministic_serialization():
    obj = {"b": 1, "a": {"z": True, "y": None, "x": "s"}}
    j1 = canonical_json(obj)
    j2 = canonical_json({"a": {"x": "s", "y": None, "z": True},
                         "b": 1})
    assert j1 == j2
    assert j1 == '{"a":{"x":"s","y":null,"z":true},"b":1}'


def test_non_ascii_deterministic():
    obj = {"name": "España"}
    j = canonical_json(obj)
    assert "\\u00f1" in j  # ensure_ascii: escapado deterministico
    assert semantic_sha256(obj) == semantic_sha256(
        {"name": "España", "generated_at": "now"})
