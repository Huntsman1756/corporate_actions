"""P7.2 — CA_ES_OPS_CONFIG_V1: validacion fail-closed del config.

Sin secretos en config; claves desconocidas -> error; ningun
default introduce semantica de negocio.
"""

from __future__ import annotations

from typing import Any

OPS_CONFIG_SCHEMA = "CA_ES_OPS_CONFIG_V1"

_TOP_KEYS = {
    "schema", "inputs", "action_queue", "reconciliation",
    "inbox", "health", "alerts", "lineage", "sources",
}
_INPUT_KEYS = {
    "canon", "source_policy", "positions", "deadline_rules",
    "calendars", "cash_movements", "impact_rules",
    "election_rules", "instructions",
}
_ACTION_QUEUE_KEYS = {"window_days", "due_soon_days"}
_RECON_KEYS = {"events"}
_INBOX_KEYS = {"path"}
_HEALTH_KEYS = {"positions_max_age_days", "canon_max_age_hours",
                "source_checkpoint_max_age_days"}
_ALERT_KEYS = {"enabled"}
_LINEAGE_KEYS = {"enabled", "required", "path"}

_SOURCES_KEYS = {
    "enabled", "adapters", "timeout_seconds", "retries",
    "politeness_seconds", "max_bytes", "stale_after_days",
}
_SOURCES_ADAPTER_KEYS = {
    "adapter", "portal", "source_id", "surface_id",
    "enabled", "required", "desde", "hasta",
    "overlap_days", "refetch_known", "kinds", "index_url",
}
_SECTION_KEYS = {
    "inputs": _INPUT_KEYS,
    "action_queue": _ACTION_QUEUE_KEYS,
    "reconciliation": _RECON_KEYS,
    "inbox": _INBOX_KEYS,
    "health": _HEALTH_KEYS,
    "alerts": _ALERT_KEYS,
    "lineage": _LINEAGE_KEYS,
    "sources": _SOURCES_KEYS,
}


def _reject_unknown(name: str, obj: dict, allowed: set) -> None:
    unknown = set(obj) - allowed
    if unknown:
        raise ValueError(
            f"INVALID_OPS_CONFIG:unknown_key:{name}:"
            f"{sorted(unknown)[0]}")


def validate_ops_config(doc: Any) -> dict:
    """Valida y devuelve el config normalizado. Fail-closed."""
    if not isinstance(doc, dict) or doc.get("schema") != \
            OPS_CONFIG_SCHEMA:
        raise ValueError("INVALID_OPS_CONFIG:schema")
    _reject_unknown("top", doc, _TOP_KEYS)

    inputs = doc.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise ValueError("INVALID_OPS_CONFIG:inputs")
    _reject_unknown("inputs", inputs, _INPUT_KEYS)
    for name, spec in inputs.items():
        if not isinstance(spec, dict):
            raise ValueError(f"INVALID_OPS_CONFIG:input:{name}")
        _reject_unknown(f"input:{name}", spec,
                        {"path", "paths", "required"})
        if not spec.get("path") and not spec.get("paths"):
            raise ValueError(f"INVALID_OPS_CONFIG:input:{name}:path")

    for section in ("action_queue", "reconciliation", "inbox",
                    "health", "alerts", "lineage", "sources"):
        sub = doc.get(section)
        if sub is None:
            continue
        if not isinstance(sub, dict):
            raise ValueError(f"INVALID_OPS_CONFIG:{section}")
        _reject_unknown(section, sub, _SECTION_KEYS[section])

    sources = doc.get("sources") or {}
    adapters = sources.get("adapters") or {}
    if not isinstance(adapters, dict):
        raise ValueError("INVALID_OPS_CONFIG:sources:adapters")
    for name, spec in adapters.items():
        if not isinstance(spec, dict):
            raise ValueError(
                f"INVALID_OPS_CONFIG:sources:adapters:{name}")
        _reject_unknown(
            f"sources:adapters:{name}", spec, _SOURCES_ADAPTER_KEYS)
        if not spec.get("source_id") or not spec.get("surface_id"):
            raise ValueError(
                f"INVALID_OPS_CONFIG:sources:adapters:{name}:"
                "identity")

    aq = doc.get("action_queue") or {}
    for k in ("window_days", "due_soon_days"):
        v = aq.get(k)
        if not isinstance(v, int) or v < 0:
            raise ValueError(f"INVALID_OPS_CONFIG:action_queue:{k}")

    health = doc.get("health") or {}
    for k, v in health.items():
        if not isinstance(v, (int, float)) or v < 0:
            raise ValueError(f"INVALID_OPS_CONFIG:health:{k}")

    return doc


def input_required(config: dict, name: str) -> bool:
    spec = (config.get("inputs") or {}).get(name)
    return bool(spec and spec.get("required"))


def input_path(config: dict, name: str) -> str | None:
    spec = (config.get("inputs") or {}).get(name)
    return spec.get("path") if spec else None
