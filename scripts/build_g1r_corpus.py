# -*- coding: utf-8 -*-
"""Construye el corpus G1-R: 40 seeds nuevos + split 15 HOLDOUT / 25 DEV.

Implementa literalmente el algoritmo congelado en
docs/gates/g1r-preregistered.json (CA_ES_G1R_PREREG_V2):

  1. eliminar del frame G1 los 150 frame_item_id de
     excluded-g1-frame-items.json
  2. sample_score = SHA256("CA_ES_G1R_SAMPLE_V1" + stratum + frame_item_id)
  3. ordenar por score; 20 MAIN_MARKET / 10 BME_GROWTH_MTF / 10 PORTFOLIO
  4. dedup misma CA + backfill (pre_split_dedup: automated_only,
     sin inspeccion manual; evidencia permitida = metadata congelada
     del frame)
  5. split_score = SHA256("CA_ES_G1R_SPLIT_V1" + frame_item_id)
  6. ordenar los 40 por split_score; los 15 primeros -> HOLDOUT
  7. los 25 restantes -> DEV
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ca_es.canonical import canonical_bytes, sha256_text  # noqa: E402

FRAME_PATH = REPO / "g1/manifests/sampling-frame.json"
EXCLUDED_PATH = REPO / "g1r/manifests/excluded-g1-frame-items.json"
OUT_CORPUS = REPO / "g1r/manifests/g1r-corpus.json"
OUT_SPLIT = REPO / "g1r/manifests/dev-holdout.json"

SAMPLE_NS = "CA_ES_G1R_SAMPLE_V1"
SPLIT_NS = "CA_ES_G1R_SPLIT_V1"
STRATUM_TARGETS = {"MAIN_MARKET": 20, "BME_GROWTH_MTF": 10, "PORTFOLIO": 10}
HOLDOUT_COUNT = 15


def no_floats(obj):
    if isinstance(obj, float):
        return repr(obj)
    if isinstance(obj, dict):
        return {k: no_floats(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [no_floats(v) for v in obj]
    return obj


# claves añadidas al frame DESPUES de fijar parent_frame_sha256 en G1
POST_HASH_KEYS = {"sample_score", "split_score", "partition"}


def frame_items_for_hash(items: list[dict]) -> list[dict]:
    return [{k: v for k, v in i.items() if k not in POST_HASH_KEYS} for i in items]


def same_ca_key(item: dict) -> tuple:
    """Evidencia permitida pre-split: solo metadata estructurada congelada
    del frame (isin + categoria oficial + fecha + emisor). Si no es
    determinable automaticamente, los dos seeds permanecen."""
    isin = item.get("instrument_isin")
    cat = item.get("official_category")
    date = item.get("publication_date")
    issuer = item.get("issuer_raw")
    if not (isin and cat and date and issuer):
        return None
    return (isin, cat, date, issuer)


def main() -> int:
    frame = json.loads(FRAME_PATH.read_text(encoding="utf-8"))
    excluded = json.loads(EXCLUDED_PATH.read_text(encoding="utf-8"))
    excluded_ids = {
        fid for g in excluded["groups"].values() for fid in g["frame_item_ids"]
    }
    frame_sha = hashlib.sha256(
        canonical_bytes(no_floats(frame_items_for_hash(frame["items"])))
    ).hexdigest()
    assert frame_sha == excluded["parent_frame_sha256"], frame_sha

    pool = [i for i in frame["items"] if i["frame_item_id"] not in excluded_ids]
    for item in pool:
        item["sample_score"] = sha256_text(
            SAMPLE_NS + item["stratum"] + item["frame_item_id"]
        )

    dedup_log = []
    selected = []
    for stratum, target in STRATUM_TARGETS.items():
        ordered = sorted(
            (i for i in pool if i["stratum"] == stratum),
            key=lambda i: i["sample_score"],
        )
        picked, seen_keys = [], {}
        for item in ordered:
            key = same_ca_key(item)
            if key is not None and key in seen_keys:
                dedup_log.append({
                    "kept": seen_keys[key]["frame_item_id"],
                    "dropped": item["frame_item_id"],
                    "evidence": "instrument_isin+official_category+publication_date+issuer_raw",
                    "reason": "same corporate action (automated only)",
                })
                continue
            picked.append(item)
            if key is not None:
                seen_keys[key] = item
            if len(picked) == target:
                break
        selected.extend(picked)
        if len(picked) < target:
            print(f"  COVERAGE GAP {stratum}: {len(picked)} < {target}")

    for item in selected:
        item["split_score"] = sha256_text(SPLIT_NS + item["frame_item_id"])
    ordered = sorted(selected, key=lambda i: i["split_score"])
    holdout_ids = {i["frame_item_id"] for i in ordered[:HOLDOUT_COUNT]}
    for item in selected:
        item["partition"] = "HOLDOUT" if item["frame_item_id"] in holdout_ids else "DEV"

    corpus = {
        "corpus_version": "CA_ES_G1R_CORPUS_V1",
        "protocol": "CA_ES_G1R_PREREG_V2 / g1r-protocol",
        "frozen_at": "2026-09-14",
        "parent_frame": "g1/manifests/sampling-frame.json",
        "parent_frame_sha256": frame_sha,
        "excluded_g1_items": "g1r/manifests/excluded-g1-frame-items.json",
        "excluded_ids_sha256": excluded["excluded_ids_sha256"],
        "sampling_namespace": SAMPLE_NS,
        "split_namespace": SPLIT_NS,
        "stratum_targets": STRATUM_TARGETS,
        "holdout_count": HOLDOUT_COUNT,
        "pre_split_dedup": {
            "automated_only": True,
            "manual_document_inspection": False,
            "permitted_evidence": [
                "structured source identifiers",
                "exact official cross-references",
                "already-frozen metadata",
            ],
            "default_when_not_determinable": "both seeds remain",
        },
        "dedup_log": dedup_log,
        "selected": [
            {
                "frame_item_id": i["frame_item_id"],
                "stratum": i["stratum"],
                "partition": i["partition"],
                "sample_score": i["sample_score"],
                "split_score": i["split_score"],
            }
            for i in sorted(selected, key=lambda i: i["frame_item_id"])
        ],
    }
    OUT_CORPUS.write_text(
        json.dumps(corpus, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    split = {
        "split_version": "CA_ES_G1R_DEV_HOLDOUT_V1",
        "protocol": "CA_ES_G1R_PREREG_V2",
        "frozen_at": "2026-09-14",
        "status": "FROZEN_POPULATED",
        "development": sorted(
            i["frame_item_id"] for i in selected if i["partition"] == "DEV"
        ),
        "holdout": sorted(
            i["frame_item_id"] for i in selected if i["partition"] == "HOLDOUT"
        ),
        "holdout_content_sealed_until": "G1R_PARSER_FREEZE",
        "no_manual_holdout_inspection": True,
        "auto_acquisition_for_sha_allowed": True,
        "policy": {
            "baseline_rule": "run c431830 sobre los 25 DEV antes de modificar src/",
            "holdout": "sin inspeccion manual ni parseo hasta g1r-parser-freeze",
        },
    }
    OUT_SPLIT.write_text(
        json.dumps(split, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    n_h = sum(1 for i in selected if i["partition"] == "HOLDOUT")
    n_d = sum(1 for i in selected if i["partition"] == "DEV")
    print(f"selected={len(selected)} holdout={n_h} dev={n_d} dedup_dropped={len(dedup_log)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
