"""P12.3 — IBM MQ transport (docs/p12/p123).

Adapter real contra IBM MQ via el binding oficial ``ibmmq``
(mq-mqi-python, sucesor de PyMQI; extra opcional ``mq``). No
implementa el wire protocol. ``ibmmq`` requiere el cliente IBM MQ
C instalado — el import es lazy y la ausencia es fail-closed
(IBMMQ_UNAVAILABLE).

Semantica (patron ibm-messaging/mq-dev-patterns):

    browse por CorrelId determinista
        -> existe + sha casa    -> MQ_PUT_CONFIRMED (replay)
        -> sha distinto         -> COLLISION permanente
        -> ausente              -> MQPUT bajo MQPMO_SYNCPOINT
                                 -> commit -> MQ_PUT_CONFIRMED

    CorrelId = "CAES" + sha256(delivery_id)[:20]  (24 bytes)

    MQ_PUT_CONFIRMED prueba que el queue manager confirmo el put
    bajo transaccion. NO prueba consumo por gateway ni aceptacion
    SWIFT. verify() re-busca por CorrelId + sha del payload.

Clasificacion MQRC (semantica oficial IBM) en _RETRYABLE/
_PERMANENT; el resto -> permanente conservador. El reason numerico
viaja en transport_metadata_json — nunca el payload ni secretos.
"""
from __future__ import annotations

import hashlib
import os

from ..ops_send import (
    O_FAILED_PERMANENT, O_FAILED_RETRYABLE, O_SPOOLED,
    SendAdapterResult, SendRequest,
    V_COLLISION, V_NOT_SPOOLED, V_SPOOLED, V_UNKNOWN,
    content_sha256_of)

CONFIG_KEYS = frozenset({
    "queue_manager", "channel", "connection_name", "request_queue",
    "reply_queue", "username_env", "password_env",
    "ssl_cipher_spec", "key_repository", "connect_timeout_seconds"})
REQUIRED_KEYS = frozenset({
    "queue_manager", "channel", "connection_name", "request_queue"})

# MQRC -> permanente (config/entorno) o retryable (transitorio).
# Solo se clasifican codes relevantes; el resto -> permanente
# conservador.
_RETRYABLE_REASONS = frozenset({
    2009,   # MQRC_CONNECTION_BROKEN (pre-put: no comprometido)
    2053,   # MQRC_Q_FULL
    2059,   # MQRC_Q_MGR_NOT_AVAILABLE
    2161,   # MQRC_Q_MGR_QUIESCING
    2162,   # MQRC_Q_MGR_STOPPING
    2051,   # MQRC_PUT_INHIBITED
})
_PERMANENT_REASONS = frozenset({
    2035,   # MQRC_NOT_AUTHORIZED
    2058,   # MQRC_Q_MGR_NAME_ERROR
    2085,   # MQRC_UNKNOWN_OBJECT_NAME
    2087,   # MQRC_UNKNOWN_REMOTE_Q_MGR
    2195,   # MQRC_UNEXPECTED_ERROR
})
# post-put-commit ambiguity: no se puede saber si el put quedo
_AMBIGUOUS_REASONS = frozenset({
    2009,   # MQRC_CONNECTION_BROKEN durante/despues del put
    2543,   # MQRC_CONNECTION_NOT_AVAILABLE
})


class _MissingIbmMq(Exception):
    pass


def _mqi(injected=None):
    """ibmmq real, o el modulo/clase inyectada por tests."""
    if injected is not None:
        return injected
    try:
        import ibmmq
        return ibmmq
    except ImportError:
        try:
            import pymqi
            return pymqi
        except ImportError as exc:
            raise _MissingIbmMq() from exc


def _cfg(cfg: dict, key, default=None):
    v = (cfg or {}).get(key)
    return v if v not in (None, "") else default


def _correl_id(delivery_id: str) -> bytes:
    """CorrelId determinista 24B: 'CAES' + sha256(delivery_id)[:20]."""
    return b"CAES" + hashlib.sha256(
        delivery_id.encode("utf-8")).digest()[:20]


def _evidence(cfg, msg_id: bytes | None, correl: bytes,
              reason=None) -> dict:
    return {
        "transport_evidence": "MQ_PUT_CONFIRMED",
        "queue_manager": _cfg(cfg, "queue_manager"),
        "queue": _cfg(cfg, "request_queue"),
        "msg_id_hex": msg_id.hex() if msg_id else None,
        "correl_id_hex": correl.hex(),
        "mq_reason": reason}


def _connect(mqi, cfg):
    """QueueManager conectado por client channel. Credenciales solo
    via *_env — nunca embebidas ni persistidas."""
    kwargs = {
        "channel": _cfg(cfg, "channel"),
        "conn_info": _cfg(cfg, "connection_name"),
    }
    user_env = _cfg(cfg, "username_env")
    if user_env:
        kwargs["user"] = os.environ.get(str(user_env), "")
        pw_env = _cfg(cfg, "password_env")
        if pw_env:
            kwargs["password"] = os.environ.get(str(pw_env), "")
    ssl_spec = _cfg(cfg, "ssl_cipher_spec")
    if ssl_spec:
        kwargs["ssl_cipher_spec"] = ssl_spec
    key_repo = _cfg(cfg, "key_repository")
    if key_repo:
        kwargs["key_repository"] = key_repo
    return mqi.QueueManager.connect_with_options(
        _cfg(cfg, "queue_manager"), **kwargs)


def _reason_of(exc) -> int | None:
    r = getattr(exc, "reason", None)
    try:
        return int(r) if r is not None else None
    except (TypeError, ValueError):
        return None


def _classify(reason: int | None) -> str:
    """PERMANENT|RETRYABLE — conservador por defecto."""
    if reason in _RETRYABLE_REASONS:
        return "RETRYABLE"
    if reason in _PERMANENT_REASONS:
        return "PERMANENT"
    return "PERMANENT"


def _browse_for_correl(qmgr, mqi, cfg, correl: bytes):
    """(payload_bytes|None, msg_id) del mensaje con ese CorrelId,
    leido en modo browse (no destructivo)."""
    queue_name = _cfg(cfg, "request_queue")
    q = mqi.Queue(qmgr, queue_name,
                  mqi.CMQC.MQOO_BROWSE + mqi.CMQC.MQOO_FAIL_IF_QUIESCING)
    try:
        gmo = mqi.GMO(Options=mqi.CMQC.MQGMO_BROWSE_NEXT
                      + mqi.CMQC.MQGMO_FAIL_IF_QUIESCING
                      + mqi.CMQC.MQGMO_ACCEPT_TRUNCATED_MSG,
                      WaitInterval=1000)
        md = mqi.MD()
        md.CorrelId = correl
        gmo.MatchOptions = mqi.CMQC.MQMO_MATCH_CORREL_ID
        while True:
            try:
                data = q.get(None, md, gmo)
            except mqi.MQMIError as exc:
                if _reason_of(exc) == 2033:  # MQRC_NO_MSG_AVAILABLE
                    return None, None
                raise
            if bytes(md.CorrelId) == correl:
                return data, bytes(md.MsgId)
    finally:
        q.close()


# ------------------------------------------------------------------
# adapter contract
# ------------------------------------------------------------------

def deliver(request: SendRequest, dest_config: dict,
            mqi=None) -> SendAdapterResult:
    """MQPUT transaccional. Replay idempotente via CorrelId browse."""
    actual_sha = content_sha256_of(request.message_text)
    if actual_sha != request.content_sha256:
        return SendAdapterResult(
            O_FAILED_PERMANENT, error_code="CONTENT_HASH_MISMATCH",
            error_detail_safe="message_text no casa con "
                              "content_sha256 del ledger")
    cfg = dest_config or {}
    correl = _correl_id(request.delivery_id)
    body = request.message_text.encode("utf-8")

    try:
        api = _mqi(mqi)
    except _MissingIbmMq:
        return SendAdapterResult(
            O_FAILED_PERMANENT, error_code="IBMMQ_UNAVAILABLE",
            error_detail_safe="pip install ca-es[mq] + IBM MQ client")

    try:
        qmgr = _connect(api, cfg)
    except Exception as exc:  # noqa: BLE001
        reason = _reason_of(exc)
        cls = _classify(reason)
        return SendAdapterResult(
            O_FAILED_PERMANENT if cls == "PERMANENT"
            else O_FAILED_RETRYABLE,
            error_code=f"MQ_CONNECT_{reason or 'ERROR'}",
            error_detail_safe=exc.__class__.__name__)

    # ---- idempotencia: browse por CorrelId -------------------------
    try:
        payload, msg_id = _browse_for_correl(qmgr, api, cfg, correl)
    except Exception as exc:  # noqa: BLE001
        qmgr.disconnect()
        reason = _reason_of(exc)
        cls = _classify(reason)
        return SendAdapterResult(
            O_FAILED_PERMANENT if cls == "PERMANENT"
            else O_FAILED_RETRYABLE,
            error_code=f"MQ_BROWSE_{reason or 'ERROR'}",
            error_detail_safe=exc.__class__.__name__)

    if payload is not None:
        if hashlib.sha256(payload).hexdigest() == actual_sha:
            qmgr.disconnect()
            return SendAdapterResult(
                O_SPOOLED, receipt={
                    "replayed": True,
                    **_evidence(cfg, msg_id, correl)})
        qmgr.disconnect()
        return SendAdapterResult(
            O_FAILED_PERMANENT, error_code="DELIVERY_ID_COLLISION",
            error_detail_safe="CorrelId en cola con payload distinto")

    # ---- MQPUT bajo syncpoint + commit ------------------------------
    q = None
    try:
        q = api.Queue(qmgr, _cfg(cfg, "request_queue"),
                      api.CMQC.MQOO_OUTPUT
                      + api.CMQC.MQOO_FAIL_IF_QUIESCING)
        md = api.MD()
        md.CorrelId = correl
        md.Format = api.CMQC.MQFMT_STRING
        pmo = api.PMO(Options=api.CMQC.MQPMO_SYNCPOINT
                      + api.CMQC.MQPMO_FAIL_IF_QUIESCING)
        q.put(body, md, pmo)
    except Exception as exc:  # noqa: BLE001
        reason = _reason_of(exc)
        try:
            if q is not None:
                q.close()
            qmgr.backout()
            qmgr.disconnect()
        except Exception:  # noqa: BLE001
            pass
        if reason in _AMBIGUOUS_REASONS:
            return SendAdapterResult(
                "UNKNOWN", error_code=f"MQ_PUT_{reason}",
                error_detail_safe="fallo post-put: estado del commit "
                                  "indeterminado")
        cls = _classify(reason)
        return SendAdapterResult(
            O_FAILED_PERMANENT if cls == "PERMANENT"
            else O_FAILED_RETRYABLE,
            error_code=f"MQ_PUT_{reason or 'ERROR'}",
            error_detail_safe=exc.__class__.__name__)

    try:
        qmgr.commit()
        assigned_msg_id = bytes(md.MsgId) if md.MsgId else None
        q.close()
        qmgr.disconnect()
    except Exception as exc:  # noqa: BLE001
        reason = _reason_of(exc)
        try:
            qmgr.disconnect()
        except Exception:  # noqa: BLE001
            pass
        return SendAdapterResult(
            "UNKNOWN", error_code=f"MQ_COMMIT_{reason or 'ERROR'}",
            error_detail_safe="fallo en commit: estado indeterminado")

    return SendAdapterResult(
        O_SPOOLED, receipt={
            "replayed": False,
            **_evidence(cfg, assigned_msg_id, correl)})


def verify(request: SendRequest, dest_config: dict,
           mqi=None) -> str:
    """Verificacion post-crash: browse por CorrelId + sha.

    La cola es la fuente de verdad del commit; un fallo de
    conexion/browse es UNKNOWN — nunca NOT_SPOOLED fingido.
    """
    cfg = dest_config or {}
    correl = _correl_id(request.delivery_id)
    try:
        api = _mqi(mqi)
    except _MissingIbmMq:
        return V_UNKNOWN
    try:
        qmgr = _connect(api, cfg)
    except Exception:  # noqa: BLE001
        return V_UNKNOWN
    try:
        payload, _msg_id = _browse_for_correl(qmgr, api, cfg, correl)
        qmgr.disconnect()
    except Exception:  # noqa: BLE001
        try:
            qmgr.disconnect()
        except Exception:  # noqa: BLE001
            pass
        return V_UNKNOWN
    if payload is None:
        return V_NOT_SPOOLED
    return V_SPOOLED if hashlib.sha256(payload).hexdigest() == \
        content_sha256_of(request.message_text) else V_COLLISION
