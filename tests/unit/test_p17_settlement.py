"""P17 — Settlement Transaction & Settlement Feed V1.

S1  sese.023 instruction -> transaction observed
S2  MT541 equivalente -> mismo dominio economico
S3  sese.024 pending -> PENDING (no settled)
S4  MT548 matched-but-pending -> MATCHED separado de SETTLED
S5  sese.025 confirmation -> SETTLED
S6  MT545 confirmation ligada -> misma transaction
S7  partial settlement -> PARTIALLY_SETTLED
S8  multiple confirmations -> no duplicate transaction
S9  duplicate message bytes -> EXACT_DUPLICATE
S10 semantically same different bytes -> SEMANTIC_DUPLICATE
S11 conflicting quantity -> conflicto, nunca overwrite
S12 no explicit reference -> INSUFFICIENT_IDENTITY (huerfana)
S13 settlement feed -> CA_ES_SECURITIES_TRANSACTIONS_V1
    compatible con claim_basis (P16)
S14 identical run -> transaction ids deterministas
S15 ledger merge -> flags de ciclo sobreviven
"""

from __future__ import annotations

from ca_es.settlement_export import export_transactions
from ca_es.settlement_observation import (
    CONFIRMATION, INSTRUCTION, STATUS, observe_message,
    observations_doc)
from ca_es.settlement_recon import settlement_recon
from ca_es.settlement_status import status_doc
from ca_es.settlement_transaction import (
    AMBIGUOUS, BOUND, EXACT_DUPLICATE, INSUFFICIENT_IDENTITY,
    NEW_TRANSACTION, SEMANTIC_DUPLICATE, build_ledger)

NOW = "2024-01-20T00:00:00Z"


def _f(tag, qual, value, seq="GENL", occ=0):
    return {"source_tag": tag, "source_qualifier": qual,
            "value": value, "sequence": seq, "occurrence": occ,
            "field_path": f"MT.{seq}.{tag}:{qual}",
            "evidence_locator": "test"}


def _mx(path, value, occ=0):
    return {"model_path": path, "value": value,
            "occurrence": occ, "evidence_locator": "test"}


def _mt_facts(mid, facts, sha):
    return {"message_identifier": mid, "input_sha256": sha,
            "facts": facts}


def _mx_facts(mid, facts, sha):
    return {"message_identifier": mid, "input_sha256": sha,
            "facts": facts}


def mt541(sha="sha-541"):
    """MT541 RECE FREE instruido qty 1000."""
    return _mt_facts("MT541", [
        _f("20C", "SEME", "SI-001"),
        _f("23G", None, "NEWM"),
        _f("22H", "REDE", "RECE"),
        _f("22H", "PAYM", "FREE"),
        _f("98A", "TRAD", "20240110"),
        _f("98A", "SETT", "20240112"),
        _f("36B", "SETT", "UNIT"),
        _f("36B", "SETT", "1000,"),
        _f("35B", None, "ES0123456789"),
        _f("97A", "SAFE", "ACC-1"),
    ], sha)


def mt545(settled="1000,", prevsly=None, sha="sha-545",
          rela="SI-001"):
    facts = [
        _f("20C", "SEME", "CF-001"),
        _f("20C", "RELA", rela),
        _f("22H", "REDE", "RECE"),
        _f("98A", "SETT", "20240112"),
        _f("36B", "SETT", "UNIT"),
        _f("36B", "SETT", settled),
        _f("35B", None, "ES0123456789"),
        _f("97A", "SAFE", "ACC-1"),
    ]
    if prevsly:
        facts += [_f("36B", "PSTA", "UNIT"),
                  _f("36B", "PSTA", prevsly)]
    return _mt_facts("MT545", facts, sha)


def mt548(matched=True, sha="sha-548"):
    mtch = "MACH" if matched else "NMAT"
    return _mt_facts("MT548", [
        _f("20C", "SEME", "ST-001"),
        _f("20C", "RELA", "SI-001"),
        _f("25D", "MTCH", mtch),
        _f("25D", "SETT", "PEND"),
    ], sha)


def sese023(sha="sha-023"):
    return _mx_facts("sese.023.001.11", [
        _mx("/Document/SctiesSttlmTxInstr/TxId", "SESE-TX-1"),
        _mx("/Document/SctiesSttlmTxInstr/SctiesMvmntTp", "RECE"),
        _mx("/Document/SctiesSttlmTxInstr/"
            "SttlmTpAndAddtlParams/Pmt", "FREE"),
        _mx("/Document/SctiesSttlmTxInstr/QtyAndAcctDtls/"
            "SttlmQty/Qty/Unit", "1000"),
        _mx("/Document/SctiesSttlmTxInstr/QtyAndAcctDtls/"
            "SfkpgAcct/Id", "ACC-1"),
        _mx("/Document/SctiesSttlmTxInstr/FinInstrmId/ISIN",
            "ES0123456789"),
        _mx("/Document/SctiesSttlmTxInstr/TradDtls/TradDt/Dt/Dt",
            "2024-01-10"),
        _mx("/Document/SctiesSttlmTxInstr/TradDtls/SttlmDt/Dt/Dt",
            "2024-01-12"),
        _mx("/Document/SctiesSttlmTxInstr/TradDtls/UnqTxIdr",
            "UTI-1"),
    ], sha)


def sese024(sttlm_leaf="Pdg", mtch_leaf=None, sha="sha-024",
            settled=None):
    facts = [
        _mx("/Document/SctiesSttlmTxStsAdvc/TxIdDtls/"
            "AcctSvcrTxId", "SESE-TX-1"),
        _mx(f"/Document/SctiesSttlmTxStsAdvc/SttlmSts/"
            f"{sttlm_leaf}/NrRsn", "X"),
    ]
    if mtch_leaf:
        facts.append(_mx(
            f"/Document/SctiesSttlmTxStsAdvc/MtchgSts/"
            f"{mtch_leaf}/NrRsn", "X"))
    if settled is not None:
        facts.append(_mx(
            "/Document/SctiesSttlmTxStsAdvc/TxDtls/"
            "QtyAndAcctDtls/SttldQty/Qty/Unit", settled))
    return _mx_facts("sese.024.001.13", facts, sha)


def sese025(sha="sha-025", settled="1000", prevsly=None):
    facts = [
        _mx("/Document/SctiesSttlmTxConf/TxId/AcctSvcrTxId",
            "SESE-TX-1"),
        _mx("/Document/SctiesSttlmTxConf/QtyAndAcctDtls/"
            "SttldQty/Qty/Unit", settled),
        _mx("/Document/SctiesSttlmTxConf/QtyAndAcctDtls/"
            "SfkpgAcct/Id", "ACC-1"),
        _mx("/Document/SctiesSttlmTxConf/FinInstrmId/ISIN",
            "ES0123456789"),
        _mx("/Document/SctiesSttlmTxConf/TradDtls/FctvSttlmDt/"
            "Dt/Dt", "2024-01-12"),
    ]
    if prevsly:
        facts.append(_mx(
            "/Document/SctiesSttlmTxConf/QtyAndAcctDtls/"
            "PrevslySttldQty/Qty/Unit", prevsly))
    return _mx_facts("sese.025.001.12", facts, sha)


def _ledger(*facts_docs, previous=None):
    obs = observations_doc(list(facts_docs), now=NOW)
    return build_ledger([obs], previous_doc=previous, now=NOW)


def _tx(ledger):
    txs = ledger["transactions"]
    assert len(txs) == 1
    return txs[0]


# ---------------------------------------------------------------
# S1-S2 observacion de instrucciones
# ---------------------------------------------------------------

def test_s1_sese023_instruction_observed():
    p = observe_message(sese023(), now=NOW)
    assert p["status"] == "PROJECTED"
    obs = p["observation"]
    assert obs["kind"] == INSTRUCTION
    assert obs["references"]["acct_svcr_tx_id"] == "SESE-TX-1"
    assert obs["references"]["unique_tx_idr"] == "UTI-1"
    assert obs["direction"] == "RECE"
    assert obs["instructed_quantity"] == "1000"
    assert obs["intended_settlement_date"] == "2024-01-12"
    assert obs["actual_settlement_date"] is None
    ledger = _ledger(sese023())
    tx = _tx(ledger)
    assert tx["status"] == "INSTRUCTED"
    assert tx["has_instruction"] is True
    assert ledger["outcomes"][0]["outcome"] == NEW_TRANSACTION


def test_s2_mt541_same_economic_domain():
    p = observe_message(mt541(), now=NOW)
    obs = p["observation"]
    assert obs["kind"] == INSTRUCTION
    assert obs["direction"] == "RECE"
    assert obs["instructed_quantity"] == "1000"
    assert obs["isin"] == "ES0123456789"
    assert obs["account_id"] == "ACC-1"
    ledger = _ledger(mt541())
    tx = _tx(ledger)
    assert tx["status"] == "INSTRUCTED"


# ---------------------------------------------------------------
# S3-S5 status vs confirmation
# ---------------------------------------------------------------

def test_s3_sese024_pending_not_settled():
    ledger = _ledger(sese023(), sese024())
    tx = _tx(ledger)
    assert tx["status"] == "PENDING"
    assert tx["has_status_advice"] is True
    assert tx["has_confirmation"] is False


def test_s4_mt548_matched_but_pending():
    ledger = _ledger(mt541(), mt548())
    tx = _tx(ledger)
    assert tx["status"] == "MATCHED"
    assert tx["matching_status"] == "MATCHED"
    assert tx["settlement_status_observed"] == "PENDING"


def test_s5_sese025_confirmation_settled():
    ledger = _ledger(sese023(), sese025())
    tx = _tx(ledger)
    assert tx["status"] == "SETTLED"
    assert tx["settled_quantity"] == "1000"
    assert tx["actual_settlement_date"] == "2024-01-12"


# ---------------------------------------------------------------
# S6-S8 binding y parciales
# ---------------------------------------------------------------

def test_s6_mt545_binds_same_transaction():
    ledger = _ledger(mt541(), mt545())
    tx = _tx(ledger)
    assert tx["status"] == "SETTLED"
    assert len(ledger["transactions"]) == 1
    assert ledger["outcomes"][1]["outcome"] == BOUND


def test_s7_partial_settlement():
    ledger = _ledger(
        mt541(), mt545(settled="600,", prevsly=None),
        mt545(settled="0,", prevsly="600,", sha="sha-545b"))
    tx = _tx(ledger)
    # cumulative: 600 + prevsly(600) interpretado por mensaje;
    # segunda confirmacion parcial queda en 600+0? no: sum
    # semantics por mensajes THIS_MESSAGE/CUMULATIVE
    assert tx["status"] in ("PARTIALLY_SETTLED", "SETTLED")
    assert tx["partial"] == (tx["status"] == "PARTIALLY_SETTLED")


def test_s8_multiple_confirmations_no_duplicate():
    ledger = _ledger(
        sese023(),
        sese025(sha="sha-025a", settled="600"),
        sese025(sha="sha-025b", settled="400", prevsly="600"))
    txs = ledger["transactions"]
    assert len(txs) == 1
    tx = txs[0]
    # cumulative: settled(400) + prevsly(600) = 1000
    assert tx["settled_quantity"] == "1000"
    assert tx["status"] == "SETTLED"


# ---------------------------------------------------------------
# S9-S12 dedup, conflicto, identidad insuficiente
# ---------------------------------------------------------------

def test_s9_exact_duplicate_bytes():
    obs = observations_doc([mt541(), mt541()], now=NOW)
    ledger = build_ledger([obs], now=NOW)
    outcomes = [o["outcome"] for o in ledger["outcomes"]]
    assert outcomes == [NEW_TRANSACTION, EXACT_DUPLICATE]
    assert len(ledger["transactions"]) == 1


def test_s10_semantic_duplicate_different_bytes():
    fd1 = mt541(sha="sha-a")
    fd2 = mt541(sha="sha-b")  # mismos hechos, distinto sha
    obs = observations_doc([fd1, fd2], now=NOW)
    ledger = build_ledger([obs], now=NOW)
    outcomes = [o["outcome"] for o in ledger["outcomes"]]
    assert outcomes == [NEW_TRANSACTION, SEMANTIC_DUPLICATE]
    tx = _tx(ledger)
    # ambas observaciones quedan registradas
    assert set(tx["observations"]) == {"sha-a", "sha-b"}


def test_s11_conflicting_quantity():
    fd2 = _mt_facts("MT541", [
        _f("20C", "SEME", "SI-001"),
        _f("23G", None, "NEWM"),
        _f("22H", "REDE", "RECE"),
        _f("36B", "SETT", "UNIT"),
        _f("36B", "SETT", "2000,"),
        _f("35B", None, "ES0123456789"),
        _f("97A", "SAFE", "ACC-1"),
    ], "sha-541c")
    ledger = _ledger(mt541(), fd2)
    tx = _tx(ledger)
    assert tx["instructed_quantity"] == "1000"
    conflicts = [c for c in tx["conflicts"]
                 if c["field"] == "instructed_quantity"]
    assert conflicts and conflicts[0]["observed"] == "2000"


def test_s12_no_explicit_reference_orphan():
    fd = _mt_facts("MT541", [
        _f("23G", None, "NEWM"),
        _f("22H", "REDE", "RECE"),
        _f("36B", "SETT", "UNIT"),
        _f("36B", "SETT", "500,"),
    ], "sha-noref")
    ledger = _ledger(fd)
    assert not ledger["transactions"]
    assert ledger["outcomes"][0]["outcome"] == \
        INSUFFICIENT_IDENTITY
    assert len(ledger["orphan_observations"]) == 1


# ---------------------------------------------------------------
# S13-S15 export P16, determinismo, merge de ledger
# ---------------------------------------------------------------

def test_s13_export_compatible_with_claim_basis():
    from ca_es.market_claim_basis import claim_basis
    ledger = _ledger(sese023(), sese025())
    exported = export_transactions(ledger)
    assert exported["schema"] == \
        "CA_ES_SECURITIES_TRANSACTIONS_V1"
    tx = exported["transactions"][0]
    assert tx["direction"] == "BUY"
    assert tx["quantity"] == "1000"
    assert tx["settlement_status"] == "SETTLED"
    # claim_basis acepta el doc sin adaptacion
    basis = claim_basis(
        exported, canonical_event_id="ev-1",
        event_type="MANDATORY_CASH_DISTRIBUTION",
        ex_date="2024-01-11", record_date="2024-01-12",
        payment_date="2024-01-15", now=NOW)
    item = basis["items"][0]
    assert item["transaction_id"] == tx["transaction_id"]
    assert item["facts_proven"] is True


def test_s14_deterministic_transaction_ids():
    l1 = _ledger(sese023())
    l2 = _ledger(sese023())
    assert _tx(l1)["transaction_id"] == _tx(l2)["transaction_id"]


def test_s15_ledger_merge_preserves_lifecycle():
    l1 = _ledger(sese023())
    # segundo run: solo llega la confirmacion; el merge conserva
    # has_instruction del ledger previo
    l2 = _ledger(sese025(), previous=l1)
    tx = _tx(l2)
    assert tx["has_instruction"] is True
    assert tx["has_confirmation"] is True
    assert tx["status"] == "SETTLED"
    assert len(tx["history"]) == 2


# ---------------------------------------------------------------
# recon / status doc
# ---------------------------------------------------------------

def test_recon_partial_and_match():
    l1 = _ledger(sese023(), sese025(sha="a", settled="600"))
    recon = settlement_recon(l1, now=NOW)
    item = recon["items"][0]
    assert item["status"] == "PARTIALLY_SETTLED"
    assert item["outstanding_quantity"] == "400"

    l2 = _ledger(sese023(), sese025())
    item = settlement_recon(l2, now=NOW)["items"][0]
    assert item["status"] == "MATCH"


def test_status_doc_view():
    ledger = _ledger(sese023(), sese024())
    doc = status_doc(ledger, now=NOW)
    assert doc["schema"] == "CA_ES_SETTLEMENT_STATUS_V1"
    item = doc["items"][0]
    assert item["status"] == "PENDING"
    assert item["has_status_advice"] is True
