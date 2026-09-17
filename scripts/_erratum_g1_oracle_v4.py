# -*- coding: utf-8 -*-
"""Erratum V4 del regression oracle (iter-3, EVENT_TYPE_FAMILY_BOUNDARY).

CNMV-OIR-37214 y CNMV-OIR-40729 figuraban como known_correct con
event_type=CASH_DIVIDEND heredado del baseline c431830. Los documentos
declaran explicitamente "DIVIDENDO FLEXIBLE (SCRIP DIVIDEND) ...
pagadero en efectivo o en acciones a eleccion del accionista":
bajo la frontera firmada (dividendo flexible + holder choice ->
SCRIP_DIVIDEND) el GT era semanticamente incorrecto, misma deuda que
el erratum IP-2670 de iter-1.

Se reescriben expected_claims + canonical_concepts de las dos filas
(review_status=ERRATUM), se documenta en `errata` y se recomputa
oracle_sha256. El resto de filas no cambia.

Uso:
    PYTHONPATH=src python scripts/_erratum_g1_oracle_v4.py
"""
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from ca_es.canonical import canonical_bytes  # noqa: E402

REG_PATH = REPO / "g1r/manifests/g1-regression-oracle.json"
ERRATUM_IDS = {"CNMV-OIR-37214", "CNMV-OIR-40729"}
REASON = (
    "GT heredado de c431830: el documento declara 'DIVIDENDO FLEXIBLE "
    "(SCRIP DIVIDEND)' pagadero 'en efectivo o en acciones a eleccion "
    "del accionista'; bajo la frontera EVENT_TYPE_FAMILY_BOUNDARY "
    "firmada (dividendo flexible + holder choice) el tipo canonico es "
    "SCRIP_DIVIDEND. Detectado por el gate de iter-3 como FAIL nuevo "
    "sobre known_correct; mismo mecanismo que el erratum IP-2670."
)


def main():
    oracle = json.loads(REG_PATH.read_text(encoding="utf-8"))
    applied = 0
    for e in oracle["known_correct_critical_fields"]:
        if e["frame_item_id"] in ERRATUM_IDS and e["field"] == "event_type":
            e["expected_claims"] = {"event_type": "SCRIP_DIVIDEND"}
            e["review_status"] = "ERRATUM"
            e["canonical_concepts"] = [{
                "canonical_concept": "EVENT_TYPE.SCRIP_DIVIDEND",
                "field_path": "event_type",
                "value": "SCRIP_DIVIDEND",
                "external_semantic_mapping_status": "PROVEN",
            }]
            applied += 1
            oracle["errata"].append({
                "frame_item_id": e["frame_item_id"],
                "set": e["set"],
                "field": "event_type",
                "expected_claims": dict(e["expected_claims"]),
                "reason": REASON,
                "applied_at": "2026-09-14",
            })
    if applied != 2:
        print(f"ERROR: errata aplicados={applied}, esperados 2")
        return 1
    oracle["oracle_version"] = "CA_ES_G1_REGRESSION_ORACLE_V4"
    oracle["provenance_note"] += (
        " V4: errata iter-3 — 37214/40729 event_type CASH_DIVIDEND -> "
        "SCRIP_DIVIDEND (GT heredado; frontera firmada lo contradice).")
    oracle.pop("oracle_sha256", None)
    oracle["oracle_sha256"] = hashlib.sha256(
        canonical_bytes(oracle)).hexdigest()
    REG_PATH.write_text(
        json.dumps(oracle, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(f"V4 escrito: {applied} errata aplicados")
    return 0


if __name__ == "__main__":
    sys.exit(main())
