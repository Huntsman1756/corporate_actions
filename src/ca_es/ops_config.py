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
    "delivery", "send",
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
    "delivery": {"enabled", "destinations", "retry", "payload_policy"},
    "send": {"enabled", "destinations", "retry", "send_policy"},
}

# ------------------------------------------------------------------
# P10 — delivery (docs/p10/p103-delivery-policy.md)
# ------------------------------------------------------------------

_DELIVERY_RETRY_KEYS = {
    "max_attempts", "base_delay_seconds", "max_delay_seconds",
    "backoff_factor"}
_DELIVERY_PAYLOAD_POLICY_KEYS = {
    "max_payload_bytes", "notify_on_open", "notify_on_change",
    "notify_on_clear"}
_DELIVERY_DEST_KEYS = {
    "destination_id", "adapter", "enabled", "categories", "config"}
_DELIVERY_ADAPTERS = {"file", "webhook", "smtp"}

_DELIVERY_ADAPTER_CONFIG_KEYS = {
    "file": {"directory"},
    "webhook": {
        "url", "url_env", "token_env", "timeout_seconds",
        "max_response_bytes", "expected_statuses", "max_redirects",
        "host_allowlist", "allow_insecure_http", "extra_headers"},
    "smtp": {
        "host", "port", "security", "username_env", "password_env",
        "from_address", "to_addresses", "message_id_domain",
        "timeout_seconds", "allow_plaintext_localhost"},
}

# ------------------------------------------------------------------
# P11 — send (docs/p11/p112-send-ledger.md)
# ------------------------------------------------------------------

_SEND_RETRY_KEYS = {
    "max_attempts", "base_delay_seconds", "max_delay_seconds",
    "backoff_factor"}
_SEND_POLICY_KEYS = {"max_message_bytes"}
_SEND_DEST_KEYS = {
    "destination_id", "adapter", "enabled", "message_schemas",
    "config"}
_SEND_ADAPTERS = {"filespool"}

_SEND_ADAPTER_CONFIG_KEYS = {
    "filespool": {"spool_directory"},
}
_SEND_ADAPTER_REQUIRED = {
    "filespool": {"spool_directory"},
}

_SECRETISH = (
    "password", "passwd", "token", "api_key", "apikey",
    "authorization", "secret", "credential", "bearer")


def _reject_secretish(name: str, obj: dict) -> None:
    for key in obj:
        k = str(key).lower()
        if k.endswith("_env"):
            continue
        if any(marker in k for marker in _SECRETISH):
            raise ValueError(
                f"INVALID_OPS_CONFIG:{name}:secretish_key:{key}")


def _validate_delivery(doc: dict) -> None:
    validate_delivery_config(doc.get("delivery"))


def validate_delivery_config(delivery) -> None:
    """Valida solo la seccion `delivery` (fail-closed).

    Exportada para `alert-deliver`, que no exige el doc
    CA_ES_OPS_CONFIG_V1 completo.
    """
    if delivery is None:
        return
    if not isinstance(delivery, dict):
        raise ValueError("INVALID_OPS_CONFIG:delivery")
    _reject_unknown("delivery", delivery, _SECTION_KEYS["delivery"])
    _reject_secretish("delivery", delivery)

    retry = delivery.get("retry") or {}
    if not isinstance(retry, dict):
        raise ValueError("INVALID_OPS_CONFIG:delivery:retry")
    _reject_unknown("delivery:retry", retry, _DELIVERY_RETRY_KEYS)
    if "max_attempts" in retry and (
            not isinstance(retry["max_attempts"], int)
            or retry["max_attempts"] < 1):
        raise ValueError(
            "INVALID_OPS_CONFIG:delivery:retry:max_attempts")
    for k in ("base_delay_seconds", "max_delay_seconds"):
        if k in retry and (
                not isinstance(retry[k], (int, float))
                or retry[k] < 0):
            raise ValueError(f"INVALID_OPS_CONFIG:delivery:retry:{k}")
    if "backoff_factor" in retry and (
            not isinstance(retry["backoff_factor"], (int, float))
            or retry["backoff_factor"] < 1.0):
        raise ValueError(
            "INVALID_OPS_CONFIG:delivery:retry:backoff_factor")

    pp = delivery.get("payload_policy") or {}
    if not isinstance(pp, dict):
        raise ValueError("INVALID_OPS_CONFIG:delivery:payload_policy")
    _reject_unknown(
        "delivery:payload_policy", pp, _DELIVERY_PAYLOAD_POLICY_KEYS)
    if "max_payload_bytes" in pp and (
            not isinstance(pp["max_payload_bytes"], int)
            or pp["max_payload_bytes"] <= 0):
        raise ValueError(
            "INVALID_OPS_CONFIG:delivery:payload_policy:"
            "max_payload_bytes")

    destinations = delivery.get("destinations") or []
    if not isinstance(destinations, list):
        raise ValueError("INVALID_OPS_CONFIG:delivery:destinations")
    seen_ids = set()
    for i, dest in enumerate(destinations):
        name = f"delivery:destinations[{i}]"
        if not isinstance(dest, dict):
            raise ValueError(f"INVALID_OPS_CONFIG:{name}")
        _reject_unknown(name, dest, _DELIVERY_DEST_KEYS)
        _reject_secretish(name, dest)
        dest_id = dest.get("destination_id")
        if not dest_id or not isinstance(dest_id, str):
            raise ValueError(
                f"INVALID_OPS_CONFIG:{name}:destination_id")
        if dest_id in seen_ids:
            raise ValueError(
                f"INVALID_OPS_CONFIG:{name}:duplicate_destination_id")
        seen_ids.add(dest_id)
        adapter = dest.get("adapter")
        if adapter not in _DELIVERY_ADAPTERS:
            raise ValueError(f"INVALID_OPS_CONFIG:{name}:adapter")
        cats = dest.get("categories")
        if not isinstance(cats, list) or not all(
                isinstance(c, str) for c in cats):
            raise ValueError(f"INVALID_OPS_CONFIG:{name}:categories")
        cfg = dest.get("config") or {}
        if not isinstance(cfg, dict):
            raise ValueError(f"INVALID_OPS_CONFIG:{name}:config")
        _reject_secretish(f"{name}:config", cfg)
        _reject_unknown(
            f"{name}:config", cfg,
            _DELIVERY_ADAPTER_CONFIG_KEYS[adapter])


def _validate_send(doc: dict) -> None:
    validate_send_config(doc.get("send"))


def validate_send_config(send) -> None:
    """Valida solo la seccion `send` (fail-closed).

    Exportada para los comandos send-*, que no exigen el doc
    CA_ES_OPS_CONFIG_V1 completo.
    """
    if send is None:
        return
    if not isinstance(send, dict):
        raise ValueError("INVALID_OPS_CONFIG:send")
    _reject_secretish("send", send)
    _reject_unknown("send", send, _SECTION_KEYS["send"])

    retry = send.get("retry") or {}
    if not isinstance(retry, dict):
        raise ValueError("INVALID_OPS_CONFIG:send:retry")
    _reject_unknown("send:retry", retry, _SEND_RETRY_KEYS)
    if "max_attempts" in retry and (
            not isinstance(retry["max_attempts"], int)
            or retry["max_attempts"] < 1):
        raise ValueError(
            "INVALID_OPS_CONFIG:send:retry:max_attempts")
    for k in ("base_delay_seconds", "max_delay_seconds"):
        if k in retry and (
                not isinstance(retry[k], (int, float))
                or retry[k] < 0):
            raise ValueError(f"INVALID_OPS_CONFIG:send:retry:{k}")
    if "backoff_factor" in retry and (
            not isinstance(retry["backoff_factor"], (int, float))
            or retry["backoff_factor"] < 1.0):
        raise ValueError(
            "INVALID_OPS_CONFIG:send:retry:backoff_factor")

    sp = send.get("send_policy") or {}
    if not isinstance(sp, dict):
        raise ValueError("INVALID_OPS_CONFIG:send:send_policy")
    _reject_unknown("send:send_policy", sp, _SEND_POLICY_KEYS)
    if "max_message_bytes" in sp and (
            not isinstance(sp["max_message_bytes"], int)
            or sp["max_message_bytes"] <= 0):
        raise ValueError(
            "INVALID_OPS_CONFIG:send:send_policy:max_message_bytes")

    destinations = send.get("destinations") or []
    if not isinstance(destinations, list):
        raise ValueError("INVALID_OPS_CONFIG:send:destinations")
    seen_ids = set()
    for i, dest in enumerate(destinations):
        name = f"send:destinations[{i}]"
        if not isinstance(dest, dict):
            raise ValueError(f"INVALID_OPS_CONFIG:{name}")
        _reject_secretish(name, dest)
        _reject_unknown(name, dest, _SEND_DEST_KEYS)
        dest_id = dest.get("destination_id")
        if not dest_id or not isinstance(dest_id, str):
            raise ValueError(
                f"INVALID_OPS_CONFIG:{name}:destination_id")
        if dest_id in seen_ids:
            raise ValueError(
                f"INVALID_OPS_CONFIG:{name}:duplicate_destination_id")
        seen_ids.add(dest_id)
        adapter = dest.get("adapter")
        if adapter not in _SEND_ADAPTERS:
            raise ValueError(f"INVALID_OPS_CONFIG:{name}:adapter")
        schemas = dest.get("message_schemas")
        if not isinstance(schemas, list) or not all(
                isinstance(s, str) for s in schemas):
            raise ValueError(
                f"INVALID_OPS_CONFIG:{name}:message_schemas")
        cfg = dest.get("config") or {}
        if not isinstance(cfg, dict):
            raise ValueError(f"INVALID_OPS_CONFIG:{name}:config")
        _reject_secretish(f"{name}:config", cfg)
        _reject_unknown(
            f"{name}:config", cfg,
            _SEND_ADAPTER_CONFIG_KEYS[adapter])
        missing = _SEND_ADAPTER_REQUIRED.get(adapter, set()) - \
            set(cfg)
        if missing:
            raise ValueError(
                f"INVALID_OPS_CONFIG:{name}:config:"
                f"missing:{sorted(missing)[0]}")


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
                    "health", "alerts", "lineage", "sources",
                    "delivery", "send"):
        sub = doc.get(section)
        if sub is None:
            continue
        if not isinstance(sub, dict):
            raise ValueError(f"INVALID_OPS_CONFIG:{section}")
        _reject_unknown(section, sub, _SECTION_KEYS[section])

    _validate_delivery(doc)
    _validate_send(doc)

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
