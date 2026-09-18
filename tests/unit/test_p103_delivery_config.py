"""P10.3 — delivery config: whitelist fail-closed, secretos
rechazados, routing categories, adapters conocidos."""
from __future__ import annotations

import pytest

from ca_es.ops_config import validate_ops_config

BASE = {"schema": "CA_ES_OPS_CONFIG_V1",
        "action_queue": {"window_days": 30, "due_soon_days": 7}}


def _cfg(delivery):
    return dict(BASE, delivery=delivery)


def _dest(**kw):
    base = {"destination_id": "d1", "adapter": "file",
            "enabled": True, "categories": ["*"],
            "config": {"directory": "/tmp/x"}}
    base.update(kw)
    return base


def test_no_delivery_section_ok():
    validate_ops_config(BASE)


def test_delivery_disabled_ok():
    validate_ops_config(_cfg({"enabled": False}))


def test_valid_file_destination():
    validate_ops_config(_cfg({
        "enabled": True,
        "destinations": [_dest()]}))


def test_valid_webhook_destination():
    validate_ops_config(_cfg({
        "enabled": True,
        "destinations": [_dest(
            adapter="webhook",
            config={"url_env": "CA_ES_WEBHOOK_URL",
                    "token_env": "CA_ES_WEBHOOK_TOKEN",
                    "timeout_seconds": 5})],
        "retry": {"max_attempts": 3, "base_delay_seconds": 60,
                  "max_delay_seconds": 600, "backoff_factor": 2.0},
        "payload_policy": {"max_payload_bytes": 8192,
                           "notify_on_clear": True}}))


def test_unknown_top_key_rejected():
    with pytest.raises(ValueError, match="unknown_key"):
        validate_ops_config(_cfg({
            "enabled": True, "surprise": 1}))


def test_unknown_destination_key_rejected():
    with pytest.raises(ValueError, match="unknown_key"):
        validate_ops_config(_cfg({
            "enabled": True,
            "destinations": [_dest(foo=1)]}))


def test_unknown_adapter_rejected():
    with pytest.raises(ValueError, match="adapter"):
        validate_ops_config(_cfg({
            "enabled": True,
            "destinations": [_dest(adapter="slack")]}))


def test_unknown_adapter_config_key_rejected():
    with pytest.raises(ValueError, match="unknown_key"):
        validate_ops_config(_cfg({
            "enabled": True,
            "destinations": [_dest(config={"directory": "/x",
                                           "bogus": 1})]}))


def test_plaintext_password_rejected():
    with pytest.raises(ValueError, match="secretish"):
        validate_ops_config(_cfg({
            "enabled": True,
            "destinations": [_dest(
                adapter="smtp",
                config={"host": "h", "port": 587,
                        "security": "starttls",
                        "from_address": "a@b.c",
                        "to_addresses": ["x@y.z"],
                        "password": "cleartext"})]}))


def test_plaintext_token_rejected():
    with pytest.raises(ValueError, match="secretish"):
        validate_ops_config(_cfg({
            "enabled": True,
            "destinations": [_dest(
                adapter="webhook",
                config={"url": "https://h/x", "token": "abc"})]}))


def test_env_suffixed_secret_names_allowed():
    validate_ops_config(_cfg({
        "enabled": True,
        "destinations": [_dest(
            adapter="smtp",
            config={"host": "h", "port": 587, "security": "smtps",
                    "from_address": "a@b.c",
                    "to_addresses": ["x@y.z"],
                    "username_env": "U", "password_env": "P"})]}))


def test_duplicate_destination_id_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        validate_ops_config(_cfg({
            "enabled": True,
            "destinations": [_dest(), _dest()]}))


def test_missing_categories_rejected():
    dest = _dest()
    del dest["categories"]
    with pytest.raises(ValueError, match="categories"):
        validate_ops_config(_cfg({
            "enabled": True, "destinations": [dest]}))


def test_bad_retry_values_rejected():
    with pytest.raises(ValueError, match="max_attempts"):
        validate_ops_config(_cfg({
            "enabled": True,
            "retry": {"max_attempts": 0}}))
    with pytest.raises(ValueError, match="backoff_factor"):
        validate_ops_config(_cfg({
            "enabled": True,
            "retry": {"backoff_factor": 0.5}}))


def test_bad_max_payload_bytes_rejected():
    with pytest.raises(ValueError, match="max_payload_bytes"):
        validate_ops_config(_cfg({
            "enabled": True,
            "payload_policy": {"max_payload_bytes": -1}}))


def test_destinations_not_list_rejected():
    with pytest.raises(ValueError, match="destinations"):
        validate_ops_config(_cfg({
            "enabled": True, "destinations": {"d1": {}}}))
