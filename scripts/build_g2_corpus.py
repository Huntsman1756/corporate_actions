# -*- coding: utf-8 -*-
"""Compone g2/manifests/qualification-corpus.json (G2_QUALIFICATION_CORPUS_V1).

Para cada documento del preregistro (docs/gates/g2-preregistered.json):
  1. localiza la entrada en su manifest origen por official_document_id
  2. exige content_sha256 identico al fijado (64 hex completos)
  3. exige raw LOCAL_ONLY presente y sha256 coincidente

Falta un raw -> INCONCLUSIVE/STOP; hash divergente -> STOP. En ambos
casos el script aborta sin escribir el manifest.

    PYTHONPATH=src python scripts/build_g2_corpus.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PREREG = REPO / "docs/gates/g2-preregistered.json"
OUT = REPO / "g2/manifests/qualification-corpus.json"
CORPUS_ID = "CA_ES_G2_QUALIFICATION_V1"


def main() -> int:
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    entries = []
    errors = []
    seen = set()
    for case in prereg["qualification_corpus"]["cases"]:
        for pinned in case["documents"]:
            doc_id = pinned["id"]
            if doc_id in seen:
                continue
            seen.add(doc_id)
            origin = json.loads(
                (REPO / pinned["from_manifest"]).read_text(encoding="utf-8")
            )
            entry = next(
                (
                    d
                    for d in origin["documents"]
                    if d["official_document_id"] == doc_id
                ),
                None,
            )
            if entry is None:
                errors.append(f"NOT_IN_MANIFEST:{doc_id}")
                continue
            if entry["content_sha256"] != pinned["content_sha256"]:
                errors.append(f"PREREG_SHA_MISMATCH:{doc_id}")
                continue
            raw = REPO / entry["raw_relpath"]
            if not raw.exists():
                errors.append(f"MISSING_RAW:{doc_id}")
                continue
            if hashlib.sha256(raw.read_bytes()).hexdigest() != pinned["content_sha256"]:
                errors.append(f"RAW_SHA_MISMATCH:{doc_id}")
                continue
            entries.append(dict(entry))
            print(f"  {doc_id}: sello OK ({entry['source_id']})")

    if errors:
        print(f"STOP: {errors}", file=sys.stderr)
        return 2

    manifest = {
        "manifest_version": "CA_ES_SOURCE_MANIFEST_V1",
        "corpus_id": CORPUS_ID,
        "retrieved_at": "2026-09-16",
        "note": "G2 qualification corpus: documentos compuestos desde manifests origen con content_sha256 fijado en g2-preregistered.json",
        "documents": sorted(entries, key=lambda d: d["official_document_id"]),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"{len(entries)} docs -> {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
