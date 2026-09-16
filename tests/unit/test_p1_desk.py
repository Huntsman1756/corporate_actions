# -*- coding: utf-8 -*-
"""Tests P1.2: Ops Desk — frontera UI sobre brief(), no su semantica."""
import asyncio
import json
from pathlib import Path

import pytest

from ca_es.desk import (
    build_desk_model,
    detail_lines,
    evidence_blocks,
    item_matches,
)
from ca_es.surface import Surface, load_surface

pytest.importorskip("textual")

from ca_es.desk_tui import DetailScreen, EvidenceScreen, OpsDesk  # noqa: E402
from textual.widgets import OptionList, Static  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CANON = REPO / "g3/input/canon.json"
POLICY = REPO / "docs/sources/source-policy.json"

MFE = "59303c3c-8be7-578f-bc59-8e5e43a1fdf3"
ALMIRALL = "035e32ca-ba61-5105-8756-e0234e5335fc"
POEX = "e885fff1-0a3b-57d7-a2fa-f51a6e613f10"


@pytest.fixture(scope="module")
def surface() -> Surface:
    return load_surface(CANON, POLICY)


@pytest.fixture(scope="module")
def brief(surface) -> dict:
    return surface.brief("2026-07-15")


def _surface_of(canon_dict) -> Surface:
    return Surface(
        canon_dict, json.loads(POLICY.read_text(encoding="utf-8"))
    )


def _canon_copy() -> dict:
    return json.loads(CANON.read_text(encoding="utf-8"))


def _brief_with_changed_assertion(surface) -> dict:
    previous_canon = _canon_copy()
    mfe = next(
        e for e in previous_canon["events"] if e["canonical_event_id"] == MFE
    )
    target = next(
        f for f in mfe["facts"]
        if f["field_path"] == "date.ex_date" and f["value"] == "2026-07-20"
    )
    target["value"] = "2026-07-19"
    return surface.brief("2026-07-15", previous=_surface_of(previous_canon))


# ------------------------------------------------------------ modelo puro

def test_model_sections_contain_exactly_brief_items(brief):
    model = build_desk_model(brief)
    keys = [s["key"] for s in model["sections"]]
    assert keys == [
        "action_required",
        "new_since_previous",
        "conflicts",
        "unsupported",
    ]
    for section in model["sections"]:
        expected = brief.get(section["key"]) or []
        # los items son EXACTAMENTE los del brief: mismo orden, mismo
        # objeto, cero inventados o descartados
        assert [e["item"] for e in section["items"]] == expected
        keys_ = [e["item_key"] for e in section["items"]]
        assert len(set(keys_)) == len(keys_)


def test_model_without_previous_canon(brief):
    # brief sin previous: la seccion existe pero vacia y explicita
    assert "new_since_previous" not in brief
    model = build_desk_model(brief)
    section = next(
        s for s in model["sections"] if s["key"] == "new_since_previous"
    )
    assert section["items"] == []
    assert section["note"] == "no previous canon supplied"


def test_model_with_previous_canon(surface):
    brief = _brief_with_changed_assertion(surface)
    model = build_desk_model(brief)
    section = next(
        s for s in model["sections"] if s["key"] == "new_since_previous"
    )
    assert [e["item"] for e in section["items"]] == brief[
        "new_since_previous"
    ]
    assert section["note"] is None


def test_detail_action_required_preserves_evidence(brief):
    for item in brief["action_required"]:
        text = "\n".join(detail_lines("action_required", item))
        assert item["assertion_id"] in text
        assert item["source_document_id"] in text
        assert item["evidence_locator"] in text
        assert item["date"] in text


def test_detail_changed_assertion_before_after(surface):
    brief = _brief_with_changed_assertion(surface)
    changed = next(
        i for i in brief["new_since_previous"]
        if i["kind"] == "CHANGED_ASSERTION"
    )
    text = "\n".join(detail_lines("new_since_previous", changed))
    assert "Previous: 2026-07-19" in text
    assert "Current:  2026-07-20" in text
    assert changed["assertion_id"] in text
    assert changed["previous_assertion_id"] in text
    assert changed["evidence_locator"] in text
    assert changed["previous_evidence_locator"] in text


def test_detail_unsupported_never_a_value(brief):
    poex = next(
        i for i in brief["unsupported"] if i["canonical_event_id"] == POEX
    )
    text = "\n".join(detail_lines("unsupported", poex))
    assert "UNSUPPORTED" in text
    assert "capital_increase_issue_price" in text
    assert "QUARANTINED_UNSUPPORTED" in text
    # nunca se renderiza como dato disponible ni como error
    assert "Value:" not in text
    assert "ERROR" not in text
    entry = next(
        e
        for s in build_desk_model(brief)["sections"]
        if s["key"] == "unsupported"
        for e in s["items"]
        if e["item"] is poex
    )
    assert "UNSUPPORTED" in entry["label"]


def test_detail_conflict_no_winner(brief):
    conflict = next(
        i for i in brief["conflicts"]
        if i["canonical_event_id"] == ALMIRALL
    )
    text = "\n".join(detail_lines("conflicts", conflict))
    assert "no winner" in text
    assert "2023-06-12" in text
    assert "2023-06-13" in text
    for aid in conflict["assertion_ids"]:
        assert aid in text
    # ninguna accion de decision en el detalle
    for word in ("accept", "resolve", "choose"):
        assert word not in text.casefold()


def test_filter_is_view_only(brief):
    model = build_desk_model(brief)
    before = json.dumps(model, sort_keys=True, default=str)
    section = model["sections"][0]
    matched = [
        e for e in section["items"] if item_matches(e, "date.ex_date")
    ]
    assert matched and len(matched) < len(section["items"])
    assert not item_matches(section["items"][0], "zzz-nonexistent")
    assert json.dumps(model, sort_keys=True, default=str) == before
    assert json.dumps(brief, sort_keys=True, default=str)


def test_model_empty_brief_clean():
    empty = {
        "as_of": "2026-07-15",
        "window_days": 7,
        "summary": {
            "events": 0,
            "action_required": 0,
            "revised_events": 0,
            "conflicting_events": 0,
            "unsupported_items": 0,
        },
        "action_required": [],
        "recent_changes": [],
        "conflicts": [],
        "unsupported": [],
    }
    model = build_desk_model(empty)
    assert all(s["items"] == [] for s in model["sections"])
    assert detail_lines("conflicts", {"field_path": "f", "values": []})


def test_model_deterministic(surface):
    brief = _brief_with_changed_assertion(surface)
    a = json.dumps(build_desk_model(brief), sort_keys=True, default=str)
    b = json.dumps(build_desk_model(brief), sort_keys=True, default=str)
    assert a == b


# ---------------------------------------------------------------- TUI

def _enabled_options(app):
    ol = app.query_one("#queue", OptionList)
    return [
        ol.get_option_at_index(i)
        for i in range(ol.option_count)
        if not ol.get_option_at_index(i).disabled
    ]


def test_desk_lists_every_brief_item(brief, surface):
    model = build_desk_model(brief)
    app = OpsDesk(model, surface)

    async def go():
        async with app.run_test(size=(100, 30)):
            prompts = [str(o.prompt) for o in _enabled_options(app)]
            n_items = sum(
                len(s["items"]) for s in model["sections"]
            )
            assert len(prompts) == n_items  # cero inventados/descartados
            joined = "\n".join(
                str(o.prompt) for o in app.query_one(
                    "#queue", OptionList
                ).options
            )
            for section in model["sections"]:
                assert section["title"] in joined
                for entry in section["items"]:
                    assert any(entry["label"] in p for p in prompts)

    asyncio.run(go())


def test_desk_detail_and_evidence_navigation(brief, surface):
    model = build_desk_model(brief)
    app = OpsDesk(model, surface)
    first = brief["action_required"][0]

    async def go():
        async with app.run_test(size=(100, 30)) as pilot:
            ol = app.query_one("#queue", OptionList)
            ol.highlighted = app._first_index["action_required"]
            await pilot.press("enter")
            assert isinstance(app.screen, DetailScreen)
            text = str(app.screen.query_one("#detail", Static).visual)
            assert first["assertion_id"] in text
            assert first["evidence_locator"] in text
            await pilot.press("e")
            assert isinstance(app.screen, EvidenceScreen)
            evidence = str(
                app.screen.query_one("#evidence", Static).visual
            )
            assert first["assertion_id"] in evidence
            await pilot.press("escape")
            assert isinstance(app.screen, DetailScreen)
            await pilot.press("escape")

    asyncio.run(go())


def test_desk_goto_and_filter(brief, surface):
    model = build_desk_model(brief)
    app = OpsDesk(model, surface)

    async def go():
        async with app.run_test(size=(100, 30)) as pilot:
            ol = app.query_one("#queue", OptionList)
            await pilot.press("3")
            assert ol.highlighted == app._first_index["conflicts"]
            status = str(app.query_one("#status", Static).visual)
            assert "CONFLICTS" in status
            await pilot.press("4")
            assert ol.highlighted == app._first_index["unsupported"]
            status = str(app.query_one("#status", Static).visual)
            assert "UNSUPPORTED" in status
            # la busqueda filtra la vista sin tocar el modelo
            await pilot.press("slash")
            search = app.query_one("#search")
            assert search.has_class("visible")
            search.value = "almirall"
            await pilot.pause()
            prompts = [
                str(o.prompt) for o in _enabled_options(app)
            ]
            assert prompts
            assert all("almirall" in p.casefold() for p in prompts)
            await pilot.press("escape")
            await pilot.pause()
            n_items = sum(
                len(s["items"]) for s in model["sections"]
            )
            assert len(_enabled_options(app)) == n_items

    asyncio.run(go())


def test_desk_small_terminal_keeps_all_items(brief, surface):
    model = build_desk_model(brief)
    app = OpsDesk(model, surface)

    async def go():
        async with app.run_test(size=(40, 12)):
            n_items = sum(
                len(s["items"]) for s in model["sections"]
            )
            # terminal pequena: scroll conserva todos los items
            assert len(_enabled_options(app)) == n_items
            headers = [
                str(o.prompt)
                for o in app.query_one("#queue", OptionList).options
                if o.disabled
            ]
            assert len(headers) == len(model["sections"])

    asyncio.run(go())


def test_desk_empty_brief_runs(surface):
    model = build_desk_model(
        {
            "as_of": "2026-07-15",
            "window_days": 7,
            "summary": {
                "events": 0,
                "action_required": 0,
                "revised_events": 0,
                "conflicting_events": 0,
                "unsupported_items": 0,
            },
            "action_required": [],
            "recent_changes": [],
            "conflicts": [],
            "unsupported": [],
        }
    )
    app = OpsDesk(model, surface)

    async def go():
        async with app.run_test(size=(80, 24)) as pilot:
            assert _enabled_options(app) == []
            await pilot.press("q")

    asyncio.run(go())


def test_evidence_bilateral_changed_assertion(surface):
    previous_canon = _canon_copy()
    mfe = next(
        e for e in previous_canon["events"] if e["canonical_event_id"] == MFE
    )
    target = next(
        f for f in mfe["facts"]
        if f["field_path"] == "date.ex_date" and f["value"] == "2026-07-20"
    )
    target["value"] = "2026-07-19"
    previous = _surface_of(previous_canon)
    brief = surface.brief("2026-07-15", previous=previous)
    changed = next(
        i for i in brief["new_since_previous"]
        if i["kind"] == "CHANGED_ASSERTION"
    )
    blocks = evidence_blocks(
        surface, previous, "new_since_previous", changed
    )
    assert [b["label"] for b in blocks] == ["CURRENT", "PREVIOUS"]
    cur, prev = blocks[0]["payload"], blocks[1]["payload"]
    assert cur["assertion_id"] == changed["assertion_id"]
    assert cur["value"] == "2026-07-20"
    assert cur["raw_pointer"] and cur["source_document"]
    assert prev["assertion_id"] == changed["previous_assertion_id"]
    assert prev["value"] == "2026-07-19"
    assert prev["raw_pointer"]


def test_evidence_removed_assertion_uses_previous(surface):
    previous_canon = _canon_copy()
    mfe = next(
        e for e in previous_canon["events"] if e["canonical_event_id"] == MFE
    )
    retracted = dict(mfe["facts"][0])
    retracted["field_path"] = "date.election_deadline"
    retracted["value"] = "2026-07-24"
    retracted["assertion_id"] = "test-retracted-id"
    mfe["facts"].append(retracted)
    previous = _surface_of(previous_canon)
    brief = surface.brief("2026-07-15", previous=previous)
    removed = next(
        i for i in brief["new_since_previous"]
        if i["kind"] == "REMOVED_ASSERTION"
    )
    blocks = evidence_blocks(
        surface, previous, "new_since_previous", removed
    )
    assert [b["label"] for b in blocks] == ["PREVIOUS"]
    payload = blocks[0]["payload"]
    # resuelto contra el snapshot previo, no metadata degradada
    assert payload["assertion_id"] == "test-retracted-id"
    assert payload["value"] == "2026-07-24"
    assert payload["raw_pointer"]


def test_evidence_conflict_expands_all_assertions(brief, surface):
    conflict = next(
        i for i in brief["conflicts"]
        if i["canonical_event_id"] == ALMIRALL
    )
    blocks = evidence_blocks(surface, None, "conflicts", conflict)
    assert len(blocks) == len(conflict["assertion_ids"])
    values = {b["payload"]["value"] for b in blocks}
    assert values == {"2023-06-12", "2023-06-13"}
    for block in blocks:
        assert block["payload"]["assertion_id"] in conflict[
            "assertion_ids"
        ]
        assert block["payload"]["raw_pointer"]


def test_evidence_resolved_conflict_uses_previous(surface):
    current_canon = _canon_copy()
    almirall = next(
        e for e in current_canon["events"]
        if e["canonical_event_id"] == ALMIRALL
    )
    # el conflicto y sus facts desaparecen del current: la cadena solo
    # es resoluble contra previous
    aids = {a for c in almirall["conflicts"] for a in c["assertion_ids"]}
    almirall["conflicts"] = []
    almirall["facts"] = [
        f for f in almirall["facts"] if f["assertion_id"] not in aids
    ]
    current = _surface_of(current_canon)
    brief = current.brief("2026-07-15", previous=surface)
    resolved = next(
        i for i in brief["new_since_previous"]
        if i["kind"] == "RESOLVED_CONFLICT"
    )
    blocks = evidence_blocks(
        current, surface, "new_since_previous", resolved
    )
    assert len(blocks) == len(resolved["assertion_ids"])
    for block in blocks:
        payload = block["payload"]
        # resuelto contra previous: cadena completa, no fallback
        assert payload["assertion_id"] in resolved["assertion_ids"]
        assert payload["value"] in ("2023-06-12", "2023-06-13")
        assert payload["raw_pointer"]


def test_desk_evidence_bilateral_tui(surface):
    previous_canon = _canon_copy()
    mfe = next(
        e for e in previous_canon["events"] if e["canonical_event_id"] == MFE
    )
    target = next(
        f for f in mfe["facts"]
        if f["field_path"] == "date.ex_date" and f["value"] == "2026-07-20"
    )
    target["value"] = "2026-07-19"
    previous = _surface_of(previous_canon)
    brief = surface.brief("2026-07-15", previous=previous)
    model = build_desk_model(brief)
    app = OpsDesk(model, surface, previous_surface=previous)

    async def go():
        async with app.run_test(size=(100, 30)) as pilot:
            ol = app.query_one("#queue", OptionList)
            ol.highlighted = app._first_index["new_since_previous"]
            await pilot.press("enter")
            assert isinstance(app.screen, DetailScreen)
            await pilot.press("e")
            assert isinstance(app.screen, EvidenceScreen)
            text = str(
                app.screen.query_one("#evidence", Static).visual
            )
            assert "== CURRENT ==" in text
            assert "== PREVIOUS ==" in text
            assert "2026-07-20" in text
            assert "2026-07-19" in text

    asyncio.run(go())


def test_desk_render_snapshot(brief, surface):
    """Snapshot estable de las lineas de opciones (no golden pixel)."""
    model = build_desk_model(brief)
    app = OpsDesk(model, surface)

    async def go():
        async with app.run_test(size=(100, 30)):
            ol = app.query_one("#queue", OptionList)
            lines = [str(o.prompt) for o in ol.options]
            assert lines[0].startswith("── ACTION REQUIRED (3)")
            assert any(
                "2026-07-20" in line and "date.ex_date" in line
                for line in lines
            )
            assert any("CONFLICTS (2)" in line for line in lines)
            assert any("UNSUPPORTED (1)" in line for line in lines)
            assert any(
                "issue_price_per_share" in line and "UNSUPPORTED" in line
                for line in lines
            )

    asyncio.run(go())
