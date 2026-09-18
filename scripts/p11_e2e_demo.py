"""P11 — demo e2e de aceptacion (ad-hoc, no en CI).

Leg 1: prepare + dispatch -> SPOOLED: msg+meta atomicos en outbox,
       bytes exactos, intento durable STARTED->SUCCEEDED.
Leg 2: rerun idempotente -> prepare dedup + dispatch UNCHANGED +
       replay adapter no-op.
Leg 3: delivery_id con bytes ajenos en outbox -> COLLISION
       fail-closed, nunca overwrite.
Leg 4: crash tras STARTED -> verify() recupera SPOOLED / reintenta
       sin evidencia (no double-send, no perdida).
Leg 5: receipt externo .ack -> GATEWAY_ACCEPTED +
       transport_reference; .nak -> GATEWAY_REJECTED.
Leg 6: receipts malformed/duplicados/conflictivos -> quarantine,
       estado legitimo intacto.
Leg 7: concurrencia -> mismo delivery_id desde N hilos: nunca
       corrupcion, convergencia a un unico artefacto.
Leg 8: audit replay -> send-show: send + attempts + transitions +
       receipts append-only.

Los receipts se escriben a mano como haria un consumidor externo;
en la demo NO constituyen evidencia de aceptacion SWIFT real —
solo ejercitan la maquina de estados del ledger.

Uso: PYTHONPATH=src python scripts/p11_e2e_demo.py <work_dir>
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ca_es.ops_send import (  # noqa: E402
    O_SPOOLED, S_GATEWAY_ACCEPTED, S_GATEWAY_REJECTED, S_SPOOLED,
    SCHEMA_TRANSPORT_RECEIPT, SendRequest, content_sha256_of,
    derive_delivery_id, get_send, list_send_attempts,
    list_send_receipts, list_send_transitions, prepare_sends,
    run_send_dispatch, send_status_doc)
from ca_es.ops_state import OpsState  # noqa: E402
from ca_es.transport import filespool  # noqa: E402

FIN = ("{1:F01TEST}{4:\r\n:20C::SEME//INS-0001\r\n"
       ":20C::CORP//CORP-REF-42\r\n:23G:NEWM\r\n"
       ":35B:ISIN ES0105448007\r\n-}")
SHA = content_sha256_of(FIN)
FIN2 = ("{1:F01TEST}{4:\r\n:20C::SEME//INS-0002\r\n"
        ":23G:CANC\r\n-}")
SHA2 = content_sha256_of(FIN2)


def _msg_doc(text, sha):
    return {"schema": "CA_ES_MT565_FIN_V1", "write_status": "OK",
            "fin": text, "fin_sha256": sha}


def _cfg(root):
    return {"enabled": True,
            "destinations": [{
                "destination_id": "gw-file-1", "adapter": "filespool",
                "enabled": True, "message_schemas": ["*"],
                "config": {"spool_directory": str(root / "spool")}}],
            "retry": {"max_attempts": 5, "base_delay_seconds": 0,
                      "max_delay_seconds": 0, "backoff_factor": 1.0}}


def _dispatch(state, cfg):
    conn = state.acquire_run_lock("demo-dispatch")
    try:
        doc = run_send_dispatch(state, conn, cfg)
        state.checkpoint()
        return doc
    finally:
        state.release_run_lock()


def _prepare(state, doc, iid, cfg):
    conn = state.acquire_run_lock("demo-prepare")
    try:
        res = prepare_sends(conn, doc, iid, cfg)
        state.checkpoint()
        return res
    finally:
        state.release_run_lock()


def _write_receipt(root, did, kind, doc):
    receipts = root / "spool" / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    p = receipts / f"{did}.{kind}.json"
    p.write_text(json.dumps(doc) if not isinstance(doc, str)
                 else doc, encoding="utf-8")
    return p


def _receipt(did, status, sha, **extra):
    d = {"schema": SCHEMA_TRANSPORT_RECEIPT, "delivery_id": did,
         "content_sha256": sha, "status": status,
         "gateway_reference": "SAA-GW-9001",
         "received_at": "2026-07-16T01:00:00Z", "reason": None}
    d.update(extra)
    return d


def main(work_dir: str) -> int:
    root = Path(work_dir)
    root.mkdir(parents=True, exist_ok=True)
    cfg = _cfg(root)
    state = OpsState(root / "state").init()
    did = derive_delivery_id("INS-0001", SHA, "gw-file-1")

    print("=== LEG 1: prepare + dispatch -> SPOOLED ==============")
    r = _prepare(state, _msg_doc(FIN, SHA), "INS-0001", cfg)
    d1 = _dispatch(state, cfg)
    send = None
    with state.open() as conn:
        send = get_send(conn, did)
        atts = list_send_attempts(conn, did)
    outbox = root / "spool" / "outbox"
    msg = outbox / f"{did}.msg"
    meta = json.loads(
        (outbox / f"{did}.meta.json").read_text(encoding="utf-8"))
    print("prepare:", len(r["created"]), "| dispatch:",
          d1["status"], "spooled:", d1["spooled"],
          "| send:", send["status"],
          "| msg==FIN:", msg.read_bytes() == FIN.encode("utf-8"),
          "| meta sha:", meta["content_sha256"] == SHA,
          "| attempt:", atts[0]["status"])
    assert (d1["spooled"] == 1 and send["status"] == S_SPOOLED
            and msg.read_bytes() == FIN.encode("utf-8")
            and meta["content_sha256"] == SHA
            and meta["schema"] == "CA_ES_SEND_META_V1")

    print("=== LEG 2: rerun -> dedup + UNCHANGED + replay ========")
    r2 = _prepare(state, _msg_doc(FIN, SHA), "INS-0001", cfg)
    d2 = _dispatch(state, cfg)
    from ca_es.ops_send import SendRequest as SR
    replay = filespool.deliver(
        SR(delivery_id=did, instruction_id="INS-0001",
           message_reference="INS-0001",
           message_schema="CA_ES_MT565_FIN_V1", message_text=FIN,
           content_sha256=SHA, destination_id="gw-file-1",
           adapter_type="filespool", generation=1),
        {"spool_directory": str(root / "spool")})
    n_outbox = len(list(outbox.iterdir()))
    print("prepare2 created:", len(r2["created"]),
          "existing:", len(r2["existing"]),
          "| dispatch2:", d2["status"], "attempted:", d2["attempted"],
          "| replay:", replay.outcome, replay.receipt.get("replayed"),
          "| outbox files:", n_outbox)
    assert (not r2["created"] and d2["attempted"] == 0
            and replay.outcome == O_SPOOLED
            and replay.receipt["replayed"] is True
            and n_outbox == 2)

    print("=== LEG 3: delivery_id + bytes ajenos -> COLLISION ====")
    foreign = root / "spool" / "outbox" / f"{did}.msg"
    saved = foreign.read_bytes()
    foreign.write_bytes(b"FOREIGN BYTES")
    coll = filespool.deliver(
        SR(delivery_id=did, instruction_id="INS-0001",
           message_reference="INS-0001",
           message_schema="CA_ES_MT565_FIN_V1", message_text=FIN,
           content_sha256=SHA, destination_id="gw-file-1",
           adapter_type="filespool", generation=1),
        {"spool_directory": str(root / "spool")})
    print("collision outcome:", coll.outcome, coll.error_code,
          "| file intact:", foreign.read_bytes() == b"FOREIGN BYTES")
    assert coll.outcome == "FAILED_PERMANENT"
    assert coll.error_code == "DELIVERY_ID_COLLISION"
    assert foreign.read_bytes() == b"FOREIGN BYTES"
    foreign.write_bytes(saved)  # restaura evidencia leg 1

    print("=== LEG 4: crash tras STARTED -> recovery ============")
    # 4a: attempt huerfano con side effect completo -> recovered
    conn = state.acquire_run_lock("demo-crash")
    conn.execute(
        "INSERT INTO send_attempts(attempt_id, delivery_id,"
        " attempt_number, started_at, status) VALUES"
        " ('SNA-orphan-demo', ?, 9, '2026-07-16T00:30:00Z',"
        " 'STARTED')", (did,))
    state.checkpoint()
    state.release_run_lock()
    d4 = _dispatch(state, cfg)
    with state.open() as conn:
        send4 = get_send(conn, did)
    print("orphan recovered:", d4["orphan_attempts_recovered"],
          "| send:", send4["status"])
    assert d4["orphan_attempts_recovered"] == 1
    assert send4["status"] == S_SPOOLED

    # 4b: orphan sin evidencia (nuevo send, sin outbox) -> reintenta
    did2 = derive_delivery_id("INS-0002", SHA2, "gw-file-1")
    _prepare(state, _msg_doc(FIN2, SHA2), "INS-0002", cfg)
    conn = state.acquire_run_lock("demo-crash2")
    conn.execute(
        "INSERT INTO send_attempts(attempt_id, delivery_id,"
        " attempt_number, started_at, status) VALUES"
        " ('SNA-orphan-demo2', ?, 1, '2026-07-16T00:31:00Z',"
        " 'STARTED')", (did2,))
    state.checkpoint()
    state.release_run_lock()
    d4b = _dispatch(state, cfg)
    with state.open() as conn:
        send4b = get_send(conn, did2)
    print("orphan no-evidence: dispatch:", d4b["status"],
          "spooled:", d4b["spooled"], "| send2:", send4b["status"])
    assert send4b["status"] == S_SPOOLED

    print("=== LEG 5: receipt externo -> GATEWAY_* ===============")
    _write_receipt(root, did, "ack", _receipt(did, "ACCEPTED", SHA))
    _write_receipt(root, did2, "nak",
                   _receipt(did2, "REJECTED", SHA2,
                            reason="CHECKSUM_MISMATCH"))
    d5 = _dispatch(state, cfg)
    with state.open() as conn:
        s1 = get_send(conn, did)
        s2 = get_send(conn, did2)
    print("ingested:", d5["receipts_ingested"],
          "| send1:", s1["status"], "tref:",
          s1["transport_reference"],
          "| send2:", s2["status"])
    assert (s1["status"] == S_GATEWAY_ACCEPTED
            and s1["transport_reference"] == "SAA-GW-9001"
            and s2["status"] == S_GATEWAY_REJECTED)
    processed = root / "spool" / "receipts" / "processed"
    assert (processed / f"{did}.ack.json").exists()
    assert (processed / f"{did2}.nak.json").exists()

    print("=== LEG 6: malformed/conflicting -> quarantine ========")
    _write_receipt(root, did2, "ack", "{not json")
    _write_receipt(root, did, "ack",
                   _receipt(did, "ACCEPTED", SHA,
                            gateway_reference="OTHER-REF"))
    did3 = "SND-" + "cd" * 32
    _write_receipt(root, did3, "ack",
                   _receipt(did3, "ACCEPTED", "0" * 64))
    d6 = _dispatch(state, cfg)
    quarantine = root / "spool" / "quarantine"
    with state.open() as conn:
        s1b = get_send(conn, did)
        status_doc = send_status_doc(state, conn, cfg)
    print("quarantined:", d6["receipts_quarantined"],
          "| files:", len(list(quarantine.iterdir())),
          "| send1 sigue:", s1b["status"], "tref:",
          s1b["transport_reference"],
          "| status doc:", status_doc["status"],
          "quarantined:", status_doc["quarantined_receipts"])
    assert d6["receipts_quarantined"] == 3
    # el receipt legitimo de leg 5 no se contamina
    assert (s1b["status"] == S_GATEWAY_ACCEPTED
            and s1b["transport_reference"] == "SAA-GW-9001")

    print("=== LEG 7: concurrencia -> converge sin corrupcion ====")
    did4 = derive_delivery_id("INS-0001", SHA, "gw-conc")
    req = SendRequest(
        delivery_id=did4, instruction_id="INS-0001",
        message_reference="INS-0001",
        message_schema="CA_ES_MT565_FIN_V1", message_text=FIN,
        content_sha256=SHA, destination_id="gw-conc",
        adapter_type="filespool", generation=1)
    conc_cfg = {"spool_directory": str(root / "spool-conc")}
    outcomes, errs = [], []

    def work():
        try:
            outcomes.append(filespool.deliver(req, conc_cfg).outcome)
        except Exception as exc:  # noqa: BLE001
            errs.append(exc)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for _ in range(20):
        if filespool.deliver(req, conc_cfg).outcome == O_SPOOLED:
            break
    msg4 = root / "spool-conc" / "outbox" / f"{did4}.msg"
    names4 = sorted(
        p.name for p in (root / "spool-conc" / "outbox").iterdir())
    print("outcomes:", sorted(set(outcomes)), "| errors:", len(errs),
          "| verdict:", filespool.verify(req, conc_cfg),
          "| bytes ok:", msg4.read_bytes() == FIN.encode("utf-8"))
    assert not errs
    assert all(o in (O_SPOOLED, "FAILED_RETRYABLE", "UNKNOWN")
               for o in outcomes)
    assert filespool.verify(req, conc_cfg) == "SPOOLED"
    assert msg4.read_bytes() == FIN.encode("utf-8")
    assert names4 == [f"{did4}.meta.json", f"{did4}.msg"]

    print("=== LEG 8: audit replay (send-show) ====================")
    with state.open() as conn:
        s = get_send(conn, did)
        atts = list_send_attempts(conn, did)
        trs = list_send_transitions(conn, did)
        recs = list_send_receipts(conn, did)
    print("send:", s["status"], "| attempts:", len(atts),
          "| transitions:", len(trs), "| receipts:", len(recs))
    for tr in trs:
        print("   ", tr["at"], tr["from_status"], "->",
              tr["to_status"], f"({tr['actor']})", tr["note"])
    for rc in recs:
        print("   receipt:", rc["status"], "src:", rc["source_path"],
              "q:", rc["quarantine_reason"])
    assert len(trs) >= 3
    assert len(recs) >= 1
    # append-only: timestamps monotonos por insercion
    assert [t["id"] for t in trs] == sorted(t["id"] for t in trs)

    print("\nP11 demo: todos los legs OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1
                          else "build/p11-demo"))
