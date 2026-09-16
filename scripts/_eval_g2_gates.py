# -*- coding: utf-8 -*-
"""Evaluador de gates G2 + expectativas del qualification corpus.

Lee los artefactos canon producidos por run_g2.py (run-1, run-2,
control-e) y evalua los ocho gates y los casos A-E+AUX de
docs/gates/g2-preregistered.json. Produce g2/results/gates-eval.json.

NO declara PASS/FAIL: el veredicto es adjudicacion humana.

    PYTHONPATH=src python scripts/_eval_g2_gates.py
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from ca_es.namespaces import candidate_event_id  # noqa: E402
from ca_es.pipeline import load_and_parse  # noqa: E402

RESULTS = REPO / "g2" / "results"
PREREG = json.loads(
    (REPO / "docs/gates/g2-preregistered.json").read_text(encoding="utf-8")
)
MANIFEST_RELPATH = "g2/manifests/qualification-corpus.json"
POLICY_RELPATH = "docs/sources/source-policy.json"
ADJUDICATIONS = REPO / "g0/manifests/adjudications-real.json"
FIRDS = REPO / "g0/corpus/reference/esma-firds-listings-real.json"
BINDINGS = REPO / "g0/corpus/reference/portfolio-instruments.json"

# Capacidad QUARANTINED_UNSUPPORTED -> (source_id, field_path) prohibido.
CAPABILITY_FIELD = {
    "capital_increase_issue_price": "amount.issue_price_per_share",
}


def _latest(prefix: str) -> Path:
    matches = sorted(RESULTS.glob(f"{prefix}-*-canon.json"))
    if not matches:
        raise SystemExit(f"falta artefacto {prefix}-*-canon.json en {RESULTS}")
    return matches[-1]


def _load_canon(prefix: str) -> dict:
    return json.loads(_latest(prefix).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- raw pointers

def _resolution_roots() -> dict:
    """Raiz de resolucion por source_document_id, conforme al contrato
    del parser: raw_record del documento + namespace del ParsedDocument
    (event_type, infrastructure_roles); artefactos de referencia para
    ESMA_FIRDS / instrument bindings."""
    corpus = load_and_parse(
        REPO, REPO / MANIFEST_RELPATH, REPO / POLICY_RELPATH
    )
    roots = {}
    for document_id, parsed in corpus.parsed.items():
        root = dict(corpus.raw_records[document_id])
        root["event_type"] = parsed.event_type
        root["infrastructure_roles"] = [asdict(r) for r in parsed.infrastructure_roles]
        root["issuer_name"] = parsed.issuer_name
        root["isin"] = parsed.isin
        root["lei"] = parsed.lei
        roots[document_id] = root
    listings: dict[str, list] = {}
    for entry in json.loads(FIRDS.read_text(encoding="utf-8"))["listings"]:
        listings.setdefault(entry["isin"], []).append(entry)
    roots["ESMA_FIRDS"] = {"listings": listings}
    bindings = json.loads(BINDINGS.read_text(encoding="utf-8"))
    roots["INSTRUMENT_BINDING"] = {"instrument_bindings": bindings}
    for instrument in bindings["instruments"]:
        pid = instrument.get("product_id")
        if pid is not None:
            roots[f"PORTFOLIO-PRODUCT-{pid}"] = {"instrument_bindings": instrument}
    return roots


def _resolve(root: object, pointer: str) -> bool:
    """JSON-pointer mecanico sobre la raiz; el ultimo tramo puede ser
    una clave o indice de lista. Para /listings/<isin>/<locator> el
    locator es intra-fixture del listing."""
    if not pointer.startswith("/"):
        return False
    node = root
    segments = [s.replace("~1", "/").replace("~0", "~") for s in pointer[1:].split("/")]
    for i, segment in enumerate(segments):
        if isinstance(node, dict):
            if segment not in node:
                return False
            node = node[segment]
        elif isinstance(node, list):
            if not segment.isdigit():
                # localizador intra-fixture (p. ej. sufijo de listing
                # "lei:..." o "POSE:0:admission" sobre la entrada ISIN)
                return i == len(segments) - 1 and bool(node)
            if int(segment) >= len(node):
                return False
            node = node[int(segment)]
        else:
            return False
    return True


# ------------------------------------------------------------------- gates

def gate_unproven_merges(canon: dict) -> dict:
    relations = canon["identity"]["relations"]
    parent: dict[str, str] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    def qualifies(r):
        if r["relation"] != "SAME_CORPORATE_ACTION":
            return False
        if r["decision_basis"] == "DETERMINISTIC":
            return bool(r.get("evidence"))
        if r["decision_basis"] == "MANUAL_ADJUDICATION":
            return bool(r.get("reviewer") and r.get("reviewed_at"))
        return False

    links = [(r["a"], r["b"]) for r in relations if qualifies(r)]
    for a, b in links:
        union(a, b)
    bad = []
    for event in canon["events"]:
        cands = event["provenance"]["candidate_ids"]
        if len(cands) > 1 and len({find(c) for c in cands}) != 1:
            bad.append(event["canonical_event_id"])
    return {"measured": len(bad), "required": 0, "detail": bad}


def gate_revision_history(canon: dict) -> dict:
    bad = []
    facts_by_revision: dict[str, int] = {}
    for event in canon["events"]:
        for fact in event["facts"]:
            facts_by_revision[fact["revision_id"]] = (
                facts_by_revision.get(fact["revision_id"], 0) + 1
            )
        ids = {r["revision_id"] for r in event["revisions"]}
        generations = sorted(r["generation"] for r in event["revisions"])
        if generations != list(range(len(generations))):
            bad.append((event["canonical_event_id"], "GENERATION_GAP"))
        for revision in event["revisions"]:
            if revision["generation"] > 0 and (
                revision["supersedes_revision_id"] not in ids
            ):
                bad.append((event["canonical_event_id"], "BROKEN_SUPERSEDES"))
            if revision["generation"] < generations[-1]:
                if not revision["document_ids"]:
                    bad.append((event["canonical_event_id"], "LOST_DOCS"))
                if not facts_by_revision.get(revision["revision_id"]):
                    bad.append((event["canonical_event_id"], "LOST_FACTS"))
    return {"measured": len(bad), "required": 0, "detail": bad}


def gate_fact_provenance(canon: dict, roots: dict) -> dict:
    total = 0
    bad = []
    for event in canon["events"]:
        for fact in event["facts"]:
            total += 1
            root = roots.get(fact["source_document_id"])
            ok = (
                bool(fact["evidence_locator"])
                and bool(fact["raw_pointer"])
                and root is not None
                and _resolve(root, fact["raw_pointer"])
            )
            if not ok:
                bad.append(
                    (fact["assertion_id"], fact["field_path"], fact["raw_pointer"])
                )
    return {
        "measured": (total - len(bad)) / total if total else 0.0,
        "required": 1.0,
        "total_facts": total,
        "detail": bad,
    }


def gate_deterministic_export(run1: dict, run2: dict) -> dict:
    b1 = _latest("run-1").read_bytes()
    b2 = _latest("run-2").read_bytes()
    same = b1 == b2
    return {
        "measured": 1.0 if same else 0.0,
        "required": 1.0,
        "bytes_identical": same,
        "run1_sha256": __import__("hashlib").sha256(b1).hexdigest(),
        "run2_sha256": __import__("hashlib").sha256(b2).hexdigest(),
    }


def _fingerprint(value: object) -> str:
    if isinstance(value, dict) and value.get("__financial__"):
        return json.dumps(
            {"normalized": value["normalized"], "currency": value["currency"]},
            sort_keys=True,
        )
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def gate_silent_conflicts(canon: dict) -> dict:
    bad = []
    for event in canon["events"]:
        groups: dict[tuple, list] = {}
        for fact in event["facts"]:
            if fact["fact_origin"] == "REFERENCE_ENRICHMENT":
                continue
            key = (
                fact["revision_id"],
                fact["field_path"],
                fact["asserted_as_of"],
            )
            groups.setdefault(key, []).append(fact)
        recorded = {
            (c["revision_id"], c["field_path"], c["asserted_as_of"])
            for c in event["conflicts"]
        }
        for key, group in groups.items():
            if len({_fingerprint(f["value"]) for f in group}) <= 1:
                continue
            if key not in recorded:
                bad.append((event["canonical_event_id"],) + key)
                continue
            covered = next(
                c for c in event["conflicts"]
                if (c["revision_id"], c["field_path"], c["asserted_as_of"]) == key
            )
            missing = {f["assertion_id"] for f in group} - set(
                covered["assertion_ids"]
            )
            if missing:
                bad.append((event["canonical_event_id"],) + key)
    return {"measured": len(bad), "required": 0, "detail": bad}


def gate_human_facts(canon: dict) -> dict:
    adj = json.loads(ADJUDICATIONS.read_text(encoding="utf-8"))
    relation_only = all(
        set(a) <= {"relation", "a", "b", "reviewed_at", "reviewer", "evidence"}
        for a in adj.get("adjudications", [])
    )
    bad = []
    allowed_origins = {
        "SOURCE_ASSERTION",
        "DETERMINISTIC_DERIVATION",
        "REFERENCE_ENRICHMENT",
    }
    for event in canon["events"]:
        for fact in event["facts"]:
            if fact["fact_origin"] not in allowed_origins or "adjudic" in (
                fact["source_document_id"].lower()
                + fact["evidence_locator"].lower()
                + fact["assertion_id"].lower()
            ):
                bad.append(fact["assertion_id"])
    return {
        "measured": len(bad) if relation_only else len(bad) + 1,
        "required": 0,
        "detail": {"adjudications_relations_only": relation_only, "facts": bad},
    }


def gate_precision(canon: dict) -> dict:
    bad = []

    def scan(node, path):
        if isinstance(node, float):
            bad.append(("float", path))
        elif isinstance(node, dict):
            if node.get("__financial__"):
                if not isinstance(node.get("raw_lexeme"), str):
                    bad.append(("raw_lexeme", path))
                if not isinstance(node.get("scale"), int):
                    bad.append(("scale", path))
                try:
                    Decimal(str(node["normalized"]))
                except Exception:
                    bad.append(("normalized", path))
            for key, value in node.items():
                scan(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                scan(value, f"{path}[{i}]")

    scan(canon, "$")
    return {"measured": len(bad), "required": 0, "detail": bad}


def gate_unsupported(canon: dict) -> dict:
    policy = json.loads((REPO / POLICY_RELPATH).read_text(encoding="utf-8"))
    forbidden = set()
    for source_id, source in policy["sources"].items():
        for name, cap in (source.get("capabilities") or {}).items():
            if cap["status"] == "QUARANTINED_UNSUPPORTED":
                forbidden.add((source_id, CAPABILITY_FIELD[name]))
    bad = [
        (f["source_id"], f["field_path"], f["assertion_id"])
        for event in canon["events"]
        for f in event["facts"]
        if (f["source_id"], f["field_path"]) in forbidden
    ]
    return {"measured": len(bad), "required": 0, "detail": bad}


# ------------------------------------------------------------------- cases

def _event_of(canon: dict, official_document_id: str, source_id: str) -> dict | None:
    cand = candidate_event_id(source_id, official_document_id)
    for event in canon["events"]:
        if cand in event["provenance"]["candidate_ids"]:
            return event
    return None


def _fin(fact: dict) -> str:
    value = fact.get("value") or {}
    return value.get("normalized") if isinstance(value, dict) else ""


def eval_cases(canon: dict, control: dict) -> dict:
    results = {}

    event_a = _event_of(canon, "CNMV-IP-1884", "CNMV")
    ok = event_a is not None
    detail = {}
    if ok:
        cands = event_a["provenance"]["candidate_ids"]
        linked = any(
            r["relation"] == "SAME_CORPORATE_ACTION"
            and r["decision_basis"] == "DETERMINISTIC"
            and r.get("evidence")
            and {r["a"], r["b"]} == set(cands)
            for r in canon["identity"]["relations"]
        )
        conflict = [
            c for c in event_a["conflicts"]
            if c["field_path"] == "date.announcement_date"
        ]
        detail = {
            "one_event": len(cands) == 2,
            "event_type": event_a["event_type"] == "CAPITAL_INCREASE",
            "deterministic_link": linked,
            "announcement_conflict": bool(conflict)
            and len(conflict[0]["values"]) == 2,
            "single_revision": len(event_a["revisions"]) == 1,
        }
    results["A"] = {"pass": ok and all(detail.values()), "detail": detail}

    event_b = _event_of(canon, "CNMV-OIR-40280", "CNMV")
    detail = {}
    if event_b is not None:
        revs = {r["generation"]: r for r in event_b["revisions"]}
        g0, g1 = revs.get(0), revs.get(1)
        detail = {
            "one_event": len(event_b["provenance"]["candidate_ids"]) == 2,
            "event_type": event_b["event_type"] == "CASH_DIVIDEND",
            "two_revisions": len(event_b["revisions"]) == 2,
            "supersedes": bool(
                g0 and g1
                and g1["supersedes_revision_id"] == g0["revision_id"]
                and g1["evidence"]
            ),
        }
        if g0 and g1:
            f0 = {f["field_path"]: f for f in event_b["facts"] if f["revision_id"] == g0["revision_id"]}
            f1 = {f["field_path"]: f for f in event_b["facts"] if f["revision_id"] == g1["revision_id"]}
            detail.update(
                {
                    "gen0_amount_0.22": _fin(f0.get("amount.gross_per_share", {}))
                    == "0.22",
                    "gen1_no_amount": "amount.gross_per_share" not in f1,
                    "gen0_dates": (
                        f0.get("date.ex_date", {}).get("value") == "2026-07-27"
                        and f0.get("date.record_date", {}).get("value") == "2026-07-28"
                        and f0.get("date.payment_date", {}).get("value") == "2026-07-29"
                    ),
                    "gen1_dates": (
                        f1.get("date.ex_date", {}).get("value") == "2026-07-20"
                        and f1.get("date.record_date", {}).get("value") == "2026-07-21"
                        and f1.get("date.payment_date", {}).get("value") == "2026-07-22"
                    ),
                }
            )
    results["B"] = {
        "pass": event_b is not None and all(detail.values()),
        "detail": detail,
    }

    event_c = _event_of(
        canon, "BMEG-Dividends-ES0105448007-2026-07-08", "BME_GROWTH"
    )
    detail = {}
    if event_c is not None:
        facts = {f["field_path"]: f for f in event_c["facts"]}
        detail = {
            "event_type": event_c["event_type"] == "CASH_DIVIDEND",
            "isin": event_c["affected_instrument"]["isin"] == "ES0105448007",
            "ex_date": facts.get("date.ex_date", {}).get("value") == "2026-07-08",
            "payment_date": facts.get("date.payment_date", {}).get("value")
            == "2026-07-10",
            "gross": _fin(facts.get("amount.gross_per_share", {})) == "0.08690661",
            "net": _fin(facts.get("amount.net_per_share", {})) == "0.07039435",
        }
    results["C"] = {
        "pass": event_c is not None and all(detail.values()),
        "detail": detail,
    }

    event_d = _event_of(
        canon, "BMEG-CapitalIncreases-ES0105606190-2025-03-27", "BME_GROWTH"
    )
    detail = {}
    if event_d is not None:
        facts = {f["field_path"]: f for f in event_d["facts"]}
        expected_amounts = {
            "amount.disbursement_per_share": "0.15",
            "amount.price": "0.15",
            "amount.rights_price": "0.0",
            "amount.effective_total": "0.0",
            "amount.liberated_percentage": "0.0",
            "amount.nominal_total": "83333.3",
        }
        detail = {
            "event_type": event_d["event_type"] == "CAPITAL_INCREASE",
            "isin": event_d["affected_instrument"]["isin"] == "ES0105606190",
            "amounts": all(
                _fin(facts.get(k, {})) == v for k, v in expected_amounts.items()
            ),
        }
    results["D"] = {
        "pass": event_d is not None and all(detail.values()),
        "detail": detail,
    }

    san_cand_a = candidate_event_id("CNMV", "CNMV-SAN-DIV-2026")
    san_cand_b = candidate_event_id("ISSUER_IR", "SAN-IR-REMUNERATION")
    control_events = {
        r["candidate_id"]: r["canonical_event_id"]
        for r in control["identity"]["resolutions"]
    }
    control_links = [
        r for r in control["identity"]["relations"]
        if {r["a"], r["b"]} == {san_cand_a, san_cand_b}
    ]
    main_event = _event_of(canon, "CNMV-SAN-DIV-2026", "CNMV")
    contrast = any(
        r["relation"] == "SAME_CORPORATE_ACTION"
        and r["decision_basis"] == "MANUAL_ADJUDICATION"
        and {r["a"], r["b"]} == {san_cand_a, san_cand_b}
        for r in canon["identity"]["relations"]
    )
    detail = {
        "distinct_without_adjudication": control_events.get(san_cand_a)
        not in (None, control_events.get(san_cand_b)),
        "no_relation_in_control": not control_links,
        "manual_merge_contrast": contrast
        and main_event is not None
        and san_cand_b in main_event["provenance"]["candidate_ids"],
    }
    results["E"] = {"pass": all(detail.values()), "detail": detail}

    aux_event = _event_of(canon, "POEX-DOC-39649", "PORTFOLIO_STOCK_EXCHANGE")
    no_issue_price = not any(
        f["field_path"] == "amount.issue_price_per_share"
        for event in canon["events"]
        for f in event["facts"]
        if f["source_id"] == "PORTFOLIO_STOCK_EXCHANGE"
    )
    detail = {
        "poex_event_present": aux_event is not None
        and aux_event["event_type"] == "CAPITAL_INCREASE",
        "no_issue_price_anywhere": no_issue_price,
    }
    results["AUX"] = {"pass": all(detail.values()), "detail": detail}

    return results


def main() -> int:
    canon1 = _load_canon("run-1")
    canon2 = _load_canon("run-2")
    control = _load_canon("control-e")
    roots = _resolution_roots()

    gates = {
        "canonical_identity_unproven_merges": gate_unproven_merges(canon1),
        "revision_history_loss": gate_revision_history(canon1),
        "fact_provenance_rate": gate_fact_provenance(canon1, roots),
        "deterministic_export": gate_deterministic_export(canon1, canon2),
        "silent_conflicts": gate_silent_conflicts(canon1),
        "human_authored_business_facts": gate_human_facts(canon1),
        "financial_precision_loss": gate_precision(canon1),
        "unsupported_capability_emissions": gate_unsupported(canon1),
    }
    cases = eval_cases(canon1, control)

    report = {
        "eval_version": "CA_ES_G2_GATES_EVAL_V1",
        "protocol": "docs/gates/g2-preregistered.json @ g2-protocol",
        "artifacts": {
            "run1": str(_latest("run-1").relative_to(REPO)).replace("\\", "/"),
            "run2": str(_latest("run-2").relative_to(REPO)).replace("\\", "/"),
            "control_e": str(_latest("control-e").relative_to(REPO)).replace("\\", "/"),
        },
        "gates": {
            name: {
                "measured": g["measured"],
                "required": g["required"],
                "met": g["measured"] == g["required"],
                "detail": g["detail"],
            }
            for name, g in gates.items()
        },
        "cases": cases,
        "verdict": "PENDING_HUMAN_ADJUDICATION",
    }
    out = RESULTS / "gates-eval.json"
    out.write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(
        {"gates": {k: v["met"] for k, v in report["gates"].items()},
         "cases": {k: v["pass"] for k, v in cases.items()}},
        indent=1,
    ))
    print(f"out={out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
