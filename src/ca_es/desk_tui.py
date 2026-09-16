"""P1.2 Ops Desk — TUI read-only sobre Surface.brief().

Solo navegacion, filtrado y render: consume el desk model
(ca_es.desk.build_desk_model) y, opcionalmente, la Surface para la
cadena de evidencia. No llama a parsers, identity ni source policy,
y no recalcula deadlines ni conflictos.

Extra opcional: ``pip install 'ca-es[desk]'`` (textual).
"""
from __future__ import annotations

import json

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from .desk import detail_lines, evidence_blocks, item_matches


class EvidenceScreen(ModalScreen):
    """Cadenas de evidencia/provenance, solo lectura. Cada bloque va
    rotulado con su origen (CURRENT / PREVIOUS / ASSERTION <id>)."""

    BINDINGS = [
        Binding("escape", "dismiss", "Back"),
        Binding("q", "dismiss", "Back"),
        Binding("enter", "dismiss", "Back"),
    ]

    def __init__(self, blocks: list[dict]) -> None:
        super().__init__()
        self.blocks = blocks

    def compose(self) -> ComposeResult:
        text = "\n\n".join(
            "== {label} ==\n{payload}".format(
                label=block["label"],
                payload=json.dumps(
                    block["payload"],
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                    default=str,
                ),
            )
            for block in self.blocks
        )
        with VerticalScroll(id="evidence-box"):
            yield Static(text, id="evidence")


class DetailScreen(ModalScreen):
    """Detalle operacional minimo de un item del desk."""

    BINDINGS = [
        Binding("escape", "dismiss", "Back"),
        Binding("q", "dismiss", "Back"),
        Binding("e", "evidence", "Evidence"),
    ]

    def __init__(self, section_key: str, item: dict) -> None:
        super().__init__()
        self.section_key = section_key
        self.item = item

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="detail-box"):
            yield Static(
                "\n".join(detail_lines(self.section_key, self.item)),
                id="detail",
            )

    def action_evidence(self) -> None:
        desk = self.app
        blocks = evidence_blocks(
            desk.surface,
            desk.previous_surface,
            self.section_key,
            self.item,
        )
        if blocks:
            self.app.push_screen(EvidenceScreen(blocks))


class OpsDesk(App):
    """Desk operacional read-only: una unica pantalla con las cuatro
    secciones del brief. El filtrado actua sobre la vista; el modelo
    y el brief no se mutan jamas."""

    CSS = """
    #summary {
        dock: top;
        height: auto;
        padding: 0 1;
        background: $boost;
    }
    #search {
        dock: top;
        display: none;
    }
    #search.visible {
        display: block;
    }
    #queue {
        height: 1fr;
    }
    #status {
        dock: bottom;
        height: 1;
        padding: 0 1;
        background: $boost;
    }
    DetailScreen, EvidenceScreen {
        align: center middle;
    }
    #detail-box, #evidence-box {
        width: 80%;
        height: 80%;
        border: solid $primary;
        padding: 1 2;
        background: $surface;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("1", "goto(0)", "Action"),
        Binding("a", "goto(0)", "Action"),
        Binding("2", "goto(1)", "New"),
        Binding("n", "goto(1)", "New"),
        Binding("3", "goto(2)", "Conflicts"),
        Binding("c", "goto(2)", "Conflicts"),
        Binding("4", "goto(3)", "Unsupported"),
        Binding("u", "goto(3)", "Unsupported"),
        Binding("slash", "search", "Filter"),
        Binding("e", "evidence", "Evidence"),
        Binding("escape", "cancel_search", "Back"),
    ]

    def __init__(
        self, model: dict, surface=None, previous_surface=None
    ) -> None:
        super().__init__()
        self.model = model
        self.surface = surface
        self.previous_surface = previous_surface
        self._items: dict[str, tuple[str, dict]] = {}
        self._first_index: dict[str, int] = {}

    def compose(self) -> ComposeResult:
        summary = self.model["summary"]
        yield Static(
            "CA-ES DESK  as_of={as_of}  window={window}d   "
            "action={action}  new={new}  conflicts={conflicts}  "
            "unsupported={unsup}".format(
                as_of=self.model["as_of"],
                window=self.model["window_days"],
                action=summary["action_required"],
                new=summary.get("new_since_previous", "-"),
                conflicts=summary["conflicting_events"],
                unsup=summary["unsupported_items"],
            ),
            id="summary",
        )
        yield Input(placeholder="filter — esc clears", id="search")
        yield OptionList(id="queue")
        yield Static(id="status")

    def on_mount(self) -> None:
        self._populate("")
        self.query_one("#queue", OptionList).focus()

    def _section_title(self, key: str) -> str:
        for section in self.model["sections"]:
            if section["key"] == key:
                return section["title"]
        return key

    def _set_status(self, section_key: str | None) -> None:
        status = self.query_one("#status", Static)
        where = (
            self._section_title(section_key) if section_key else "-"
        )
        status.update(
            f"{where}   1-4/a n c u secciones · enter detalle · "
            f"e evidencia · / filtro · q salir"
        )

    # ---------------------------------------------------------- view

    def _populate(self, query: str) -> None:
        """Reconstruye las opciones visibles. El modelo no se toca."""
        options = self.query_one("#queue", OptionList)
        options.clear_options()
        self._items = {}
        self._first_index = {}
        for section in self.model["sections"]:
            title = f"── {section['title']} ({len(section['items'])}) ──"
            if section["note"]:
                title += f"  {section['note']}"
            options.add_option(Option(title, disabled=True))
            for entry in section["items"]:
                if query and not item_matches(entry, query):
                    continue
                if section["key"] not in self._first_index:
                    self._first_index[section["key"]] = options.option_count
                options.add_option(
                    Option("  " + entry["label"], id=entry["item_key"])
                )
                self._items[entry["item_key"]] = (
                    section["key"],
                    entry["item"],
                )
        self._set_status(self.model["sections"][0]["key"])

    def _selected_item(self) -> tuple[str, dict] | None:
        options = self.query_one("#queue", OptionList)
        highlighted = options.highlighted
        if highlighted is None:
            return None
        option = options.get_option_at_index(highlighted)
        if option is None or option.id is None:
            return None
        return self._items.get(option.id)

    # --------------------------------------------------------- events

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        found = self._items.get(event.option.id or "")
        if found is not None:
            self.push_screen(DetailScreen(*found))

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        option_id = event.option.id
        if option_id:
            self._set_status(option_id.split(":", 1)[0])

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self._populate(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            self.query_one("#queue", OptionList).focus()

    # -------------------------------------------------------- actions

    def action_goto(self, index: int) -> None:
        section = self.model["sections"][index]
        first = self._first_index.get(section["key"])
        options = self.query_one("#queue", OptionList)
        options.focus()
        if first is not None:
            options.highlighted = first

    def action_search(self) -> None:
        search = self.query_one("#search", Input)
        search.add_class("visible")
        search.focus()

    def action_cancel_search(self) -> None:
        search = self.query_one("#search", Input)
        if search.has_class("visible"):
            search.value = ""
            search.remove_class("visible")
            self._populate("")
            self.query_one("#queue", OptionList).focus()

    def action_evidence(self) -> None:
        found = self._selected_item()
        if found is None:
            return
        blocks = evidence_blocks(
            self.surface, self.previous_surface, found[0], found[1]
        )
        if blocks:
            self.push_screen(EvidenceScreen(blocks))
