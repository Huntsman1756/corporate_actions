from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from ca_es.pipeline import run_pipeline
from ca_es.reference.esma_firds import load_firds_listings
from ca_es.source_policy import load_source_policy

REPO_ROOT = Path(__file__).resolve().parents[1]

REAL_RAW_REQUIRED = (
    "g0/corpus/raw/parlem/borme-c-2026-4914.html",
    "g0/corpus/raw/cnmv/almirall/ip-1884.pdf",
    "g0/corpus/raw/cnmv/almirall/ip-1885.pdf",
    "g0/corpus/raw/mfe/oir-40280.pdf",
    "g0/corpus/raw/mfe/oir-40319.pdf",
    "g0/corpus/raw/san/cnmv-dividend.pdf",
    "g0/corpus/raw/san/ir-remuneration.html",
    "g0/corpus/raw/portfolio/p3-dividend-4733.pdf",
)


def _real_corpus_available() -> bool:
    if importlib.util.find_spec("pypdf") is None:
        return False
    return all((REPO_ROOT / rel).exists() for rel in REAL_RAW_REQUIRED)


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
def real_run(repo_root: Path, resolver):
    if not _real_corpus_available():
        pytest.skip("corpus real LOCAL_ONLY o pypdf no disponibles")
    return run_pipeline(
        repo_root,
        manifest_relpath="g0/manifests/real-corpus.json",
        adjudications_relpath="g0/manifests/adjudications-real.json",
        resolver=resolver,
        run_id="real-test",
    )


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
