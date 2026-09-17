# -*- coding: utf-8 -*-
"""Tests P2.0: cash dividend entitlement — derecho monetario
determinista, Decimal-only, INDETERMINATE nunca estimacion."""
import json
from decimal import Decimal, Inexact, InvalidOperation, Rounded, localcontext
from pathlib import Path

import pytest

from ca_es.entitlement_engine import (
    compute_entitlements,
    load_positions,
)
from ca_es.surface import Surface, load_surface

REPO = Path(__file__).resolve().parents[2]
CANON = REPO / "g3/input/canon.json"
POLICY = REPO / "docs/sources/source-policy.json"

MFE = "59303c3c-8be7-578f-bc59-8e5e43a1fdf3"
ALMIRALL = "035e32ca-ba61-5105-8756-e0234e5335fc"
BMEG_DIV = "6881d24a-ef46-5053-80ce-1743a1792f8b"
BMEG_CAP = "3c9270d8-76b3-5953-942c-b1f42c1cc56a"
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


def _surface_of(canon_dict) -> Surface:
    return Surface(
        canon_dict, json.loads(POLICY.read_text(encoding="utf-8"))
    )


def _canon_copy() -> dict:
    return json.loads(CANON.read_text(encoding="utf-8"))


# ------------------------------------------------------------- entitled

def test_entitled_cash_dividend(surface):
    doc = compute_entitlements(surface, SAN, _positions(_pos()))
    assert doc["entitlement_version"] == "CA_ES_ENTITLEMENT_V1"
    assert doc["event_type"] == "CASH_DIVIDEND"
    ent = doc["entitlements"][0]
    assert ent["status"] == "ENTITLED"
    assert ent["entitled_quantity"] == "12500"
    assert ent["gross_per_share"]["normalized"] == "0.125"
    assert ent["gross_per_share"]["currency"] == "EUR"
    # Decimal exacto: 0.125 x 12500 = 1562.500 (escala 3)
    assert ent["gross_cash"]["normalized"] == "1562.500"
    assert ent["gross_cash"]["currency"] == "EUR"
    assert ent["gross_cash"]["scale"] == 3
    assert Decimal(ent["gross_cash"]["normalized"]) == Decimal("1562.500")
    assert ent["basis"]["position_eligibility"] == "POSITION_AT_RECORD_DATE"
    assert ent["basis"]["record_date"] == SAN_RECORD


def test_entitled_evidence_resolvable(surface):
    doc = compute_entitlements(surface, SAN, _positions(_pos()))
    ent = doc["entitlements"][0]
    evidence = ent["evidence"]
    assert evidence["rule"].startswith("CASH_DIVIDEND_")
    # dos fuentes afirman el mismo gross (CURRENT multi-fuente) + record
    assert len(evidence["assertion_ids"]) == 3
    assert len(evidence["source_document_ids"]) == 3
    for aid in evidence["assertion_ids"]:
        chain = surface.evidence(aid)
        assert chain is not None
        assert chain["raw_pointer"]
        assert chain["source_document"]["official_document_id"]


def test_fractional_quantity_decimal_exact(surface):
    doc = compute_entitlements(
        surface, SAN, _positions(_pos(quantity="333.5"))
    )
    ent = doc["entitlements"][0]
    # 0.125 x 333.5 = 41.6875 exacto, sin artefactos float
    assert ent["gross_cash"]["normalized"] == "41.6875"
    assert ent["status"] == "ENTITLED"


@pytest.mark.parametrize("precision", [1, 6, 28])
@pytest.mark.parametrize(
    "gross,quantity,expected",
    [
        ("0.125", "123456789012345678901234567890",
         "15432098626543209862654320986.250"),
        ("1.0000000000000000000000000000000000000001", "9",
         "9.0000000000000000000000000000000000000009"),
        ("1E-80", "1E-80", "0." + "0" * 159 + "1"),
        ("1E+40", "9", "9" + "0" * 40),
    ],
)
def test_multiplication_independent_of_precision(
    precision, gross, quantity, expected,
):
    canon = _canon_copy()
    san = next(e for e in canon["events"] if e["canonical_event_id"] == SAN)
    for fact in san["facts"]:
        if fact["field_path"] == "amount.gross_per_share":
            fact["value"].update(
                normalized=gross, raw_lexeme=gross,
                scale=-Decimal(gross).as_tuple().exponent,
            )
    surface = _surface_of(canon)
    with localcontext() as context:
        context.prec = precision
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        context.clear_flags()
        ent = compute_entitlements(
            surface, SAN, _positions(_pos(quantity=quantity))
        )["entitlements"][0]
        assert context.prec == precision
        assert not any(context.flags.values())
    assert ent["status"] == "ENTITLED"
    assert ent["gross_cash"]["normalized"] == expected
    assert ent["gross_cash"]["scale"] == (
        -Decimal(gross).as_tuple().exponent
        - Decimal(quantity).as_tuple().exponent
    )


@pytest.mark.parametrize("trap", [True, False])
@pytest.mark.parametrize("quantity", ["NaN", "sNaN", "Infinity", "-Infinity"])
def test_nonfinite_quantity_indeterminate(surface, quantity, trap):
    with localcontext() as context:
        context.traps[InvalidOperation] = trap
        ent = compute_entitlements(
            surface, SAN, _positions(_pos(quantity=quantity))
        )["entitlements"][0]
    assert ent["status"] == "INDETERMINATE"
    assert ent["reasons"] == ["INVALID_QUANTITY"]
    assert ent["position_quantity"] is None
    assert "gross_cash" not in ent


@pytest.mark.parametrize("trap", [True, False])
@pytest.mark.parametrize(
    "gross", ["NaN", "sNaN", "Infinity", "-Infinity", "abc", None, 0.125],
)
def test_invalid_gross_indeterminate(surface, monkeypatch, gross, trap):
    from copy import deepcopy

    state = deepcopy(surface._current_state(surface._find(SAN)))
    for entry in state["amount.gross_per_share"]["values"]:
        entry["value"]["normalized"] = gross
    monkeypatch.setattr(surface, "_current_state", lambda event: state)
    with localcontext() as context:
        context.traps[InvalidOperation] = trap
        ent = compute_entitlements(
            surface, SAN, _positions(_pos())
        )["entitlements"][0]
    assert ent["status"] == "INDETERMINATE"
    assert ent["reasons"] == ["INVALID_GROSS_AMOUNT"]
    assert "gross_cash" not in ent


def test_multiple_positions_summary(surface):
    doc = compute_entitlements(
        surface,
        SAN,
        _positions(
            _pos(account="A001"),
            _pos(account="A002", isin="ES0000000000"),  # no match
            _pos(account="A003", as_of="2026-05-03"),  # stale
            _pos(account="A004", quantity="0"),  # zero
        ),
    )
    statuses = {e["account_id"]: e["status"] for e in doc["entitlements"]}
    assert statuses == {
        "A001": "ENTITLED",
        "A002": "INDETERMINATE",
        "A003": "INDETERMINATE",
        "A004": "NOT_ENTITLED",
    }
    assert doc["summary"]["entitled"] == 1
    assert doc["summary"]["indeterminate"] == 2
    assert doc["summary"]["not_entitled"] == 1


# --------------------------------------------------------- indeterminate

def test_missing_record_date_indeterminate(surface):
    # BMEG_DIV tiene gross + isin pero no record_date
    doc = compute_entitlements(
        surface, BMEG_DIV, _positions(_pos(isin="ES0105448007"))
    )
    ent = doc["entitlements"][0]
    assert ent["status"] == "INDETERMINATE"
    assert ent["reasons"] == ["MISSING_RECORD_DATE"]
    assert "gross_cash" not in ent


def test_no_position_for_instrument(surface):
    # MFE no tiene isin en el canon: ninguna posicion es demostrable
    doc = compute_entitlements(surface, MFE, _positions(_pos()))
    assert doc["entitlements"][0]["reasons"] == [
        "NO_POSITION_FOR_INSTRUMENT"
    ]
    # isin ajeno al evento
    doc = compute_entitlements(
        surface, SAN, _positions(_pos(isin="ES0105448007"))
    )
    ent = doc["entitlements"][0]
    assert ent["status"] == "INDETERMINATE"
    assert "NO_POSITION_FOR_INSTRUMENT" in ent["reasons"]


def test_snapshot_not_at_record(surface):
    before = compute_entitlements(
        surface, SAN, _positions(_pos(as_of="2026-05-03"))
    )["entitlements"][0]
    after = compute_entitlements(
        surface, SAN, _positions(_pos(as_of="2026-05-05"))
    )["entitlements"][0]
    assert before["reasons"] == ["POSITION_SNAPSHOT_BEFORE_RECORD"]
    assert after["reasons"] == ["POSITION_SNAPSHOT_AFTER_RECORD"]
    assert before["status"] == after["status"] == "INDETERMINATE"


def test_missing_position_as_of(surface):
    doc = compute_entitlements(
        surface, SAN, _positions(
            {"account_id": "A1", "isin": SAN_ISIN, "quantity": "10"}
        )
    )
    ent = doc["entitlements"][0]
    assert ent["reasons"] == ["MISSING_POSITION_AS_OF"]
    # file-level as_of sustituye al de posicion ausente
    doc = compute_entitlements(
        surface,
        SAN,
        _positions(
            {"account_id": "A1", "isin": SAN_ISIN, "quantity": "10"},
            as_of=SAN_RECORD,
        ),
    )
    assert doc["entitlements"][0]["status"] == "ENTITLED"


def test_conflicting_gross_amount(surface):
    canon = _canon_copy()
    san = next(
        e for e in canon["events"] if e["canonical_event_id"] == SAN
    )
    revision = max(r["generation"] for r in san["revisions"])
    rev_id = next(
        r["revision_id"]
        for r in san["revisions"] if r["generation"] == revision
    )
    conflicting = dict(san["facts"][0])
    conflicting["field_path"] = "amount.gross_per_share"
    conflicting["revision_id"] = rev_id
    conflicting["value"] = {
        "__financial__": True,
        "normalized": "0.130",
        "currency": "EUR",
        "raw_lexeme": "0.130",
        "scale": 3,
    }
    san["facts"].append(conflicting)
    doc = compute_entitlements(
        _surface_of(canon), SAN, _positions(_pos())
    )
    ent = doc["entitlements"][0]
    assert ent["status"] == "INDETERMINATE"
    assert ent["reasons"] == ["CONFLICTING_GROSS_AMOUNT"]


def test_missing_currency_indeterminate(surface):
    canon = _canon_copy()
    san = next(
        e for e in canon["events"] if e["canonical_event_id"] == SAN
    )
    for fact in san["facts"]:
        if fact["field_path"] == "amount.gross_per_share":
            fact["value"]["currency"] = None
    doc = compute_entitlements(
        _surface_of(canon), SAN, _positions(_pos())
    )
    assert doc["entitlements"][0]["reasons"] == ["MISSING_CURRENCY"]


def test_invalid_positions(surface):
    bad_qty = compute_entitlements(
        surface, SAN, _positions(_pos(quantity="abc"))
    )["entitlements"][0]
    assert bad_qty["reasons"] == ["INVALID_QUANTITY"]
    float_qty = compute_entitlements(
        surface, SAN, _positions(_pos(quantity=12.5))
    )["entitlements"][0]
    assert float_qty["reasons"] == ["INVALID_QUANTITY"]
    negative = compute_entitlements(
        surface, SAN, _positions(_pos(quantity="-10"))
    )["entitlements"][0]
    assert negative["reasons"] == ["NEGATIVE_QUANTITY_UNSUPPORTED"]
    no_isin = compute_entitlements(
        surface,
        SAN,
        _positions({"account_id": "A1", "quantity": "10"}),
    )["entitlements"][0]
    assert no_isin["reasons"] == ["MISSING_ISIN"]


def test_unsupported_event_type(surface):
    doc = compute_entitlements(surface, BMEG_CAP, _positions(_pos()))
    ent = doc["entitlements"][0]
    assert ent["status"] == "UNSUPPORTED"
    assert ent["reasons"] == ["UNSUPPORTED_EVENT_TYPE"]
    assert doc["summary"]["unsupported"] == 1


def test_event_not_found(surface):
    assert compute_entitlements(surface, "nope", _positions(_pos())) is None


def test_no_mutation_and_determinism(surface):
    positions = _positions(_pos(), _pos(account="A2", quantity="7"))
    before_canon = json.dumps(surface.canon, sort_keys=True, default=str)
    before_pos = json.dumps(positions, sort_keys=True)
    a = compute_entitlements(surface, SAN, positions)
    b = compute_entitlements(surface, SAN, positions)
    from ca_es.canonical import canonical_json
    assert canonical_json(a) == canonical_json(b)
    assert json.dumps(surface.canon, sort_keys=True, default=str) == (
        before_canon
    )
    assert json.dumps(positions, sort_keys=True) == before_pos


def test_load_positions_schema(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "OTHER"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_positions(bad)
    good = tmp_path / "p.json"
    good.write_text(json.dumps(_positions(_pos())), encoding="utf-8")
    assert load_positions(good)["positions"][0]["account_id"] == "A001"
