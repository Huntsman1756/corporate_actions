"""P16 — demo e2e de aceptacion: Market Claims Lifecycle V1
(ad-hoc, no en CI).

Mensajes seev.050-053 REALES via adapter JVM/Prowide (fatJar
requerido; sin jar -> SKIP explicito). El lado basis/assessment
usa transacciones declaradas CA_ES_SECURITIES_TRANSACTIONS_V1.

Legs (mapeo M1-M15 del mandato):

  M0: seev.050/051/052/053 reales -> facts -> proyecciones.
  M1: CA obligatoria cash + tx elegible -> PROVEN.
  M2: misma CA sin basis suficiente -> INDETERMINATE, 0 claims.
  M3: seev.050 real -> bound determinista al claim.
  M4: seev.050 desconocida -> NO_MATCH.
  M5: cash claim expected 125 + actual 125 -> MATCH.
  M6: actual 120 -> AMOUNT_MISMATCH + caso P3.5.
  M7: securities claim -> expected delivery -> recon.
  M8: seev.052 accepted/rejected -> status lifecycle.
  M9/M10: seev.051 intent + seev.053 accepted -> CANCELLED.
  M11: seev.050 duplicada -> DUPLICATE_IGNORED.
  M12: amount cambiado -> CONFLICTING_NOTIFICATION.
  M13: tx desaparece del feed -> evidencia previa preservada.
  M14: sin regla de mercado -> MARKET_PRACTICE_REQUIRED.
  M15: re-assessment identico -> deterministico, sin dups.

Uso: python scripts/p16_e2e_demo.py
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ca_es.exceptions import classify_cases  # noqa: E402
from ca_es.market_claim_assessment import (  # noqa: E402
    INDETERMINATE, MARKET_PRACTICE_REQUIRED, PROVEN,
    claim_assessment)
from ca_es.market_claim_basis import claim_basis  # noqa: E402
from ca_es.market_claim_cancellation import (  # noqa: E402
    cancellation_doc)
from ca_es.market_claim_case import (  # noqa: E402
    CANCELLED, merge_claims, open_claims)
from ca_es.market_claim_messages import (  # noqa: E402
    bind_claim, project_claim_cancellation, project_claim_status,
    project_market_claim)
from ca_es.market_claim_recon import (  # noqa: E402
    AMOUNT_MISMATCH, MATCH, claim_recon)
from ca_es.market_claim_rules import RULES_SCHEMA  # noqa: E402
from ca_es.market_claim_status import (  # noqa: E402
    apply_claim_events)
from ca_es.mx_facts import parse_mx  # noqa: E402
from ca_es.swift_mt import AdapterUnavailable  # noqa: E402

RES = REPO / "adapters" / "iso-adapter-jvm" / "src" / "test" / "resources"
EID = "evt-mc-demo"
ISIN = "ES0113900J37"
NOW = "2026-08-01T00:00:00Z"

_results: list[tuple[str, str]] = []


def leg(name: str, status: str, detail: str = "") -> None:
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    _results.append((name, status))


def check(name: str, cond: bool, detail: str = "") -> None:
    leg(name, "PASS" if cond else "FAIL", detail)


def _skip(name: str, detail: str) -> None:
    leg(name, "SKIP", detail)


def _mx(name: str) -> dict | None:
    xml = (RES / name).read_bytes()
    try:
        doc, code = parse_mx(xml)
    except AdapterUnavailable as exc:
        print(f"  adapter no disponible: {exc}")
        return None
    if code != 0:
        return None
    return doc


def _tx_doc(txs):
    return {"schema": "CA_ES_SECURITIES_TRANSACTIONS_V1",
            "transactions": txs}


def _tx(tid="TX-1", siid="SI-DEMO-1", direction="BUY",
        qty="1000", trade="2026-07-20", settle="2026-07-30",
        status="PENDING"):
    return {"transaction_id": tid,
            "settlement_instruction_id": siid,
            "account_id": "ACC-ES-1", "isin": ISIN,
            "quantity": qty, "direction": direction,
            "trade_date": trade, "settlement_date": settle,
            "settlement_status": status,
            "provenance": [{"source": "feed", "ref": tid}]}


def _basis(txs, event_type="CASH_DIVIDEND"):
    return claim_basis(
        _tx_doc(txs), canonical_event_id=EID,
        event_type=event_type, ex_date="2026-07-27",
        record_date="2026-07-28", payment_date="2026-07-29",
        now=NOW)


def _rules(kind="CASH", event_type="CASH_DIVIDEND"):
    return {
        "schema": RULES_SCHEMA, "ruleset_id": "es-mc-demo",
        "rules": [{
            "rule_id": "ES-DVCA-MKTC-001",
            "jurisdiction": "ES", "event_type": event_type,
            "valid_from": "2020-01-01",
            "claim_type": "MKTC",
            "claim_direction": "BUYER_COMPENSATED",
            "eligibility": {
                "trade_date_relation": "BEFORE_EX_DATE",
                "settlement_status": ["PENDING", "SETTLED_LATE"],
                "settlement_date_relation": "AFTER_RECORD_DATE"},
            "proceeds": {"kind": kind},
            "deadline": {"basis": "RECORD_DATE", "days": 30}}]}


def _assess(basis, rules=None, rate="0.125",
            ccy="EUR", ratio=None, target=None):
    if rules is None:
        rules = _rules()
    return claim_assessment(
        basis, rules, jurisdiction="ES",
        assessment_date="2026-08-01", proceeds_rate=rate,
        proceeds_currency=ccy,
        proceeds_quantity_ratio=ratio,
        proceeds_target_isin=target, now=NOW)


def _movement(amount, ref, mid="M-1"):
    return {"schema": "CA_ES_CASH_MOVEMENTS_V2",
            "movements": [{"movement_id": mid,
                           "account_id": "ACC-ES-1",
                           "event_id": EID, "amount": amount,
                           "currency": "EUR", "direction": "CRDT",
                           "source_reference": ref}]}


def _sec_movement(qty, ref):
    return {"schema": "CA_ES_SECURITIES_MOVEMENTS_V1",
            "movements": [{"movement_id": "SM-1",
                           "account_id": "ACC-ES-1",
                           "event_id": EID, "quantity": qty,
                           "isin": ISIN, "direction": "RECE",
                           "source_reference": ref}]}


def _status_events(claims, internal, at, ref):
    cid = claims["claims"][0]["claim_id"]
    return [{"event_type": "STATUS", "claim_id": cid, "at": at,
             "source_ref": ref, "internal_status": internal}]


def _bind_and_notify(claims, proj050, ref, observed=None):
    """seev.050 proyectada -> bind -> evento NOTIFICATION."""
    binding = bind_claim(proj050["projection"], claims)
    if binding["binding_status"] != "BOUND":
        return binding, None
    ev = {"event_type": "NOTIFICATION",
          "claim_id": binding["claim_id"],
          "at": "2026-08-02", "source_ref": ref,
          "projection": proj050["projection"]}
    if observed is not None:
        ev["observed_amount"] = observed
    out = apply_claim_events(claims, [ev], now=NOW)
    return binding, out


def main() -> int:
    print("P16 e2e demo — Market Claims Lifecycle")

    # M0: mensajes reales via pin SRU2025
    docs = {}
    for key, name in [("050", "seev050-mktclm.xml"),
                      ("052", "seev052-accepted.xml"),
                      ("051", "seev051-cxl.xml"),
                      ("053", "seev053-cxl-accepted.xml")]:
        d = _mx(name)
        if d is None:
            _skip("M0 real MX facts", "adapter/jar no disponible")
            docs = None
            break
        docs[key] = d
    if docs:
        proj050 = project_market_claim(docs["050"], now=NOW)
        proj052 = project_claim_status(docs["052"], now=NOW)
        proj051 = project_claim_cancellation(docs["051"], now=NOW)
        proj053 = project_claim_cancellation(docs["053"], now=NOW)
        p = proj050["projection"]
        check("M0 seev.050 real -> projection",
              proj050["status"] == "PROJECTED"
              and p["market_claim_type"] == "MKTC"
              and p["transfer_of_proceeds"] == "CLFT"
              and p["cash_movements"][0]["amount"] == "125.00",
              f"refs={p['references']}")
        check("M0 seev.052/051/053 real -> projections",
              proj052["projection"]["internal_status"] == "ACCEPTED"
              and proj051["projection"]["kind"]
              == "CANCELLATION_REQUEST"
              and proj053["projection"]["internal_status"]
              == "CANCEL_ACCEPTED")

    # M1: tx elegible -> PROVEN
    basis = _basis([_tx()])
    assessment = _assess(basis)
    item = assessment["items"][0]
    check("M1 eligible tx -> PROVEN",
          item["status"] == PROVEN
          and item["expected_amount"] == "125.000",
          f"claim_id={item['claim_id']}")

    # M2: basis insuficiente (tx sin quantity) -> INDETERMINATE
    tx_incomplete = _tx()
    del tx_incomplete["quantity"]
    basis2 = _basis([tx_incomplete])
    assessment2 = _assess(basis2)
    claims2 = open_claims(assessment2, now=NOW)
    check("M2 insufficient basis -> INDETERMINATE, 0 claims",
          assessment2["items"][0]["status"] == INDETERMINATE
          and claims2["claims"] == [])

    claims = open_claims(assessment, now=NOW)
    cid = claims["claims"][0]["claim_id"]

    def ensure_notified(doc_claims):
        """NOTIFICATION sintetica si el claim sigue EXPECTED (la
        real via seev.050 ya la aplico _bind_and_notify)."""
        if doc_claims["claims"][0]["status"] == "EXPECTED":
            apply_claim_events(doc_claims, [{
                "event_type": "NOTIFICATION",
                "claim_id": doc_claims["claims"][0]["claim_id"],
                "at": "2026-08-02", "source_ref": "sha-050"}], now=NOW)

    # M3/M4: binding seev.050
    if docs:
        binding, out = _bind_and_notify(claims, proj050, "sha-050")
        check("M3 seev.050 -> BOUND + NOTIFIED",
              binding["binding_status"] == "BOUND"
              and binding["claim_id"] == cid
              and claims["claims"][0]["status"] == "NOTIFIED",
              f"matched={binding.get('matched_references')}")

        # M4: ref desconocida -> NO_MATCH (todas las refs que
        # podrian ligar se sustituyen por desconocidas)
        fake = dict(proj050)
        fake["projection"] = dict(proj050["projection"])
        fake["projection"]["references"] = {
            "account_servicer_tx_id": "CLM-UNKNOWN-9"}
        fake["projection"]["related_settlement_instruction_id"] = \
            "SI-UNKNOWN-9"
        b4 = bind_claim(fake["projection"],
                        {"claims": claims["claims"]})
        check("M4 unknown seev.050 -> NO_MATCH",
              b4["binding_status"] == "NO_MATCH")

    # M5/M6: cash recon por referencia explicita
    ensure_notified(claims)
    recon = claim_recon(claims, [_movement("125.00", cid)], now=NOW)
    check("M5 expected 125 == actual 125 -> MATCH",
          recon["items"][0]["status"] == MATCH)
    recon = claim_recon(claims, [_movement("120.00", cid)], now=NOW)
    cases = classify_cases(recon)
    check("M6 actual 120 -> AMOUNT_MISMATCH + P3.5 case",
          recon["items"][0]["status"] == AMOUNT_MISMATCH
          and len(cases) == 1
          and cases[0]["case_key"].startswith("market-claim|"))

    # M7: securities claim
    basis7 = _basis([_tx()], event_type="STOCK_SPLIT")
    a7 = claim_assessment(
        basis7, _rules(kind="SECURITIES",
                       event_type="STOCK_SPLIT"),
        jurisdiction="ES", assessment_date="2026-08-01",
        proceeds_quantity_ratio="0.5",
        proceeds_target_isin="ES0113900J38", now=NOW)
    claims7 = open_claims(a7, now=NOW)
    cid7 = claims7["claims"][0]["claim_id"]
    apply_claim_events(claims7, [{
        "event_type": "NOTIFICATION", "claim_id": cid7,
        "at": "2026-08-02", "source_ref": "sha-050-sec"}],
        now=NOW)
    recon7 = claim_recon(claims7, [_sec_movement("500", cid7)],
                         now=NOW)
    check("M7 securities claim -> expected + MATCH",
          Decimal(claims7["claims"][0]["expected_quantity"])
          == Decimal("500")
          and recon7["items"][0]["status"] == MATCH,
          f"exp={claims7['claims'][0]['expected_quantity']}")

    # M8: seev.052 lifecycle
    if docs:
        apply_claim_events(claims, _status_events(
            claims, "ACCEPTED", "2026-08-05", "sha-052"), now=NOW)
        check("M8 seev.052 accepted -> ACCEPTED",
              claims["claims"][0]["status"] == "ACCEPTED")
        # REJECTED desde NOTIFIED/PENDING (ACCEPTED no es
        # rechazable: solo cancela o liquida)
        claims_r = open_claims(assessment, now=NOW)
        ensure_notified(claims_r)
        apply_claim_events(claims_r, _status_events(
            claims_r, "REJECTED", "2026-08-06", "sha-052r"),
            now=NOW)
        check("M8 seev.052 rejected -> REJECTED",
              claims_r["claims"][0]["status"] == "REJECTED")

    # M9/M10: cancelacion via seev.051 + seev.053
    claims_c = open_claims(assessment, now=NOW)
    cid_c = claims_c["claims"][0]["claim_id"]
    ensure_notified(claims_c)
    apply_claim_events(claims_c, [{
        "event_type": "CANCELLATION_REQUEST", "claim_id": cid_c,
        "at": "2026-08-03", "source_ref": "sha-051",
        "projection": proj051["projection"] if docs else None}],
        now=NOW)
    still = claims_c["claims"][0]["status"]
    cancel_events = [{
        "event_type": "CANCELLATION_STATUS", "claim_id": cid_c,
        "at": "2026-08-04", "source_ref": "sha-053",
        "cancel_outcome": "CANCEL_ACCEPTED",
        "projection": proj053["projection"] if docs else None}]
    apply_claim_events(claims_c, cancel_events, now=NOW)
    cdoc = cancellation_doc(claims_c, [
        {"event_type": "CANCELLATION_REQUEST", "claim_id": cid_c,
         "source_ref": "sha-051"},
        *cancel_events], now=NOW)
    check("M9 seev.051 intent separado -> CANCELLATION_REQUESTED",
          still == "CANCELLATION_REQUESTED"
          and cdoc["items"][0]["current_outcome"] == "ACCEPTED")
    check("M10 seev.053 accepted -> CANCELLED",
          claims_c["claims"][0]["status"] == CANCELLED)

    # M11: seev.050 duplicada -> idempotente
    if docs:
        binding, out = _bind_and_notify(claims, proj050, "sha-050")
        check("M11 duplicate seev.050 -> DUPLICATE_IGNORED",
              out["outcomes"][0]["outcome"] == "DUPLICATE_IGNORED")

    # M12: amount cambiado -> conflicto, nunca overwrite
    if docs:
        before = claims["claims"][0]["expected_amount"]
        _, out12 = _bind_and_notify(claims, proj050,
                                    "sha-050b", observed="120.00")
        check("M12 changed amount -> CONFLICTING, preserved",
              out12["outcomes"][0]["outcome"]
              == "CONFLICTING_NOTIFICATION"
              and claims["claims"][0]["expected_amount"] == before)

    # M13: tx desaparece -> evidencia previa preservada
    empty_basis = _basis([])
    a13 = _assess(empty_basis)
    claims13 = open_claims(a13, now=NOW)
    merged = merge_claims(claims, claims13, now=NOW)
    check("M13 tx gone -> prior claim preserved",
          len(merged["claims"]) == 1
          and merged["claims"][0]["claim_id"] == cid)

    # M14: sin regla de mercado -> MARKET_PRACTICE_REQUIRED
    a14 = _assess(basis, rules={"schema": RULES_SCHEMA,
                                "ruleset_id": "empty",
                                "rules": []})
    check("M14 no market rule -> MARKET_PRACTICE_REQUIRED",
          a14["items"][0]["status"] == MARKET_PRACTICE_REQUIRED)

    # M15: re-assessment identico -> deterministico, sin dups
    a15 = _assess(basis)
    claims15 = open_claims(a15, now=NOW)
    merged15 = merge_claims(claims, claims15, now=NOW)
    check("M15 identical run -> deterministic, no dups",
          a15["items"][0]["claim_id"] == item["claim_id"]
          and len(merged15["claims"]) == 1)

    passed = sum(1 for _, s in _results if s == "PASS")
    skipped = sum(1 for _, s in _results if s == "SKIP")
    failed = sum(1 for _, s in _results if s == "FAIL")
    print(f"\n{passed} PASS / {skipped} SKIP / {failed} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
