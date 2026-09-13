from __future__ import annotations

import pytest

from ca_es.canonical import canonical_json, sha256_hex, strict_json_loads


def test_float_rejected_in_canonical_json():
    with pytest.raises(ValueError):
        canonical_json({"amount": 1.5})


def test_duplicate_keys_rejected():
    with pytest.raises(ValueError):
        strict_json_loads('{"a":1,"a":2}')


def test_float_rejected_when_loading():
    with pytest.raises(ValueError):
        strict_json_loads('{"amount": 1.5}')


def test_key_order_does_not_affect_hash():
    assert sha256_hex({"a": 1, "b": 2}) == sha256_hex({"b": 2, "a": 1})
