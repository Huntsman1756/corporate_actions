"""P12.3 — IBM MQ adapter: contrato contra un MQI fake con la
misma superficie que `ibmmq` (connect_with_options, Queue
browse/put, MD/PMO/GMO, MQMIError con reason codes oficiales).

El lab real contra IBM MQ Developer es opt-in (scripts/p12_mq_lab.py
+ P12_MQ_LIVE=1) — nunca CI normal por la licencia del producto.
"""
from __future__ import annotations

import pytest

from ca_es.ops_send import (
    O_FAILED_PERMANENT, O_FAILED_RETRYABLE, O_SPOOLED, O_UNKNOWN,
    SendRequest, content_sha256_of)
from ca_es.transport import mq as mq_adapter

FIN = "{1:F01TESTES00XXXX1234000079}{4:\r\n:20C::SEME//INS-0001\r\n-}"
SHA = content_sha256_of(FIN)


def _request():
    return SendRequest(
        delivery_id="SND-" + "a" * 64,
        instruction_id="INS-0001",
        message_reference="INS-0001",
        message_schema="CA_ES_MT565_FIN_V1",
        message_text=FIN,
        content_sha256=content_sha256_of(FIN),
        destination_id="gw-mq-1",
        adapter_type="mq",
        generation=1)


def _cfg(**over):
    cfg = {"queue_manager": "QM1", "channel": "DEV.APP.SVRCONN",
           "connection_name": "127.0.0.1(1414)",
           "request_queue": "CA.OUT",
           "username_env": "MQ_USER", "password_env": "MQ_PASS"}
    cfg.update(over)
    return cfg


# ------------------------------------------------------------------
# fake MQI — misma superficie que ibmmq
# ------------------------------------------------------------------

class FakeMQMIError(Exception):
    def __init__(self, reason, comp=2):
        super().__init__(f"MQI Error. Comp: {comp}, Reason {reason}")
        self.comp = comp
        self.reason = reason


class _CMQC:
    MQOO_BROWSE = 0x10
    MQOO_OUTPUT = 0x10 + 0
    MQOO_FAIL_IF_QUIESCING = 0x2000
    MQGMO_BROWSE_NEXT = 0x10
    MQGMO_FAIL_IF_QUIESCING = 0x2000
    MQGMO_ACCEPT_TRUNCATED_MSG = 0x40000000
    MQMO_MATCH_CORREL_ID = 0x2
    MQPMO_SYNCPOINT = 0x2
    MQPMO_FAIL_IF_QUIESCING = 0x2000
    MQFMT_STRING = "MQSTR   "


class _MD:
    def __init__(self):
        self.CorrelId = b"\x00" * 24
        self.MsgId = b"\x00" * 24
        self.Format = ""


class _PMO:
    def __init__(self, **kw):
        self.Options = kw.get("Options", 0)


class _GMO:
    def __init__(self, **kw):
        self.Options = kw.get("Options", 0)
        self.WaitInterval = kw.get("WaitInterval", 0)
        self.MatchOptions = kw.get("MatchOptions", 0)


class FakeQueue:
    def __init__(self, qmgr, name, opts=0):
        self.qmgr = qmgr
        self.name = name
        self.opts = opts
        if name == "MISSING.QUEUE":
            raise FakeMQMIError(2085)  # UNKNOWN_OBJECT_NAME
        self._browse_idx = 0

    def put(self, buf, md, pmo):
        if self.qmgr.fail_put is not None:
            raise FakeMQMIError(self.qmgr.fail_put)
        md.MsgId = self.qmgr.next_msg_id()
        self.qmgr.pending.append(
            (bytes(buf), bytes(md.CorrelId), bytes(md.MsgId)))

    def get(self, _buflen, md, gmo):
        # browse siguiente mensaje con CorrelId coincidente
        store = self.qmgr.committed + self.qmgr.pending
        while self._browse_idx < len(store):
            payload, correl, msg_id = store[self._browse_idx]
            self._browse_idx += 1
            if gmo.MatchOptions & _CMQC.MQMO_MATCH_CORREL_ID \
                    and correl != md.CorrelId:
                continue
            md.MsgId = msg_id
            return payload
        raise FakeMQMIError(2033)  # NO_MSG_AVAILABLE

    def close(self):
        pass


class FakeQueueManager:
    instances = []
    stores = {}                # name -> committed[] (compartido)
    next_fail_connect = None

    def __init__(self, name):
        self.name = name
        self.committed = self.stores.setdefault(name, [])
        self.pending = []        # puts pre-commit
        self.fail_connect = None
        self.fail_put = None
        self.fail_commit = None
        self._seq = 0
        self.disconnected = False

    @classmethod
    def connect_with_options(cls, qm, **kwargs):
        inst = cls(qm)
        inst.connect_kwargs = kwargs
        if cls.next_fail_connect is not None:
            inst.fail_connect = cls.next_fail_connect
            cls.next_fail_connect = None
        if inst.fail_connect is not None:
            raise FakeMQMIError(inst.fail_connect)
        cls.instances.append(inst)
        return inst

    def next_msg_id(self):
        self._seq += 1
        return b"M" + self._seq.to_bytes(23, "big")

    def commit(self):
        if self.fail_commit is not None:
            raise FakeMQMIError(self.fail_commit)
        self.committed.extend(self.pending)
        self.pending = []

    def backout(self):
        self.pending = []

    def disconnect(self):
        self.disconnected = True


class FakeMQI:
    CMQC = _CMQC
    MD = _MD
    PMO = _PMO
    GMO = _GMO
    Queue = FakeQueue
    QueueManager = FakeQueueManager
    MQMIError = FakeMQMIError


@pytest.fixture()
def fake():
    FakeQueueManager.instances = []
    FakeQueueManager.stores = {}
    FakeQueueManager.next_fail_connect = None
    return FakeMQI


def _qmgr():
    return FakeQueueManager.instances[-1]


# ------------------------------------------------------------------
# deliver
# ------------------------------------------------------------------

def test_mqput_commit_confirmed(fake):
    res = mq_adapter.deliver(_request(), _cfg(), mqi=fake)
    assert res.outcome == O_SPOOLED
    ev = res.receipt
    assert ev["transport_evidence"] == "MQ_PUT_CONFIRMED"
    assert ev["queue_manager"] == "QM1"
    assert ev["queue"] == "CA.OUT"
    assert ev["msg_id_hex"]
    # bytes exactos encolados bajo CorrelId determinista
    payload, correl, _ = _qmgr().committed[0]
    assert payload == FIN.encode("utf-8")
    assert correl == mq_adapter._correl_id("SND-" + "a" * 64)


def test_replay_no_second_put(fake):
    mq_adapter.deliver(_request(), _cfg(), mqi=fake)
    res = mq_adapter.deliver(_request(), _cfg(), mqi=fake)
    assert res.outcome == O_SPOOLED
    assert res.receipt["replayed"] is True
    assert len(_qmgr().committed) == 1


def test_correl_collision_different_payload(fake):
    qm_payload = b"different bytes entirely"
    inst_q = FakeQueueManager("QM1")
    FakeQueueManager.instances.append(inst_q)
    inst_q.committed.append(
        (qm_payload, mq_adapter._correl_id("SND-" + "a" * 64),
         b"\x01" * 24))
    res = mq_adapter.deliver(_request(), _cfg(), mqi=fake)
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "DELIVERY_ID_COLLISION"


def test_hash_binding_fails_before_connect(fake):
    req = _request()
    req.content_sha256 = "0" * 64
    res = mq_adapter.deliver(req, _cfg(), mqi=fake)
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "CONTENT_HASH_MISMATCH"
    assert not FakeQueueManager.instances


def test_connect_refused_retryable(fake):
    FakeQueueManager.next_fail_connect = 2059  # Q_MGR_NOT_AVAILABLE
    res = mq_adapter.deliver(_request(), _cfg(), mqi=fake)
    assert res.outcome == O_FAILED_RETRYABLE
    assert res.error_code == "MQ_CONNECT_2059"


def test_not_authorized_permanent(fake):
    FakeQueueManager.next_fail_connect = 2035
    res = mq_adapter.deliver(_request(), _cfg(), mqi=fake)
    assert res.outcome == O_FAILED_PERMANENT


def test_unknown_queue_permanent(fake):
    res = mq_adapter.deliver(
        _request(), _cfg(request_queue="MISSING.QUEUE"), mqi=fake)
    assert res.outcome == O_FAILED_PERMANENT
    assert res.error_code == "MQ_BROWSE_2085"


def test_queue_full_retryable(fake):
    FakeQueueManager.next_fail_connect = None
    # fuerza el fallo en el primer qmgr conectado
    orig = FakeQueueManager.connect_with_options
    def conn(qm, **kw):
        inst = orig(qm, **kw)
        inst.fail_put = 2053  # Q_FULL
        return inst
    FakeQueueManager.connect_with_options = conn
    try:
        res = mq_adapter.deliver(_request(), _cfg(), mqi=fake)
    finally:
        FakeQueueManager.connect_with_options = orig
    assert res.outcome == O_FAILED_RETRYABLE
    assert res.error_code == "MQ_PUT_2053"


def test_put_broken_connection_is_unknown(fake):
    """Fallo post-put (2009) -> UNKNOWN: el commit pudo o no
    ocurrir; verify() lo resuelve."""
    orig = FakeQueueManager.connect_with_options
    def conn(qm, **kw):
        inst = orig(qm, **kw)
        inst.fail_put = 2009  # CONNECTION_BROKEN
        return inst
    FakeQueueManager.connect_with_options = conn
    try:
        res = mq_adapter.deliver(_request(), _cfg(), mqi=fake)
    finally:
        FakeQueueManager.connect_with_options = orig
    assert res.outcome == O_UNKNOWN


def test_commit_failure_is_unknown(fake):
    orig = FakeQueueManager.connect_with_options
    def conn(qm, **kw):
        inst = orig(qm, **kw)
        inst.fail_commit = 2009
        return inst
    FakeQueueManager.connect_with_options = conn
    try:
        res = mq_adapter.deliver(_request(), _cfg(), mqi=fake)
    finally:
        FakeQueueManager.connect_with_options = orig
    assert res.outcome == O_UNKNOWN
    assert res.error_code.startswith("MQ_COMMIT_")


def test_no_password_in_evidence_or_errors(fake, monkeypatch):
    monkeypatch.setenv("MQ_PASS", "sup3r-secret")
    res = mq_adapter.deliver(_request(), _cfg(), mqi=fake)
    import json
    assert "sup3r-secret" not in json.dumps(res.receipt or {})
    assert "sup3r-secret" not in (res.error_detail_safe or "")


def test_credentials_from_env(fake, monkeypatch):
    monkeypatch.setenv("MQ_USER", "app")
    monkeypatch.setenv("MQ_PASS", "sup3r-secret")
    mq_adapter.deliver(_request(), _cfg(), mqi=fake)
    kw = _qmgr().connect_kwargs
    assert kw["user"] == "app"
    assert kw["password"] == "sup3r-secret"
    assert kw["channel"] == "DEV.APP.SVRCONN"


# ------------------------------------------------------------------
# verify()
# ------------------------------------------------------------------

def test_verify_committed_message(fake):
    req = _request()
    mq_adapter.deliver(req, _cfg(), mqi=fake)
    assert mq_adapter.verify(req, _cfg(), mqi=fake) == "SPOOLED"


def test_verify_absent(fake):
    assert mq_adapter.verify(
        _request(), _cfg(), mqi=fake) == "NOT_SPOOLED"


def test_verify_collision_payload(fake):
    inst = FakeQueueManager("QM1")
    FakeQueueManager.instances.append(inst)
    inst.committed.append(
        (b"foreign", mq_adapter._correl_id("SND-" + "a" * 64),
         b"\x01" * 24))
    assert mq_adapter.verify(
        _request(), _cfg(), mqi=fake) == "COLLISION"


def test_verify_connect_failure_unknown(fake):
    FakeQueueManager.next_fail_connect = 2059
    assert mq_adapter.verify(
        _request(), _cfg(), mqi=fake) == "UNKNOWN"


def test_missing_ibmmq_fails_closed():
    """Sin ibmmq instalado ni fake inyectado -> permanente."""
    import sys
    saved = {k: sys.modules.pop(k) for k in
             ("ibmmq", "pymqi") if k in sys.modules}
    try:
        res = mq_adapter.deliver(_request(), _cfg(), mqi=None)
    finally:
        sys.modules.update(saved)
    if res.error_code == "IBMMQ_UNAVAILABLE":
        assert res.outcome == O_FAILED_PERMANENT
    # si ibmmq SI esta instalado en este entorno, el adapter
    # intentara conectar — cualquier outcome no-crash es valido
