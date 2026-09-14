# -*- coding: utf-8 -*-
"""Migra los oracles G1-R al formato ORACLE_CLAIM con provenance
(ADR-017 seccion 5). No toca HOLDOUT.

Entradas:
  g1r/adjudication/dev-missingness-review.jsonl  (DEV oracle firmado)
  g1r/manifests/g1-regression-oracle.json        (regression V2.1)
  manifests DEV / G1 sealed (para content_sha256)

Salidas:
  g1r/adjudication/dev-oracle-claims.jsonl
  g1r/manifests/g1-regression-oracle.json        (V3, provenance)
"""
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ca_es.canonical import canonical_bytes  # noqa: E402

DEV_REVIEW = REPO / "g1r/adjudication/dev-missingness-review.jsonl"
DEV_OUT = REPO / "g1r/adjudication/dev-oracle-claims.jsonl"
REG_OUT = REPO / "g1r/manifests/g1-regression-oracle.json"

FIELD_CONCEPT = {
    "event_type": "EVENT_TYPE",
    "ex_date": "DATE_ROLE.EX_DATE",
    "record_date": "DATE_ROLE.RECORD_DATE",
    "payment_date": "DATE_ROLE.PAYMENT_DATE",
    "announcement_date": "DATE_ROLE.ANNOUNCEMENT_DATE",
    "amount_or_ratio": "AMOUNT_ROLE",
    "currency": "IDENTIFIER.CURRENCY",
    "instrument": "IDENTIFIER.ISIN",
}


def manifest_sha(set_dir, fid):
    mp = REPO / "g1r/manifests" / set_dir / f"{fid}.json"
    if not mp.exists():
        mp = REPO / "g1/manifests" / set_dir / f"{fid}.json"
    if not mp.exists():
        return None
    docs = json.loads(mp.read_text(encoding="utf-8")).get("documents", [])
    return docs[0].get("content_sha256") if docs else None


def migrate_dev():
    rows = [json.loads(l) for l in DEV_REVIEW.read_text(
        encoding="utf-8").splitlines() if l.strip()]
    claims = []
    for row in rows:
        fid, field = row["frame_item_id"], row["field"]
        claims.append({
            "oracle_claim_id": f"DEV::{fid}::{field}",
            "frame_item_id": fid,
            "set": "development",
            "field": field,
            "canonical_concept": FIELD_CONCEPT.get(field, "AMOUNT_ROLE"),
            "classification": row["classification"],
            "p0_error": row.get("p0_error"),
            "expected_value": row["expected_claims"],
            "baseline_claims": row["pipeline"]["emitted_claims"] or None,
            "mapping_status": "PROVEN" if row["classification"] == "CORRECT"
            else "NOT_APPLICABLE" if row["classification"] == "NOT_APPLICABLE"
            else "UNMAPPED",
            "evidence_locator": row["source_review"]["evidence_locator"],
            "source_content_sha256": manifest_sha("dev", fid),
            "semantic_reference": "docs/semantics/canonical-registry.json",
            "review_status": "SIGNED",
            "reviewed_at": row["source_review"]["reviewed_at"],
        })
    DEV_OUT.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False, sort_keys=True)
                  for c in claims) + "\n",
        encoding="utf-8")
    return len(claims)


def migrate_regression():
    oracle = json.loads(REG_OUT.read_text(encoding="utf-8"))
    for section, status in (("known_correct_critical_fields", "SIGNED"),
                            ("known_p0_incorrect_fields", "SIGNED")):
        for e in oracle[section]:
            e["oracle_claim_id"] = (
                f"G1REG::{e['set'].upper()}::{e['frame_item_id']}::{e['field']}")
            e["canonical_concept"] = FIELD_CONCEPT.get(e["field"], "AMOUNT_ROLE")
            e["source_content_sha256"] = manifest_sha(e["set"], e["frame_item_id"])
            e["review_status"] = "ERRATUM" if e.get("erratum") else status
            e["reviewed_at"] = "2026-09-14"
    oracle["oracle_version"] = "CA_ES_G1_REGRESSION_ORACLE_V3"
    oracle["provenance_note"] = (
        "ORACLE_CLAIM con provenance (ADR-017): oracle_claim_id, "
        "canonical_concept, source_content_sha256, review_status por claim. "
        "Los expected/forbidden/allowed no cambian respecto a V2.1.")
    oracle.pop("oracle_sha256", None)
    oracle["oracle_sha256"] = hashlib.sha256(
        canonical_bytes(oracle)).hexdigest()
    REG_OUT.write_text(
        json.dumps(oracle, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return len(oracle["known_correct_critical_fields"]) + len(
        oracle["known_p0_incorrect_fields"])


if __name__ == "__main__":
    n_dev = migrate_dev()
    n_reg = migrate_regression()
    print(f"dev-oracle-claims: {n_dev} | regression V3 claims: {n_reg}")
