# -*- coding: utf-8 -*-
"""Construye el corpus G1-R2: snapshot Portfolio -> ELIGIBILITY_V1 ->
exclusion (190 ids vistos + spent CA groups) -> CA_GROUP_V1 ->
precondition >= 8 -> seleccion HOLDOUT (8 CA-groups).

Implementa literalmente docs/gates/g1r2-preregistered.json
(CA_ES_G1R2_PREREG_V1, tag g1r2-protocol).

  1. snapshot nuevo: index + product pages -> g1r2/corpus/raw/snapshot-*/
  2. enumerate_portfolio (misma extraccion que G1) -> doc rows
  3. ELIGIBILITY_V1 sobre metadata oficial
  4. exclusion: document_id en los 190 vistos, o ca_group_id de un
     cluster que contenga >=1 doc visto (spent-equivalence, misma
     funcion CA_GROUP_V1 sobre nuevos+vistos)
  5. si distinct unseen CA-groups < 8 -> WAITING_FOR_CORPUS
     si >= 8 -> sample_score = SHA256(CA_ES_G1R2_SAMPLE_V1+gid),
     los 8 primeros -> HOLDOUT; raw acquisition solo para sha256
     (auto_acquisition_for_sha_allowed), sin inspeccion
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import build_g1_frame as bgf  # noqa: E402
import fetch_cnmv as cnmv  # noqa: E402

TODAY = date.today().isoformat()
SNAP_DIR = REPO / "g1r2" / "corpus" / "raw" / f"snapshot-{TODAY}"
HOLDOUT_RAW = REPO / "g1r2" / "corpus" / "raw" / "holdout"
MANIFEST_DIR = REPO / "g1r2" / "manifests"
STATE_PATH = REPO / "g1r2" / "state.json"

SAMPLE_NS = "CA_ES_G1R2_SAMPLE_V1"
CAGROUP_NS = "CA_ES_G1R2_CAGROUP_V1"
MIN_STRATUM_CAS = 8
HOLDOUT_TARGET_CAS = 8
LINKAGE_GAP_DAYS = 62

# --- ELIGIBILITY_V1 (congelada en g1r2-preregistered.json) ---
TYPE_LIST_V1: frozenset[str] = frozenset()
SUBTYPE_LIST_V1 = frozenset({"ampliacion de capital"})
TITLE_REGEX_V1 = re.compile(
    r"ampliacion de capital|aumento de capital"
    r"|suscripcion preferente|derechos de suscripcion"
)
REDUCTION_SUBTYPE = "reduccion del capital social"

ISIN_RE = re.compile(r"ES[A-Z0-9]{10}", re.I)
POEX_ID_RE = re.compile(r"^POEX-DOC-(\d+)$")

normalize = bgf.normalize


def eligible_v1(row: dict) -> bool:
    return (
        normalize(row.get("type")) in TYPE_LIST_V1
        or normalize(row.get("subtype")) in SUBTYPE_LIST_V1
        or bool(TITLE_REGEX_V1.search(normalize(row.get("title"))))
    )


def family_v1(row: dict) -> str:
    if eligible_v1(row):
        return "CAPITAL_INCREASE"
    if normalize(row.get("subtype")) == REDUCTION_SUBTYPE:
        return "CAPITAL_REDUCTION"
    return "OTHER"


def isin_of(row: dict) -> str | None:
    for field in ("product", "issuer_raw", "product_url"):
        m = ISIN_RE.search(row.get(field) or "")
        if m:
            return m.group(0).upper()
    return (row.get("instrument_isin") or "").upper() or None


# --- CA_GROUP_V1 (congelada en g1r2-preregistered.json) ---
def ca_groups(docs: list[dict]) -> dict[str, list[dict]]:
    """Asigna ca_group_id por documento. Literal de la spec:
    isin null -> singleton DOC:<id>; si no, (isin,family) + orden por
    date + single-linkage gap<=62d; gid = sha256(NS|isin|fam|min_date)."""
    out: dict[str, list[dict]] = {}
    buckets: dict[tuple[str, str], list[dict]] = {}
    for d in docs:
        if not d["isin"]:
            out[f"DOC:{d['document_id']}"] = [d]
        else:
            buckets.setdefault((d["isin"], d["family"]), []).append(d)
    for (isin, fam), ds in buckets.items():
        dated = sorted(
            (d for d in ds if d["date"]),
            key=lambda d: (d["date"], str(d["document_id"])))
        for d in ds:  # sin date: metadata insuficiente -> singleton
            if not d["date"]:
                out[f"DOC:{d['document_id']}"] = [d]
        if not dated:
            continue
        cluster = [dated[0]]
        for prev, cur in zip(dated, dated[1:]):
            if (date.fromisoformat(cur["date"])
                    - date.fromisoformat(prev["date"])).days <= LINKAGE_GAP_DAYS:
                cluster.append(cur)
            else:
                _flush_cluster(out, isin, fam, cluster)
                cluster = [cur]
        _flush_cluster(out, isin, fam, cluster)
    return out


def _flush_cluster(out, isin, fam, cluster):
    min_date = min(d["date"] for d in cluster)
    gid = hashlib.sha256(
        f"{CAGROUP_NS}|{isin}|{fam}|{min_date}".encode()
    ).hexdigest()
    out[gid] = cluster


def load_seen():
    """190 ids vistos + filas de metadata de los docs Portfolio vistos."""
    seen_ids: set[str] = set()
    e = json.loads(
        (REPO / "g1r/manifests/excluded-g1-frame-items.json").read_text(
            encoding="utf-8"))
    for grp in e["groups"].values():
        seen_ids.update(grp["frame_item_ids"])
    sp = json.loads(
        (REPO / "g1r/manifests/dev-holdout.json").read_text(encoding="utf-8"))
    for key in ("development", "holdout"):
        v = sp[key]
        seen_ids.update(v["frame_item_ids"] if isinstance(v, dict) else v)
    seen_doc_ids = {
        m.group(1) for fid in seen_ids if (m := POEX_ID_RE.match(fid))
    }
    frame = json.loads(
        (REPO / "g1/manifests/sampling-frame.json").read_text(encoding="utf-8"))
    frame_by_id = {i["frame_item_id"]: i for i in frame["items"]}
    seen_rows = {}
    for fid in seen_ids:
        m = POEX_ID_RE.match(fid)
        item = frame_by_id.get(fid)
        if not (m and item):
            continue
        seen_rows[m.group(1)] = {
            "document_id": m.group(1),
            "title": item.get("title"),
            "subtype": None,
            "type": item.get("official_category"),
            "date": item.get("publication_date"),
            "product": item.get("issuer_raw"),
            "product_url": (item.get("metadata") or {}).get("product_url"),
            "instrument_isin": item.get("instrument_isin"),
            "seen": True,
        }
    return seen_ids, seen_doc_ids, seen_rows


def acquire_raws(docs: list[dict], opener) -> None:
    HOLDOUT_RAW.mkdir(parents=True, exist_ok=True)
    (MANIFEST_DIR / "holdout").mkdir(parents=True, exist_ok=True)
    for d in docs:
        doc_id = d["document_id"]
        official_id = f"POEX-DOC-{doc_id}"
        url = f"https://api.portfolio.exchange/poex/document/{doc_id}"
        raw = bgf.get(opener, url)
        raw_path = HOLDOUT_RAW / f"{official_id}.pdf"
        raw_path.write_bytes(raw)
        manifest = {
            "manifest_version": "CA_ES_SOURCE_MANIFEST_V1",
            "corpus_id": f"G1R2_HOLDOUT_{official_id}",
            "retrieved_at": TODAY,
            "documents": [{
                "source_id": "PORTFOLIO_STOCK_EXCHANGE",
                "official_document_id": official_id,
                "content_sha256": hashlib.sha256(raw).hexdigest(),
                "retrieved_at": TODAY,
                "publication_date": d.get("date"),
                "media_type": "application/pdf",
                "raw_relpath": f"g1r2/corpus/raw/holdout/{official_id}.pdf",
                "synthetic": False,
                "retrieval_status": "OK",
                "acquisition": {"url": url, "retrieval_method": "HTTP_GET"},
                "relations": [],
            }],
        }
        (MANIFEST_DIR / "holdout" / f"{official_id}.json").write_text(
            json.dumps(manifest, indent=1, ensure_ascii=False),
            encoding="utf-8")
        print(f"  holdout raw {official_id}: {len(raw)} bytes", flush=True)


def main() -> int:
    opener = cnmv.build_opener()
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    bgf.RAW_DIR = SNAP_DIR  # mismo extractor, raw dir nuevo
    rows = bgf.enumerate_portfolio(opener, force=False)
    for r in rows:
        r["isin"] = isin_of(r)
        r["family"] = family_v1(r)
        r["eligible"] = eligible_v1(r)
        r["seen"] = False

    seen_ids, seen_doc_ids, seen_rows = load_seen()
    snap_by_id = {r["document_id"]: r for r in rows}
    universe = [r for r in rows if r["eligible"]]
    for doc_id, frow in seen_rows.items():
        snap = snap_by_id.get(doc_id)
        if snap is not None:
            snap["seen"] = True  # doc visto: metadata fresca del snapshot
        else:
            frow["isin"] = isin_of(frow)
            frow["family"] = family_v1(frow)
            universe.append(frow)

    groups = ca_groups(universe)
    eligible_groups, excluded_groups = [], []
    for gid, members in groups.items():
        has_seen = any(
            m.get("seen") or str(m["document_id"]) in seen_doc_ids
            for m in members)
        all_eligible = all(
            m.get("eligible") or m.get("seen") for m in members)
        rec = {
            "ca_group_id": gid,
            "document_ids": sorted(str(m["document_id"]) for m in members),
            "contains_seen": has_seen,
        }
        if has_seen:
            excluded_groups.append(rec)
        elif all_eligible:
            eligible_groups.append(rec)
    eligible_groups.sort(
        key=lambda g: hashlib.sha256(
            f"{SAMPLE_NS}{g['ca_group_id']}".encode()).hexdigest())

    n = len(eligible_groups)
    precondition_met = n >= MIN_STRATUM_CAS
    selected = eligible_groups[:HOLDOUT_TARGET_CAS] if precondition_met else []

    snapshot_manifest = {
        "manifest_version": "CA_ES_G1R2_SNAPSHOT_V1",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "raw_dir": str(SNAP_DIR.relative_to(REPO)).replace("\\", "/"),
        "documents_enumerated": len(rows),
        "eligible_documents": sum(1 for r in rows if r["eligible"]),
        "excluded_seen_ids": len(seen_ids),
        "excluded_spent_groups": excluded_groups,
        "distinct_unseen_ca_groups": n,
        "precondition": {
            "min_stratum_cas": MIN_STRATUM_CAS,
            "met": precondition_met,
        },
        "eligible_groups": eligible_groups,
        "rows": [{
            "document_id": r["document_id"], "title": r.get("title"),
            "subtype": r.get("subtype"), "type": r.get("type"),
            "date": r.get("date"), "product": r.get("product"),
            "isin": r.get("isin"), "family": r["family"],
            "eligible": r["eligible"], "seen": r["seen"],
            "url": r.get("url"),
        } for r in rows],
    }
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    snap_path = MANIFEST_DIR / f"snapshot-portfolio-{TODAY}.json"
    snap_path.write_text(
        json.dumps(snapshot_manifest, indent=1, ensure_ascii=False),
        encoding="utf-8")

    phase = "HOLDOUT_SEALED" if precondition_met else "WAITING_FOR_CORPUS"
    if precondition_met:
        holdout_docs = [
            snap_by_id[d]
            for g in selected for d in g["document_ids"]
            if d in snap_by_id
        ]
        acquire_raws(holdout_docs, opener)
        (MANIFEST_DIR / "holdout.json").write_text(json.dumps({
            "manifest_version": "CA_ES_G1R2_HOLDOUT_V1",
            "sealed_at": datetime.now(timezone.utc).isoformat(),
            "selection": "sample_score = SHA256(CA_ES_G1R2_SAMPLE_V1 + ca_group_id), sorted, first 8",
            "ca_groups": selected,
            "document_ids": sorted(
                d for g in selected for d in g["document_ids"]),
            "sealed_until": "g1r2-parser-freeze",
            "no_manual_inspection": True,
        }, indent=1, ensure_ascii=False), encoding="utf-8")

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({
        "state_version": "CA_ES_G1R2_STATE_V1",
        "updated_at": TODAY,
        "protocol": "docs/gates/g1r2-preregistered.json",
        "protocol_tag": "g1r2-protocol",
        "phase": phase,
        "snapshot": str(snap_path.relative_to(REPO)).replace("\\", "/"),
        "precondition": {
            "min_stratum_cas": MIN_STRATUM_CAS,
            "holdout_target_cas": HOLDOUT_TARGET_CAS,
            "distinct_unseen_ca_groups": n,
            "met": precondition_met,
        },
        "next": ("sealed holdout -> desarrollo AMOUNT_ROLE_MISBINDING"
                 if precondition_met
                 else "snapshot posterior; acumular hasta >=8 CA-groups"),
    }, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"docs={len(rows)} eligible={snapshot_manifest['eligible_documents']} "
          f"unseen_ca_groups={n} phase={phase}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
