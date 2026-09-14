# -*- coding: utf-8 -*-
"""Migra los oracles G1-R al formato ORACLE_CLAIM atomico con
provenance (ADR-017 seccion 5). No toca HOLDOUT.

Un ORACLE_CLAIM = un fact canonico esperado (o la ausencia del campo
cuando no hay expected). Cada claim separa:

  source_to_canonical_status        evidencia fuente -> concepto
                                    ( adjudicacion )
  external_semantic_mapping_status  concepto -> referencia externa
                                    ( segun canonical-registry.json )

Entradas:
  g1r/adjudication/dev-missingness-review.jsonl  (DEV oracle firmado)
  g1r/manifests/g1-regression-oracle.json        (regression)
  docs/semantics/canonical-registry.json
  manifests DEV / G1 sealed (content_sha256)

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
REG_PATH = REPO / "g1r/manifests/g1-regression-oracle.json"
REGISTRY = REPO / "docs/semantics/canonical-registry.json"

FIELD_LEVEL_CONCEPT = {
    "event_type": "EVENT_TYPE",
    "ex_date": "DATE_ROLE.EX_DATE",
    "record_date": "DATE_ROLE.RECORD_DATE",
    "payment_date": "DATE_ROLE.PAYMENT_DATE",
    "announcement_date": "DATE_ROLE.ANNOUNCEMENT_DATE",
    "amount_or_ratio": "AMOUNT_ROLE.*",
    "currency": "IDENTIFIER.CURRENCY",
    "instrument": "IDENTIFIER.ISIN",
}

_PATH_CONCEPT = {
    "amount.gross_per_share": "AMOUNT_ROLE.GROSS_UNIT_AMOUNT",
    "amount.net_per_share": "AMOUNT_ROLE.NET_UNIT_AMOUNT",
    "amount.gross_total": "AMOUNT_ROLE.GROSS_TOTAL",
    "amount.issue_price_per_share": "AMOUNT_ROLE.ISSUE_PRICE_PER_SHARE",
    "amount.max_total": "AMOUNT_ROLE.MAX_TOTAL",
    "amount.issue_premium_total_max": "AMOUNT_ROLE.MAX_TOTAL",
    "ratio.dividing_factor": "RATIO.SPLIT_FACTOR",
    "ratio.multiplying_factor": "RATIO.SPLIT_FACTOR",
    "ratio.terms": "RATIO.TERMS",
    "instrument.isin": "IDENTIFIER.ISIN",
    "instrument.currency": "IDENTIFIER.CURRENCY",
}

_SRC2CAN = {
    "CORRECT": "PROVEN",
    "MISSING": "PROVEN",
    "UNKNOWN": "UNMAPPED",
    "NOT_APPLICABLE": "NOT_APPLICABLE",
    "AMBIGUOUS": "CONFLICTING",
}


def concept_for(path, expected_value=None):
    """Resuelve el concepto canonico de un field_path.

    event_type usa el valor esperado (EVENT_TYPE.CASH_DIVIDEND...);
    el resto se mapea por path; lo no registrado queda UNREGISTERED
    para hacer visible la deuda del registry.
    """
    if path == "event_type" and expected_value:
        return f"EVENT_TYPE.{expected_value}"
    if path.startswith("date."):
        return f"DATE_ROLE.{path[5:].upper()}"
    if path.endswith(".currency"):
        return "IDENTIFIER.CURRENCY"
    if path in _PATH_CONCEPT:
        return _PATH_CONCEPT[path]
    if path.startswith("amount.nominal"):
        return "AMOUNT_ROLE.NOMINAL_AMOUNT"
    if path.startswith(("amount.", "ratio.", "shares.")):
        return f"UNREGISTERED::{path}"
    return f"UNREGISTERED::{path}"


def registry_status():
    concepts = {c["canonical_id"]: c["mapping_status"]
                for c in json.loads(
                    REGISTRY.read_text(encoding="utf-8"))["concepts"]}

    def lookup(cid):
        if cid in concepts:
            return concepts[cid]
        if cid.startswith("EVENT_TYPE."):
            # puede no existir como concepto propio (p.ej. valores
            # internos sin entrada); usar el status de la familia
            base = f"EVENT_TYPE.{cid.split('.', 1)[1]}"
            return concepts.get(base, "UNMAPPED")
        if cid.endswith(".*"):
            return "UNMAPPED"
        if cid.startswith("DATE_ROLE."):
            return concepts.get(cid) or concepts.get(
                "DATE_ROLE.OTHER", "UNMAPPED")
        if cid.startswith("AMOUNT_ROLE."):
            return concepts.get(cid) or concepts.get(
                "AMOUNT_ROLE.OTHER", "UNMAPPED")
        return "UNMAPPED"

    return lookup


def manifest_sha(set_dir, fid):
    for root in (REPO / "g1r/manifests", REPO / "g1/manifests"):
        mp = root / set_dir / f"{fid}.json"
        if mp.exists():
            docs = json.loads(mp.read_text(
                encoding="utf-8")).get("documents", [])
            return docs[0].get("content_sha256") if docs else None
    return None


def migrate_dev(ext_status):
    rows = [json.loads(l) for l in DEV_REVIEW.read_text(
        encoding="utf-8").splitlines() if l.strip()]
    claims = []
    for row in rows:
        fid, field = row["frame_item_id"], row["field"]
        baseline = row["pipeline"]["emitted_claims"] or {}
        s2c = _SRC2CAN.get(row["classification"], "UNMAPPED")
        expected = row["expected_claims"]
        common = {
            "frame_item_id": fid,
            "set": "development",
            "field": field,
            "classification": row["classification"],
            "p0_error": row.get("p0_error"),
            "baseline_claims": baseline or None,
            "source_to_canonical_status": s2c,
            "evidence_locator": row["source_review"]["evidence_locator"],
            "source_content_sha256": manifest_sha("dev", fid),
            "semantic_reference": "docs/semantics/canonical-registry.json",
            "review_status": "SIGNED",
            "reviewed_at": row["source_review"]["reviewed_at"],
        }
        if expected:
            for path, value in sorted(expected.items()):
                cid = concept_for(path, value if path == "event_type"
                                  else None)
                claims.append({
                    "oracle_claim_id": f"DEV::{fid}::{field}::{path}",
                    **common,
                    "field_path": path,
                    "canonical_concept": cid,
                    "expected_value": value,
                    "baseline_value": baseline.get(path),
                    "external_semantic_mapping_status": ext_status(cid),
                })
        else:
            claims.append({
                "oracle_claim_id": f"DEV::{fid}::{field}",
                **common,
                "field_path": None,
                "canonical_concept": FIELD_LEVEL_CONCEPT.get(
                    field, "UNREGISTERED"),
                "expected_value": "ABSENT",
                "baseline_value": None,
                "external_semantic_mapping_status": "NOT_APPLICABLE",
            })
    DEV_OUT.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False, sort_keys=True)
                  for c in claims) + "\n",
        encoding="utf-8")
    return len(claims)


def _atomic_claims(claims_dict, fid, field, ext_status):
    """Descompone un claim-set {path: value} en ORACLE_CLAIM atomicos."""
    out = []
    for path, value in sorted((claims_dict or {}).items()):
        cid = concept_for(path, value if path == "event_type" else None)
        out.append({
            "canonical_concept": cid,
            "field_path": path,
            "value": value,
            "external_semantic_mapping_status": ext_status(cid),
        })
    return out


def migrate_regression(ext_status):
    oracle = json.loads(REG_PATH.read_text(encoding="utf-8"))
    for section in ("known_correct_critical_fields",
                    "known_p0_incorrect_fields"):
        for e in oracle[section]:
            fid, field = e["frame_item_id"], e["field"]
            e["oracle_claim_id"] = (
                f"G1REG::{e['set'].upper()}::{fid}::{field}")
            e["canonical_concept"] = FIELD_LEVEL_CONCEPT.get(
                field, "UNREGISTERED")
            e["canonical_concepts"] = _atomic_claims(
                e.get("expected_claims") or e.get("forbidden_claims"),
                fid, field, ext_status)
            e["source_content_sha256"] = manifest_sha(e["set"], fid)
            e["source_to_canonical_status"] = "PROVEN"
            e["review_status"] = "ERRATUM" if e.get("erratum") else "SIGNED"
            e["reviewed_at"] = "2026-09-14"
    oracle["oracle_version"] = "CA_ES_G1_REGRESSION_ORACLE_V3"
    oracle["provenance_note"] = (
        "ORACLE_CLAIM con provenance (ADR-017): oracle_claim_id, "
        "canonical_concepts atomicos por fact, source_content_sha256, "
        "source_to_canonical_status separado de "
        "external_semantic_mapping_status. Los expected/forbidden/"
        "allowed no cambian respecto a V2.1.")
    oracle.pop("oracle_sha256", None)
    oracle["oracle_sha256"] = hashlib.sha256(
        canonical_bytes(oracle)).hexdigest()
    REG_PATH.write_text(
        json.dumps(oracle, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return sum(len(oracle[s]) for s in
               ("known_correct_critical_fields",
                "known_p0_incorrect_fields"))


if __name__ == "__main__":
    ext = registry_status()
    print(f"dev-oracle-claims: {migrate_dev(ext)} | "
          f"regression V3 claims: {migrate_regression(ext)}")
