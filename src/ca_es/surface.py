"""Superficie operacional G3 sobre CA_ES_OPERATIONAL_CANON_V1.

Capa de consumo del canon exportado: consultas, materializacion del
estado vigente (CURRENT_STATE_V1), timeline de revisiones, conflictos,
navegacion de evidencia y honestidad de capacidades UNSUPPORTED.

Contrato: docs/gates/g3-preregistered.json (tag g3-protocol).

Reglas fijadas:
- la superficie consume un artefacto canonico ya generado; nunca
  re-ejecuta run_pipeline;
- source-policy.json es un segundo input READ_ONLY pinneado: unica
  fuente del estado contractual de capacidades;
- el estado vigente se materializa por CURRENT_STATE_V1, sin destruir
  historia ni inventar datos;
- salida determinista: los payloads se renderizan con canonical_json.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from .canonical import load_strict_json_object

SURFACE_VERSION = "CA_ES_OPERATIONAL_SURFACE_V1"
EVENT_SCOPE = "EVENT_SCOPE"

# Mapeo contractual capability -> field(s) afectados. El ESTADO de la
# capacidad (QUARANTINED_UNSUPPORTED) nunca vive aqui: viene siempre del
# source-policy.json pinneado.
CAPABILITY_FIELDS: dict[str, dict] = {
    "capital_increase_issue_price": {
        "field_paths": ["amount.issue_price_per_share"],
        "event_types": ["CAPITAL_INCREASE", "RIGHTS_ISSUE"],
    },
}


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.split()).casefold()


def _fingerprint(value: object) -> str:
    """Huella economica de un valor: los importes comparan por
    normalized+currency (Decimal canonico), el resto por JSON."""
    if isinstance(value, dict) and value.get("__financial__"):
        return json.dumps(
            {"normalized": value["normalized"], "currency": value["currency"]},
            sort_keys=True,
        )
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


class Surface:
    """Vista operacional sobre un canon CA_ES_OPERATIONAL_CANON_V1."""

    def __init__(self, canon: dict, policy: dict):
        self.canon = canon
        self.policy = policy
        self._events = {e["canonical_event_id"]: e for e in canon["events"]}
        self._unsupported = self._load_unsupported_capabilities()

    # ------------------------------------------------------------ policy

    def _load_unsupported_capabilities(self) -> list[dict]:
        """(source_id, capability, field_paths, event_types) para cada
        capacidad QUARANTINED_UNSUPPORTED del policy pinneado."""
        unsupported = []
        for source_id, source in sorted(self.policy.get("sources", {}).items()):
            for name, cap in sorted((source.get("capabilities") or {}).items()):
                if cap.get("status") != "QUARANTINED_UNSUPPORTED":
                    continue
                mapping = CAPABILITY_FIELDS.get(name)
                if mapping is None:
                    continue
                unsupported.append(
                    {
                        "source_id": source_id,
                        "capability": name,
                        "field_paths": list(mapping["field_paths"]),
                        "event_types": list(mapping["event_types"]),
                        "evidence": cap.get("evidence"),
                    }
                )
        return unsupported

    def _unsupported_for_event(self, event: dict) -> list[dict]:
        source_ids = {d["source_id"] for d in event["source_documents"]}
        present = {f["field_path"] for f in event["facts"]}
        out = []
        for cap in self._unsupported:
            if cap["source_id"] not in source_ids:
                continue
            if event["event_type"] not in cap["event_types"]:
                continue
            for field_path in cap["field_paths"]:
                if field_path in present:
                    continue
                out.append(
                    {
                        "field_path": field_path,
                        "status": "UNSUPPORTED",
                        "capability": cap["capability"],
                        "capability_status": "QUARANTINED_UNSUPPORTED",
                        "source_id": cap["source_id"],
                        "evidence": cap["evidence"],
                    }
                )
        return sorted(out, key=lambda item: item["field_path"])

    # ------------------------------------------------------------- events

    def _event_isins(self, event: dict) -> set[str]:
        isins = set()
        affected = event["affected_instrument"].get("isin")
        if affected:
            isins.add(affected)
        for fact in event["facts"]:
            if fact["field_path"] in ("instrument.isin", "affected_instrument.isin"):
                if isinstance(fact["value"], str):
                    isins.add(fact["value"])
        return isins

    def _summary(self, event: dict) -> dict:
        current = self._current_state(event)
        dates = {
            field: value["values"][0]["value"]
            for field, value in current.items()
            if field.startswith("date.")
            and value["status"] == "CURRENT"
            and value["values"]
        }
        return {
            "canonical_event_id": event["canonical_event_id"],
            "event_type": event["event_type"],
            "status": event["status"],
            "issuer_name": event["issuer"]["issuer_name"],
            "isin": event["affected_instrument"].get("isin"),
            "isins": sorted(self._event_isins(event)),
            "ex_date": dates.get("date.ex_date"),
            "payment_date": dates.get("date.payment_date"),
            "revision_count": len(event["revisions"]),
            "conflict_count": len(event["conflicts"]),
            "unsupported": [
                item["field_path"] for item in self._unsupported_for_event(event)
            ],
        }

    def search(
        self,
        isin: str | None = None,
        event_type: str | None = None,
        issuer: str | None = None,
    ) -> list[dict]:
        """Busqueda determinista: --isin/--type exactos, --issuer
        NFKD+casefold contains, AND, orden por canonical_event_id."""
        matched = []
        for event in self.canon["events"]:
            if isin is not None and isin not in self._event_isins(event):
                continue
            if event_type is not None and event["event_type"] != event_type:
                continue
            if issuer is not None:
                name = event["issuer"].get("issuer_name") or ""
                if _normalize(issuer) not in _normalize(name):
                    continue
            matched.append(event)
        return [self._summary(e) for e in sorted(
            matched, key=lambda e: e["canonical_event_id"]
        )]

    # ------------------------------------------------------- current state

    def _generations(self, event: dict) -> dict[str, int]:
        return {r["revision_id"]: r["generation"] for r in event["revisions"]}

    def _current_state(self, event: dict) -> dict:
        """CURRENT_STATE_V1: para cada field_path, la revision de mayor
        generation que lo contiene (EVENT_SCOPE = siempre vigente).
        1 valor -> CURRENT; >1 divergentes -> CONFLICTING sin ganador.
        La ausencia posterior no borra el ultimo valor publicado."""
        generations = self._generations(event)
        by_field: dict[str, dict[str, list[dict]]] = {}
        for fact in event["facts"]:
            by_field.setdefault(fact["field_path"], {}).setdefault(
                fact["revision_id"], []
            ).append(fact)

        state = {}
        for field_path in sorted(by_field):
            revision_facts = by_field[field_path]
            winning_revision = max(
                revision_facts,
                key=lambda rev: (
                    float("inf") if rev == EVENT_SCOPE else generations.get(rev, -1),
                    rev,
                ),
            )
            group = sorted(
                revision_facts[winning_revision], key=lambda f: f["assertion_id"]
            )
            fingerprints = {_fingerprint(f["value"]) for f in group}
            values = [
                {
                    "value": f["value"],
                    "assertion_id": f["assertion_id"],
                    "revision_id": f["revision_id"],
                    "generation": generations.get(f["revision_id"]),
                    "source_document_id": f["source_document_id"],
                    "source_id": f["source_id"],
                    "evidence_locator": f["evidence_locator"],
                    "raw_pointer": f["raw_pointer"],
                    "asserted_as_of": f["asserted_as_of"],
                    "fact_origin": f["fact_origin"],
                }
                for f in group
            ]
            state[field_path] = {
                "status": "CURRENT" if len(fingerprints) == 1 else "CONFLICTING",
                "values": values,
                "origin_revision_id": winning_revision,
                "origin_generation": generations.get(winning_revision),
            }
        return state

    # ----------------------------------------------------------- commands

    def _find(self, canonical_event_id: str) -> dict | None:
        return self._events.get(canonical_event_id)

    def show(self, canonical_event_id: str) -> dict | None:
        event = self._find(canonical_event_id)
        if event is None:
            return None
        return {
            "surface_version": SURFACE_VERSION,
            "canonical_event_id": event["canonical_event_id"],
            "event_type": event["event_type"],
            "status": event["status"],
            "issuer": event["issuer"],
            "affected_instrument": event["affected_instrument"],
            "current_state": self._current_state(event),
            "conflicts": event["conflicts"],
            "unsupported_capabilities": self._unsupported_for_event(event),
            "revisions": [
                {
                    "revision_id": r["revision_id"],
                    "generation": r["generation"],
                    "supersedes_revision_id": r["supersedes_revision_id"],
                }
                for r in event["revisions"]
            ],
            "provenance": event["provenance"],
            "source_documents": event["source_documents"],
        }

    def timeline(self, canonical_event_id: str) -> dict | None:
        event = self._find(canonical_event_id)
        if event is None:
            return None
        docs_by_id = {d["document_id"]: d for d in event["source_documents"]}
        facts_by_revision: dict[str, dict[str, list[dict]]] = {}
        for fact in event["facts"]:
            facts_by_revision.setdefault(fact["revision_id"], {}).setdefault(
                fact["field_path"], []
            ).append(fact)

        generations = self._generations(event)
        carried: dict[str, dict] = {}
        revisions_out = []
        for revision in sorted(
            event["revisions"], key=lambda r: (r["generation"], r["revision_id"])
        ):
            rid = revision["revision_id"]
            published = facts_by_revision.get(rid, {})
            changes = {}
            for field_path in sorted(published):
                seen: dict[str, dict] = {}
                for f in published[field_path]:
                    seen.setdefault(_fingerprint(f["value"]), f["value"])
                values = [seen[k] for k in sorted(seen)]
                previous = carried.get(field_path)
                changes[field_path] = {
                    "kind": (
                        "ADDED"
                        if previous is None
                        else (
                            "CHANGED"
                            if sorted(seen) != previous["fingerprints"]
                            else "REPUBLISHED"
                        )
                    ),
                    "previous_values": previous["values"] if previous else [],
                    "values": values,
                }
                carried[field_path] = {
                    "fingerprints": sorted(seen),
                    "values": values,
                }
            revisions_out.append(
                {
                    "revision_id": rid,
                    "generation": revision["generation"],
                    "supersedes_revision_id": revision["supersedes_revision_id"],
                    "source_documents": [
                        docs_by_id[d]["official_document_id"]
                        for d in sorted(revision["document_ids"])
                        if d in docs_by_id
                    ],
                    "changes": changes,
                    "carried_forward": sorted(
                        f for f in carried if f not in published
                    ),
                }
            )
        return {
            "surface_version": SURFACE_VERSION,
            "canonical_event_id": event["canonical_event_id"],
            "revisions": revisions_out,
        }

    def conflicts(self, canonical_event_id: str) -> dict | None:
        event = self._find(canonical_event_id)
        if event is None:
            return None
        current = self._current_state(event)
        return {
            "surface_version": SURFACE_VERSION,
            "canonical_event_id": event["canonical_event_id"],
            "conflicts": event["conflicts"],
            "conflicting_current_fields": sorted(
                field
                for field, state in current.items()
                if state["status"] == "CONFLICTING"
            ),
        }

    def evidence(self, assertion_id: str) -> dict | None:
        for event in self.canon["events"]:
            for fact in event["facts"]:
                if fact["assertion_id"] != assertion_id:
                    continue
                generations = self._generations(event)
                current = self._current_state(event)
                state = current.get(fact["field_path"], {})
                doc = next(
                    (
                        d
                        for d in event["source_documents"]
                        if d["document_id"] == fact["source_document_id"]
                    ),
                    None,
                )
                if doc is None:
                    # artefacto de referencia (INSTRUMENT_BINDING,
                    # ESMA_FIRDS, PORTFOLIO-PRODUCT-*): no es un source
                    # document del corpus pero si un origen verificable
                    doc = {
                        "source_id": fact["source_id"],
                        "official_document_id": fact["source_document_id"],
                        "role": "REFERENCE_ARTIFACT",
                    }
                return {
                    "surface_version": SURFACE_VERSION,
                    "assertion_id": assertion_id,
                    "canonical_event_id": event["canonical_event_id"],
                    "field_path": fact["field_path"],
                    "value": fact["value"],
                    "status": state.get("status"),
                    "is_current_value": any(
                        v["assertion_id"] == assertion_id
                        for v in state.get("values", [])
                    ),
                    "revision_id": fact["revision_id"],
                    "generation": generations.get(fact["revision_id"]),
                    "evidence_locator": fact["evidence_locator"],
                    "raw_pointer": fact["raw_pointer"],
                    "asserted_as_of": fact["asserted_as_of"],
                    "fact_origin": fact["fact_origin"],
                    "evidence_mode": fact["evidence_mode"],
                    "source_document": doc,
                    "source_id": fact["source_id"],
                }
        return None

    def export_event(self, canonical_event_id: str) -> dict | None:
        """Fidelidad canonica: el subarbol del evento tal cual."""
        return self._find(canonical_event_id)

    # -------------------------------------------------------------- brief

    def delta(self, previous: "Surface") -> list[dict]:
        """NEW_SINCE_PREVIOUS: diferencias operacionales entre dos
        snapshots canonicos (P1.1).

        Compara identidad estructural + payload de la afirmacion, no
        blobs: un cambio de serializacion o de provenance
        (evidence_locator / raw_pointer / assertion_id) que no altere
        la afirmacion NO genera item; una variacion factual si.

        Categorias explicitas:
          NEW_EVENT / REMOVED_EVENT /
          NEW_ASSERTION / CHANGED_ASSERTION / REMOVED_ASSERTION /
          NEW_CONFLICT / RESOLVED_CONFLICT /
          NEW_UNSUPPORTED / SUPPORTED_NOW

        Desapariciones: el canon es append-mostly, pero nada garantiza
        que un evento o una afirmacion no pueda desaparecer entre
        snapshots (correccion, recorte de universo, reconstruccion).
        Las desapariciones se hacen explicitas — REMOVED_EVENT /
        REMOVED_ASSERTION — nunca silenciosas. Un REMOVED_EVENT cubre
        sus aserciones/conflictos/unsupported (sin cascada); un
        conflicto que desaparece con el evento presente es
        RESOLVED_CONFLICT, y un unsupported que desaparece con el
        evento presente es SUPPORTED_NOW.
        """
        items = []

        prev_events = {e["canonical_event_id"] for e in previous.canon["events"]}
        cur_events = {e["canonical_event_id"] for e in self.canon["events"]}
        new_event_ids = set()
        removed_event_ids = set()
        for event in self.canon["events"]:
            if event["canonical_event_id"] not in prev_events:
                new_event_ids.add(event["canonical_event_id"])
                items.append(
                    {
                        "kind": "NEW_EVENT",
                        "canonical_event_id": event["canonical_event_id"],
                        "event_type": event["event_type"],
                        "issuer_name": event["issuer"].get("issuer_name"),
                    }
                )
        for event in previous.canon["events"]:
            if event["canonical_event_id"] not in cur_events:
                removed_event_ids.add(event["canonical_event_id"])
                items.append(
                    {
                        "kind": "REMOVED_EVENT",
                        "canonical_event_id": event["canonical_event_id"],
                        "event_type": event["event_type"],
                        "issuer_name": event["issuer"].get("issuer_name"),
                    }
                )

        def claim_index(surface: "Surface") -> dict:
            index = {}
            for event in surface.canon["events"]:
                for fact in event["facts"]:
                    key = (
                        event["canonical_event_id"],
                        fact["source_document_id"],
                        fact["field_path"],
                    )
                    index[key] = fact
            return index

        current_claims = claim_index(self)
        previous_claims = claim_index(previous)
        for key in sorted(set(current_claims) | set(previous_claims)):
            cur = current_claims.get(key)
            prev = previous_claims.get(key)
            event_id, source_document_id, field_path = key
            if event_id in new_event_ids or event_id in removed_event_ids:
                continue  # NEW_EVENT / REMOVED_EVENT cubren sus aserciones
            if prev is None:
                items.append(
                    {
                        "kind": "NEW_ASSERTION",
                        "canonical_event_id": event_id,
                        "field_path": field_path,
                        "value": cur["value"],
                        "assertion_id": cur["assertion_id"],
                        "source_document_id": source_document_id,
                        "evidence_locator": cur["evidence_locator"],
                    }
                )
            elif cur is None:
                items.append(
                    {
                        "kind": "REMOVED_ASSERTION",
                        "canonical_event_id": event_id,
                        "field_path": field_path,
                        "previous_value": prev["value"],
                        "previous_assertion_id": prev["assertion_id"],
                        "source_document_id": source_document_id,
                        "previous_evidence_locator": prev["evidence_locator"],
                    }
                )
            elif (
                _fingerprint(cur["value"]) != _fingerprint(prev["value"])
                or cur["asserted_as_of"] != prev["asserted_as_of"]
                or cur["fact_origin"] != prev["fact_origin"]
            ):
                items.append(
                    {
                        "kind": "CHANGED_ASSERTION",
                        "canonical_event_id": event_id,
                        "field_path": field_path,
                        "previous_value": prev["value"],
                        "value": cur["value"],
                        "assertion_id": cur["assertion_id"],
                        "previous_assertion_id": prev["assertion_id"],
                        "source_document_id": source_document_id,
                        "evidence_locator": cur["evidence_locator"],
                        "previous_evidence_locator": prev["evidence_locator"],
                    }
                )

        def conflict_index(surface: "Surface") -> dict:
            index = {}
            for event in surface.canon["events"]:
                for conflict in event["conflicts"]:
                    index[
                        (
                            event["canonical_event_id"],
                            conflict["field_path"],
                            conflict["asserted_as_of"],
                        )
                    ] = conflict
            return index

        current_conflicts = conflict_index(self)
        previous_conflicts = conflict_index(previous)
        for key in sorted(set(current_conflicts) - set(previous_conflicts)):
            if key[0] in new_event_ids:
                continue
            c = current_conflicts[key]
            items.append(
                {
                    "kind": "NEW_CONFLICT",
                    "canonical_event_id": key[0],
                    "field_path": key[1],
                    "values": c["values"],
                    "assertion_ids": c["assertion_ids"],
                }
            )
        for key in sorted(set(previous_conflicts) - set(current_conflicts)):
            if key[0] in removed_event_ids:
                continue  # el REMOVED_EVENT cubre sus conflictos
            c = previous_conflicts[key]
            items.append(
                {
                    "kind": "RESOLVED_CONFLICT",
                    "canonical_event_id": key[0],
                    "field_path": key[1],
                    "values": c["values"],
                    "assertion_ids": c["assertion_ids"],
                }
            )

        def unsupported_index(surface: "Surface") -> set:
            out = set()
            for event in surface.canon["events"]:
                for item in surface._unsupported_for_event(event):
                    out.add(
                        (
                            event["canonical_event_id"],
                            item["field_path"],
                            item["capability"],
                        )
                    )
            return out

        current_unsup = unsupported_index(self)
        previous_unsup = unsupported_index(previous)
        for key in sorted(current_unsup - previous_unsup):
            if key[0] in new_event_ids:
                continue
            items.append(
                {
                    "kind": "NEW_UNSUPPORTED",
                    "canonical_event_id": key[0],
                    "field_path": key[1],
                    "capability": key[2],
                }
            )
        for key in sorted(previous_unsup - current_unsup):
            if key[0] in removed_event_ids:
                continue  # el REMOVED_EVENT cubre sus unsupported
            items.append(
                {
                    "kind": "SUPPORTED_NOW",
                    "canonical_event_id": key[0],
                    "field_path": key[1],
                    "capability": key[2],
                }
            )

        kind_order = [
            "NEW_EVENT",
            "REMOVED_EVENT",
            "NEW_ASSERTION",
            "CHANGED_ASSERTION",
            "REMOVED_ASSERTION",
            "NEW_CONFLICT",
            "RESOLVED_CONFLICT",
            "NEW_UNSUPPORTED",
            "SUPPORTED_NOW",
        ]
        items.sort(
            key=lambda i: (
                kind_order.index(i["kind"]),
                i["canonical_event_id"],
                i.get("field_path") or "",
                i.get("source_document_id") or "",
                i.get("assertion_id") or "",
            )
        )
        return items

    def brief(
        self,
        as_of: str,
        window_days: int = 7,
        previous: "Surface | None" = None,
    ) -> dict:
        """Morning brief operacional (P1).

        Reglas explicitas y deterministas sobre el canon:

        - ACTION_REQUIRED: todo field date.* del estado vigente
          (CURRENT) con as_of <= fecha <= as_of + window_days.
        - REVISED: eventos con revisiones generation>0; se muestra el
          diff de la ultima revision (CHANGED/ADDED) y los fields
          carried_forward.
        - CONFLICTS: eventos con conflicts[] del canon; cada conflicto
          conserva todos sus values y fuentes (sin ganador).
        - UNSUPPORTED: capacidades QUARANTINED_UNSUPPORTED aplicables
          segun la policy pinneada; nunca se rellenan.
        - NEW_SINCE_PREVIOUS (si previous != None): delta entre
          snapshots canonicos via Surface.delta(); pregunta distinta de
          RECENT_CHANGES (revisiones dentro de un mismo canon).

        Nada se modifica ni se infiere: todo item enlaza a sus
        assertion_ids / source_documents / evidence_locators.
        """
        from datetime import date, timedelta

        start = date.fromisoformat(as_of)
        horizon = start + timedelta(days=window_days)

        action_required = []
        revised = []
        conflict_items = []
        unsupported_items = []

        for event in self.canon["events"]:
            eid = event["canonical_event_id"]
            issuer = event["issuer"].get("issuer_name")
            current = self._current_state(event)

            for field_path in sorted(current):
                if not field_path.startswith("date."):
                    continue
                field_state = current[field_path]
                if field_state["status"] != "CURRENT":
                    continue
                for entry in field_state["values"]:
                    value = entry["value"]
                    if not isinstance(value, str):
                        continue
                    try:
                        day = date.fromisoformat(value)
                    except ValueError:
                        continue
                    if start <= day <= horizon:
                        action_required.append(
                            {
                                "canonical_event_id": eid,
                                "issuer_name": issuer,
                                "event_type": event["event_type"],
                                "field_path": field_path,
                                "date": value,
                                "days_until": (day - start).days,
                                "assertion_id": entry["assertion_id"],
                                "source_document_id": entry[
                                    "source_document_id"
                                ],
                                "evidence_locator": entry["evidence_locator"],
                            }
                        )

            timeline = self.timeline(eid)
            if len(timeline["revisions"]) > 1:
                last = timeline["revisions"][-1]
                revised.append(
                    {
                        "canonical_event_id": eid,
                        "issuer_name": issuer,
                        "event_type": event["event_type"],
                        "latest_generation": last["generation"],
                        "source_documents": last["source_documents"],
                        "changes": {
                            field: change
                            for field, change in sorted(last["changes"].items())
                            if change["kind"] in ("ADDED", "CHANGED")
                        },
                        "carried_forward": last["carried_forward"],
                    }
                )

            for conflict in event["conflicts"]:
                conflict_items.append(
                    {
                        "canonical_event_id": eid,
                        "issuer_name": issuer,
                        "event_type": event["event_type"],
                        "field_path": conflict["field_path"],
                        "values": conflict["values"],
                        "assertion_ids": conflict["assertion_ids"],
                        "asserted_as_of": conflict["asserted_as_of"],
                    }
                )

            for item in self._unsupported_for_event(event):
                unsupported_items.append(
                    {
                        "canonical_event_id": eid,
                        "issuer_name": issuer,
                        "event_type": event["event_type"],
                        **item,
                    }
                )

        action_required.sort(
            key=lambda i: (i["date"], i["canonical_event_id"], i["field_path"])
        )
        revised.sort(key=lambda i: i["canonical_event_id"])
        conflict_items.sort(
            key=lambda i: (i["canonical_event_id"], i["field_path"])
        )
        unsupported_items.sort(
            key=lambda i: (i["canonical_event_id"], i["field_path"])
        )

        delta_items = self.delta(previous) if previous is not None else None
        summary = {
            "events": len(self.canon["events"]),
            "action_required": len(action_required),
            "revised_events": len(revised),
            "conflicting_events": len(
                {i["canonical_event_id"] for i in conflict_items}
            ),
            "unsupported_items": len(unsupported_items),
        }
        if delta_items is not None:
            summary["new_since_previous"] = len(delta_items)
        out = {
            "surface_version": SURFACE_VERSION,
            "brief_version": "CA_ES_MORNING_BRIEF_V1",
            "as_of": as_of,
            "window_days": window_days,
            "summary": summary,
            "action_required": action_required,
            "recent_changes": revised,
            "conflicts": conflict_items,
            "unsupported": unsupported_items,
        }
        if delta_items is not None:
            out["previous_canon_logical_sha256"] = previous.canon.get(
                "logical_sha256"
            )
            out["new_since_previous"] = delta_items
        return out

    def brief_v2(
        self,
        as_of: str,
        action_queue: dict,
        previous: "Surface | None" = None,
    ) -> dict:
        """Morning brief V2 (P5.1): action_required := action queue.

        V1 queda intacto (brief()). Aqui `action_required` son items
        de CA_ES_ACTION_QUEUE_V1 — deadlines SOURCE/DERIVED ya
        ajustados, no "todo date.* proximo". INDETERMINATE viaja en
        `indeterminate_deadlines`. recent_changes/conflicts/
        unsupported/new_since_previous se reutilizan de V1 sin
        cambios. Cada item se enriquece con issuer_name/event_type
        para el desk; la cola original no se muta.

        Binding fail-closed (P5.1.1): la cola debe haberse calculado
        para este as_of y sobre este canon; si no, ValueError con
        QUEUE_AS_OF_MISMATCH / QUEUE_CANON_MISMATCH — nunca se
        muestran days_until ni action_status de otro snapshot.
        """
        if action_queue.get("as_of") != as_of:
            raise ValueError("QUEUE_AS_OF_MISMATCH")
        if action_queue.get("source_canon_logical_sha256") != \
                self.canon.get("logical_sha256"):
            raise ValueError("QUEUE_CANON_MISMATCH")
        brief = self.brief(
            as_of,
            window_days=action_queue["window_days"],
            previous=previous,
        )
        info = {
            e["canonical_event_id"]: (
                e["issuer"].get("issuer_name"),
                e["event_type"],
            )
            for e in self.canon["events"]
        }
        items = []
        for item in action_queue.get("items", []):
            issuer, etype = info.get(
                item["canonical_event_id"], (None, None))
            items.append({**item, "issuer_name": issuer,
                          "event_type": etype})
        indeterminate = action_queue.get("indeterminate", [])
        brief["brief_version"] = "CA_ES_MORNING_BRIEF_V2"
        brief["action_required"] = items
        brief["indeterminate_deadlines"] = indeterminate
        brief["summary"]["action_required"] = len(items)
        brief["summary"]["indeterminate_deadlines"] = len(indeterminate)
        return brief


def render_brief(brief: dict) -> str:
    """Render de terminal deterministico del morning brief."""
    lines = [
        f"CA-ES BRIEF  as_of={brief['as_of']}  window={brief['window_days']}d",
        "",
        "SUMMARY",
        "  events={events}  action_required={action_required}  "
        "revised={revised_events}  conflicts={conflicting_events}  "
        "unsupported={unsupported_items}".format(**brief["summary"]),
        "",
    ]
    lines.append("ACTION REQUIRED")
    if not brief["action_required"]:
        lines.append("  (none)")
    for item in brief["action_required"]:
        if "action_status" in item:
            # V2: item de CA_ES_ACTION_QUEUE_V1 (deadline ajustado)
            lines.append(
                "  {status} {date} ({days}d) {issuer} {etype} "
                "{dtype} [{eid}]".format(
                    status=item["action_status"],
                    date=item["deadline_date"],
                    days=item["days_until"],
                    issuer=item["issuer_name"] or "-",
                    etype=item["event_type"],
                    dtype=item["deadline_type"],
                    eid=item["canonical_event_id"][:8],
                )
            )
        else:
            lines.append(
                "  {date} ({days}d) {issuer} {etype} {field} "
                "[{eid}]".format(
                    date=item["date"],
                    days=item["days_until"],
                    issuer=item["issuer_name"] or "-",
                    etype=item["event_type"],
                    field=item["field_path"],
                    eid=item["canonical_event_id"][:8],
                )
            )
            lines.append(f"      evidence: {item['evidence_locator']}")
    indeterminate = brief.get("indeterminate_deadlines")
    if indeterminate is not None:
        lines.append("")
        lines.append("INDETERMINATE DEADLINES")
        if not indeterminate:
            lines.append("  (none)")
        for item in indeterminate:
            lines.append(
                "  {dtype} {reasons} [{eid}]".format(
                    dtype=item["deadline_type"],
                    reasons=",".join(item.get("reasons") or []),
                    eid=item["canonical_event_id"][:8],
                )
            )
    lines.append("")
    lines.append("RECENT CHANGES")
    if not brief["recent_changes"]:
        lines.append("  (none)")
    for item in brief["recent_changes"]:
        lines.append(
            "  {issuer} {etype} gen{gen} [{eid}]".format(
                issuer=item["issuer_name"] or "-",
                etype=item["event_type"],
                gen=item["latest_generation"],
                eid=item["canonical_event_id"][:8],
            )
        )
        for field, change in item["changes"].items():
            prev = ", ".join(
                str(v["normalized"]) if isinstance(v, dict) else str(v)
                for v in change["previous_values"]
            ) or "-"
            cur = ", ".join(
                str(v["normalized"]) if isinstance(v, dict) else str(v)
                for v in change["values"]
            )
            lines.append(f"    {change['kind']:11s} {field}: {prev} -> {cur}")
        for field in item["carried_forward"]:
            lines.append(f"    RETAINED    {field}")
    lines.append("")
    lines.append("CONFLICTS")
    if not brief["conflicts"]:
        lines.append("  (none)")
    for item in brief["conflicts"]:
        lines.append(
            "  {issuer} {field} [{eid}]".format(
                issuer=item["issuer_name"] or "-",
                field=item["field_path"],
                eid=item["canonical_event_id"][:8],
            )
        )
        lines.append(f"      values: {', '.join(item['values'])}")
    lines.append("")
    lines.append("UNSUPPORTED")
    if not brief["unsupported"]:
        lines.append("  (none)")
    for item in brief["unsupported"]:
        lines.append(
            "  {issuer} {field} -> UNSUPPORTED ({cap}) [{eid}]".format(
                issuer=item["issuer_name"] or "-",
                field=item["field_path"],
                cap=item["capability"],
                eid=item["canonical_event_id"][:8],
            )
        )
    if "new_since_previous" in brief:
        lines.append("")
        lines.append("NEW SINCE PREVIOUS")
        if not brief["new_since_previous"]:
            lines.append("  (none)")
        for item in brief["new_since_previous"]:
            field = item.get("field_path") or ""
            lines.append(
                "  {kind} {eid} {field}".format(
                    kind=item["kind"],
                    eid=item["canonical_event_id"][:8],
                    field=field,
                )
            )
            if item["kind"] == "CHANGED_ASSERTION":
                prev = item["previous_value"]
                cur = item["value"]
                if isinstance(prev, dict):
                    prev = prev.get("normalized", prev)
                if isinstance(cur, dict):
                    cur = cur.get("normalized", cur)
                lines.append(f"      {prev} -> {cur}")
            if item["kind"] == "REMOVED_ASSERTION":
                prev = item["previous_value"]
                if isinstance(prev, dict):
                    prev = prev.get("normalized", prev)
                lines.append(f"      removed: {prev}")
            if item.get("evidence_locator"):
                lines.append(f"      evidence: {item['evidence_locator']}")
            if item.get("previous_evidence_locator"):
                lines.append(
                    f"      previous evidence: {item['previous_evidence_locator']}"
                )
            if item["kind"] in ("NEW_CONFLICT", "RESOLVED_CONFLICT"):
                lines.append(f"      values: {', '.join(item['values'])}")
    return "\n".join(lines) + "\n"


def load_surface(canon_path: Path, policy_path: Path) -> Surface:
    canon = load_strict_json_object(canon_path)
    policy = load_strict_json_object(policy_path)
    return Surface(canon, policy)
