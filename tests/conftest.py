from __future__ import annotations

from pathlib import Path

import pytest

from ca_es.pipeline import run_pipeline
from ca_es.reference.esma_firds import load_firds_listings
from ca_es.source_policy import load_source_policy

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def policy(repo_root: Path):
    return load_source_policy(repo_root / "docs/sources/source-policy.json")


@pytest.fixture(scope="session")
def resolver(repo_root: Path):
    return load_firds_listings(
        repo_root / "g0/corpus/reference/esma-firds-listings.json"
    )


@pytest.fixture(scope="session")
def run_result(repo_root: Path, resolver):
    return run_pipeline(repo_root, resolver=resolver, run_id="test-run")


@pytest.fixture(scope="session")
def events_by_type(run_result):
    grouped: dict[str, list[dict]] = {}
    for event in run_result["body"]["events"]:
        grouped.setdefault(event["event_type"], []).append(event)
    return grouped


@pytest.fixture
def facts_for():
    def _facts(run_result: dict, event: dict) -> list[dict]:
        return [
            fact
            for fact in run_result["body"]["facts"]
            if fact["event_id"] == event["canonical_event_id"]
        ]

    return _facts


@pytest.fixture
def event_for(events_by_type):
    def _event(event_type: str, issuer_name: str) -> dict:
        for event in events_by_type[event_type]:
            if event.get("issuer_name") == issuer_name:
                return event
        raise KeyError(f"no event {event_type}/{issuer_name}")

    return _event
