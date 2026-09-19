"""P15.5 — CA_ES_TAX_RECOVERY_INSTRUCTION_V1 + provider profile.

La instruccion de recovery es un artefacto INTERNO: el estandar
publico no define un mensaje "Tax Reclaim Instruction" (el set CA
es seev.031-044; TARE/BORE son referencias dentro de la
confirmacion, no un canal). Por tanto:

- channel=MANUAL siempre valido -> status MANUAL_SUBMISSION_REQUIRED
- channel=PROVIDER_PROFILE solo con CA_ES_TAX_RECOVERY_PROVIDER_V1
  valido y channel demostrado (SFTP|MQ|API via P11); sin perfil
  valido NUNCA se fabrica payload MT/MX ni se finge submission.
- payload = referencias estructuradas (claim, doc set, importe),
  payload_format=INTERNAL_V1; la serializacion a un canal
  propietario queda fuera del core.
"""

from __future__ import annotations

import hashlib
import json

from .tax_recovery_case import READY_TO_SUBMIT

INSTRUCTION_SCHEMA = "CA_ES_TAX_RECOVERY_INSTRUCTION_V1"
PROVIDER_SCHEMA = "CA_ES_TAX_RECOVERY_PROVIDER_V1"

PROVIDER_CHANNELS = {"SFTP", "MQ", "API"}

READY = "READY"
MANUAL_SUBMISSION_REQUIRED = "MANUAL_SUBMISSION_REQUIRED"
BLOCKED = "BLOCKED"


def _sha(doc) -> str:
    raw = json.dumps(doc, sort_keys=True,
                     separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def validate_provider(doc: dict | None) -> list[str]:
    """Errores estaticos del provider profile; [] = valido."""
    if doc is None:
        return ["NO_PROVIDER_PROFILE"]
    if doc.get("schema") != PROVIDER_SCHEMA:
        return [f"schema debe ser {PROVIDER_SCHEMA}"]
    errors = []
    if not doc.get("provider_id"):
        errors.append("provider_id ausente")
    if doc.get("channel") not in PROVIDER_CHANNELS:
        errors.append("channel debe ser SFTP|MQ|API")
    if not doc.get("endpoint_ref"):
        errors.append("endpoint_ref ausente (referencia al "
                      "destino configurado, nunca credenciales)")
    return errors


def build_instruction(claim: dict, doc_set: dict | None,
                      rule: dict | None,
                      provider_doc: dict | None = None,
                      now: str | None = None) -> dict:
    """Claim READY_TO_SUBMIT -> instruccion.

    Fail-closed: doc set incompleto o claim no READY_TO_SUBMIT ->
    BLOCKED con reasons; no emite instruccion enviable.
    """
    reasons = []
    if claim.get("status") != READY_TO_SUBMIT:
        reasons.append(f"CLAIM_STATUS_{claim.get('status')}")
    if doc_set is not None and doc_set.get("set_status") != \
            "COMPLETE":
        reasons.append("DOCUMENT_SET_INCOMPLETE")

    channel_pref = ((rule or {}).get("submission") or {}).get(
        "channel") or "MANUAL"
    provider_errors = []
    if channel_pref == "PROVIDER_PROFILE":
        provider_errors = validate_provider(provider_doc)
        if provider_errors:
            # perfil requerido pero no demostrado -> manual
            channel = "MANUAL"
        else:
            channel = provider_doc["channel"]
    else:
        channel = "MANUAL"

    if reasons:
        status = BLOCKED
    elif channel == "MANUAL":
        status = MANUAL_SUBMISSION_REQUIRED
        if channel_pref == "PROVIDER_PROFILE":
            reasons.extend(provider_errors)
            reasons.append("FELL_BACK_TO_MANUAL")
    else:
        status = READY

    amount = claim.get("claim_amount")
    payload = {
        "payload_format": "INTERNAL_V1",
        "claim_id": claim.get("claim_id"),
        "canonical_event_id": claim.get("canonical_event_id"),
        "account_id": claim.get("account_id"),
        "recovery_method": claim.get("recovery_method"),
        "claim_kind": claim.get("claim_kind"),
        "amount": amount,
        "entitled_rate_fraction": claim.get(
            "entitled_rate_fraction"),
        "document_set_ref": doc_set.get("claim_id") if doc_set
        else None,
        "document_references": [
            {"doc_type": i.get("doc_type"),
             "reference": i.get("reference")}
            for i in (doc_set or {}).get("items") or []
            if i.get("status") == "PRESENT"],
    }
    instruction_id = "txi-" + _sha({
        "claim_id": claim.get("claim_id"),
        "amount": amount,
        "channel": channel,
    })[:16]

    return {
        "schema": INSTRUCTION_SCHEMA,
        "generated_at": now,
        "instruction_id": instruction_id,
        "claim_id": claim.get("claim_id"),
        "canonical_event_id": claim.get("canonical_event_id"),
        "status": status,
        "reason_codes": reasons,
        "submission_channel": channel,
        "provider_id": provider_doc.get("provider_id")
        if status == READY and provider_doc else None,
        "provider_sha256": _sha(provider_doc)
        if status == READY and provider_doc else None,
        "payload": payload,
        "rule_id": (rule or {}).get("rule_id"),
    }


def build_instructions(cases_doc: dict, doc_sets_doc: dict | None,
                       ruleset_doc: dict | None,
                       provider_doc: dict | None = None,
                       now: str | None = None) -> dict:
    """Instrucciones para todos los claims elegibles del doc."""
    rules = {r.get("rule_id"): r
             for r in (ruleset_doc or {}).get("rules") or []}
    sets = (doc_sets_doc or {}).get("sets") or {}
    instructions = []
    for claim in cases_doc.get("claims") or []:
        ins = build_instruction(
            claim, sets.get(claim.get("claim_id")),
            rules.get(claim.get("rule_id")), provider_doc, now=now)
        instructions.append(ins)
    return {
        "schema": INSTRUCTION_SCHEMA,
        "generated_at": now,
        "canonical_event_id": cases_doc.get("canonical_event_id"),
        "kind": "INDEX",
        "instructions": instructions,
    }
