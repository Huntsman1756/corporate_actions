"""P10 — Alert delivery boundary (dispatcher + ledger + payload).

docs/p10/*. El outbox sigue siendo la verdad de negocio de alertas;
este modulo deriva entregas por destino a partir de el. Transporte
agnostico: adapters en ``ca_es.delivery.*``.

Invariantes: alert lifecycle != delivery lifecycle; at-least-once
en el boundary (nunca exactly-once); identidad de entrega estable
por (alert_key, payload_sem_sha, destination_id); STARTED persistido
antes del side effect; UNKNOWN_OUTCOME sin auto-retry; credenciales
solo por env.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .semantic_hash import canonical_json, semantic_sha256

SCHEMA_DELIVERY_REQUEST = "CA_ES_ALERT_DELIVERY_REQUEST_V1"
SCHEMA_DELIVERY_PAYLOAD = "CA_ES_ALERT_DELIVERY_PAYLOAD_V1"
SCHEMA_DELIVERY_ATTEMPT = "CA_ES_ALERT_DELIVERY_ATTEMPT_V1"
SCHEMA_DELIVERY_RESULT = "CA_ES_ALERT_DELIVERY_RESULT_V1"
SCHEMA_DELIVERY_STATUS = "CA_ES_DELIVERY_STATUS_V1"

# version de politica incluida en delivery_key: un cambio de
# contrato de payload versiona la identidad de entrega.
ADAPTER_POLICY_VERSION = SCHEMA_DELIVERY_PAYLOAD

# estados de entrega (ledger)
D_PENDING = "PENDING"
D_DELIVERED = "DELIVERED"
D_FAILED_RETRYABLE = "FAILED_RETRYABLE"
D_FAILED_PERMANENT = "FAILED_PERMANENT"
D_UNKNOWN = "UNKNOWN_OUTCOME"
D_ABANDONED = "ABANDONED"

# estados de intento
A_STARTED = "STARTED"
A_SUCCEEDED = "SUCCEEDED"
A_FAILED = "FAILED"
A_UNKNOWN = "UNKNOWN"

# outcomes devueltos por adapters
O_SUCCEEDED = "SUCCEEDED"
O_FAILED_RETRYABLE = "FAILED_RETRYABLE"
O_FAILED_PERMANENT = "FAILED_PERMANENT"
O_UNKNOWN = "UNKNOWN"

DEFAULT_MAX_PAYLOAD_BYTES = 32768
_DEFAULT_SUMMARY_LEN = 200


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat(
    ).replace("+00:00", "Z")


def _truncate(text: object, limit: int = 300) -> str | None:
    if text is None:
        return None
    return str(text)[:limit]


# ------------------------------------------------------------------
# payload minimizado (P10.3): allowlist por familia de categoria
# ------------------------------------------------------------------

_DETAILS_ALLOWLIST: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("DEADLINE_", (
        "canonical_event_id", "deadline_type", "deadline_date",
        "action_status", "days_until")),
    ("EXCEPTION_CASE", (
        "canonical_event_id", "factual_status", "workflow_status",
        "reason_codes", "last_action")),
    ("PROCESSING_FAILURE", (
        "message_identifier", "processing_status")),
    ("RUN_FAILED", (
        "run_id", "error_summary")),
    ("SOURCE_REFRESH_FAILED", (
        "source_id", "surface_id", "status", "error",
        "fetch_failures", "pagination_complete")),
    ("SOURCE_PARTIAL", (
        "source_id", "surface_id", "status", "error",
        "fetch_failures", "pagination_complete")),
    ("SOURCE_PARSE_FAILED", (
        "document_id", "content_sha256", "error")),
    ("SOURCE_CONTENT_CHANGED", (
        "document_id", "from", "to", "notice")),
    ("SOURCE_STALE", (
        "source_id", "surface_id", "last_checkpoint_at",
        "age_days", "stale_after_days")),
)


def _allowed_details(category: str, payload: dict) -> dict:
    """Campos del payload outbox permitidos en la salida.

    Categoria no listada -> {} (fail-minimal: solo campos base).
    """
    allowed: tuple[str, ...] = ()
    for prefix, keys in _DETAILS_ALLOWLIST:
        if category == prefix or (
                prefix.endswith("_") and category.startswith(prefix)):
            allowed = keys
            break
    out = {}
    for key in allowed:
        if key in payload:
            value = payload[key]
            if key in ("error", "error_summary"):
                value = _truncate(value)
            out[key] = value
    return out


def build_outbound_payload(alert: dict, delivery_key: str | None
                           ) -> dict:
    """CA_ES_ALERT_DELIVERY_PAYLOAD_V1 minimizado.

    ``alert`` es la fila outbox dict (payload_json ya parseado en
    ``alert["payload"]``, evidence_refs en ``alert["evidence_refs"]``).
    """
    payload = alert.get("payload") or {}
    refs = alert.get("evidence_refs")
    if isinstance(refs, str):
        refs = json.loads(refs)
    doc = {
        "schema": SCHEMA_DELIVERY_PAYLOAD,
        "alert_key": alert["alert_key"],
        "category": alert["category"],
        "subject_type": alert.get("subject_type"),
        "subject_key": alert.get("subject_key"),
        "state": alert["state"],
        "alert_semantic_sha256": alert.get("semantic_sha256"),
        "first_observed_run_id": alert.get("first_observed_run_id"),
        "last_observed_run_id": alert.get("last_observed_run_id"),
        "summary": _truncate(
            f"{alert['category']} {alert.get('subject_key')}",
            _DEFAULT_SUMMARY_LEN),
        "details": _allowed_details(alert["category"], payload),
        "evidence_refs": list(refs or []),
    }
    if delivery_key is not None:
        doc["delivery_key"] = delivery_key
    return doc


def payload_semantic_sha256(payload_doc: dict) -> str:
    """Sem-sha del payload de salida SIN delivery_key (es input de
    la derivacion de delivery_key, no puede contenerla)."""
    clean = {k: v for k, v in payload_doc.items()
             if k != "delivery_key"}
    return semantic_sha256(clean)


def derive_delivery_key(alert_key: str, alert_state: str,
                        alert_sem_sha: str | None,
                        destination_id: str) -> str:
    """Identidad estable de entrega (docs/p10/p101).

    Material: alert_key + alert_state + alert semantic sha256
    (hash del payload de NEGOCIO de la alerta, no del payload
    outbound — este incluye metadatos de run volatiles como
    last_observed_run_id) + destination_id + policy version.
    """
    material = "|".join((
        "CA_ES_ALERT_DELIVERY_V1",
        alert_key,
        alert_state,
        alert_sem_sha or "",
        destination_id,
        ADAPTER_POLICY_VERSION,
    ))
    return "DLV-" + hashlib.sha256(
        material.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------
# routing / policy
# ------------------------------------------------------------------

def category_routed(categories: list[str], category: str) -> bool:
    """`*` = todas; `PREFIX_*` = prefijo; exacto en otro caso."""
    for entry in categories or []:
        if entry == "*" or entry == category:
            return True
        if entry.endswith("*") and category.startswith(entry[:-1]):
            return True
    return False


def enabled_destinations(delivery_cfg: dict) -> list[dict]:
    if not (delivery_cfg or {}).get("enabled"):
        return []
    out = []
    for dest in delivery_cfg.get("destinations") or []:
        if dest.get("enabled") and dest.get("destination_id"):
            out.append(dest)
    return out


# ------------------------------------------------------------------
# adapter boundary
# ------------------------------------------------------------------

@dataclass
class AdapterResult:
    """Resultado de UN intento de transporte.

    outcome: O_SUCCEEDED | O_FAILED_RETRYABLE | O_FAILED_PERMANENT
    | O_UNKNOWN. receipt/transport_metadata solo metadata segura.
    """
    outcome: str
    error_code: str | None = None
    error_detail_safe: str | None = None
    retry_after_seconds: int | None = None
    receipt: dict | None = None


@dataclass
class DeliveryRequest:
    delivery_key: str
    alert_key: str
    alert_semantic_sha256: str | None
    alert_state: str
    adapter_type: str
    destination_id: str
    generation: int
    payload_schema: str
    payload: dict
    created_at: str
    payload_bytes: bytes = b""


def adapter_registry() -> dict:
    """adapter_type -> deliver(request, dest_config) -> AdapterResult."""
    from .delivery import file_adapter, smtp_adapter, webhook_adapter

    return {
        "file": file_adapter.deliver,
        "webhook": webhook_adapter.deliver,
        "smtp": smtp_adapter.deliver,
    }


# ------------------------------------------------------------------
# ledger helpers
# ------------------------------------------------------------------

def _insert_transition(conn, delivery_key: str, from_status,
                       to_status: str, actor: str, note: str | None,
                       now: str) -> None:
    conn.execute(
        "INSERT INTO delivery_transitions"
        " (delivery_key, at, from_status, to_status, actor, note)"
        " VALUES (?,?,?,?,?,?)",
        (delivery_key, now, from_status, to_status, actor, note))


def get_delivery(conn, delivery_key: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM deliveries WHERE delivery_key=?",
        (delivery_key,)).fetchone()
    return dict(row) if row else None


def list_deliveries(conn, *, alert_key: str | None = None,
                    status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM deliveries"
    args: list = []
    conds = []
    if alert_key is not None:
        conds.append("alert_key=?")
        args.append(alert_key)
    if status is not None:
        conds.append("status=?")
        args.append(status)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY first_created_at"
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def list_attempts(conn, delivery_key: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM delivery_attempts WHERE delivery_key=?"
        " ORDER BY attempt_number", (delivery_key,)).fetchall()
    return [dict(r) for r in rows]


def list_transitions(conn, delivery_key: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM delivery_transitions WHERE delivery_key=?"
        " ORDER BY id", (delivery_key,)).fetchall()
    return [dict(r) for r in rows]


def _set_delivery_status(conn, delivery_key: str, to_status: str,
                         actor: str, now: str, *, note=None,
                         next_attempt_after=None,
                         delivered_at=None, receipt=None) -> None:
    row = conn.execute(
        "SELECT status FROM deliveries WHERE delivery_key=?",
        (delivery_key,)).fetchone()
    if row is None:
        return
    from_status = row["status"]
    sets = ["status=?"]
    args: list = [to_status]
    if next_attempt_after is not None or to_status == D_PENDING:
        sets.append("next_attempt_after=?")
        args.append(next_attempt_after)
    if delivered_at is not None:
        sets.append("delivered_at=?")
        args.append(delivered_at)
    if receipt is not None:
        sets.append("external_receipt_json=?")
        args.append(json.dumps(receipt, sort_keys=True))
    args.append(delivery_key)
    conn.execute(
        f"UPDATE deliveries SET {', '.join(sets)}"
        " WHERE delivery_key=?", args)
    if from_status != to_status:
        _insert_transition(
            conn, delivery_key, from_status, to_status,
            actor, note, now)


# ------------------------------------------------------------------
# dispatcher
# ------------------------------------------------------------------

def _mark_orphan_attempts(conn, now: str) -> int:
    """Attempts STARTED de un proceso muerto -> UNKNOWN.

    El dispatcher es single-writer (run lock): todo STARTED
    presente al inicio es huerfano por definicion.
    """
    rows = conn.execute(
        "SELECT attempt_id, delivery_key FROM delivery_attempts"
        " WHERE status='STARTED'").fetchall()
    for r in rows:
        conn.execute(
            "UPDATE delivery_attempts SET status=?, completed_at=?"
            " WHERE attempt_id=?",
            (A_UNKNOWN, now, r["attempt_id"]))
        _set_delivery_status(
            conn, r["delivery_key"], D_UNKNOWN,
            "dispatcher", now, note="ORPHANED_STARTED_ATTEMPT")
    return len(rows)


def _derive_for_alert(conn, alert: dict, dest: dict, now: str,
                      payload_policy: dict) -> tuple[dict | None, bool]:
    """Crea (si no existe) la entrega de esta alerta para este
    destino en la generacion vigente. Devuelve (fila, created)."""
    outbound = build_outbound_payload(alert, delivery_key=None)
    p_sha = payload_semantic_sha256(outbound)
    dk = derive_delivery_key(
        alert["alert_key"], alert["state"],
        alert.get("semantic_sha256"), dest["destination_id"])
    existing = get_delivery(conn, dk)
    if existing is not None:
        return existing, False

    prior = [d for d in list_deliveries(conn, alert_key=alert["alert_key"])
             if d["destination_id"] == dest["destination_id"]]
    generation = len(prior) + 1
    state = alert["state"]
    if state == "OPEN":
        gate = ("notify_on_open" if generation == 1
                else "notify_on_change")
    else:
        gate = "notify_on_clear"
    if not payload_policy.get(gate, gate != "notify_on_clear"):
        return None, False

    max_bytes = int(payload_policy.get(
        "max_payload_bytes", DEFAULT_MAX_PAYLOAD_BYTES))
    outbound["delivery_key"] = dk
    payload_json = canonical_json(outbound)
    if len(payload_json.encode("utf-8")) > max_bytes:
        conn.execute(
            "INSERT INTO deliveries"
            " (delivery_key, alert_key, alert_semantic_sha256,"
            "  alert_state, payload_semantic_sha256, payload_json,"
            "  destination_id, adapter_type, generation, status,"
            "  next_attempt_after, attempt_count, first_created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,0,?)",
            (dk, alert["alert_key"], alert.get("semantic_sha256"),
             state, p_sha, payload_json, dest["destination_id"],
             dest["adapter"], generation, D_FAILED_PERMANENT,
             None, now))
        _insert_transition(
            conn, dk, None, D_FAILED_PERMANENT, "dispatcher",
            "PAYLOAD_TOO_LARGE", now)
        return get_delivery(conn, dk), True

    conn.execute(
        "INSERT INTO deliveries"
        " (delivery_key, alert_key, alert_semantic_sha256,"
        "  alert_state, payload_semantic_sha256, payload_json,"
        "  destination_id, adapter_type, generation, status,"
        "  next_attempt_after, attempt_count, first_created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,NULL,0,?)",
        (dk, alert["alert_key"], alert.get("semantic_sha256"),
         state, p_sha, payload_json, dest["destination_id"],
         dest["adapter"], generation, D_PENDING, now))
    _insert_transition(
        conn, dk, None, D_PENDING, "dispatcher", "DERIVED", now)
    return get_delivery(conn, dk), True


def _payload_for(delivery: dict) -> dict:
    """Payload outbound persistido en la fila (derivado en
    derivacion, nunca reconstruido: la alerta pudo cambiar)."""
    return json.loads(delivery["payload_json"])


def _retry_delay_seconds(retry_cfg: dict, attempt_number: int) -> int:
    base = float(retry_cfg.get("base_delay_seconds", 300))
    factor = float(retry_cfg.get("backoff_factor", 2.0))
    cap = float(retry_cfg.get("max_delay_seconds", 3600))
    delay = base * (factor ** max(0, attempt_number - 1))
    return int(min(delay, cap))


def _iso_plus_seconds(now_iso: str, seconds: int) -> str:
    from datetime import timedelta

    base = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    return (base + timedelta(seconds=seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _is_eligible(delivery: dict, now: str, retry_cfg: dict) -> bool:
    status = delivery["status"]
    if status == D_PENDING:
        return True
    if status != D_FAILED_RETRYABLE:
        return False
    max_attempts = int(retry_cfg.get("max_attempts", 5))
    if int(delivery["attempt_count"]) >= max_attempts:
        return False
    naa = delivery.get("next_attempt_after")
    return naa is None or naa <= now


def _record_attempt(conn, delivery: dict, result: AdapterResult,
                    attempt_number: int, now: str,
                    retry_cfg: dict) -> str:
    """Persiste el resultado de un intento y transiciona la entrega.
    Devuelve el nuevo status."""
    attempt_id = f"ATT-{delivery['delivery_key']}-{attempt_number}"
    outcome = result.outcome
    if outcome == O_SUCCEEDED:
        conn.execute(
            "UPDATE delivery_attempts SET status=?, completed_at=?,"
            " retryable=0, transport_metadata_json=?"
            " WHERE attempt_id=?",
            (A_SUCCEEDED, now,
             json.dumps(result.receipt or {}, sort_keys=True),
             attempt_id))
        _set_delivery_status(
            conn, delivery["delivery_key"], D_DELIVERED,
            "dispatcher", now, delivered_at=now,
            receipt=result.receipt)
        return D_DELIVERED

    if outcome == O_UNKNOWN:
        conn.execute(
            "UPDATE delivery_attempts SET status=?, completed_at=?,"
            " error_code=?, error_detail_safe=?,"
            " transport_metadata_json=? WHERE attempt_id=?",
            (A_UNKNOWN, now, result.error_code,
             _truncate(result.error_detail_safe, 200),
             json.dumps(result.receipt or {}, sort_keys=True),
             attempt_id))
        _set_delivery_status(
            conn, delivery["delivery_key"], D_UNKNOWN,
            "dispatcher", now, note=result.error_code)
        return D_UNKNOWN

    retryable = outcome == O_FAILED_RETRYABLE
    max_attempts = int(retry_cfg.get("max_attempts", 5))
    exhausted = retryable and attempt_number >= max_attempts
    new_status = (D_FAILED_RETRYABLE if retryable and not exhausted
                  else D_FAILED_PERMANENT)
    error_code = result.error_code or (
        "RETRY_EXHAUSTED" if exhausted else "DELIVERY_FAILED")
    if exhausted:
        error_code = "RETRY_EXHAUSTED"
    metadata = dict(result.receipt or {})
    if result.retry_after_seconds is not None:
        metadata["retry_after_seconds"] = result.retry_after_seconds
    conn.execute(
        "UPDATE delivery_attempts SET status=?, completed_at=?,"
        " retryable=?, error_code=?, error_detail_safe=?,"
        " transport_metadata_json=? WHERE attempt_id=?",
        (A_FAILED, now, 1 if retryable else 0, error_code,
         _truncate(result.error_detail_safe, 200),
         json.dumps(metadata, sort_keys=True), attempt_id))
    if new_status == D_FAILED_RETRYABLE:
        delay = _retry_delay_seconds(retry_cfg, attempt_number)
        if result.retry_after_seconds is not None:
            delay = max(delay, int(result.retry_after_seconds))
        _set_delivery_status(
            conn, delivery["delivery_key"], new_status,
            "dispatcher", now, note=error_code,
            next_attempt_after=_iso_plus_seconds(now, delay))
    else:
        _set_delivery_status(
            conn, delivery["delivery_key"], new_status,
            "dispatcher", now, note=error_code)
    return new_status


def _recompute_aggregate(conn, alert_keys: set[str],
                         destinations: list[dict]) -> None:
    """Recalcula outbox.delivery_state como agregado del ledger.

    Solo cuenta deliveries de la generacion vigente
    (alert_semantic_sha256 + alert_state actuales) y solo destinos
    actualmente habilitados. Sin deliveries vigentes: conserva el
    estado previo.
    """
    for alert_key in alert_keys:
        row = conn.execute(
            "SELECT * FROM outbox WHERE alert_key=?",
            (alert_key,)).fetchone()
        if row is None:
            continue
        routed = [d["destination_id"] for d in destinations
                  if category_routed(
                      d.get("categories") or [], row["category"])]
        if not routed:
            continue
        marks = ",".join("?" for _ in routed)
        deliveries = conn.execute(
            f"SELECT status FROM deliveries WHERE alert_key=?"
            f" AND alert_semantic_sha256=? AND alert_state=?"
            f" AND destination_id IN ({marks})",
            (alert_key, row["semantic_sha256"], row["state"],
             *routed)).fetchall()
        if not deliveries:
            continue
        statuses = {d["status"] for d in deliveries}
        if statuses == {D_DELIVERED}:
            agg = "DELIVERED"
        elif statuses & {D_FAILED_PERMANENT, D_ABANDONED}:
            agg = "FAILED_DELIVERY"
        else:
            agg = "PENDING_DELIVERY"
        if agg != row["delivery_state"]:
            conn.execute(
                "UPDATE outbox SET delivery_state=? WHERE alert_key=?",
                (agg, alert_key))


def run_alert_deliver(state, conn, delivery_cfg: dict,
                      *, now_fn=None, adapters: dict | None = None,
                      only_delivery_key: str | None = None) -> dict:
    """Una pasada del dispatcher (P10.7).

    Requiere conn single-writer (run lock adquirido por el caller).
    Usa ``state.checkpoint()`` para persistir STARTED antes de cada
    side effect.

    ``adapters``: mapa adapter_type -> callable inyectable (tests).
    """
    now = (now_fn or _utcnow)()
    cfg = delivery_cfg or {}
    payload_policy = cfg.get("payload_policy") or {}
    retry_cfg = cfg.get("retry") or {}
    destinations = enabled_destinations(cfg)
    adapters = adapters or adapter_registry()

    if not cfg.get("enabled"):
        return {
            "schema": SCHEMA_DELIVERY_RESULT,
            "generated_at": now,
            "status": "DISABLED",
            "deliveries_created": 0,
            "attempted": 0,
            "succeeded": 0,
            "failed_retryable": 0,
            "failed_permanent": 0,
            "unknown": 0,
            "skipped_delivered": 0,
            "orphan_attempts_marked_unknown": 0,
            "per_destination": [],
        }

    orphans = _mark_orphan_attempts(conn, now)
    if orphans:
        state.checkpoint()

    # ---- derivacion ------------------------------------------------
    created = 0
    touched_alerts: set[str] = set()
    routed_dests = [d for d in destinations
                    if d["adapter"] in adapters]
    alert_rows = conn.execute(
        "SELECT * FROM outbox ORDER BY created_at").fetchall()
    for row in alert_rows:
        alert = dict(row)
        alert["payload"] = json.loads(row["payload_json"] or "{}")
        alert["evidence_refs"] = json.loads(
            row["evidence_refs_json"] or "[]")
        if alert["state"] not in ("OPEN", "CLEARED"):
            continue
        if alert["state"] == "CLEARED" and not payload_policy.get(
                "notify_on_clear", False):
            continue
        for dest in routed_dests:
            if not category_routed(
                    dest.get("categories") or [], alert["category"]):
                continue
            touched_alerts.add(alert["alert_key"])
            delivery, was_created = _derive_for_alert(
                conn, alert, dest, now, payload_policy)
            if delivery is not None and was_created:
                created += 1
    if created:
        state.checkpoint()

    # ---- dispatch --------------------------------------------------
    counters = {"attempted": 0, "succeeded": 0,
                "failed_retryable": 0, "failed_permanent": 0,
                "unknown": 0, "skipped_delivered": 0}
    per_dest: dict[str, dict] = {}

    all_deliveries = list_deliveries(conn)
    alert_cache = {r["alert_key"]: dict(r) for r in alert_rows}
    dest_by_id = {d["destination_id"]: d for d in routed_dests}

    for delivery in all_deliveries:
        dk = delivery["delivery_key"]
        if only_delivery_key and dk != only_delivery_key:
            continue
        if delivery["status"] == D_DELIVERED:
            counters["skipped_delivered"] += 1
            continue
        dest = dest_by_id.get(delivery["destination_id"])
        if dest is None:
            # destino retirado/deshabilitado: entrega congelada
            continue
        if not _is_eligible(delivery, now, retry_cfg):
            continue
        alert_row = alert_cache.get(delivery["alert_key"])
        if alert_row is None:
            continue

        attempt_number = int(delivery["attempt_count"]) + 1
        attempt_id = f"ATT-{dk}-{attempt_number}"
        started_at = (now_fn or _utcnow)()
        conn.execute(
            "INSERT INTO delivery_attempts"
            " (attempt_id, delivery_key, attempt_number, started_at,"
            "  status) VALUES (?,?,?,?,?)",
            (attempt_id, dk, attempt_number, started_at, A_STARTED))
        conn.execute(
            "UPDATE deliveries SET attempt_count=?, last_attempt_at=?"
            " WHERE delivery_key=?",
            (attempt_number, started_at, dk))
        conn.execute(
            "UPDATE outbox SET delivery_attempts="
            " delivery_attempts+1 WHERE alert_key=?",
            (delivery["alert_key"],))
        state.checkpoint()  # STARTED durable ANTES del side effect

        payload = _payload_for(delivery)
        request = DeliveryRequest(
            delivery_key=dk,
            alert_key=delivery["alert_key"],
            alert_semantic_sha256=delivery["alert_semantic_sha256"],
            alert_state=delivery["alert_state"],
            adapter_type=delivery["adapter_type"],
            destination_id=delivery["destination_id"],
            generation=delivery["generation"],
            payload_schema=SCHEMA_DELIVERY_PAYLOAD,
            payload=payload,
            created_at=delivery["first_created_at"],
            payload_bytes=(delivery["payload_json"] or "").encode(
                "utf-8"))
        deliver_fn = adapters[delivery["adapter_type"]]
        try:
            result = deliver_fn(request, dest.get("config") or {})
        except Exception as exc:  # noqa: BLE001 — adapter bug => permanente
            result = AdapterResult(
                O_FAILED_PERMANENT, error_code="ADAPTER_ERROR",
                error_detail_safe=(
                    f"{exc.__class__.__name__}:{exc}")[:200])
        new_status = _record_attempt(
            conn, {**delivery, "attempt_count": attempt_number},
            result, attempt_number,
            now=(now_fn or _utcnow)(), retry_cfg=retry_cfg)
        counters["attempted"] += 1
        key = {D_DELIVERED: "succeeded",
               D_FAILED_RETRYABLE: "failed_retryable",
               D_FAILED_PERMANENT: "failed_permanent",
               D_UNKNOWN: "unknown"}[new_status]
        counters[key] += 1
        touched_alerts.add(delivery["alert_key"])
        pd = per_dest.setdefault(delivery["destination_id"], {
            "destination_id": delivery["destination_id"],
            "adapter": delivery["adapter_type"],
            "attempted": 0, "succeeded": 0,
            "failed_retryable": 0, "failed_permanent": 0,
            "unknown": 0})
        pd["attempted"] += 1
        pd[key] += 1
        state.checkpoint()

    # ---- agregado outbox -------------------------------------------
    _recompute_aggregate(conn, touched_alerts, routed_dests)

    if counters["attempted"] == 0 and created == 0 and orphans == 0:
        status = "UNCHANGED"
    elif counters["failed_permanent"] or counters["unknown"]:
        status = "PARTIAL"
    elif counters["failed_retryable"]:
        status = "PARTIAL"
    else:
        status = "SUCCESS"

    return {
        "schema": SCHEMA_DELIVERY_RESULT,
        "generated_at": (now_fn or _utcnow)(),
        "status": status,
        "deliveries_created": created,
        "attempted": counters["attempted"],
        "succeeded": counters["succeeded"],
        "failed_retryable": counters["failed_retryable"],
        "failed_permanent": counters["failed_permanent"],
        "unknown": counters["unknown"],
        "skipped_delivered": counters["skipped_delivered"],
        "orphan_attempts_marked_unknown": orphans,
        "per_destination": [per_dest[k] for k in sorted(per_dest)],
    }


# ------------------------------------------------------------------
# operator controls (P10.8/P10.13)
# ------------------------------------------------------------------

def delivery_retry(conn, delivery_key: str, *, now: str,
                   actor: str = "operator",
                   force_unknown: bool = False) -> dict:
    """Re-elegibiliza una entrega (nunca intenta inline).

    FAILED_RETRYABLE/FAILED_PERMANENT -> PENDING (audit).
    UNKNOWN_OUTCOME solo con force_unknown=True.
    DELIVERED/ABANDONED -> error.
    """
    d = get_delivery(conn, delivery_key)
    if d is None:
        raise ValueError(f"DELIVERY_NOT_FOUND:{delivery_key}")
    status = d["status"]
    if status == D_DELIVERED:
        raise ValueError(f"DELIVERY_ALREADY_DELIVERED:{delivery_key}")
    if status == D_ABANDONED:
        raise ValueError(f"DELIVERY_ABANDONED:{delivery_key}")
    if status == D_UNKNOWN and not force_unknown:
        raise ValueError(
            f"DELIVERY_UNKNOWN_REQUIRES_FORCE:{delivery_key}")
    _set_delivery_status(
        conn, delivery_key, D_PENDING, actor, now,
        note="MANUAL_RETRY" + (
            "_FORCE_UNKNOWN" if status == D_UNKNOWN else ""),
        next_attempt_after=None)
    return get_delivery(conn, delivery_key)


def delivery_abandon(conn, delivery_key: str, *, now: str,
                     actor: str = "operator",
                     note: str | None = None) -> dict:
    """ABANDONED: decision operadora terminal; nunca toca la alerta."""
    d = get_delivery(conn, delivery_key)
    if d is None:
        raise ValueError(f"DELIVERY_NOT_FOUND:{delivery_key}")
    if d["status"] == D_DELIVERED:
        raise ValueError(f"DELIVERY_ALREADY_DELIVERED:{delivery_key}")
    _set_delivery_status(
        conn, delivery_key, D_ABANDONED, actor, now,
        note=note or "MANUAL_ABANDON")
    return get_delivery(conn, delivery_key)


# ------------------------------------------------------------------
# status doc (P10.11)
# ------------------------------------------------------------------

def delivery_status_doc(state, conn, delivery_cfg: dict | None,
                        *, now: str | None = None) -> dict:
    """CA_ES_DELIVERY_STATUS_V1 — salud del subsistema, separada
    del health del runtime de negocio."""
    now = now or _utcnow()
    cfg = delivery_cfg or {}
    enabled = bool(cfg.get("enabled"))
    destinations = enabled_destinations(cfg)

    rows = list_deliveries(conn)
    counts = {s: 0 for s in (D_PENDING, D_DELIVERED,
                             D_FAILED_RETRYABLE, D_FAILED_PERMANENT,
                             D_UNKNOWN, D_ABANDONED)}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    pending_ages = []
    for r in rows:
        if r["status"] == D_PENDING and r.get("first_created_at"):
            pending_ages.append(r["first_created_at"])
    oldest_pending = min(pending_ages) if pending_ages else None

    attempts = conn.execute(
        "SELECT COUNT(*) c FROM delivery_attempts").fetchone()["c"]
    per_dest: dict[str, dict] = {}
    for r in rows:
        e = per_dest.setdefault(r["destination_id"], {
            "destination_id": r["destination_id"],
            "adapter_type": r["adapter_type"],
            "configured": r["destination_id"] in {
                d["destination_id"] for d in destinations},
            "deliveries": 0, "delivered": 0, "pending": 0,
            "failed_retryable": 0, "failed_permanent": 0,
            "unknown": 0, "abandoned": 0})
        e["deliveries"] += 1
        for status_key, col in (
                (D_DELIVERED, "delivered"), (D_PENDING, "pending"),
                (D_FAILED_RETRYABLE, "failed_retryable"),
                (D_FAILED_PERMANENT, "failed_permanent"),
                (D_UNKNOWN, "unknown"), (D_ABANDONED, "abandoned")):
            if r["status"] == status_key:
                e[col] += 1

    if not enabled:
        status = "DISABLED"
    elif counts[D_FAILED_PERMANENT] or counts[D_UNKNOWN]:
        status = "FAILED"
    elif counts[D_FAILED_RETRYABLE] or counts[D_PENDING]:
        status = "DEGRADED"
    else:
        status = "HEALTHY"

    return {
        "schema": SCHEMA_DELIVERY_STATUS,
        "generated_at": now,
        "status": status,
        "enabled": enabled,
        "pending_deliveries": counts[D_PENDING],
        "delivered": counts[D_DELIVERED],
        "retryable_failures": counts[D_FAILED_RETRYABLE],
        "permanent_failures": counts[D_FAILED_PERMANENT],
        "unknown_outcomes": counts[D_UNKNOWN],
        "abandoned": counts[D_ABANDONED],
        "oldest_pending_at": oldest_pending,
        "total_attempts": attempts,
        "destinations": [
            per_dest[k] for k in sorted(per_dest)],
    }
