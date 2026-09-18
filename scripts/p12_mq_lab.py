"""P12.4 — laboratorio IBM MQ real (OPT-IN, local, nunca CI).

Requisitos previos del OPERADOR (nada se vendorea ni se instala
por este script):

1. IBM MQ Advanced for Developers en contenedor — imagen
   documentada upstream `icr.io/ibm-messaging/mq`
   (repo ibm-messaging/mq-container). El producto dentro de la
   imagen esta bajo licencia IBM propia: NO redistribuible y
   NUNCA requisito de CI publica. El operador acepta la licencia
   el mismo arrancando el contenedor con `-e LICENSE=accept` y
   exportando LICENSE=accept aqui como acuse explicito:

       docker run -e LICENSE=accept -e MQ_QMGR_NAME=QM1 \
           -p 1414:1414 -p 9443:9443 -d icr.io/ibm-messaging/mq:latest

   (la imagen developer crea QM1, canal DEV.APP.SVRCONN,
   app/appuser/passw0rd y DEV.QUEUE.1)

2. Cliente IBM MQ + binding Python `ibmmq`
   (`pip install ca-es[mq]`, requiere IBM MQ C client instalado).

3. Variables de entorno:
       P12_MQ_LIVE=1            opt-in explicito (sin el: SKIP)
       LICENSE=accept           acuse del operador de la licencia IBM
       P12_MQ_QM=QM1            queue manager
       P12_MQ_CHANNEL=DEV.APP.SVRCONN
       P12_MQ_CONN=localhost(1414)
       P12_MQ_QUEUE=DEV.QUEUE.1
       P12_MQ_USER=app          (opcional; usuario MQ, no persistido)
       P12_MQ_PASSWORD=...      (opcional; solo env, nunca en logs)

Legs:
  M1: deliver() -> MQPUT commit -> verify() SPOOLED ->
      consumidor INDEPENDIENTE lee bytes exactos -> sha identico.
  M2: connection_name inalcanzable -> outcome conservador
      (FAILED_RETRYABLE/FAILED_PERMANENT/UNKNOWN) — nunca exito.
  M3: segundo deliver() mismo delivery_id -> replay via CorrelId
      browse -> la cola sigue teniendo UN solo mensaje con ese
      CorrelId (sin duplicado).
  M4: verify() tras consumo destructivo -> NOT_SPOOLED honesto.

Uso: PYTHONPATH=src P12_MQ_LIVE=1 LICENSE=accept \
     python scripts/p12_mq_lab.py
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

FIN = ("{1:F01TEST}{4:\r\n:20C::SEME//INS-0001\r\n"
       ":20C::CORP//CORP-REF-42\r\n:23G:NEWM\r\n"
       ":35B:ISIN ES0105448007\r\n-}")


def _skip(msg: str) -> int:
    print("P12_MQ_LAB SKIPPED:", msg)
    return 0


def main() -> int:
    if os.environ.get("P12_MQ_LIVE") != "1":
        return _skip("P12_MQ_LIVE=1 no definido — lab opt-in local.")
    if os.environ.get("LICENSE") != "accept":
        return _skip(
            "LICENSE=accept no definido — el operador debe aceptar "
            "la licencia IBM MQ Advanced for Developers el mismo.")

    try:
        import ibmmq
    except ImportError:
        return _skip("ibmmq no instalado (pip install ca-es[mq] + "
                     "IBM MQ C client).")

    from ca_es.ops_send import (  # noqa: E402
        O_SPOOLED, SendRequest, content_sha256_of)
    from ca_es.transport import mq as mq_adapter  # noqa: E402

    cfg = {
        "queue_manager": os.environ.get("P12_MQ_QM", "QM1"),
        "channel": os.environ.get("P12_MQ_CHANNEL", "DEV.APP.SVRCONN"),
        "connection_name": os.environ.get("P12_MQ_CONN",
                                          "localhost(1414)"),
        "request_queue": os.environ.get("P12_MQ_QUEUE", "DEV.QUEUE.1"),
    }
    if os.environ.get("P12_MQ_USER"):
        cfg["username_env"] = "P12_MQ_USER"
        if os.environ.get("P12_MQ_PASSWORD"):
            cfg["password_env"] = "P12_MQ_PASSWORD"

    sha = content_sha256_of(FIN)
    delivery_id = "P12MQLAB-" + sha[:16]
    req = SendRequest(
        delivery_id=delivery_id,
        instruction_id="INS-0001",
        message_reference="INS-0001",
        message_schema="CA_ES_MT565_FIN_V1",
        message_text=FIN,
        content_sha256=sha,
        destination_id="gw-mq-lab",
        adapter_type="mq",
        generation=1)
    correl = mq_adapter._correl_id(delivery_id)

    def _connect():
        return ibmmq.QueueManager.connect_with_options(
            cfg["queue_manager"], channel=cfg["channel"],
            conn_info=cfg["connection_name"],
            user=os.environ.get("P12_MQ_USER", ""),
            password=os.environ.get("P12_MQ_PASSWORD", ""))

    def _browse_count() -> int:
        """Cuenta mensajes con nuestro CorrelId (browse, no
        destructivo) — cuantos puts logicos quedaron en cola."""
        qmgr = _connect()
        try:
            q = ibmmq.Queue(qmgr, cfg["request_queue"],
                            ibmmq.CMQC.MQOO_BROWSE)
            try:
                n = 0
                md = ibmmq.MD()
                md.CorrelId = correl
                gmo = ibmmq.GMO(
                    Options=ibmmq.CMQC.MQGMO_BROWSE_NEXT
                    + ibmmq.CMQC.MQGMO_WAIT,
                    WaitInterval=3000)
                gmo.MatchOptions = ibmmq.CMQC.MQMO_MATCH_CORREL_ID
                while True:
                    try:
                        q.get(None, md, gmo)
                        n += 1
                    except ibmmq.MQMIError as exc:
                        if exc.reason == ibmmq.CMQC.MQRC_NO_MSG_AVAILABLE:
                            return n
                        raise
            finally:
                q.close()
        finally:
            qmgr.disconnect()

    def _consume_one() -> bytes:
        """Consumidor independiente: MQGET destructivo por
        CorrelId — simula el gateway leyendo la entrega."""
        qmgr = _connect()
        try:
            q = ibmmq.Queue(qmgr, cfg["request_queue"])
            try:
                md = ibmmq.MD()
                md.CorrelId = correl
                gmo = ibmmq.GMO(
                    Options=ibmmq.CMQC.MQGMO_WAIT
                    + ibmmq.CMQC.MQGMO_FAIL_IF_QUIESCING,
                    WaitInterval=5000)
                gmo.MatchOptions = ibmmq.CMQC.MQMO_MATCH_CORREL_ID
                return bytes(q.get(None, md, gmo))
            finally:
                q.close()
        finally:
            qmgr.disconnect()

    # ---- M2: conexion inalcanzable -> outcome conservador ------
    print("=== M2: connect failure -> outcome conservador =========")
    bad = dict(cfg, connection_name="127.0.0.1(59999)")
    r_bad = mq_adapter.deliver(req, bad)
    print("outcome:", r_bad.outcome, "| code:", r_bad.error_code)
    assert r_bad.outcome in ("FAILED_RETRYABLE", "FAILED_PERMANENT",
                             "UNKNOWN"), r_bad.outcome
    assert r_bad.outcome != O_SPOOLED
    assert "password" not in (r_bad.error_detail_safe or "").lower()

    # ---- M1: MQPUT commit -> verify -> consumer bytes exactos --
    print("=== M1: MQPUT commit -> verify/consumer ================")
    r1 = mq_adapter.deliver(req, cfg)
    print("outcome:", r1.outcome, "| receipt:", r1.receipt)
    assert r1.outcome == O_SPOOLED, r1.error_code
    assert r1.receipt["transport_evidence"] == "MQ_PUT_CONFIRMED"

    verdict = mq_adapter.verify(req, cfg)
    print("verify:", verdict)
    assert verdict == "SPOOLED", verdict
    assert _browse_count() == 1

    # ---- M3: segundo deliver -> replay, cola sigue en 1 --------
    print("=== M3: replay mismo delivery_id -> sin duplicado ======")
    r2 = mq_adapter.deliver(req, cfg)
    print("outcome:", r2.outcome,
          "| replayed:", r2.receipt.get("replayed"))
    assert r2.outcome == O_SPOOLED
    assert r2.receipt["replayed"] is True
    n = _browse_count()
    print("mensajes con ese CorrelId:", n)
    assert n == 1, "segundo logical send -> duplicado en cola"

    # ---- consumer independiente: bytes exactos + sha -----------
    print("=== M1b: consumer MQGET -> sha identico ================")
    payload = _consume_one()
    ok = payload == FIN.encode("utf-8")
    print("bytes exactos:", ok,
          "| sha:", hashlib.sha256(payload).hexdigest() == sha)
    assert ok

    # ---- M4: verify tras consumo -> NOT_SPOOLED honesto --------
    print("=== M4: verify() tras consumo ==========================")
    verdict = mq_adapter.verify(req, cfg)
    print("verify:", verdict)
    assert verdict == "NOT_SPOOLED", verdict

    print("P12_MQ_LAB PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
