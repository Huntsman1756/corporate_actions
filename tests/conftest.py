from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

from ca_es.pipeline import run_pipeline
from ca_es.reference.esma_firds import load_firds_listings
from ca_es.source_policy import load_source_policy

REPO_ROOT = Path(__file__).resolve().parents[1]

PRIVATE_MANIFESTS = {
    "g0": "g0/manifests/real-corpus.json",
    "g2": "g2/manifests/qualification-corpus.json",
}


def pytest_addoption(parser):
    group = parser.getgroup("private corpus")
    group.addoption(
        "--run-private-corpus", action="store_true", default=False,
        dest="run_private_corpus",
        help="Opt in to LOCAL_ONLY and qualification corpus tests; requires authorization.",
    )
    group.addoption(
        "--no-private-corpus", action="store_false", dest="run_private_corpus",
        help="Disable private corpus tests even when local raw files are available.",
    )
    group.addoption(
        "--live", action="store_true", default=False,
        help="Opt in to live public-source smoke tests (network).",
    )


def pytest_collection_modifyitems(config, items):
    disabled = not config.getoption("run_private_corpus")
    live = config.getoption("live") or \
        os.environ.get("CA_ES_LIVE_SMOKE") == "1"
    for item in items:
        if "real_run" in item.fixturenames and not item.get_closest_marker("private_corpus"):
            item.add_marker(pytest.mark.private_corpus("g0"))
        if disabled and item.get_closest_marker("private_corpus"):
            item.add_marker(pytest.mark.skip(reason="requires --run-private-corpus"))
        if not live and item.get_closest_marker("live"):
            item.add_marker(pytest.mark.skip(
                reason="requires --live (network smoke)"))


@pytest.fixture(scope="session")
def private_corpus(request):
    if not request.config.getoption("run_private_corpus"):
        pytest.skip("requires --run-private-corpus")
    checked = set()

    def require(name):
        if name in checked:
            return
        if name not in PRIVATE_MANIFESTS:
            pytest.fail(f"unknown private corpus: {name}", pytrace=False)
        manifest_path = REPO_ROOT / PRIVATE_MANIFESTS[name]
        if not manifest_path.is_file():
            pytest.fail(f"private corpus manifest unavailable: {manifest_path}", pytrace=False)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        paths = [
            REPO_ROOT / document["raw_relpath"]
            for document in manifest["documents"]
            if document.get("raw_relpath")
        ]
        missing = [str(path.relative_to(REPO_ROOT)) for path in paths if not path.is_file()]
        if any(path.suffix.lower() == ".pdf" for path in paths):
            if importlib.util.find_spec("pypdf") is None:
                missing.append("pypdf (install ca-es[pdf])")
        if missing:
            pytest.fail("private corpus prerequisites unavailable: " + ", ".join(missing), pytrace=False)
        checked.add(name)

    return require


@pytest.fixture(autouse=True)
def _private_corpus_guard(request):
    marker = request.node.get_closest_marker("private_corpus")
    if marker is not None:
        require = request.getfixturevalue("private_corpus")
        require(marker.args[0] if marker.args else "g0")


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
def real_resolver(repo_root: Path):
    return load_firds_listings(
        repo_root / "g0/corpus/reference/esma-firds-listings-real.json"
    )


@pytest.fixture(scope="session")
def run_result(repo_root: Path, resolver):
    return run_pipeline(repo_root, resolver=resolver, run_id="test-run")


@pytest.fixture(scope="session")
def real_run(repo_root: Path, private_corpus, real_resolver):
    private_corpus("g0")
    return run_pipeline(
        repo_root,
        manifest_relpath="g0/manifests/real-corpus.json",
        adjudications_relpath="g0/manifests/adjudications-real.json",
        instrument_bindings_relpath="g0/corpus/reference/portfolio-instruments.json",
        resolver=real_resolver,
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
