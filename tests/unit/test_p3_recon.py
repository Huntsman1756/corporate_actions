# -*- coding: utf-8 -*-
"""Tests P3.0: cash reconciliation — expected vs actual, sin
tolerancias, sin sumas silenciosas, INDETERMINATE nunca excepcion
falsa."""
import json
from decimal import Decimal
from pathlib import Path

import pytest

from ca_es.entitlement_engine import compute_entitlements
from ca_es.reconciliation import load_movements, reconcile
from ca_es.surface import Surface, load_surface

REPO = Path(__file__).resolve().parents[2]
CANON = REPO / "g3/input/canon.json"
POLICY = REPO / "docs/sources/source-policy.json"

SAN = "6443e2be-b70d-50c7-88d1-4a62f43789e9"
SAN_RECORD = "2026-05-04"
SAN_ISIN = "ESTIMACIONES"


@pytest.fixture(scope="module")
def surface() -> Surface:
    return load_surface(CANON, POLICY)


def _positions(*positions, as_of=None):
    doc = {"schema": "CA_ES_POSITIONS_V1", "positions": list(positions)}
    if as_of is not None:
        doc["as_of"] = as_of
    return doc


def _pos(account="A001", isin=SAN_ISIN, quantity="12500", as_of=SAN_RECORD):
    return {
        "account_id": account,
        "isin": isin,
        "quantity": quantity,
        "as_of": as_of,
    }


def _movements(*movements):
    return {
        "schema": "CA_ES_CASH_MOVEMENTS_V1",
        "movements": list(movements),
    }


def _mov(mid="MOV-1", account="A001", amount="1562.50",
         event_id=SAN, isin=None, currency="EUR",
         value_date="2026-05-06"):
    m = {
        "movement_id": mid,
        "account_id": account,
        "amount": amount,
        "currency": currency,
        "value_date": value_date,
    }
    if event_id is not None:
        m["event_id"] = event_id
    if isin is not None:
        m["isin"] = isin
    return m


def _entitlements(surface, *positions):
    return compute_entitlements(surface, SAN, _positions(*positions))


def _by_account(doc):
    return {i["account_id"]: i for i in doc["items"]}


# ------------------------------------------------------------------ match

def test_match_exact_amount(surface):
    ent = _entitlements(surface, _pos())
    recon = reconcile(ent, _movements(_mov()))
    item = recon["items"][0]
    assert item["status"] == "MATCH"
    assert item["expected_gross_cash"]["normalized"] == "1562.500"
    assert item["actual_amount"] == "1562.50"
    assert Decimal(item["delta"]["normalized"]) == 0
    assert item["movement_ids"] == ["MOV-1"]
    assert item["evidence"]["entitlement"]["assertion_ids"]
    assert item["evidence"]["movement_ids"] == ["MOV-1"]
    assert recon["summary"]["match"] == 1


def test_match_via_isin_reference(surface):
    # el movimiento referencia por isin en vez de event_id
    ent = _entitlements(surface, _pos())
    recon = reconcile(
        ent, _movements(_mov(event_id=None, isin=SAN_ISIN))
    )
    assert recon["items"][0]["status"] == "MATCH"


def test_amount_mismatch_exact_delta(surface):
    ent = _entitlements(surface, _pos())
    recon = reconcile(ent, _movements(_mov(amount="1500.00")))
    item = recon["items"][0]
    assert item["status"] == "AMOUNT_MISMATCH"
    # delta exacto: actual - expected = 1500.00 - 1562.500 = -62.5
    assert Decimal(item["delta"]["normalized"]) == Decimal("-62.5")
    assert item["delta"]["currency"] == "EUR"


def test_missing_cash(surface):
    ent = _entitlements(surface, _pos())
    recon = reconcile(ent, _movements())
    item = recon["items"][0]
    assert item["status"] == "MISSING_CASH"
    assert item["expected_gross_cash"]["normalized"] == "1562.500"


def test_unexpected_cash(surface):
    ent = _entitlements(surface, _pos())
    recon = reconcile(
        ent,
        _movements(
            _mov(),
            _mov(mid="MOV-X", account="A999", amount="10.00"),
        ),
    )
    items = _by_account(recon)
    assert items["A001"]["status"] == "MATCH"
    unexpected = items["A999"]
    assert unexpected["status"] == "UNEXPECTED_CASH"
    assert unexpected["actual_amount"] == "10.00"
    assert unexpected["evidence"]["entitlement"] is None


def test_currency_mismatch_is_missing_plus_unexpected(surface):
    ent = _entitlements(surface, _pos())
    recon = reconcile(
        ent, _movements(_mov(amount="1562.50", currency="USD"))
    )
    # el cash en USD no casa la clave EUR: expected sin cash + cash
    # sin expected — nunca match cross-currency silencioso
    missing = [
        i for i in recon["items"]
        if i["account_id"] == "A001" and i["status"] == "MISSING_CASH"
    ]
    assert len(missing) == 1
    unexpected = [
        i for i in recon["items"] if i["status"] == "UNEXPECTED_CASH"
    ]
    assert len(unexpected) == 1 and unexpected[0]["currency"] == "USD"


def test_multiple_movements_indeterminate(surface):
    ent = _entitlements(surface, _pos())
    recon = reconcile(
        ent,
        _movements(
            _mov(mid="MOV-1", amount="1000.00"),
            _mov(mid="MOV-2", amount="562.50"),
        ),
    )
    item = recon["items"][0]
    # la suma cuadraria (1562.50) pero v1 NO agrega silenciosamente
    assert item["status"] == "INDETERMINATE"
    assert item["reasons"] == ["MULTIPLE_CASH_MOVEMENTS"]
    assert set(item["movement_ids"]) == {"MOV-1", "MOV-2"}


def test_duplicate_entitled_key_indeterminate(surface):
    ent = _entitlements(surface, _pos(), _pos(quantity="10"))
    recon = reconcile(ent, _movements(_mov()))
    assert all(
        i["status"] == "INDETERMINATE"
        and "DUPLICATE_ENTITLEMENT_KEY" in i["reasons"]
        for i in recon["items"]
    )


# ------------------------------------------------------ non-entitled pass

def test_indeterminate_entitlement_never_exception(surface):
    # A002: isin ajeno al evento -> entitlement INDETERMINATE
    ent = _entitlements(
        surface, _pos(), _pos(account="A002", isin="ES0105448007")
    )
    recon = reconcile(ent, _movements(_mov()))
    items = _by_account(recon)
    assert items["A001"]["status"] == "MATCH"
    ind = items["A002"]
    assert ind["status"] == "INDETERMINATE"
    assert ind["entitlement_status"] == "INDETERMINATE"
    assert "ENTITLEMENT_INDETERMINATE" in ind["reasons"]
    assert "NO_POSITION_FOR_INSTRUMENT" in ind["reasons"]


def test_cash_linked_to_indeterminate_is_not_unexpected(surface):
    ent = _entitlements(
        surface,
        _pos(account="A002", isin="ES0105448007"),  # indeterminate
    )
    recon = reconcile(
        ent,
        _movements(_mov(mid="MOV-9", account="A002", isin="ES0105448007",
                        event_id=None)),
    )
    item = recon["items"][0]
    assert item["status"] == "INDETERMINATE"
    # el movimiento queda vinculado informativamente, no UNEXPECTED_CASH
    assert item["linked_movement_ids"] == ["MOV-9"]
    assert not [
        i for i in recon["items"] if i["status"] == "UNEXPECTED_CASH"
    ]


def test_invalid_movements_never_match(surface):
    ent = _entitlements(surface, _pos())
    recon = reconcile(
        ent,
        _movements(
            _mov(),
            {"movement_id": "BAD-1", "account_id": "A001",
             "event_id": SAN, "amount": 12.5, "currency": "EUR"},  # float
            {"movement_id": "BAD-2", "account_id": "A001",
             "amount": "1.00", "currency": "EUR"},  # sin ref de evento
        ),
    )
    assert recon["summary"]["match"] == 1
    assert recon["summary"]["invalid_movements"] == 2
    assert recon["summary"]["unexpected_cash"] == 0
    reasons = {
        m["movement"]["movement_id"]: m["reasons"]
        for m in recon["invalid_movements"]
    }
    assert "amount(parseable)" in reasons["BAD-1"]
    assert "event_id|isin" in reasons["BAD-2"]


def test_value_date_informative_only(surface):
    ent = _entitlements(surface, _pos())
    recon = reconcile(
        ent, _movements(_mov(value_date="2030-01-01"))
    )
    item = recon["items"][0]
    # value_date lejana no afecta al match; solo se conserva
    assert item["status"] == "MATCH"
    assert item["value_date"] == "2030-01-01"


def test_no_mutation_and_determinism(surface):
    ent = _entitlements(surface, _pos())
    mov = _movements(_mov(), _mov(mid="M2", amount="1.00",
                                  account="A9"))
    before_ent = json.dumps(ent, sort_keys=True, default=str)
    before_mov = json.dumps(mov, sort_keys=True)
    a = reconcile(ent, mov)
    b = reconcile(ent, mov)
    from ca_es.canonical import canonical_json
    assert canonical_json(a) == canonical_json(b)
    assert json.dumps(ent, sort_keys=True, default=str) == before_ent
    assert json.dumps(mov, sort_keys=True) == before_mov


def test_load_movements_schema(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "OTHER"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_movements(bad)
    good = tmp_path / "m.json"
    good.write_text(json.dumps(_movements(_mov())), encoding="utf-8")
    assert load_movements(good)["movements"][0]["movement_id"] == "MOV-1"
