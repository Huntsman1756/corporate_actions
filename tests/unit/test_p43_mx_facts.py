"""P4.3 — MX facts: CA_ES_SWIFT_MX_FACTS_V1 via iso-adapter-jvm.

Los fixtures XML viven en adapters/iso-adapter-jvm/src/test/resources.
Los tests que invocan el JVM se saltan si el fat jar no esta
construido (`cd adapters/iso-adapter-jvm && gradlew fatJar`).
"""

from pathlib import Path

import pytest

from ca_es import mx_facts
from ca_es.swift_mt import default_adapter_jar

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "adapters" / "iso-adapter-jvm" / "src" / "test" / "resources"
JAR = default_adapter_jar()

requires_jar = pytest.mark.skipif(
    not JAR.is_file(), reason="iso-adapter.jar no construido"
)


@requires_jar
def test_seev031_facts_end_to_end():
    xml = (RES / "seev031-002.xml").read_bytes()
    doc, code = mx_facts.parse_mx(xml)
    assert code == 0
    assert doc["schema_version"] == "CA_ES_SWIFT_MX_FACTS_V1"
    assert doc["message_identifier"] == "seev.031.002.15"
    assert doc["parse_status"] == "PARSE_OK"
    assert doc["standard_family"] == "ISO20022"
    assert doc["library"] == "prowide-iso20022"
    assert doc["library_version"] == "SRU2025-10.3.10"

    paths = {f["model_path"]: f["value"] for f in doc["facts"]}
    assert paths[
        "/Document/CorpActnNtfctn/CorpActnGnlInf/EvtTp/Cd"] == "DVCA"
    assert paths[
        "/Document/CorpActnNtfctn/CorpActnGnlInf/UndrlygScty"
        "/FinInstrmId/ISIN"] == "ES0105448007"
    assert paths[
        "/Document/CorpActnNtfctn/CorpActnOptnDtls"
        "/RateAndAmtDtls/GrssDstrbtnRate/Amt"] == "0.25"
    assert paths[
        "/Document/CorpActnNtfctn/CorpActnOptnDtls"
        "/RateAndAmtDtls/GrssDstrbtnRate/Amt/@Ccy"] == "EUR"
    # cada fact lleva locator determinista e input_sha256
    assert all(
        f["evidence_locator"].startswith("element:")
        and f["input_sha256"] == doc["input_sha256"]
        for f in doc["facts"]
    )


@requires_jar
def test_xxe_and_doctype_fail_closed():
    xxe = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        b'<Document xmlns="urn:iso:std:iso:20022:tech:xsd:'
        b'seev.031.002.15"><CorpActnNtfctn><CorpActnGnlInf>'
        b'<CorpActnEvtId>&x;</CorpActnEvtId></CorpActnGnlInf>'
        b'</CorpActnNtfctn></Document>'
    )
    doc, code = mx_facts.parse_mx(xxe)
    assert code == 2
    assert doc["parse_status"] == "PARSE_ERROR"
    assert not doc["facts"]


@requires_jar
def test_malformed_and_unsupported():
    doc, code = mx_facts.parse_mx(b"<broken")
    assert code == 2
    assert doc["parse_status"] == "PARSE_ERROR"

    camt = (
        b'<Document xmlns="urn:iso:std:iso:20022:tech:xsd:'
        b'camt.054.001.08"><BkToCstmrDbtCdtNtfctn/></Document>'
    )
    doc, code = mx_facts.parse_mx(camt)
    assert code == 3
    assert doc["parse_status"] == "UNSUPPORTED_MESSAGE_TYPE"
    assert doc["message_identifier"] == "camt.054.001.08"


@requires_jar
def test_determinism():
    xml = (RES / "seev031-002.xml").read_bytes()
    a, _ = mx_facts.parse_mx(xml)
    b, _ = mx_facts.parse_mx(xml)
    a.pop("generated_at")
    b.pop("generated_at")
    assert a == b
