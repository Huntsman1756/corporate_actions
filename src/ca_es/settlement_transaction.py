"""P17.2 — observaciones -> ledger de transacciones de settlement.

Identidad SOLO por referencias explicitas de la cadena:
acct_svcr_tx_id > acct_ownr_tx_id > mkt_infrstrctr_tx_id >
prcr_tx_id > common_id > linked_settlement_tx_id > trade_id(s) >
unique_tx_idr (UTI). NUNCA isin+qty+fecha.

Outcomes por observacion:
- NEW_TRANSACTION: refs suficientes, sin candidato -> tx nueva.
- BOUND: exactamente una tx candidata -> merge.
- EXACT_DUPLICATE: mismo input_sha256 ya observado -> ignora.
- SEMANTIC_DUPLICATE: mismo mensaje+refs, bytes distintos ->
  observacion preservada, tx no duplicada.
- AMBIGUOUS: >1 candidata -> no merge, auditada.
- INSUFFICIENT_IDENTITY: sin ref usable -> observacion huerfana.

Estados del ciclo:
INSTRUCTED -> PENDING -> MATCHED -> PARTIALLY_SETTLED ->
SETTLED | CANCELLED | FAILED.

Semantica de confirmacion: CUMULATIVE (prevsly presente) ->
settled_total = settled + prevsly; THIS_MESSAGE -> suma de
confirmaciones distintas por ref de mensaje. Si la semantica no
permite consolidar -> INDETERMINATE en cantidades.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation

TRANSACTION_SCHEMA = "CA_ES_SETTLEMENT_TRANSACTION_V1"

INSTRUCTED = "INSTRUCTED"
PENDING = "PENDING"
MATCHED = "MATCHED"
PARTIALLY_SETTLED = "PARTIALLY_SETTLED"
SETTLED = "SETTLED"
CANCELLED = "CANCELLED"
FAILED = "FAILED"

NEW_TRANSACTION = "NEW_TRANSACTION"
BOUND = "BOUND"
EXACT_DUPLICATE = "EXACT_DUPLICATE"
SEMANTIC_DUPLICATE = "SEMANTIC_DUPLICATE"
AMBIGUOUS = "AMBIGUOUS"
INSUFFICIENT_IDENTITY = "INSUFFICIENT_IDENTITY"

REF_PRIORITY = (
    "acct_svcr_tx_id", "acct_ownr_tx_id",
    "mkt_infrstrctr_tx_id", "prcr_tx_id", "common_id",
    "linked_settlement_tx_id", "unique_tx_idr", "pool_id",
)


def _dec(raw):
    if raw is None:
        return None
    try:
        v = Decimal(str(raw).replace(",", "."))
    except InvalidOperation:
        return None
    return v if v.is_finite() else None


def _fmt(v):
    return format(v, "f") if v is not None else None


def _hash16(*parts):
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p or "-").encode("utf-8"))
        h.update(b"|")
    return h.hexdigest()[:16]


def _obs_hash(obs: dict) -> str:
    """Hash semantico del contenido normalizado de una
    observacion (excluye input_sha256/provenance). Dos mensajes
    byte-distintos con el mismo contenido son el mismo hecho;
    dos confirmaciones con cantidades distintas NO lo son."""
    payload = {k: v for k, v in (obs or {}).items()
               if k not in ("input_sha256", "provenance")}
    return _hash16(json.dumps(payload, sort_keys=True,
                              default=str))


def _ref_set(refs: dict) -> set[str]:
    out = set()
    for k, v in (refs or {}).items():
        if k == "trade_id":
            out.update(v for v in (v or []) if v)
        elif v:
            out.add(v)
    return out


def _primary(refs: dict) -> tuple[str | None, str | None]:
    for k in REF_PRIORITY:
        v = refs.get(k)
        if v:
            return k, v
    trades = refs.get("trade_id") or []
    if trades:
        return "trade_id", sorted(trades)[0]
    return None, None


def _tx_id(refs, account):
    kind, value = _primary(refs)
    if value is None:
        return None
    return "ST-" + _hash16(kind, value, account)


def _new_tx(obs, refs, now):
    pk, pv = _primary(refs)
    return {
        "transaction_id": _tx_id(refs, obs.get("account_id")),
        "primary_ref_kind": pk,
        "primary_ref": pv,
        "account_id": obs.get("account_id"),
        "isin": obs.get("isin"),
        "direction": obs.get("direction"),
        "payment_type": obs.get("payment_type"),
        "instructed_quantity": obs.get("instructed_quantity"),
        "settled_quantity": "0",
        "quantity_semantics": None,
        "settlement_amount": obs.get("settlement_amount"),
        "settlement_currency": obs.get("settlement_currency"),
        "trade_date": obs.get("trade_date"),
        "intended_settlement_date": obs.get(
            "intended_settlement_date"),
        "actual_settlement_date": obs.get("actual_settlement_date"),
        "status": INSTRUCTED,
        "matching_status": None,
        "processing_status": None,
        "settlement_status_observed": None,
        "has_instruction": obs.get("kind") == "INSTRUCTION",
        "has_status_advice": obs.get("kind") == "STATUS",
        "has_confirmation": obs.get("kind") == "CONFIRMATION",
        "references": dict(refs),
        "conflicts": [],
        "history": [],
        "observations": [],
        "observation_meta": [],
        "partial": False,
    }


def _merge_refs(tx: dict, refs: dict) -> None:
    txr = tx.setdefault("references", {})
    for k, v in (refs or {}).items():
        if k == "trade_id":
            lst = txr.setdefault(k, [])
            for t in v or []:
                if t not in lst:
                    lst.append(t)
        elif v and not txr.get(k):
            txr[k] = v


def _conflict(tx, obs, field, prov_key):
    """Detecta conflicto factual entre obs nueva y tx."""
    old = tx.get(prov_key)
    new = obs.get(field)
    if old is not None and new is not None and \
            str(old) != str(new):
        tx.setdefault("conflicts", []).append({
            "field": prov_key, "prior": old, "observed": new,
            "source_ref": obs.get("input_sha256")})
        return True
    if old is None and new is not None:
        tx[prov_key] = new
    return False


def _apply_confirmation(tx, obs):
    """Consolida settled_total con semantica del mensaje."""
    settled = _dec(obs.get("settled_quantity"))
    prevsly = _dec(obs.get("previously_settled_quantity"))
    remaining = _dec(obs.get("remaining_quantity"))
    actual = obs.get("actual_settlement_date")
    if actual:
        tx["actual_settlement_date"] = actual
    if settled is None:
        return
    if prevsly is not None:
        # semantica cumulative explicita del estandar
        total = settled + prevsly
        prior = _dec(tx.get("settled_quantity")) or Decimal(0)
        tx["settled_quantity"] = _fmt(max(total, prior))
        tx["quantity_semantics"] = "CUMULATIVE"
    else:
        prior = _dec(tx.get("settled_quantity")) or Decimal(0)
        tx["settled_quantity"] = _fmt(prior + settled)
        tx["quantity_semantics"] = (tx.get("quantity_semantics")
                                    or "SUM_OF_PARTS")
    if remaining is not None:
        tx["remaining_quantity"] = _fmt(remaining)


def _derive_status(tx):
    """Estado del ciclo desde los hechos acumulados (campos
    persistentes — sobrevive a merges de ledger previo)."""
    if tx.get("processing_status") == "CANCELLED" or \
            tx.get("instruction_cancelled"):
        return CANCELLED
    if tx.get("processing_status") == "REJECTED":
        return FAILED
    instructed = _dec(tx.get("instructed_quantity"))
    settled = _dec(tx.get("settled_quantity")) or Decimal(0)
    if tx.get("has_confirmation") and instructed is not None:
        if settled >= instructed:
            return SETTLED
        if settled > 0:
            return PARTIALLY_SETTLED
    if tx.get("has_confirmation") and instructed is None \
            and settled > 0:
        return SETTLED
    if tx.get("matching_status") == "MATCHED":
        return MATCHED
    if tx.get("has_status_advice"):
        return PENDING
    return INSTRUCTED


def _apply_observation(tx, obs):
    kind = obs.get("kind")
    conflicting = False
    if kind == "INSTRUCTION":
        tx["has_instruction"] = True
        conflicting |= _conflict(
            tx, obs, "instructed_quantity", "instructed_quantity")
        conflicting |= _conflict(tx, obs, "isin", "isin")
        conflicting |= _conflict(
            tx, obs, "direction", "direction")
        for k in ("trade_date", "intended_settlement_date",
                  "settlement_amount", "settlement_currency",
                  "payment_type", "account_id"):
            _conflict(tx, obs, k, k)
        if obs.get("function") in ("CANC", "CANP"):
            tx["instruction_cancelled"] = True
    elif kind == "STATUS":
        tx["has_status_advice"] = True
        if obs.get("processing_status"):
            tx["processing_status"] = obs["processing_status"]
        if obs.get("matching_status"):
            tx["matching_status"] = obs["matching_status"]
        if obs.get("settlement_status"):
            tx["settlement_status_observed"] = obs[
                "settlement_status"]
        _apply_confirmation(tx, obs)
        if obs.get("actual_settlement_date"):
            tx["actual_settlement_date"] = obs[
                "actual_settlement_date"]
    elif kind == "CONFIRMATION":
        tx["has_confirmation"] = True
        _apply_confirmation(tx, obs)
        for k in ("isin", "direction", "account_id",
                  "trade_date", "intended_settlement_date",
                  "settlement_amount", "settlement_currency",
                  "payment_type"):
            _conflict(tx, obs, k, k)
    return conflicting


def _finalize(tx):
    tx["status"] = _derive_status(tx)
    instructed = _dec(tx.get("instructed_quantity"))
    settled = _dec(tx.get("settled_quantity")) or Decimal(0)
    tx["partial"] = bool(
        instructed is not None and 0 < settled < instructed)


def build_ledger(observation_docs: list[dict],
                 previous_doc: dict | None = None,
                 now: str | None = None) -> dict:
    """observations -> CA_ES_SETTLEMENT_TRANSACTION_V1 (ledger).

    previous_doc: ledger previo; las tx se mergean por
    transaction_id conservando historia (nunca se borra).
    """
    observations = []
    for doc in observation_docs or []:
        observations.extend(doc.get("items") or [])

    txs: dict[str, dict] = {}
    for tx in (previous_doc or {}).get("transactions") or []:
        clone = dict(tx)
        clone["references"] = dict(tx.get("references") or {})
        clone["history"] = list(tx.get("history") or [])
        clone["conflicts"] = list(tx.get("conflicts") or [])
        clone["observations"] = list(tx.get("observations") or [])
        clone["observation_meta"] = [
            dict(m) for m in tx.get("observation_meta") or []]
        txs[clone["transaction_id"]] = clone

    outcomes = []
    orphans = list(
        (previous_doc or {}).get("orphan_observations") or [])

    for i, obs in enumerate(observations):
        sha = obs.get("input_sha256")
        refs = obs.get("references") or {}
        outcome = {"index": i, "kind": obs.get("kind"),
                   "message_identifier": obs.get(
                       "message_identifier"),
                   "source_ref": sha}

        # exact duplicate por sha
        dup = any(sha in t.get("observations", []) for t in txs.values())
        if dup:
            outcome["outcome"] = EXACT_DUPLICATE
            outcomes.append(outcome)
            continue

        pk, pv = _primary(refs)
        ref_values = _ref_set(refs)
        if pv is None or not ref_values:
            outcome["outcome"] = INSUFFICIENT_IDENTITY
            orphans.append({
                "message_identifier": obs.get("message_identifier"),
                "kind": obs.get("kind"), "source_ref": sha,
                "reason": "NO_USABLE_REFERENCE"})
            outcomes.append(outcome)
            continue

        candidates = []
        for tid, tx in txs.items():
            if ref_values & _ref_set(tx.get("references") or {}):
                candidates.append(tid)

        # semantic duplicate: mismo contenido normalizado en una
        # tx con el mismo primary ref (bytes distintos). NO es
        # dup una segunda confirmacion con cantidades distintas.
        sem = _obs_hash(obs)
        sem_dup = False
        for tid, tx in txs.items():
            txr = tx.get("references") or {}
            if _primary(txr) == (pk, pv) and any(
                    o.get("sem") == sem
                    for o in tx.get("observation_meta", [])):
                sem_dup = True
                outcome["outcome"] = SEMANTIC_DUPLICATE
                outcome["transaction_id"] = tid
                tx.setdefault("observation_meta", []).append({
                    "mid": obs.get("message_identifier"),
                    "kind": obs.get("kind"),
                    "function": obs.get("function"),
                    "sem": sem,
                    "source_ref": sha})
                tx["observations"].append(sha)
                break
        if sem_dup:
            outcomes.append(outcome)
            continue

        if len(candidates) > 1:
            outcome["outcome"] = AMBIGUOUS
            outcome["candidates"] = sorted(candidates)
            orphans.append({
                "message_identifier": obs.get("message_identifier"),
                "kind": obs.get("kind"), "source_ref": sha,
                "reason": "AMBIGUOUS",
                "candidates": sorted(candidates)})
            outcomes.append(outcome)
            continue

        if not candidates:
            tx = _new_tx(obs, refs, now)
            tid = tx["transaction_id"]
            if tid is None:
                outcome["outcome"] = INSUFFICIENT_IDENTITY
                orphans.append({
                    "message_identifier": obs.get(
                        "message_identifier"),
                    "kind": obs.get("kind"), "source_ref": sha,
                    "reason": "NO_USABLE_REFERENCE"})
                outcomes.append(outcome)
                continue
            if tid in txs:
                candidates.append(tid)
            else:
                txs[tid] = tx
                _apply_observation(tx, obs)
                tx.setdefault("observation_meta", []).append({
                    "mid": obs.get("message_identifier"),
                    "kind": obs.get("kind"),
                    "function": obs.get("function"),
                    "sem": sem,
                    "source_ref": sha})
                tx["observations"].append(sha)
                tx["history"].append({
                    "type": "OBSERVED",
                    "kind": obs.get("kind"),
                    "message_identifier": obs.get(
                        "message_identifier"),
                    "source_ref": sha, "at": now})
                outcome["outcome"] = NEW_TRANSACTION
                outcome["transaction_id"] = tid
                outcomes.append(outcome)
                continue

        tid = candidates[0]
        tx = txs[tid]
        _merge_refs(tx, refs)
        _apply_observation(tx, obs)
        tx.setdefault("observation_meta", []).append({
            "mid": obs.get("message_identifier"),
            "kind": obs.get("kind"),
            "function": obs.get("function"),
            "sem": sem,
            "source_ref": sha})
        tx["observations"].append(sha)
        tx["history"].append({
            "type": "OBSERVED", "kind": obs.get("kind"),
            "message_identifier": obs.get("message_identifier"),
            "source_ref": sha, "at": now})
        outcome["outcome"] = BOUND
        outcome["transaction_id"] = tid
        outcomes.append(outcome)

    ordered = [txs[k] for k in sorted(txs)]
    for tx in ordered:
        _finalize(tx)

    summary = {}
    for o in outcomes:
        summary[o["outcome"]] = summary.get(o["outcome"], 0) + 1

    return {
        "schema": TRANSACTION_SCHEMA,
        "generated_at": now,
        "transactions": ordered,
        "orphan_observations": orphans,
        "outcomes": outcomes,
        "summary": {
            "transactions": len(ordered),
            "by_status": _by_status(ordered),
            "outcomes": summary,
            "orphans": len(orphans),
        },
    }


def _by_status(txs):
    out = {}
    for t in txs:
        out[t["status"]] = out.get(t["status"], 0) + 1
    return out


def find_transaction(ledger: dict, transaction_id: str) -> dict | None:
    for tx in ledger.get("transactions") or []:
        if tx.get("transaction_id") == transaction_id:
            return tx
    return None
