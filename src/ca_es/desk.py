"""P1.2 Ops Desk — proyeccion read-only del morning brief.

Modelo puro (stdlib): convierte el objeto brief() en secciones/items
navegables y renderiza detalles. Ninguna logica semantica vive aqui:
los items son EXACTAMENTE los del brief, sin recalcular deadlines,
conflictos ni capacidades. La capa TUI (desk_tui, extra `desk`) solo
hace navegacion, filtrado y render sobre este modelo.

Invariantes heredados del brief:
- todo item conserva assertion_id / source_document_id /
  evidence_locator cuando existen;
- UNSUPPORTED es una salida valida y visible, nunca un error ni un
  dato disponible;
- los conflictos se muestran sin ganador (no hay accion de decision);
- el filtrado de busqueda actua sobre la vista, nunca sobre el modelo.
"""
from __future__ import annotations

import json

from .surface import _normalize

DESK_SECTIONS = (
    ("action_required", "ACTION REQUIRED"),
    ("new_since_previous", "NEW SINCE PREVIOUS"),
    ("conflicts", "CONFLICTS"),
    ("unsupported", "UNSUPPORTED"),
)

SECTION_KEYS = {key for key, _ in DESK_SECTIONS}


def _fmt_value(value: object) -> str:
    """Valor canonico -> texto: importes como '0.22 EUR'."""
    if isinstance(value, dict):
        if value.get("__financial__"):
            return f"{value['normalized']} {value['currency']}"
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return str(value)


def _fmt_conflict_value(raw: str) -> str:
    """Los values de conflicto viajan como lexemas JSON."""
    try:
        return _fmt_value(json.loads(raw))
    except (ValueError, TypeError):
        return str(raw)


def _eid8(item: dict) -> str:
    return item.get("canonical_event_id", "")[:8]


def _label(section_key: str, item: dict) -> str:
    """Linea unica por item para la lista del desk."""
    issuer = item.get("issuer_name") or "-"
    if section_key == "action_required":
        return (
            f"{item['date']}  +{item['days_until']}d  {issuer} · "
            f"{item['event_type']} · {item['field_path']}"
        )
    if section_key == "new_since_previous":
        kind = item["kind"]
        field = item.get("field_path") or item.get("event_type") or ""
        label = f"{kind}  {field}  [{_eid8(item)}]"
        if kind == "CHANGED_ASSERTION":
            label += (
                f"  {_fmt_value(item['previous_value'])}"
                f" -> {_fmt_value(item['value'])}"
            )
        elif kind in ("NEW_ASSERTION",):
            label += f"  {_fmt_value(item['value'])}"
        elif kind == "REMOVED_ASSERTION":
            label += f"  (was {_fmt_value(item['previous_value'])})"
        elif kind in ("NEW_CONFLICT", "RESOLVED_CONFLICT"):
            label += (
                "  " + ", ".join(
                    _fmt_conflict_value(v) for v in item["values"]
                )
            )
        return label
    if section_key == "conflicts":
        return (
            f"{issuer} · {item['field_path']} · "
            f"{len(item['values'])} values  [{_eid8(item)}]"
        )
    if section_key == "unsupported":
        return (
            f"{issuer} · {item['field_path']} -> UNSUPPORTED "
            f"({item['capability']})  [{_eid8(item)}]"
        )
    return issuer


def build_desk_model(brief: dict) -> dict:
    """Proyeccion del brief en las cuatro secciones del desk.

    Cada entry referencia el item del brief SIN copiarlo ni alterarlo.
    `new_since_previous` solo existe si el brief se genero con
    previous; si falta, la seccion queda vacia con note explicita.
    """
    sections = []
    for key, title in DESK_SECTIONS:
        items = brief.get(key)
        note = None
        if items is None:
            items = []
            if key == "new_since_previous":
                note = "no previous canon supplied"
        entries = [
            {
                "item_key": f"{key}:{i}",
                "label": _label(key, item),
                "item": item,
            }
            for i, item in enumerate(items)
        ]
        sections.append(
            {
                "key": key,
                "title": title,
                "note": note,
                "items": entries,
            }
        )
    return {
        "as_of": brief["as_of"],
        "window_days": brief["window_days"],
        "summary": brief["summary"],
        "sections": sections,
    }


def _item_metadata(item: dict) -> dict:
    """Fallback de provenance a nivel de item cuando no hay cadena
    resoluble (p. ej. NEW_EVENT, UNSUPPORTED, assertion_id no
    encontrado)."""
    keys = (
        "assertion_id",
        "source_document_id",
        "evidence_locator",
        "previous_assertion_id",
        "previous_evidence_locator",
        "assertion_ids",
        "source_id",
        "capability",
        "capability_status",
        "evidence",
    )
    return {k: item[k] for k in keys if item.get(k)}


def _resolve(surface, assertion_id):
    if surface is None or not assertion_id:
        return None
    return surface.evidence(assertion_id)


def evidence_blocks(
    surface,
    previous_surface,
    section_key: str,
    item: dict,
) -> list[dict]:
    """Cadenas de evidencia de un item, conscientes del origen.

    Cada bloque es {"label", "payload"}; payload es la cadena
    completa de Surface.evidence() o, si no es resoluble, el fallback
    de metadatos del item. Reglas de origen:

      ACTION_REQUIRED    -> current
      NEW_ASSERTION      -> current
      CHANGED_ASSERTION  -> CURRENT + PREVIOUS (ambos lados)
      REMOVED_ASSERTION  -> previous
      conflicts / NEW_CONFLICT     -> todos los assertion_ids, current
      RESOLVED_CONFLICT  -> todos los assertion_ids, previous
    """
    kind = item.get("kind")
    labeled: list[tuple[str, dict | None]] = []
    if section_key == "action_required":
        labeled = [("CURRENT", _resolve(surface, item.get("assertion_id")))]
    elif section_key == "conflicts":
        labeled = [
            (f"ASSERTION {aid}", _resolve(surface, aid))
            for aid in item.get("assertion_ids", [])
        ]
    elif section_key == "new_since_previous":
        if kind == "CHANGED_ASSERTION":
            labeled = [
                ("CURRENT", _resolve(surface, item.get("assertion_id"))),
                (
                    "PREVIOUS",
                    _resolve(
                        previous_surface,
                        item.get("previous_assertion_id"),
                    ),
                ),
            ]
        elif kind == "NEW_ASSERTION":
            labeled = [
                ("CURRENT", _resolve(surface, item.get("assertion_id")))
            ]
        elif kind == "REMOVED_ASSERTION":
            labeled = [
                (
                    "PREVIOUS",
                    _resolve(
                        previous_surface,
                        item.get("previous_assertion_id"),
                    ),
                )
            ]
        elif kind == "NEW_CONFLICT":
            labeled = [
                (f"ASSERTION {aid}", _resolve(surface, aid))
                for aid in item.get("assertion_ids", [])
            ]
        elif kind == "RESOLVED_CONFLICT":
            labeled = [
                (
                    f"ASSERTION {aid}",
                    _resolve(previous_surface, aid),
                )
                for aid in item.get("assertion_ids", [])
            ]
    blocks = [
        {"label": label, "payload": chain or _item_metadata(item)}
        for label, chain in labeled
    ]
    if not blocks:
        meta = _item_metadata(item)
        if meta:
            blocks.append({"label": "ITEM", "payload": meta})
    return blocks


def _haystack(entry: dict) -> str:
    return _normalize(
        entry["label"]
        + " "
        + json.dumps(entry["item"], sort_keys=True, default=str)
    )


def item_matches(entry: dict, query: str) -> bool:
    """Filtro de vista: la consulta se aplica sobre label+payload,
    nunca muta el modelo ni el brief."""
    return _normalize(query) in _haystack(entry)


def detail_lines(section_key: str, item: dict) -> list[str]:
    """Detalle operacional minimo por tipo de item.

    Mantiene los identificadores de provenance tal cual llegan del
    brief; no resuelve ni selecciona nada.
    """
    lines: list[str] = []
    issuer = item.get("issuer_name")
    if issuer:
        lines.append(str(issuer))
    if item.get("event_type"):
        etype = item["event_type"]
        field = item.get("field_path")
        lines.append(f"{etype} / {field}" if field else etype)
    elif item.get("field_path"):
        lines.append(str(item["field_path"]))
    eid = item.get("canonical_event_id")
    if eid:
        lines.append(f"event: {eid}")
    lines.append("")

    if section_key == "action_required":
        lines.append(f"ACTION_REQUIRED · {item['days_until']} days")
        lines.append("")
        lines.append("Value")
        lines.append(f"  {item['date']}")
        lines.append("")
        lines.append("Evidence")
        lines.append(f"  assertion_id: {item['assertion_id']}")
        lines.append(f"  source_document_id: {item['source_document_id']}")
        lines.append(f"  evidence_locator: {item['evidence_locator']}")
        return lines

    if section_key == "conflicts":
        lines.append("CONFLICTING — no winner selected")
        lines.append("")
        lines.append("Values")
        for v in item["values"]:
            lines.append(f"  {_fmt_conflict_value(v)}")
        lines.append("")
        lines.append("Evidence")
        for aid in item.get("assertion_ids", []):
            lines.append(f"  assertion_id: {aid}")
        if item.get("asserted_as_of"):
            lines.append(f"  asserted_as_of: {item['asserted_as_of']}")
        return lines

    if section_key == "unsupported":
        lines.append(
            f"UNSUPPORTED ({item['capability']}) — "
            f"{item.get('capability_status', '')}"
        )
        lines.append("")
        lines.append(
            "The source cannot assert this field. It is shown as "
            "UNSUPPORTED, not as missing or zero."
        )
        lines.append("")
        lines.append(f"  source_id: {item.get('source_id')}")
        if item.get("evidence"):
            lines.append(f"  policy evidence: {item['evidence']}")
        return lines

    # new_since_previous
    kind = item["kind"]
    lines.append(kind)
    lines.append("")
    if kind in ("NEW_EVENT", "REMOVED_EVENT"):
        if item.get("issuer_name"):
            lines.append(f"  issuer: {item['issuer_name']}")
        if item.get("event_type"):
            lines.append(f"  event_type: {item['event_type']}")
        return lines
    if kind == "CHANGED_ASSERTION":
        lines.append(f"  Previous: {_fmt_value(item['previous_value'])}")
        lines.append(f"  Current:  {_fmt_value(item['value'])}")
        lines.append("")
        lines.append("Current evidence")
        lines.append(f"  assertion_id: {item.get('assertion_id')}")
        lines.append(
            f"  evidence_locator: {item.get('evidence_locator')}"
        )
        lines.append("Previous evidence")
        lines.append(
            f"  assertion_id: {item.get('previous_assertion_id')}"
        )
        lines.append(
            f"  evidence_locator: {item.get('previous_evidence_locator')}"
        )
        return lines
    if kind == "REMOVED_ASSERTION":
        lines.append(f"  Removed value: {_fmt_value(item['previous_value'])}")
        lines.append("")
        lines.append("Previous evidence")
        lines.append(
            f"  assertion_id: {item.get('previous_assertion_id')}"
        )
        lines.append(
            f"  evidence_locator: {item.get('previous_evidence_locator')}"
        )
        return lines
    if kind == "NEW_ASSERTION":
        lines.append(f"  Value: {_fmt_value(item['value'])}")
        lines.append("")
        lines.append("Evidence")
        lines.append(f"  assertion_id: {item.get('assertion_id')}")
        lines.append(
            f"  evidence_locator: {item.get('evidence_locator')}"
        )
        return lines
    if kind in ("NEW_CONFLICT", "RESOLVED_CONFLICT"):
        lines.append("Values")
        for v in item["values"]:
            lines.append(f"  {_fmt_conflict_value(v)}")
        lines.append("")
        for aid in item.get("assertion_ids", []):
            lines.append(f"  assertion_id: {aid}")
        return lines
    if kind in ("NEW_UNSUPPORTED", "SUPPORTED_NOW"):
        lines.append(f"  capability: {item.get('capability')}")
        return lines
    return lines
