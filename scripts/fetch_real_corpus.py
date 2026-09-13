"""Descarga el corpus real G0-R y verifica SHA-256.

Los originales quedan LOCAL_ONLY en g0/corpus/raw/. Este script hace la
adquisicion reproducible: misma URL, mismo SHA-256, mismo manifest.

    python scripts/fetch_real_corpus.py [--manifest g0/manifests/real-corpus.json] [--force]
"""
from __future__ import annotations

import argparse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(REPO_ROOT / "src"))

from ca_es.canonical import sha256_bytes, strict_json_loads  # noqa: E402
from ca_es.source_policy import load_source_policy  # noqa: E402
from ca_es.sources.documents import load_corpus_manifest  # noqa: E402


def fetch(manifest_path: Path, repo_root: Path, force: bool = False) -> int:
    policy = load_source_policy(repo_root / "docs/sources/source-policy.json")
    manifest = load_corpus_manifest(manifest_path, policy)
    failures = 0
    for document in manifest.documents:
        if document.raw_relpath is None:
            continue
        target = repo_root / document.raw_relpath
        if target.exists() and not force:
            observed = sha256_bytes(target.read_bytes())
            status = "OK" if observed == document.content_sha256 else "MISMATCH"
            print(f"[cache] {document.document_id} {status} {target}")
            failures += 0 if status == "OK" else 1
            continue
        url = (document.acquisition or {}).get("url")
        if not url:
            print(f"[skip ] {document.document_id} sin URL de adquisicion")
            failures += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=60) as response:
            payload = response.read()
        observed = sha256_bytes(payload)
        if observed != document.content_sha256:
            print(
                f"[FAIL ] {document.document_id} sha256 {observed} != {document.content_sha256}"
            )
            failures += 1
            continue
        target.write_bytes(payload)
        print(f"[fetch] {document.document_id} OK {len(payload)} bytes -> {target}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=REPO_ROOT / "g0/manifests/real-corpus.json"
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    manifest_path = args.manifest
    if not manifest_path.is_absolute():
        manifest_path = args.repo_root / manifest_path
    failures = fetch(manifest_path, args.repo_root.resolve(), args.force)
    print(f"failures={failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
