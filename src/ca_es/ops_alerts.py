"""P7.4 — Alert outbox (CA_ES_ALERT_OUTBOX_V1).

docs/p7/p74-alerts.md. Identidad estable `category|subject_key`;
state (OPEN/CLEARED) y delivery_state (PENDING_DELIVERY/
DELIVERED/FAILED_DELIVERY) son ejes separados. Nunca envia nada:
solo persiste registros para un conector futuro.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from .semantic_hash import semantic_sha256

OUTBOX_SCHEMA = "CA_ES_ALERT_OUTBOX_V1"

OPEN = "OPEN"
CLEARED = "CLEARED"
PENDING_DELIVERY = "PENDING_DELIVERY"
DELIVERED = "DELIVERED"
FAILED_DELIVERY = "FAILED_DELIVERY"

DEADLINE_CATEGORIES = {
    "OVERDUE": "DEADLINE_OVERDUE",
    "DUE_TODAY": "DEADLINE_DUE_TODAY",
    "DUE_SOON": "DEADLINE_DUE_SOON",
}


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat(
    ).replace("+00:00", "Z")


def _candidate(category: str, subject_type: str, subject_key: str,
               payload: dict, evidence_refs: list) -> dict:
    return {
        "alert_key": f"{category}|{subject_key}",
        "category": category,
        "subject_type": subject_type,
        "subject_key": subject_key,
        "payload": payload,
        "evidence_refs": evidence_refs,
        "semantic_sha256": semantic_sha256(payload),
    }


def derive_deadline_alerts(queue_doc: dict,
                           queue_ref: dict | None) -> list[dict]:
    """Items OVERDUE/DUE_TODAY/DUE_SOON -> alertas por deadline."""
    refs = [queue_ref["sha256"]] if queue_ref else []
    out = []
    for item in queue_doc.get("items") or []:
        cat = DEADLINE_CATEGORIES.get(item.get("action_status"))
        if cat is None:
            continue
        out.append(_candidate(
            cat, "deadline", item["deadline_key"], {
                "canonical_event_id": item.get("canonical_event_id"),
                "deadline_type": item.get("deadline_type"),
                "deadline_date": item.get("deadline_date"),
                "action_status": item.get("action_status"),
                "days_until": item.get("days_until"),
            }, refs))
    return out


def derive_exception_alerts(cases_doc: dict,
                            cases_ref: dict | None) -> list[dict]:
    """Casos con workflow OPEN -> una alerta por case_key."""
    refs = [cases_ref["sha256"]] if cases_ref else []
    out = []
    for case in cases_doc.get("cases") or []:
        if case.get("workflow_status") != "OPEN":
            continue
        history = case.get("history") or []
        last_action = history[-1]["type"] if history else None
        out.append(_candidate(
            "EXCEPTION_CASE", "exception_case",
            case["case_key"], {
                "canonical_event_id":
                    case.get("canonical_event_id"),
                "factual_status": case.get("factual_status"),
                "workflow_status": case.get("workflow_status"),
                "reason_codes": case.get("reason_codes"),
                "last_action": last_action,
            }, refs))
    return out


def derive_inbox_alerts(inbox_doc: dict,
                        inbox_ref: dict | None) -> list[dict]:
    """Mensajes FAILED del scan -> una alerta por input_sha256."""
    refs = [inbox_ref["sha256"]] if inbox_ref else []
    out = []
    for msg in inbox_doc.get("messages") or []:
        if msg.get("processing_status") != "FAILED":
            continue
        out.append(_candidate(
            "PROCESSING_FAILURE", "inbox_message",
            msg["input_sha256"], {
                "message_identifier":
                    msg.get("message_identifier"),
                "processing_status": "FAILED",
            }, refs))
    return out


def run_failed_candidate(run_id: str, error_summary) -> dict:
    return _candidate(
        "RUN_FAILED", "run", run_id,
        {"run_id": run_id, "error_summary": error_summary}, [])


def apply_alerts(conn, candidates: list[dict], run_id: str,
                 evaluated_categories: set[str],
                 now: str | None = None) -> dict:
    """Upsert por alert_key + clear de categorias evaluadas.

    Devuelve {new, reopened, updated, cleared, unchanged}.
    """
    ts = now or _utcnow()
    stats = {"new": 0, "reopened": 0, "updated": 0,
             "cleared": 0, "unchanged": 0}
    seen_keys = set()
    for c in candidates:
        seen_keys.add(c["alert_key"])
        row = conn.execute(
            "SELECT * FROM outbox WHERE alert_key=?",
            (c["alert_key"],)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO outbox(alert_key, category,"
                " subject_type, subject_key, state,"
                " first_observed_run_id, last_observed_run_id,"
                " payload_json, evidence_refs_json,"
                " semantic_sha256, delivery_state,"
                " delivery_attempts, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
                (c["alert_key"], c["category"], c["subject_type"],
                 c["subject_key"], OPEN, run_id, run_id,
                 json.dumps(c["payload"], sort_keys=True),
                 json.dumps(c["evidence_refs"], sort_keys=True),
                 c["semantic_sha256"], PENDING_DELIVERY,
                 ts, ts))
            stats["new"] += 1
            continue
        if row["state"] == CLEARED:
            conn.execute(
                "UPDATE outbox SET state=?, payload_json=?,"
                " evidence_refs_json=?, semantic_sha256=?,"
                " last_observed_run_id=?, delivery_state=?,"
                " updated_at=? WHERE alert_key=?",
                (OPEN, json.dumps(c["payload"], sort_keys=True),
                 json.dumps(c["evidence_refs"], sort_keys=True),
                 c["semantic_sha256"], run_id, PENDING_DELIVERY,
                 ts, c["alert_key"]))
            stats["reopened"] += 1
            continue
        if row["semantic_sha256"] == c["semantic_sha256"]:
            # mismo hecho: solo marca observacion; NO rearma
            # delivery (segundo run identico no re-notifica)
            conn.execute(
                "UPDATE outbox SET last_observed_run_id=?,"
                " updated_at=? WHERE alert_key=?",
                (run_id, ts, c["alert_key"]))
            stats["unchanged"] += 1
            continue
        # hechos cambiados: misma identidad, payload nuevo,
        # delivery rearma
        conn.execute(
            "UPDATE outbox SET payload_json=?,"
            " evidence_refs_json=?, semantic_sha256=?,"
            " last_observed_run_id=?, delivery_state=?,"
            " updated_at=? WHERE alert_key=?",
            (json.dumps(c["payload"], sort_keys=True),
             json.dumps(c["evidence_refs"], sort_keys=True),
             c["semantic_sha256"], run_id, PENDING_DELIVERY,
             ts, c["alert_key"]))
        stats["updated"] += 1

    # clear: alertas OPEN de categorias evaluadas que no reaparecen
    if evaluated_categories:
        marks = ",".join("?" for _ in evaluated_categories)
        rows = conn.execute(
            f"SELECT alert_key FROM outbox WHERE state=?"
            f" AND category IN ({marks})",
            (OPEN, *sorted(evaluated_categories))).fetchall()
        for r in rows:
            if r["alert_key"] in seen_keys:
                continue
            conn.execute(
                "UPDATE outbox SET state=?, updated_at=?"
                " WHERE alert_key=?",
                (CLEARED, ts, r["alert_key"]))
            stats["cleared"] += 1
    return stats


def pending_outbox(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM outbox"
        " WHERE delivery_state='PENDING_DELIVERY'"
        " ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


def outbox_all(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM outbox ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]
