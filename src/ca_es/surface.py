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


def load_surface(canon_path: Path, policy_path: Path) -> Surface:
    canon = json.loads(canon_path.read_text(encoding="utf-8"))
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    return Surface(canon, policy)
