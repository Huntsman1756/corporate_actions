"""P13.4 — position snapshot assembly + projection.

CA_ES_POSITION_OBSERVATION_V1 (uno por mensaje/pagina)
    -> CA_ES_POSITION_SNAPSHOT_V1 (statement completo)
    -> CA_ES_POSITIONS_V1 (solo si COMPLETE)

Reglas (docs/p13/p131-position-observation.md):

- una pagina de un statement multi-pagina != snapshot completo;
- completeness se prueba por evidencia: 28E ONLY/LAST o paginas
  1..N contiguas terminadas en LAST (MT535); Pgntn.LastPgInd +
  UpdTp COMP (semt.002);
- DELT (delta update) nunca es snapshot completo;
- dos statements COMPLETE para el mismo (account, as_of) con
  contenido distinto -> CONFLICTING_POSITION_SNAPSHOTS, fail-closed;
- la proyeccion a positions requiere account_map explicito;
  cuentas sin mapping no se emiten (nunca se adivina account_id).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .semantic_hash import semantic_sha256

SNAPSHOT_SCHEMA = "CA_ES_POSITION_SNAPSHOT_V1"
POSITIONS_SCHEMA = "CA_ES_POSITIONS_V1"

COMPLETE = "COMPLETE"
PARTIAL = "PARTIAL"
INDETERMINATE = "INDETERMINATE"
CONFLICTING = "CONFLICTING_POSITION_SNAPSHOTS"


def _dec(value):
    try:
        d = Decimal(str(value))
        return d if d.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _statement_semantics(obs):
    """Contenido de negocio de una observacion (para comparar
    snapshots): account, as_of, multiset de (isin, qty, type)."""
    rows = sorted(
        (p.get("isin"), p.get("quantity"), p.get("quantity_type"))
        for p in obs.get("positions") or [])
    return {
        "account_id_raw": obs.get("account_id_raw"),
        "statement_as_of": obs.get("statement_as_of"),
        "positions": rows,
    }


def _group_key(obs):
    return (obs.get("account_id_raw") or "",
            obs.get("statement_reference") or "")


def completeness(pages: list[dict]) -> tuple[str, list[str]]:
    """Observaciones de un mismo statement -> (status, reasons)."""
    reasons = []
    if not pages:
        return INDETERMINATE, ["NO_PAGES"]

    paginated = [p for p in pages if p.get("pagination")]
    if len(paginated) != len(pages):
        reasons.append("MISSING_PAGINATION")

    upd = {p["pagination"].get("update_type") for p in paginated}
    upd.discard(None)
    if "DELT" in upd:
        reasons.append("DELTA_UPDATE_TYPE")

    nums = {p["pagination"].get("page") for p in paginated}
    last_flags = {p["pagination"].get("last_page") for p in paginated}
    conts = {p["pagination"].get("continuation") for p in paginated}
    conts.discard(None)
    nums.discard(None)

    if reasons:
        return (PARTIAL if "DELTA_UPDATE_TYPE" in reasons
                else INDETERMINATE), reasons

    if len(pages) == 1:
        if "ONLY" in conts or True in last_flags:
            return COMPLETE, []
        if "MORE" in conts or False in last_flags:
            return PARTIAL, ["SINGLE_PAGE_OF_MULTIPAGE_STATEMENT"]
        return INDETERMINATE, ["SINGLE_PAGE_NO_TERMINAL_MARKER"]

    if None in nums or not last_flags or None in last_flags:
        return INDETERMINATE, ["INCOMPLETE_PAGINATION_INFO"]

    expected = set(range(1, len(pages) + 1))
    if nums != expected:
        missing = sorted(expected - nums)
        return PARTIAL, [f"MISSING_PAGES:{missing}"]

    if True not in last_flags:
        if "LAST" in conts:
            last_flags = {True}
        else:
            return PARTIAL, ["NO_LAST_PAGE_OBSERVED"]
    if len(last_flags - {True}) > 0:
        pass
    return COMPLETE, []


def build_snapshots(observations: list[dict],
                    now: str | None = None) -> dict:
    """Observaciones -> CA_ES_POSITION_SNAPSHOT_INDEX_V1.

    Agrupa por (account_id_raw, statement_reference), decide
    completitud, asigna snapshot_id determinista y detecta
    snapshots COMPLETE conflictivos. Read-only.
    """
    groups: dict[tuple, list[dict]] = {}
    for obs in observations:
        if obs.get("schema") != "CA_ES_POSITION_OBSERVATION_V1":
            continue
        groups.setdefault(_group_key(obs), []).append(obs)

    snapshots = []
    conflicts = []
    for (account_raw, ref), pages in sorted(groups.items()):
        # dedup por numero de pagina: misma pagina entregada dos veces
        # (retransmision, otro transporte) con el mismo contenido se
        # colapsa; con contenido distinto -> conflicto de pagina.
        page_map: dict[int, list[dict]] = {}
        for p in pages:
            num = (p.get("pagination") or {}).get("page") or 0
            page_map.setdefault(num, []).append(p)
        deduped = []
        page_conflict = False
        for num, group in sorted(page_map.items()):
            distinct = {semantic_sha256(_statement_semantics(p))
                        for p in group}
            if len(distinct) > 1:
                page_conflict = True
            deduped.append(group[0])
        pages = deduped

        status, reasons = completeness(pages)
        if page_conflict:
            status = INDETERMINATE
            reasons = list(reasons) + ["CONFLICTING_PAGE_CONTENT"]
        merged_positions = []
        for p in sorted(pages, key=lambda o: (
                (o.get("pagination") or {}).get("page") or 0)):
            merged_positions.extend(p.get("positions") or [])
        semantics = {
            "account_id_raw": account_raw,
            "statement_reference": ref,
            "statement_as_of": _single(
                p.get("statement_as_of") for p in pages),
            "positions": sorted(
                (p.get("isin"), p.get("quantity"),
                 p.get("quantity_type"))
                for p in merged_positions),
        }
        snap_id = "PSNAP-" + semantic_sha256(semantics)[:16]
        snapshots.append({
            "snapshot_id": snap_id,
            "account_id_raw": account_raw,
            "statement_reference": ref,
            "statement_as_of": semantics["statement_as_of"],
            "completeness": status,
            "reasons": reasons,
            "pages": sorted(
                p.get("input_sha256")
                for group in page_map.values() for p in group
                if p.get("input_sha256")),
            "page_numbers": sorted(
                (p.get("pagination") or {}).get("page") or 0
                for p in pages),
            "positions": merged_positions,
            "source_refs": [
                {"message_identifier": p.get(
                    "source_message_identifier"),
                 "input_sha256": p.get("input_sha256")}
                for group in page_map.values() for p in group],
            "semantic_sha256": semantic_sha256(semantics),
        })

    # conflicto: mismo (account, as_of), dos snapshots COMPLETE cuyas
    # POSICIONES difieren -> ninguno gana. Statement references
    # distintas con el mismo contenido NO son conflicto (restatement
    # que concuerda): se comparan las posiciones, no el metadata.
    def _positions_hash(s):
        return semantic_sha256({
            "positions": sorted(
                (p.get("isin"), p.get("quantity"),
                 p.get("quantity_type"))
                for p in s["positions"])})

    by_slot: dict[tuple, list[dict]] = {}
    for s in snapshots:
        if s["completeness"] != COMPLETE:
            continue
        by_slot.setdefault(
            (s["account_id_raw"], s["statement_as_of"]), []).append(s)
    for slot, snaps in by_slot.items():
        distinct = {_positions_hash(s) for s in snaps}
        if len(distinct) > 1:
            for s in snaps:
                s["completeness"] = CONFLICTING
                s["reasons"] = list(s["reasons"]) + [
                    "COMPLETE_SNAPSHOTS_DISAGREE"]
            conflicts.append({
                "account_id_raw": slot[0],
                "statement_as_of": slot[1],
                "snapshot_ids": sorted(
                    s["snapshot_id"] for s in snaps),
            })
        elif len(snaps) > 1:
            for s in snaps:
                s["reasons"] = list(s["reasons"]) + [
                    "DUPLICATE_STATEMENT_AGREEING"]

    return {
        "schema": "CA_ES_POSITION_SNAPSHOT_INDEX_V1",
        "generated_at": now,
        "snapshots": snapshots,
        "conflicting_slots": conflicts,
    }


def _single(values):
    unique = {v for v in values if v is not None}
    return next(iter(unique)) if len(unique) == 1 else None


def positions_doc(snapshot: dict, account_map: dict[str, str],
                  now: str | None = None) -> dict:
    """snapshot COMPLETE -> CA_ES_POSITIONS_V1.

    account_map: {account_id_raw -> account_id} explicito (profile).
    Posiciones sin ISIN o sin cantidad no se emiten (reasons en el
    snapshot). Cuentas sin mapping -> skipped_accounts, nunca
    adivinadas.
    """
    result = {
        "schema": POSITIONS_SCHEMA,
        "as_of": None,
        "positions": [],
        "_snapshot": None,
        "_skipped_accounts": [],
        "_dropped_positions": [],
    }
    if snapshot.get("completeness") != COMPLETE:
        result["_snapshot"] = {
            "snapshot_id": snapshot.get("snapshot_id"),
            "completeness": snapshot.get("completeness"),
            "reasons": snapshot.get("reasons"),
        }
        return result

    raw_account = snapshot.get("account_id_raw")
    account_id = (account_map or {}).get(raw_account)
    if account_id is None:
        result["_skipped_accounts"] = [raw_account]
        result["_snapshot"] = {
            "snapshot_id": snapshot.get("snapshot_id"),
            "completeness": "UNMAPPED_ACCOUNT",
        }
        return result

    positions = []
    dropped = []
    for p in snapshot.get("positions") or []:
        qty = _dec(p.get("quantity"))
        if not p.get("isin") or qty is None:
            dropped.append({
                "isin": p.get("isin"),
                "quantity": p.get("quantity"),
                "reason": "MISSING_ISIN" if not p.get("isin")
                else "MISSING_QUANTITY",
            })
            continue
        positions.append({
            "account_id": account_id,
            "isin": p["isin"],
            "quantity": format(qty, "f"),
        })
    positions.sort(key=lambda p: (p["account_id"], p["isin"]))

    result["as_of"] = snapshot.get("statement_as_of")
    result["positions"] = positions
    result["_dropped_positions"] = dropped
    result["_snapshot"] = {
        "snapshot_id": snapshot.get("snapshot_id"),
        "completeness": COMPLETE,
        "source_refs": snapshot.get("source_refs"),
        "pages": snapshot.get("pages"),
    }
    result["generated_at"] = now
    return result
