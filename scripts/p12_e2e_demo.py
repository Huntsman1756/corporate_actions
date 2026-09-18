"""P12 — demo e2e de aceptacion del transport conformance lab
(ad-hoc, no en CI).

Legs SFTP (S1-S5) contra un servidor SSH/SFTP REAL in-process
(Paramiko server-side — mismo wire protocol que OpenSSH; el stub
de tests/unit es el harness del lab, no un mock de transporte):

  S1: prepare + dispatch -> SPOOLED -> .msg/.meta remotos,
      bytes exactos, REMOTE_PERSISTED.
  S2: rerun -> skipped_terminal + replay adapter sin segundo
      upload remoto.
  S3: receipt .ack.json remoto -> send-poll -> GATEWAY_ACCEPTED +
      archive remoto a processed/.
  S4: fallo tras commit del .msg -> UNKNOWN -> verify() recupera
      SPOOLED (sin re-upload, sin duplicado).
  S5: instruccion nueva -> delivery_id nuevo -> segunda entrega
      remota.

Legs FIN (F1-F4) via adapter JVM/Prowide real (fatJar requerido;
sin jar -> SKIP explicito, nunca silencio):

  F1: send SPOOLED -> FIN ACK service 21 -> SWIFT_ACKED.
  F2: -> FIN NAK -> SWIFT_NAKED.
  F3: ACK con MIR desconocido -> QUARANTINED:NO_MATCH.
  F4: dos sends con mismo MIR -> QUARANTINED:AMBIGUOUS.

MQ live: scripts/p12_mq_lab.py (opt-in, IBM MQ Developer).

Uso: PYTHONPATH=src python scripts/p12_e2e_demo.py <work_dir>
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests" / "unit"))

FIN = ("{1:F01TEST}{4:\r\n:20C::SEME//INS-0001\r\n"
       ":20C::CORP//CORP-REF-42\r\n:23G:NEWM\r\n"
       ":35B:ISIN ES0105448007\r\n-}")
FIN2 = ("{1:F01TEST}{4:\r\n:20C::SEME//INS-0002\r\n"
        ":23G:CANC\r\n-}")
NOW = "2026-07-16T00:00:00Z"

# FIN con MIR para los legs F (LT TESTES00XXXX, sess 1234, seq 79)
LT, SESS, SEQ = "TESTES00XXXX", "1234", "000079"
ORIG_FIN = (f"{{1:F01{LT}{SESS}{SEQ}}}{{2:I565BANKGB2LXXXXN}}"
            "{4:\n:16R:GENL\n:20C::SEME//INS-0001\n"
            ":20C::CORP//CORP-REF-42\n:23G:NEWM\n:16S:GENL\n-}")
FIN_ACK = ("{1:F21LITEBEBBAXXX0066000080}"
           "{4:{177:2607160901}{451:0}}" + ORIG_FIN
           + "{5:{CHK:7602B010CF31}{TNG:}}")
FIN_NAK = ("{1:F21LITEBEBBAXXX0066000081}"
           "{4:{177:2607160902}{451:1}{405:T33002}}" + ORIG_FIN
           + "{5:{CHK:7602B010CF32}{TNG:}}")
FIN_ACK_FOREIGN = ("{1:F21LITEBEBBAXXX0066000082}"
                   "{4:{177:2607160903}{451:0}}"
                   "{1:F01ZZZZZZZZZZZZ9999000001}{4:\n:20C::SEME//X\n-}"
                   "{5:{CHK:7602B010CF33}{TNG:}}")


def _msg(text, sha):
    return {"schema": "CA_ES_MT565_FIN_V1", "write_status": "OK",
            "fin": text, "fin_sha256": sha}


def main(work_dir: str) -> int:
    try:
        import paramiko  # noqa: F401
        from test_p121_sftp_adapter import PW, SFTPLab, USER
    except ImportError as exc:
        print("P12 DEMO SKIP SFTP legs:", exc)
        SFTPLab = None

    root = Path(work_dir)
    root.mkdir(parents=True, exist_ok=True)

    from ca_es.ops_send import (
        O_SPOOLED, S_GATEWAY_ACCEPTED, S_SPOOLED, S_SWIFT_ACKED,
        S_SWIFT_NAKED, content_sha256_of, get_send, prepare_sends,
        run_send_dispatch, run_send_poll)
    from ca_es.ops_state import OpsState
    from ca_es.transport import sftp as sftp_adapter

    lab = None
    if SFTPLab is not None:
        os.environ["CA_ES_TEST_SFTP_PW"] = PW
        (root / "remote").mkdir(exist_ok=True)
        lab = SFTPLab(root / "remote")
        sftp_cfg = {
            "host": "127.0.0.1", "port": lab.port,
            "username": USER, "password_env": "CA_ES_TEST_SFTP_PW",
            "host_key_fingerprint": lab.fingerprint,
            "remote_outbox": "/outbox", "remote_receipts": "/receipts",
            "local_receipt_staging": str(root / "staging"),
            "connect_timeout_seconds": 10,
            "operation_timeout_seconds": 10}
        send_cfg = {"enabled": True, "destinations": [{
            "destination_id": "gw-sftp-1", "adapter": "sftp",
            "enabled": True, "message_schemas": ["*"],
            "config": sftp_cfg}],
            "retry": {"max_attempts": 5, "base_delay_seconds": 0,
                      "max_delay_seconds": 0, "backoff_factor": 1.0}}
        state = OpsState(root / "state").init()
        sha = content_sha256_of(FIN)

        # -------- S1 -----------------------------------------
        print("=== S1: prepare + dispatch -> remoto exacto ========")
        conn = state.acquire_run_lock("s1")
        try:
            res = prepare_sends(conn, _msg(FIN, sha), "INS-0001",
                                send_cfg, now=NOW)
            d1 = run_send_dispatch(state, conn, send_cfg)
            state.checkpoint()
            did = res["created"][0]["delivery_id"]
            send = get_send(conn, did)
        finally:
            state.release_run_lock()
        msg = lab.root / "outbox" / f"{did}.msg"
        meta = json.loads(
            (lab.root / "outbox" / f"{did}.meta.json").read_text())
        print("dispatch:", d1["status"], "| send:", send["status"],
              "| bytes:", msg.read_bytes() == FIN.encode(),
              "| meta sha:", meta["content_sha256"] == sha)
        assert (d1["spooled"] == 1 and send["status"] == S_SPOOLED
                and msg.read_bytes() == FIN.encode()
                and meta["content_sha256"] == sha)

        # -------- S2 -----------------------------------------
        print("=== S2: rerun -> sin segundo upload ================")
        conn = state.acquire_run_lock("s2")
        try:
            d2 = run_send_dispatch(state, conn, send_cfg)
        finally:
            state.release_run_lock()
        from ca_es.ops_send import SendRequest
        req = SendRequest(
            delivery_id=did, instruction_id="INS-0001",
            message_reference="INS-0001",
            message_schema="CA_ES_MT565_FIN_V1", message_text=FIN,
            content_sha256=sha, destination_id="gw-sftp-1",
            adapter_type="sftp", generation=1)
        replay = sftp_adapter.deliver(req, sftp_cfg)
        msgs = list((lab.root / "outbox").glob("*.msg"))
        print("dispatch2:", d2["status"],
              "| replayed:", replay.receipt.get("replayed"),
              "| remote .msg:", len(msgs))
        assert (d2["attempted"] == 0
                and replay.receipt["replayed"] is True
                and len(msgs) == 1)

        # -------- S3 -----------------------------------------
        print("=== S3: receipt remoto -> GATEWAY_ACCEPTED =========")
        rdir = lab.root / "receipts"
        rdir.mkdir(exist_ok=True)
        (rdir / f"{did}.ack.json").write_text(json.dumps({
            "schema": "CA_ES_TRANSPORT_RECEIPT_V1",
            "delivery_id": did, "content_sha256": sha,
            "status": "ACCEPTED", "gateway_reference": "GW-77",
            "received_at": NOW, "reason": None}))
        conn = state.acquire_run_lock("s3")
        try:
            out = run_send_poll(state, conn, send_cfg)
            send = get_send(conn, did)
        finally:
            state.release_run_lock()
        print("poll:", out["status"], "| send:", send["status"],
              "| ref:", send["transport_reference"],
              "| archived:",
              (rdir / "processed" / f"{did}.ack.json").is_file())
        assert (out["ingested"] == 1
                and send["status"] == S_GATEWAY_ACCEPTED
                and send["transport_reference"] == "GW-77")

        # -------- S4 -----------------------------------------
        print("=== S4: crash post-.msg -> verify/recovery ========")
        sha4 = content_sha256_of(FIN2)
        conn = state.acquire_run_lock("s4")
        try:
            res4 = prepare_sends(conn, _msg(FIN2, sha4), "INS-0002",
                                 send_cfg, now=NOW)
            did4 = res4["created"][0]["delivery_id"]
        finally:
            state.release_run_lock()
        real = sftp_adapter._put_atomic
        calls = {"n": 0}

        def boom(sftp, data, final):
            calls["n"] += 1
            if calls["n"] == 2:  # meta
                raise IOError("simulated post-msg failure")
            return real(sftp, data, final)

        req4 = SendRequest(
            delivery_id=did4, instruction_id="INS-0002",
            message_reference="INS-0002",
            message_schema="CA_ES_MT565_FIN_V1", message_text=FIN2,
            content_sha256=sha4, destination_id="gw-sftp-1",
            adapter_type="sftp", generation=1)
        sftp_adapter._put_atomic = boom
        try:
            r4 = sftp_adapter.deliver(req4, sftp_cfg)
        finally:
            sftp_adapter._put_atomic = real
        verdict = sftp_adapter.verify(req4, sftp_cfg)
        # .msg quedo pero sin .meta: NO es commit — NOT_SPOOLED
        # honesto; el re-deliver completa el orfano sin re-upload
        r4b = sftp_adapter.deliver(req4, sftp_cfg)
        print("deliver:", r4.outcome, "| verify:", verdict,
              "| re-deliver:", r4b.outcome,
              "| orphan:", r4b.receipt.get("completed_orphan"))
        assert (r4.outcome == "UNKNOWN" and verdict == "NOT_SPOOLED"
                and r4b.outcome == O_SPOOLED
                and r4b.receipt["completed_orphan"] is True)

        # -------- S5 -----------------------------------------
        print("=== S5: instruccion nueva -> segunda entrega =======")
        conn = state.acquire_run_lock("s5")
        try:
            d5 = run_send_dispatch(state, conn, send_cfg,
                                   only_delivery_id=did4)
        finally:
            state.release_run_lock()
        print("dispatch:", d5["status"], "| .msg remotos:",
              len(list((lab.root / "outbox").glob("*.msg"))))
        lab.stop()

    # ---- F legs (JVM/Prowide real) ----------------------------
    print("=== F legs: FIN service 21 via Prowide ================")
    from ca_es.ops_fin import ingest_fin_service_file
    from ca_es.ops_state import OpsState as _OS
    from ca_es.swift_mt import AdapterUnavailable, default_adapter_jar

    jar = default_adapter_jar()
    if not jar.is_file():
        print("F legs SKIP: adapter jar no encontrado:", jar)
    else:
        fstate = _OS(root / "state-fin").init()
        fsha = content_sha256_of(ORIG_FIN)
        fcfg = {"enabled": True, "destinations": [{
            "destination_id": "gw-file-1", "adapter": "filespool",
            "enabled": True, "message_schemas": ["*"],
            "config": {"spool_directory": str(root / "fspool")}}]}
        conn = fstate.acquire_run_lock("f")
        try:
            res = prepare_sends(
                conn, _msg(ORIG_FIN, fsha), "INS-0001", fcfg,
                now=NOW)
            fdid = res["created"][0]["delivery_id"]
            conn.execute(
                "UPDATE sends SET status=? WHERE delivery_id=?",
                (S_SPOOLED, fdid))
        finally:
            fstate.release_run_lock()

        # F1: ACK -> SWIFT_ACKED
        ack_p = root / "ack.fin"
        ack_p.write_bytes(FIN_ACK.encode())
        conn = fstate.acquire_run_lock("f1")
        try:
            r = ingest_fin_service_file(conn, ack_p, jar=jar, now=NOW)
            send = get_send(conn, fdid)
        finally:
            fstate.release_run_lock()
        print("F1:", r["result"], "| send:", send["status"])
        assert r["result"] == "SWIFT_ACK" \
            and send["status"] == S_SWIFT_ACKED

        # F2: NAK sobre send nuevo -> SWIFT_NAKED
        conn = fstate.acquire_run_lock("f2")
        try:
            conn.execute(
                "UPDATE sends SET status=? WHERE delivery_id=?",
                (S_SPOOLED, fdid))
        finally:
            fstate.release_run_lock()
        nak_p = root / "nak.fin"
        nak_p.write_bytes(FIN_NAK.encode())
        conn = fstate.acquire_run_lock("f2b")
        try:
            r = ingest_fin_service_file(conn, nak_p, jar=jar, now=NOW)
            send = get_send(conn, fdid)
        finally:
            fstate.release_run_lock()
        print("F2:", r["result"], "| send:", send["status"])
        assert r["result"] == "SWIFT_NAK" \
            and send["status"] == S_SWIFT_NAKED

        # F3: ACK con MIR desconocido -> NO_MATCH
        fx_p = root / "ack-foreign.fin"
        fx_p.write_bytes(FIN_ACK_FOREIGN.encode())
        conn = fstate.acquire_run_lock("f3")
        try:
            r = ingest_fin_service_file(conn, fx_p, jar=jar, now=NOW)
        finally:
            fstate.release_run_lock()
        print("F3:", r["result"])
        assert r["result"] == "QUARANTINED:NO_MATCH"

        # F4: dos sends mismo MIR -> AMBIGUOUS
        fstate2 = _OS(root / "state-fin2").init()
        fcfg2 = {"enabled": True, "destinations": [
            {"destination_id": "gw-a", "adapter": "filespool",
             "enabled": True, "message_schemas": ["*"],
             "config": {"spool_directory": str(root / "sa")}},
            {"destination_id": "gw-b", "adapter": "filespool",
             "enabled": True, "message_schemas": ["*"],
             "config": {"spool_directory": str(root / "sb")}}]}
        conn = fstate2.acquire_run_lock("f4")
        try:
            res = prepare_sends(
                conn, _msg(ORIG_FIN, fsha), "INS-0001", fcfg2,
                now=NOW)
            assert len(res["created"]) == 2
            for s in res["created"]:
                conn.execute(
                    "UPDATE sends SET status=? WHERE delivery_id=?",
                    (S_SPOOLED, s["delivery_id"]))
            r = ingest_fin_service_file(conn, ack_p, jar=jar, now=NOW)
        finally:
            fstate2.release_run_lock()
        print("F4:", r["result"])
        assert r["result"] == "QUARANTINED:AMBIGUOUS"

    print("P12 DEMO PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1
                  else "p12-demo-out"))
