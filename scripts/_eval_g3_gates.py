# -*- coding: utf-8 -*-
"""Evaluador de gates G3 + casos de producto A-F.

Lee g3/input/canon.json + policy pinneada y las salidas capturadas por
run_g3.py; produce g3/results/gates-eval.json. NO declara PASS/FAIL:
veredicto reservado a adjudicacion humana.

    PYTHONPATH=src python scripts/_eval_g3_gates.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ca_es.surface import Surface, _fingerprint, load_surface  # noqa: E402

CANON = REPO / "g3/input/canon.json"
POLICY = REPO / "docs/sources/source-policy.json"
COMMANDS = REPO / "g3/results/commands"
OUT = REPO / "g3/results/gates-eval.json"

MFE = "59303c3c-8be7-578f-bc59-8e5e43a1fdf3"
ALMIRALL = "035e32ca-ba61-5105-8756-e0234e5335fc"
BMEG_DIV = "6881d24a-ef46-5053-80ce-1743a1792f8b"
BMEG_CAP = "3c9270d8-76b3-5953-942c-b1f42c1cc56a"
SAN = "6443e2be-b70d-50c7-88d1-4a62f43789e9"
POEX = "e885fff1-0a3b-57d7-a2fa-f51a6e613f10"


def _norm(value):
    if isinstance(value, dict) and value.get("__financial__"):
        return value["normalized"]
    return value


# ------------------------------------------------------------------ gates

def gate_current_state(s: Surface) -> dict:
    bad = []
    for event in s.canon["events"]:
        state = s._current_state(event)
        generations = s._generations(event)
        for field_path, field_state in state.items():
            rev = field_state["origin_revision_id"]
            if rev != "EVENT_SCOPE" and rev not in generations:
                bad.append((event["canonical_event_id"], field_path, "BAD_ORIGIN"))
            if field_state["status"] == "CURRENT" and len(
                {_fingerprint(v["value"]) for v in field_state["values"]}
            ) != 1:
                bad.append((event["canonical_event_id"], field_path, "MULTI_CURRENT"))
            if field_state["status"] == "CONFLICTING" and len(field_state["values"]) < 2:
                bad.append((event["canonical_event_id"], field_path, "CONFLICT_SIN_VALUES"))
    # oracle MFE
    mfe = s.show(MFE)["current_state"]
    oracle = {
        "amount.gross_per_share": ("0.22", 0),
        "date.ex_date": ("2026-07-20", 1),
        "date.record_date": ("2026-07-21", 1),
        "date.payment_date": ("2026-07-22", 1),
    }
    for field_path, (expected, gen) in oracle.items():
        st = mfe[field_path]
        if _norm(st["values"][0]["value"]) != expected or st["origin_generation"] != gen:
            bad.append((MFE, field_path, "ORACLE"))
    return {"measured": 1.0 if not bad else 0.0, "required": 1.0, "detail": bad}


def gate_timeline(s: Surface) -> dict:
    bad = []
    for event in s.canon["events"]:
        tl = s.timeline(event["canonical_event_id"])
        gens = [r["generation"] for r in tl["revisions"]]
        if gens != list(range(len(gens))):
            bad.append((event["canonical_event_id"], "GENERATION_GAP"))
        ids = {r["revision_id"] for r in tl["revisions"]}
        gen_of = {r["revision_id"]: r["generation"] for r in tl["revisions"]}
        for r in tl["revisions"]:
            sup = r["supersedes_revision_id"]
            if r["generation"] > 0 and (sup not in ids or gen_of[sup] >= r["generation"]):
                bad.append((event["canonical_event_id"], "BAD_SUPERSEDES"))
            if r["generation"] > 0 and not r["source_documents"]:
                bad.append((event["canonical_event_id"], "NO_DOCS"))
    # diff MFE: gen1 cambia las tres fechas, gross carried
    tl = s.timeline(MFE)
    g1 = tl["revisions"][1]
    ok = (
        g1["changes"]["date.ex_date"]["kind"] == "CHANGED"
        and g1["changes"]["date.ex_date"]["previous_values"] == ["2026-07-27"]
        and g1["changes"]["date.payment_date"]["values"] == ["2026-07-22"]
        and "amount.gross_per_share" in g1["carried_forward"]
    )
    if not ok:
        bad.append((MFE, "DIFF_ORACLE"))
    return {"measured": 1.0 if not bad else 0.0, "required": 1.0, "detail": bad}


def gate_conflict_visibility(s: Surface) -> dict:
    bad = []
    for event in s.canon["events"]:
        out = s.conflicts(event["canonical_event_id"])
        if out["conflicts"] != event["conflicts"]:
            bad.append((event["canonical_event_id"], "CONFLICT_LOST"))
        for c in event["conflicts"]:
            if len(c["values"]) < 2:
                bad.append((event["canonical_event_id"], "WINNER_CHOSEN"))
        current = s._current_state(event)
        for field, st in current.items():
            if st["status"] == "CONFLICTING" and not any(
                c["field_path"] == field for c in event["conflicts"]
            ):
                bad.append((event["canonical_event_id"], field, "SILENT_CONFLICT"))
    return {"measured": 1.0 if not bad else 0.0, "required": 1.0, "detail": bad}


def gate_provenance(s: Surface) -> dict:
    total = 0
    bad = []
    for event in s.canon["events"]:
        for fact in event["facts"]:
            total += 1
            ev = s.evidence(fact["assertion_id"])
            if ev is None or not all(
                [
                    ev["evidence_locator"],
                    ev["raw_pointer"],
                    ev["source_document"],
                    ev["source_document"].get("source_id"),
                    ev["source_document"].get("official_document_id"),
                ]
            ):
                bad.append(fact["assertion_id"])
    return {
        "measured": (total - len(bad)) / total if total else 0.0,
        "required": 1.0,
        "total_facts": total,
        "detail": bad,
    }


def gate_unsupported_honesty(s: Surface) -> dict:
    bad = []
    for event in s.canon["events"]:
        shown = s.show(event["canonical_event_id"])
        declared = {u["field_path"] for u in shown["unsupported_capabilities"]}
        for cap in s._unsupported:
            src_ids = {d["source_id"] for d in event["source_documents"]}
            if cap["source_id"] not in src_ids or event["event_type"] not in cap["event_types"]:
                continue
            for fp in cap["field_paths"]:
                present = fp in {f["field_path"] for f in event["facts"]}
                if not present and fp not in declared:
                    bad.append((event["canonical_event_id"], fp, "SILENT_ABSENCE"))
                if fp in shown["current_state"]:
                    bad.append((event["canonical_event_id"], fp, "QUARANTINED_EMITTED"))
    return {"measured": 1.0 if not bad else 0.0, "required": 1.0, "detail": bad}


def gate_fidelity(s: Surface) -> dict:
    bad = []
    for event in s.canon["events"]:
        if s.export_event(event["canonical_event_id"]) != event:
            bad.append(event["canonical_event_id"])
    return {"measured": 1.0 if not bad else 0.0, "required": 1.0, "detail": bad}


def gate_deterministic() -> dict:
    bad = []
    for path in sorted(COMMANDS.glob("*.1.stdout")):
        twin = path.with_name(path.name.replace(".1.stdout", ".2.stdout"))
        if not twin.exists() or path.read_bytes() != twin.read_bytes():
            bad.append(path.name)
    return {
        "measured": 1.0 if not bad else 0.0,
        "required": 1.0,
        "commands_compared": len(list(COMMANDS.glob("*.1.stdout"))),
        "detail": bad,
    }


# ------------------------------------------------------------------ cases

def eval_cases(s: Surface) -> dict:
    cases = {}

    shown = s.show(MFE)
    tl = s.timeline(MFE)
    cases["G3-A"] = {
        "pass": all([
            _norm(shown["current_state"]["amount.gross_per_share"]["values"][0]["value"]) == "0.22",
            shown["current_state"]["amount.gross_per_share"]["origin_generation"] == 0,
            shown["current_state"]["date.ex_date"]["values"][0]["value"] == "2026-07-20",
            shown["current_state"]["date.ex_date"]["origin_generation"] == 1,
            shown["current_state"]["date.record_date"]["values"][0]["value"] == "2026-07-21",
            shown["current_state"]["date.payment_date"]["values"][0]["value"] == "2026-07-22",
            len(tl["revisions"]) == 2,
            tl["revisions"][1]["supersedes_revision_id"] == tl["revisions"][0]["revision_id"],
            tl["revisions"][1]["changes"]["date.ex_date"]["kind"] == "CHANGED",
            "amount.gross_per_share" in tl["revisions"][1]["carried_forward"],
            not shown["conflicts"],
        ]),
    }

    shown = s.show(ALMIRALL)
    conf = s.conflicts(ALMIRALL)
    cases["G3-B"] = {
        "pass": all([
            shown["event_type"] == "CAPITAL_INCREASE",
            len(shown["source_documents"]) == 2,
            shown["current_state"]["date.announcement_date"]["status"] == "CONFLICTING",
            {v["value"] for v in shown["current_state"]["date.announcement_date"]["values"]}
            == {"2023-06-12", "2023-06-13"},
            "date.announcement_date" in conf["conflicting_current_fields"],
        ]),
    }

    found = s.search(isin="ES0105448007")
    shown = s.show(BMEG_DIV)
    canon_event = s._events[BMEG_DIV]
    cases["G3-C"] = {
        "pass": all([
            [e["canonical_event_id"] for e in found] == [BMEG_DIV],
            shown["event_type"] == "CASH_DIVIDEND",
            _norm(shown["current_state"]["amount.gross_per_share"]["values"][0]["value"]) == "0.08690661",
            _norm(shown["current_state"]["amount.net_per_share"]["values"][0]["value"]) == "0.07039435",
            shown["current_state"]["date.ex_date"]["values"][0]["value"] == "2026-07-08",
            shown["current_state"]["date.payment_date"]["values"][0]["value"] == "2026-07-10",
            s.export_event(BMEG_DIV) == canon_event,
        ]),
    }

    shown = s.show(POEX)
    unsupported = shown["unsupported_capabilities"]
    cases["G3-D"] = {
        "pass": all([
            shown["event_type"] == "CAPITAL_INCREASE",
            any(
                u["field_path"] == "amount.issue_price_per_share"
                and u["status"] == "UNSUPPORTED"
                and u["capability_status"] == "QUARANTINED_UNSUPPORTED"
                for u in unsupported
            ),
            "amount.issue_price_per_share" not in shown["current_state"],
            "instrument.isin" in s.conflicts(POEX)["conflicting_current_fields"],
        ]),
    }

    shown = s.show(SAN)
    cases["G3-E"] = {
        "pass": all([
            len(shown["source_documents"]) == 2,
            {d["source_id"] for d in shown["source_documents"]} == {"CNMV", "ISSUER_IR"},
            any(
                r["decision_basis"] == "MANUAL_ADJUDICATION"
                for r in s.canon["identity"]["relations"]
            ),
            _norm(shown["current_state"]["amount.gross_per_share"]["values"][0]["value"]) == "0.125",
            len(shown["current_state"]["amount.gross_per_share"]["values"]) == 2,
            shown["current_state"]["instrument.isin"]["values"][0]["value"] == "ESTIMACIONES",
        ]),
    }

    shown = s.show(BMEG_CAP)
    expected = {
        "amount.disbursement_per_share": "0.15",
        "amount.price": "0.15",
        "amount.rights_price": "0.0",
        "amount.effective_total": "0.0",
        "amount.liberated_percentage": "0.0",
        "amount.nominal_total": "83333.3",
    }
    cases["G3-F"] = {
        "pass": all([
            shown["event_type"] == "CAPITAL_INCREASE",
            *[
                _norm(shown["current_state"][f]["values"][0]["value"]) == v
                for f, v in expected.items()
            ],
        ]),
    }

    return cases


def main() -> int:
    surface = load_surface(CANON, POLICY)
    gates = {
        "current_state_correctness": gate_current_state(surface),
        "revision_timeline_correctness": gate_timeline(surface),
        "conflict_visibility": gate_conflict_visibility(surface),
        "provenance_navigability": gate_provenance(surface),
        "unsupported_capability_honesty": gate_unsupported_honesty(surface),
        "canonical_export_fidelity": gate_fidelity(surface),
        "deterministic_presentation": gate_deterministic(),
    }
    cases = eval_cases(surface)
    report = {
        "eval_version": "CA_ES_G3_GATES_EVAL_V1",
        "protocol": "docs/gates/g3-preregistered.json @ g3-protocol",
        "gates": {
            name: {
                "measured": g["measured"],
                "required": g["required"],
                "met": g["measured"] == g["required"],
                "detail": g.get("detail"),
            }
            for name, g in gates.items()
        },
        "cases": cases,
        "verdict": "PENDING_HUMAN_ADJUDICATION",
    }
    OUT.write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(
        {"gates": {k: v["met"] for k, v in report["gates"].items()},
         "cases": {k: v["pass"] for k, v in cases.items()}},
        indent=1,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
