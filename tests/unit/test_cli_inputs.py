import json
from pathlib import Path

import pytest

from ca_es import cli
from ca_es.entitlement_engine import compute_entitlements, load_positions
from ca_es.exceptions import build_cases_doc, load_cases
from ca_es.reconciliation import load_movements, reconcile


INVALID_INPUTS = [
    b'{"metadata": {"value": 1, "value": 2}}',
    b'{"metadata": [{"value": 0.5}]}',
    b'{"value": 1e2}',
    b'{"value": NaN}',
    b'{"value": Infinity}',
    b'{"value": -Infinity}',
    b'[]',
    b'null',
    b'"text"',
    b'1',
    b'true',
    b'{',
    b'{"value": "\xff"}',
    None,
]


@pytest.fixture(params=INVALID_INPUTS)
def invalid_path(request, tmp_path):
    path = tmp_path / "invalid.json"
    if request.param is not None:
        path.write_bytes(request.param)
    return str(path)


@pytest.fixture
def inputs(tmp_path):
    documents = {
        "canon": {"events": [], "logical_sha256": "test"},
        "policy": {"sources": {}},
        "facts": {},
        "rules": {},
        "calendars": {},
        "positions": {"schema": "CA_ES_POSITIONS_V1", "positions": []},
        "cash": {"schema": "CA_ES_CASH_MOVEMENTS_V2", "movements": []},
        "entitlements": {"canonical_event_id": "E1", "entitlements": []},
        "recon": {"canonical_event_id": "E1", "items": []},
        "cases": {
            "schema": "CA_ES_EXCEPTION_CASES_V1",
            "canonical_event_id": "E1", "cases": [],
        },
        "deadlines": {"deadlines": []},
        "queue": {
            "as_of": "2026-07-15",
            "source_canon_logical_sha256": "test",
            "window_days": 7,
        },
    }
    paths = {}
    for label, document in documents.items():
        path = tmp_path / f"{label}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths[label] = str(path)
    return paths


def assert_input_error(capsys, label):
    captured = capsys.readouterr()
    error = json.loads(captured.out)
    assert error["status"] == "INVALID_INPUT"
    assert error["detail"].startswith(f"{label}: ")
    assert not captured.err


def test_load_json_rejects_invalid_input(invalid_path, capsys):
    assert cli._load_json(invalid_path, "artifact") == (None, 2)
    assert_input_error(capsys, "artifact")


def test_load_json_accepts_canonical_types(tmp_path, capsys):
    document = {
        "amount": "0.50", "count": 1, "enabled": True,
        "absent": None, "items": [False, {}, []], "name": "Espa\u00f1a",
    }
    path = tmp_path / "valid.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    assert cli._load_json(str(path), "artifact") == (document, 0)
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("command,label", [
    ("events", "canon"),
    ("events", "policy"),
    ("brief", "previous-canon"),
    ("brief", "queue"),
    ("reconcile", "entitlements"),
    ("exceptions", "recon"),
    ("swift-project", "facts"),
    ("swift-bind", "facts"),
    ("swift-bind", "canon"),
    ("swift-cash-candidate", "facts"),
    ("swift-cash-candidate", "canon"),
    ("swift-election", "facts"),
    ("swift-election", "canon"),
    ("swift-election", "queue"),
    ("deadlines", "canon"),
    ("deadlines", "rules"),
    ("deadlines", "calendars"),
    ("action-queue", "deadlines"),
])
def test_operational_inputs_fail_closed(
    command, label, invalid_path, inputs, capsys, monkeypatch
):
    from ca_es import swift_ca

    monkeypatch.setattr(swift_ca, "project_ca_message", lambda *a, **kw: {})
    options = {}
    if command in ("events", "brief"):
        options.update(canon=inputs["canon"], policy=inputs["policy"])
    if command == "brief":
        options.update({"as-of": "2026-07-15", "queue": inputs["queue"]})
    if command == "reconcile":
        options["cash"] = "unused.json"
    if command == "exceptions":
        options["now"] = "2026-07-15T00:00:00Z"
    if command.startswith("swift-"):
        options["facts"] = inputs["facts"]
        if command != "swift-project":
            options["canon"] = inputs["canon"]
    if command == "deadlines":
        options.update({key: inputs[key] for key in (
            "canon", "rules", "calendars")})
    if command == "action-queue":
        options.update({
            "as-of": "2026-07-15", "window-days": "7",
            "due-soon-days": "2",
        })
    options[label] = invalid_path
    argv = [command]
    for name, value in options.items():
        argv.extend([f"--{name}", value])
    assert cli.main(argv) == 2
    assert_input_error(capsys, label)


@pytest.mark.parametrize("command,extra,expected", [
    ("events", [], {"events": []}),
    ("show", ["missing"], {"status": "NOT_FOUND"}),
])
def test_surface_cli_valid_inputs(command, extra, expected, inputs, capsys):
    code = cli.main([
        command, *extra, "--canon", inputs["canon"],
        "--policy", inputs["policy"],
    ])
    assert code == (0 if command == "events" else 1)
    assert json.loads(capsys.readouterr().out) == expected


def test_exceptions_rejects_cross_event_empty_store(inputs, capsys):
    store = Path(inputs["cases"])
    store.write_text(json.dumps({
        "schema": "CA_ES_EXCEPTION_CASES_V1",
        "canonical_event_id": "OTHER", "cases": [],
    }), encoding="utf-8")
    before = store.read_bytes()
    assert cli.main([
        "exceptions", "--recon", inputs["recon"],
        "--cases", inputs["cases"], "--now", "2026-07-15T00:00:00Z",
    ]) == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "INVALID_CASES", "detail": "CASES_EVENT_MISMATCH",
    }
    assert store.read_bytes() == before


@pytest.fixture(params=[
    (load_positions, "CA_ES_POSITIONS_V1", "positions"),
    (load_movements, "CA_ES_CASH_MOVEMENTS_V1", "movements"),
    (load_movements, "CA_ES_CASH_MOVEMENTS_V2", "movements"),
    (load_cases, "CA_ES_EXCEPTION_CASES_V1", "cases"),
])
def artifact_loader(request):
    return request.param


@pytest.mark.parametrize("collection", [
    None, {}, "items", 1, True, [None], [[]], [1], ["item"], [True],
    [{}, None],
])
def test_collection_loaders_reject_malformed_lists(
    artifact_loader, collection, tmp_path
):
    loader, schema, field = artifact_loader
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps({"schema": schema, field: collection}),
                    encoding="utf-8")
    with pytest.raises(ValueError, match=f"{field} debe ser una lista"):
        loader(path)


def test_collection_loaders_require_collection(artifact_loader, tmp_path):
    loader, schema, field = artifact_loader
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps({"schema": schema}), encoding="utf-8")
    with pytest.raises(ValueError, match=f"{field} debe ser una lista"):
        loader(path)


@pytest.mark.parametrize("schema", [None, [], {}, True, "wrong"])
def test_collection_loaders_reject_invalid_schema(
    artifact_loader, schema, tmp_path
):
    loader, _, field = artifact_loader
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps({"schema": schema, field: []}),
                    encoding="utf-8")
    with pytest.raises(ValueError, match="schema debe ser"):
        loader(path)


@pytest.mark.parametrize("collection", [[], [{}]])
def test_collection_loaders_accept_object_members(
    artifact_loader, collection, tmp_path
):
    loader, schema, field = artifact_loader
    doc = {"schema": schema, field: collection}
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert loader(path) == doc


def test_collection_loaders_reject_invalid_json(artifact_loader, invalid_path):
    loader, _, _ = artifact_loader
    with pytest.raises((ValueError, OSError)):
        loader(Path(invalid_path))


@pytest.mark.parametrize("extra,reason", [
    ('"metadata": {"x": 1, "x": 2}', "duplicada"),
    ('"metadata": [0.5]', "float prohibido"),
    ('"metadata": 1e2', "float prohibido"),
    ('"metadata": NaN', "no finita"),
    ('"metadata": Infinity', "no finita"),
    ('"metadata": -Infinity', "no finita"),
])
def test_collection_loaders_use_strict_profile(
    artifact_loader, extra, reason, tmp_path
):
    loader, schema, field = artifact_loader
    path = tmp_path / "artifact.json"
    path.write_text(
        f'{{"schema": "{schema}", "{field}": [], {extra}}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=reason):
        loader(path)


def financial_argv(command, inputs):
    if command == "entitlement":
        return [command, "--canon", inputs["canon"],
                "--policy", inputs["policy"], "--event", "E1",
                "--positions", inputs["positions"]]
    if command == "reconcile-positions":
        return ["reconcile", "--canon", inputs["canon"],
                "--policy", inputs["policy"], "--event", "E1",
                "--positions", inputs["positions"], "--cash", inputs["cash"]]
    if command == "reconcile":
        return [command, "--entitlements", inputs["entitlements"],
                "--cash", inputs["cash"]]
    if command == "exceptions":
        return [command, "--recon", inputs["recon"],
                "--cases", inputs["cases"], "--now", "2026-07-15T00:00:00Z"]
    return ["case-transition", "--cases", inputs["cases"],
            "--case-key", "missing", "--to", "IN_REVIEW", "--actor", "ops",
            "--now", "2026-07-15T00:00:00Z"]


@pytest.fixture(params=[
    ("entitlement", "positions", "INVALID_POSITIONS"),
    ("reconcile-positions", "positions", "INVALID_POSITIONS"),
    ("reconcile", "cash", "INVALID_MOVEMENTS"),
    ("exceptions", "cases", "INVALID_CASES"),
    ("case-transition", "cases", "INVALID_CASES"),
])
def financial_command(request):
    return request.param


def assert_error(capsys, status, detail=None):
    captured = capsys.readouterr()
    error = json.loads(captured.out)
    assert error["status"] == status
    assert error["detail"]
    if detail is not None:
        assert detail in error["detail"]
    assert captured.err == ""


def test_financial_cli_invalid_json(
    financial_command, invalid_path, inputs, capsys
):
    command, field, status = financial_command
    inputs[field] = invalid_path
    assert cli.main(financial_argv(command, inputs)) == 2
    assert_error(capsys, status)


@pytest.mark.parametrize("collection", [None, {}, "bad", [None], [[]]])
def test_financial_cli_invalid_collections(
    financial_command, collection, inputs, capsys
):
    command, label, status = financial_command
    path = Path(inputs[label])
    doc = json.loads(path.read_text(encoding="utf-8"))
    field = "movements" if label == "cash" else label
    doc[field] = collection
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert cli.main(financial_argv(command, inputs)) == 2
    assert_error(capsys, status, f"{field} debe ser una lista")


@pytest.mark.parametrize("raw", ["NaN", "sNaN", "Infinity", "-Infinity", "bad", None])
def test_invalid_financial_values_remain_per_item(raw, inputs):
    positions = Path(inputs["positions"])
    positions.write_text(json.dumps({
        "schema": "CA_ES_POSITIONS_V1", "positions": [{
            "account_id": "A1", "isin": "ES01", "quantity": raw,
        }],
    }), encoding="utf-8")
    surface = cli.Surface({"events": [{
        "canonical_event_id": "E1", "event_type": "CASH_DIVIDEND",
        "affected_instrument": {"isin": "ES01"}, "facts": [], "revisions": [],
    }]}, {})
    ent = compute_entitlements(surface, "E1", load_positions(positions))
    assert ent["entitlements"][0]["status"] == "INDETERMINATE"
    assert ent["entitlements"][0]["reasons"] == ["INVALID_QUANTITY"]
    cash = Path(inputs["cash"])
    cash.write_text(json.dumps({
        "schema": "CA_ES_CASH_MOVEMENTS_V2", "movements": [{
            "movement_id": "M1", "account_id": "A1", "event_id": "E1",
            "currency": "EUR", "amount": raw,
        }],
    }), encoding="utf-8")
    result = reconcile({"canonical_event_id": "E1", "entitlements": []},
                       load_movements(cash))
    assert result["summary"]["invalid_movements"] == 1
    assert "amount(parseable)" in result["invalid_movements"][0]["reasons"]
    assert result["items"] == []


@pytest.mark.parametrize("command", ["reconcile", "exceptions"])
@pytest.mark.parametrize("amount", ["NaN", "sNaN", "Infinity", "bad", None])
def test_cli_controls_invalid_expected_cash(command, amount, inputs, capsys):
    Path(inputs["entitlements"]).write_text(json.dumps({
        "canonical_event_id": "E1", "entitlements": [{
            "account_id": "A1", "status": "ENTITLED",
            "gross_cash": {"normalized": amount, "currency": "EUR"},
        }],
    }), encoding="utf-8")
    argv = [command, "--entitlements", inputs["entitlements"],
            "--cash", inputs["cash"]]
    if command == "exceptions":
        argv.extend(["--now", "2026-07-15T00:00:00Z"])
    assert cli.main(argv) == 2
    assert_error(capsys, "INVALID_INPUT", "expected gross_cash")


@pytest.mark.parametrize("invalid", ["offset", "calendar", "overflow"])
def test_cli_controls_deadline_domain_errors(invalid, inputs, capsys):
    rule = {"rule_id": "R1", "deadline_type": "RESPONSE",
            "source_field": "date.payment_date", "calendar_id": "C1",
            "business_days_offset": 1}
    calendar = {"calendar_id": "C1", "business_week": [0, 1, 2, 3, 4],
                "holidays": []}
    if invalid == "offset":
        rule["business_days_offset"] = True
        reason = "INVALID_BUSINESS_DAYS_OFFSET"
    elif invalid == "calendar":
        calendar["business_week"] = []
        reason = "INVALID_BUSINESS_WEEK"
    else:
        reason = "DEADLINE_DATE_OVERFLOW"
        Path(inputs["canon"]).write_text(json.dumps({"events": [{
            "canonical_event_id": "E1", "event_type": "CASH_DIVIDEND",
            "conflicts": [], "facts": [{"field_path": "date.payment_date",
                "value": "9999-12-31", "revision_id": "R1",
                "assertion_id": "A1"}],
        }]}), encoding="utf-8")
    Path(inputs["rules"]).write_text(json.dumps({"rules": [rule]}),
                                    encoding="utf-8")
    Path(inputs["calendars"]).write_text(
        json.dumps({"calendars": [calendar]}), encoding="utf-8")
    assert cli.main([
        "deadlines", "--canon", inputs["canon"], "--rules", inputs["rules"],
        "--calendars", inputs["calendars"],
    ]) == 2
    assert_error(capsys, "INVALID_INPUT", reason)


@pytest.mark.parametrize("field", ["window-days", "due-soon-days"])
def test_cli_controls_action_queue_threshold_errors(field, inputs, capsys):
    options = {"window-days": "7", "due-soon-days": "2"}
    options[field] = "-1"
    assert cli.main([
        "action-queue", "--deadlines", inputs["deadlines"],
        "--as-of", "2026-07-15", "--window-days", options["window-days"],
        "--due-soon-days", options["due-soon-days"],
    ]) == 2
    assert_error(capsys, "INVALID_INPUT", f"INVALID_{field.upper().replace('-', '_')}")


@pytest.mark.parametrize("invalid", ["duplicate", "member-event"])
def test_cli_controls_build_cases_errors(invalid, inputs, capsys):
    doc = build_cases_doc({"canonical_event_id": "E1", "items": [{
        "status": "MISSING_CASH", "account_id": "A1", "currency": "EUR",
    }]}, now="2026-07-15T00:00:00Z")
    if invalid == "duplicate":
        doc["cases"].append(doc["cases"][0])
        reason = "DUPLICATE_PREVIOUS_CASE_KEY"
    else:
        doc["cases"][0]["canonical_event_id"] = "OTHER"
        reason = "CASES_EVENT_MISMATCH"
    path = Path(inputs["cases"])
    path.write_text(json.dumps(doc), encoding="utf-8")
    before = path.read_bytes()
    assert cli.main(financial_argv("exceptions", inputs)) == 2
    assert_error(capsys, "INVALID_INPUT", reason)
    assert path.read_bytes() == before


@pytest.mark.parametrize("event_id", [None, "", "  ", 1, [], {}])
def test_cli_rejects_invalid_empty_store_event_id(event_id, inputs, capsys):
    Path(inputs["cases"]).write_text(json.dumps({
        "schema": "CA_ES_EXCEPTION_CASES_V1",
        "canonical_event_id": event_id, "cases": [],
    }), encoding="utf-8")
    assert cli.main(financial_argv("exceptions", inputs)) == 2
    assert_error(capsys, "INVALID_CASES", "INVALID_CASES_EVENT_ID")


def test_cli_accepts_same_event_empty_store(inputs, capsys):
    assert cli.main(financial_argv("exceptions", inputs)) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["canonical_event_id"] == "E1"
    assert doc["cases"] == []


@pytest.mark.parametrize("target,command", [
    ("ca_es.deadlines.compute_deadlines", "deadlines"),
    ("ca_es.action_queue.build_action_queue", "action-queue"),
    ("ca_es.reconciliation.reconcile", "reconcile"),
    ("ca_es.exceptions.build_cases_doc", "exceptions"),
])
@pytest.mark.parametrize("error", [OSError, TypeError, KeyError])
def test_domain_boundaries_do_not_hide_unrelated_errors(
    target, command, error, inputs, monkeypatch
):
    def fail(*args, **kwargs):
        raise error("unrelated failure")

    monkeypatch.setattr(target, fail)
    if command == "deadlines":
        argv = [command, "--canon", inputs["canon"],
                "--rules", inputs["rules"], "--calendars", inputs["calendars"]]
    elif command == "action-queue":
        argv = [command, "--deadlines", inputs["deadlines"],
                "--as-of", "2026-07-15", "--window-days", "7",
                "--due-soon-days", "2"]
    else:
        argv = financial_argv(command, inputs)
    with pytest.raises(error, match="unrelated failure"):
        cli.main(argv)


@pytest.mark.parametrize("error", [ValueError, OSError, TypeError, KeyError])
def test_main_does_not_hide_unrelated_errors(error, inputs, monkeypatch):
    def fail(*args, **kwargs):
        raise error("not an input loader error")

    monkeypatch.setattr(cli.Surface, "search", fail)
    with pytest.raises(error, match="not an input loader error"):
        cli.main([
            "events", "--canon", inputs["canon"],
            "--policy", inputs["policy"],
        ])
