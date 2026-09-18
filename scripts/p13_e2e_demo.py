"""P13 — demo e2e de aceptacion del custody feed vertical
(ad-hoc, no en CI).

Parseo REAL via adapter JVM/Prowide (fatJar requerido; sin jar ->
SKIP explicito, nunca silencio). Fixtures: los sinteticos del
propio adapter (adapters/iso-adapter-jvm/src/test/resources).

Legs:

  S1: MT535 2 paginas -> custody inbox -> snapshot COMPLETE ->
      CA_ES_POSITIONS_V1 -> entitlement real sobre canon demo
      (evento CASH_DIVIDEND ES0105448007, 12500 unidades).
  S2: re-drop de las mismas paginas -> EXACT_DUPLICATE; rebuild ->
      mismo snapshot_id (dedup semantico), cero snapshots nuevos.
  S3: statement nuevo (misma cuenta, otra fecha/cantidad) ->
      snapshot nuevo -> positions actualizadas; el anterior queda
      intacto en el store.
  S4: statement incompleto (solo pagina 1 con marcador MORE) ->
      PARTIAL -> no proyecta positions.
  S5: camt.054 -> cash observation -> binding por EndToEndId
      explicito -> CA_ES_CASH_MOVEMENTS_V2 -> P3 reconcile real.
  S6: entry sin referencia CA -> NO_MATCH sin adivinar; entry sin
      ninguna ref -> INSUFFICIENT_IDENTITY.
  S7: positions esperadas vs statement custodio divergente ->
      CA_ES_POSITION_RECON_V1 -> caso P3.5.

Uso: python scripts/p13_e2e_demo.py <work_dir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ca_es import custody_bind, custody_recon, ops_custody  # noqa: E402
from ca_es.ops_state import OpsState  # noqa: E402
from ca_es.swift_mt import default_adapter_jar  # noqa: E402

RES = REPO / "adapters" / "iso-adapter-jvm" / "src" / "test" / "resources"
CANON = REPO / "g3" / "input" / "canon.json"
EVENT_ID = "6881d24a-ef46-5053-80ce-1743a1792f8b"  # CASH_DIVIDEND ES0105448007

PROFILE = {
    "schema": "CA_ES_CUSTODY_PROFILE_V1",
    "profile_id": "demo-custodian",
    "account_map": {"SAFE-ES-001": "ACC-ES-1",
                    "ES9121000418450200051332": "ACC-ES-1"},
    "reference_map": {"CA-EVT-001": {"event_id": EVENT_ID}},
}

_results: list[tuple[str, str]] = []


def leg(name: str, status: str, detail: str = "") -> None:
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    _results.append((name, status))


def drop(inbox: Path, name: str, payload: bytes) -> None:
    t = inbox / "incoming" / name
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_bytes(payload)


def latest_snapshot(index: dict, account_raw: str) -> dict | None:
    cands = [s for s in index["statements"]
             if s["completeness"] == "COMPLETE"
             and s.get("account_id_raw") == account_raw]
    if not cands:
        return None
    return sorted(cands, key=lambda s: s["statement_as_of"])[-1]


def _facts_for(state, conn, identifier: str) -> dict:
    for _sha, doc in ops_custody._facts_docs(state, conn):
        if doc.get("message_identifier") == identifier:
            return doc
    raise AssertionError(f"facts {identifier} no encontrados")


def main() -> int:
    work = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("p13_demo_out")
    work.mkdir(parents=True, exist_ok=True)
    jar = default_adapter_jar()
    if not jar or not Path(jar).is_file():
        print("SKIP — iso-adapter fatJar no construido "
              "(cd adapters/iso-adapter-jvm && ./gradlew fatJar)")
        return 0

    state = OpsState(work / "state").init()
    conn = state.acquire_run_lock("p13-demo")
    inbox = work / "custody_inbox"
    now = "2026-05-06T09:00:00Z"

    # ---------- S1: positions completas -> entitlement ----------
    print("S1 — MT535 multipagina -> positions -> entitlement")
    drop(inbox, "mt535-p1.fin", (RES / "mt535-page1.fin").read_bytes())
    drop(inbox, "mt535-p2.fin", (RES / "mt535-page2.fin").read_bytes())
    r1 = ops_custody.process_custody_inbox(state, conn, inbox, now=now)
    assert all(m["processing_status"] == "PROCESSED"
               for m in r1["messages"]), r1
    index = ops_custody.build_custody_index(state, conn, profile=PROFILE,
                                            now=now)
    snap = latest_snapshot(index, "SAFE-ES-001")
    assert snap and snap["completeness"] == "COMPLETE", index["statements"]
    pdoc = state.get_artifact(
        index["positions_docs"][0]["artifact_sha256"])
    pos_path = work / "positions.json"
    pos_path.write_text(json.dumps(pdoc, indent=1), encoding="utf-8")
    leg("S1 custody->positions", "PASS",
        f"{len(pdoc['positions'])} posiciones, "
        f"snapshot {snap['snapshot_id']}")

    import argparse
    from ca_es.cli import cmd_entitlement  # proyeccion real P2
    rc = cmd_entitlement(argparse.Namespace(
        canon=str(CANON), event=EVENT_ID, positions=str(pos_path),
        repo_root=None, policy=None))
    leg("S1 entitlement pipeline", "PASS" if rc == 0 else "FAIL",
        f"exit={rc}")

    # ---------- S2: replay -> dedup ----------
    print("S2 — replay exacto")
    n_snaps_before = len(index["statements"])
    drop(inbox, "mt535-p1b.fin", (RES / "mt535-page1.fin").read_bytes())
    drop(inbox, "mt535-p2b.fin", (RES / "mt535-page2.fin").read_bytes())
    r2 = ops_custody.process_custody_inbox(state, conn, inbox, now=now)
    assert all(m["processing_status"] == "EXACT_DUPLICATE"
               for m in r2["messages"]), r2
    index2 = ops_custody.build_custody_index(state, conn, profile=PROFILE,
                                             now=now)
    snap2 = latest_snapshot(index2, "SAFE-ES-001")
    ok = (snap2["snapshot_id"] == snap["snapshot_id"]
          and len(index2["statements"]) == n_snaps_before)
    leg("S2 exact+semantic dedup", "PASS" if ok else "FAIL",
        f"EXACT_DUPLICATE x{len(r2['messages'])}, snapshot estable")

    # ---------- S3: statement nuevo -> nuevo snapshot ----------
    print("S3 — statement nuevo (cantidad cambiada)")
    changed = (RES / "mt535-complete.fin").read_text(encoding="utf-8")
    changed = (changed.replace("STMT-2026-002", "STMT-2026-003")
               .replace("20260504", "20260505")
               .replace("/12500,", "/13000,"))
    drop(inbox, "mt535-new.fin", changed.encode("utf-8"))
    ops_custody.process_custody_inbox(state, conn, inbox, now=now)
    index3 = ops_custody.build_custody_index(state, conn, profile=PROFILE,
                                             now=now)
    snap3 = latest_snapshot(index3, "SAFE-ES-001")
    pdoc3 = state.get_artifact(
        [d for d in index3["positions_docs"]
         if d["as_of"] == snap3["statement_as_of"]][0]
        ["artifact_sha256"])
    qtys = {p["isin"]: p["quantity"] for p in pdoc3["positions"]}
    ok = (snap3["snapshot_id"] != snap["snapshot_id"]
          and qtys.get("ES0105448007") == "13000")
    leg("S3 nuevo snapshot, historia intacta", "PASS" if ok else "FAIL",
        f"ES0105448007={qtys.get('ES0105448007')} "
        f"(statements={len(index3['statements'])})")

    # ---------- S4: statement incompleto ----------
    print("S4 — pagina 1 sin continuacion -> PARTIAL")
    partial = (RES / "mt535-page1.fin").read_text(encoding="utf-8")
    partial = partial.replace("STMT-2026-001", "STMT-2026-PART")
    drop(inbox, "mt535-part.fin", partial.encode("utf-8"))
    ops_custody.process_custody_inbox(state, conn, inbox, now=now)
    index4 = ops_custody.build_custody_index(state, conn, profile=PROFILE,
                                             now=now)
    part = [s for s in index4["statements"]
            if s.get("statement_reference") == "STMT-2026-PART"]
    latest = latest_snapshot(index4, "SAFE-ES-001")
    ok = (part and part[0]["completeness"] == "PARTIAL"
          and latest["snapshot_id"] == snap3["snapshot_id"])
    leg("S4 PARTIAL no sustituye positions", "PASS" if ok else "FAIL",
        part[0]["completeness"] if part else "no snapshot")

    # ---------- S5: camt.054 -> binding -> P3 reconcile ----------
    print("S5 — camt.054 -> movement -> P3")
    drop(inbox, "camt054.xml", (RES / "camt054-00113.xml").read_bytes())
    ops_custody.process_custody_inbox(state, conn, inbox, now=now)
    index5 = ops_custody.build_custody_index(state, conn, profile=PROFILE,
                                             now=now)
    mov_doc = state.get_artifact(
        index5["movements_docs"][0]["artifact_sha256"]) \
        if index5["movements_docs"] else None
    movs = mov_doc["movements"] if mov_doc else []
    bound = [m for m in movs if m["event_id"] == EVENT_ID]
    ok = len(bound) == 1 and bound[0]["amount"] == "1562.50"
    leg("S5 binding explicito", "PASS" if ok else "FAIL",
        f"bound={len(bound)} "
        f"amount={bound[0]['amount'] if bound else '-'}")

    if bound:
        mov_path = work / "movements.json"
        mov_path.write_text(json.dumps(mov_doc, indent=1),
                            encoding="utf-8")
        from ca_es.cli import cmd_reconcile  # P3 real
        rc = cmd_reconcile(argparse.Namespace(
            canon=str(CANON), event=EVENT_ID, positions=str(pos_path),
            cash=str(mov_path), entitlements=None, recon=None,
            repo_root=None, policy=None))
        leg("S5 P3 reconcile", "PASS" if rc == 0 else "FAIL", f"exit={rc}")

    # ---------- S6: unbound / insufficient ----------
    print("S6 — sin referencia -> no guessing")
    obs = ops_custody.cash_observation(
        _facts_for(state, conn, "camt.054.001.13"), now=now)
    binding = custody_bind.bind_cash(obs, {}, now=now)
    e2 = [b for b in binding["bindings"] if b["entry_id"] == "NTRY-002"]
    no_ref = dict(obs)
    no_ref["entries"] = [dict(obs["entries"][0],
                              account_servicer_reference=None,
                              customer_reference=None,
                              transaction_reference=None,
                              structured_details=None)]
    b2 = custody_bind.bind_cash(no_ref, {}, now=now)
    ok = (e2 and e2[0]["status"] == "NO_MATCH"
          and b2["bindings"][0]["status"] == "INSUFFICIENT_IDENTITY"
          and not custody_bind.movements_doc(binding)["movements"])
    leg("S6 NO_MATCH + INSUFFICIENT_IDENTITY", "PASS" if ok else "FAIL",
        f"{e2[0]['status'] if e2 else '-'} / "
        f"{b2['bindings'][0]['status']}")

    # ---------- S7: position recon -> caso ----------
    print("S7 — custody mismatch -> recon -> caso")
    expected = {"schema": "CA_ES_POSITIONS_V1", "positions": [
        {"account_id": "ACC-ES-1", "isin": "ES0105448007",
         "quantity": "9999"}]}
    recon = custody_recon.position_recon(expected, pdoc3, now=now)
    mism = [x for x in recon["items"]
            if x["status"] == "POSITION_QUANTITY_MISMATCH"]
    from ca_es.exceptions import build_cases_doc
    cases = build_cases_doc(recon, now=now)
    ok = mism and cases["cases"]
    leg("S7 recon + caso estable", "PASS" if ok else "FAIL",
        f"{mism[0]['status'] if mism else '-'} -> "
        f"{len(cases['cases'])} caso(s)")

    state.release_run_lock()
    failed = [n for n, s in _results if s == "FAIL"]
    skipped = [n for n, s in _results if s == "SKIP"]
    print(f"\n{len(_results) - len(failed) - len(skipped)} PASS "
          f"/ {len(skipped)} SKIP / {len(failed)} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
