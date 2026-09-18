"""P11.6 — validacion fail-closed de la seccion `send`."""
from __future__ import annotations

import pytest

from ca_es.ops_config import (
    validate_ops_config, validate_send_config)

BASE = {
    "schema": "CA_ES_OPS_CONFIG_V1",
    "inputs": {},
    "action_queue": {"window_days": 5, "due_soon_days": 2},
}


def _send(**over):
    doc = {
        "enabled": True,
        "destinations": [{
            "destination_id": "gw-file-1",
            "adapter": "filespool",
            "enabled": True,
            "message_schemas": ["*"],
            "config": {"spool_directory": "var/spool"},
        }],
        "retry": {"max_attempts": 3, "base_delay_seconds": 60,
                  "max_delay_seconds": 600, "backoff_factor": 2.0},
        "send_policy": {"max_message_bytes": 65536},
    }
    doc.update(over)
    return doc


def test_valid_send_section():
    validate_send_config(_send())
    doc = dict(BASE, send=_send())
    validate_ops_config(doc)


def test_none_send_ok():
    validate_send_config(None)
    validate_ops_config(BASE)


def test_unknown_top_key_rejected():
    with pytest.raises(ValueError, match="unknown_key:send"):
        validate_send_config(_send(unknown_key=1))


def test_secretish_key_rejected():
    bad = _send()
    bad["password"] = "x"
    with pytest.raises(ValueError, match="secretish"):
        validate_send_config(bad)


def test_secretish_in_dest_config_rejected():
    bad = _send()
    bad["destinations"][0]["config"]["api_token"] = "x"
    with pytest.raises(ValueError, match="secretish"):
        validate_send_config(bad)


def test_env_suffix_keys_allowed():
    good = _send()
    good["destinations"][0]["config"]["spool_directory"] = "var/x"
    validate_send_config(good)


def test_unknown_adapter_rejected():
    bad = _send()
    bad["destinations"][0]["adapter"] = "mq"
    with pytest.raises(ValueError, match="adapter"):
        validate_send_config(bad)


def test_missing_spool_directory_rejected():
    bad = _send()
    bad["destinations"][0]["config"] = {}
    with pytest.raises(ValueError, match="missing:spool_directory"):
        validate_send_config(bad)


def test_unknown_adapter_config_key_rejected():
    bad = _send()
    bad["destinations"][0]["config"]["queue_manager"] = "QM1"
    with pytest.raises(ValueError, match="unknown_key"):
        validate_send_config(bad)


def test_duplicate_destination_id_rejected():
    bad = _send()
    bad["destinations"].append(dict(bad["destinations"][0]))
    with pytest.raises(ValueError, match="duplicate_destination"):
        validate_send_config(bad)


def test_message_schemas_required_list():
    bad = _send()
    del bad["destinations"][0]["message_schemas"]
    with pytest.raises(ValueError, match="message_schemas"):
        validate_send_config(bad)


def test_retry_validation():
    bad = _send()
    bad["retry"]["max_attempts"] = 0
    with pytest.raises(ValueError, match="max_attempts"):
        validate_send_config(bad)


def test_send_policy_validation():
    bad = _send()
    bad["send_policy"]["max_message_bytes"] = -1
    with pytest.raises(ValueError, match="max_message_bytes"):
        validate_send_config(bad)


def test_send_section_in_full_config():
    doc = dict(BASE, send={"enabled": False})
    validate_ops_config(doc)
