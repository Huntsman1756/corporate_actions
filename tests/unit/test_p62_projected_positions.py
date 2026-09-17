"""P6.2 — CA_ES_PROJECTED_POSITIONS_V1.

Proyeccion linea a linea: delta 0 para CASH_RECEIVABLE, contaminacion
por el estado menos decidido, deltas genericos sobre target_isin y
lineas nuevas para recepciones de instrumento sin posicion previa.
"""

import copy

import pytest

from ca_es.canonical import canonical_json, sha256_hex
from ca_es.projected_positions import (
    INDETERMINATE,
    PROJECTED,
    UNSUPPORTED,
    project_positions,
)

NOW = "2026-09-17T00:00:00Z"
SHA = "aa" * 32
ISIN = "ES0105448007"
EID = "E1"


def _pos(account="A001", isin=ISIN, qty="12500", as_of="2026-07-03"):
    position = {"account_id": account, "isin": isin, "quantity": qty}
    if as_of is not None:
        position["as_of"] = as_of
    return position


def _positions(*positions):
    return {"schema": "CA_ES_POSITIONS_V1", "as_of": "2026-07-03",
            "positions": list(positions)}


def _item(account="A001", source=ISIN, target=None, qty="12500",
          status=PROJECTED, impact_type="CASH_RECEIVABLE",
          delta=None, basis="2026-07-04", reasons=None):
    return {
        "canonical_event_id": EID,
        "account_id": account,
        "source_isin": source,
        "target_isin": target,
        "impact_type": impact_type,
        "status": status,
        "input_quantity": qty,
        "output_quantity": None,
        "quantity_delta": delta,
        "cash_amount": None,
        "currency": None,
        "rule_id": "R1",
        "basis_date": basis,
        "reasons": list(reasons or []),
        "source_canon_logical_sha256": SHA,
        "source_positions_logical_sha256": None,
        "evidence": {},
    }


def _impact(positions, *items):
    return {
        "schema": "CA_ES_POSITION_IMPACT_V1",
        "generated_at": NOW,
        "canonical_event_id": EID,
        "event_type": "CASH_DIVIDEND",
        "positions_as_of": "2026-07-03",
        "rule_id": "R1",
        "reasons": [],
        "source_canon_logical_sha256": SHA,
        "source_positions_logical_sha256": sha256_hex(positions),
        "source_entitlement_sha256": None,
        "impacts": list(items),
        "summary": {},
    }


def test_cash_receivable_projects_zero_delta():
    positions = _positions(_pos())
    impact = _impact(positions, _item())
    doc = project_positions(positions, impact, now=NOW)

    assert doc["schema"] == "CA_ES_PROJECTED_POSITIONS_V1"
    assert doc["canonical_event_id"] == EID
    assert doc["source_positions_logical_sha256"] == sha256_hex(
        positions)
    line = doc["lines"][0]
    assert line["status"] == PROJECTED
    assert line["pre_quantity"] == "12500"
    assert line["delta_quantity"] == "0"
    assert line["projected_quantity"] == "12500"
    assert line["effective_date"] == "2026-07-04"
    assert line["impact_refs"] == ["impacts[0]"]


def test_indeterminate_impact_contaminates_line():
    positions = _positions(_pos())
    impact = _impact(
        positions,
        _item(status=INDETERMINATE,
              reasons=["POSITION_SNAPSHOT_BEFORE_RECORD"]))
    doc = project_positions(positions, impact, now=NOW)
    line = doc["lines"][0]
    assert line["status"] == INDETERMINATE
    assert line["projected_quantity"] is None
    assert line["delta_quantity"] is None
    assert line["reasons"] == ["POSITION_SNAPSHOT_BEFORE_RECORD"]


def test_unsupported_impact_contaminates_line():
    positions = _positions(_pos())
    impact = _impact(
        positions, _item(status=UNSUPPORTED, reasons=["NO_RULE"]))
    doc = project_positions(positions, impact, now=NOW)
    line = doc["lines"][0]
    assert line["status"] == UNSUPPORTED
    assert line["projected_quantity"] is None


def test_position_without_impact_item_is_indeterminate():
    positions = _positions(_pos(), _pos(account="A002", qty="5"))
    impact = _impact(positions, _item())
    doc = project_positions(positions, impact, now=NOW)
    assert doc["lines"][1]["status"] == INDETERMINATE
    assert doc["lines"][1]["reasons"] == ["MISSING_IMPACT_ITEM"]


def test_positions_hash_mismatch_fails_closed():
    positions = _positions(_pos())
    other = _positions(_pos(qty="1"))
    impact = _impact(other, _item())
    with pytest.raises(ValueError, match="POSITIONS_HASH_MISMATCH"):
        project_positions(positions, impact, now=NOW)


def test_quantity_delta_applies_to_source_line():
    positions = _positions(_pos())
    impact = _impact(
        positions,
        _item(impact_type="SECURITY_DELIVERY", delta="-12500"))
    doc = project_positions(positions, impact, now=NOW)
    line = doc["lines"][0]
    assert line["status"] == PROJECTED
    assert line["delta_quantity"] == "-12500"
    assert line["projected_quantity"] == "0"


def test_delta_goes_to_target_isin_line():
    positions = _positions(_pos(), _pos(isin="ES0000000002", qty="0"))
    impact = _impact(
        positions,
        _item(impact_type="SECURITY_RECEIPT", target="ES0000000002",
              delta="250000"))
    doc = project_positions(positions, impact, now=NOW)
    source_line, target_line = doc["lines"]
    assert source_line["isin"] == ISIN
    assert source_line["status"] == INDETERMINATE
    assert source_line["reasons"] == ["MISSING_IMPACT_ITEM"]
    assert target_line["isin"] == "ES0000000002"
    assert target_line["delta_quantity"] == "250000"
    assert target_line["projected_quantity"] == "250000"


def test_receipt_of_new_instrument_creates_projected_line():
    positions = _positions(_pos())
    impact = _impact(
        positions,
        _item(impact_type="SECURITY_RECEIPT", target="ES0000000002",
              delta="250000"))
    doc = project_positions(positions, impact, now=NOW)
    assert len(doc["lines"]) == 2
    new_line = doc["lines"][1]
    assert new_line["isin"] == "ES0000000002"
    assert new_line["pre_quantity"] == "0"
    assert new_line["delta_quantity"] == "250000"
    assert new_line["projected_quantity"] == "250000"
    assert "NEW_INSTRUMENT_RECEIPT" in new_line["reasons"]


def test_mixed_items_worst_status_wins_and_deltas_add():
    positions = _positions(_pos())
    impact = _impact(
        positions,
        _item(impact_type="SECURITY_DELIVERY", delta="-5000"),
        _item(impact_type="SECURITY_DELIVERY", delta="-2000",
              status=INDETERMINATE, reasons=["X"]))
    doc = project_positions(positions, impact, now=NOW)
    line = doc["lines"][0]
    assert line["status"] == INDETERMINATE
    assert line["projected_quantity"] is None
    assert line["impact_refs"] == ["impacts[0]", "impacts[1]"]

    impact2 = _impact(
        positions,
        _item(impact_type="SECURITY_DELIVERY", delta="-5000"),
        _item(impact_type="SECURITY_DELIVERY", delta="-2000"))
    doc2 = project_positions(positions, impact2, now=NOW)
    line2 = doc2["lines"][0]
    assert line2["status"] == PROJECTED
    assert line2["delta_quantity"] == "-7000"
    assert line2["projected_quantity"] == "5500"


def test_determinism_and_no_mutation():
    positions = _positions(_pos())
    impact = _impact(positions, _item())
    snap = [copy.deepcopy(positions), copy.deepcopy(impact)]
    doc1 = project_positions(positions, impact, now=NOW)
    doc2 = project_positions(positions, impact, now=NOW)
    assert canonical_json(doc1) == canonical_json(doc2)
    assert positions == snap[0]
    assert impact == snap[1]


def test_invalid_schemas_fail_closed():
    positions = _positions(_pos())
    impact = _impact(positions, _item())
    with pytest.raises(ValueError):
        project_positions({"schema": "X"}, impact, now=NOW)
    with pytest.raises(ValueError):
        project_positions(positions, {"schema": "X"}, now=NOW)
