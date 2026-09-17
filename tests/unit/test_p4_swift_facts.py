"""P4.0 — thin adapter Python <-> iso-adapter-jvm.

Los fixtures FIN viven en adapters/iso-adapter-jvm/src/test/resources
(unica fuente: los tests Java y Python consumen los mismos mensajes).
Los tests que invocan el JVM se saltan si el fat jar no esta
construido (`cd adapters/iso-adapter-jvm && gradlew fatJar`).
"""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from ca_es import swift_mt
from ca_es.swift_mt import AdapterUnavailable, parse_mt

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "adapters" / "iso-adapter-jvm" / "src" / "test" / "resources"
JAR = swift_mt.default_adapter_jar()

requires_jar = pytest.mark.skipif(
    not JAR.is_file(),
    reason="iso-adapter.jar no construido",
)


def _fin(name):
    return (RES / name).read_text(encoding="utf-8")


def test_adapter_unavailable_without_jar():
    with pytest.raises(AdapterUnavailable):
        parse_mt("{4:\n-}", jar=ROOT / "no-existe.jar")


@requires_jar
def test_mt564_ok_contract():
    doc, code = parse_mt(_fin("mt564-valid.fin"))
    assert code == swift_mt.EXIT_OK
    assert doc["parse_status"] == "OK"
    assert doc["schema_version"] == "CA_ES_SWIFT_MT_FACTS_V1"
    assert doc["message_identifier"] == "MT564"
    for k in ("standard_family", "standard_release",
              "release_state_as_of", "library", "library_version",
              "adapter_version", "input_sha256", "generated_at"):
        assert doc[k] is not None, k
    sha = hashlib.sha256(_fin("mt564-valid.fin").encode()).hexdigest()
    assert doc["input_sha256"] == sha
    assert doc["facts"]
    for f in doc["facts"]:
        for k in ("message_identifier", "field_path", "value",
                  "source_tag", "source_qualifier", "sequence",
                  "evidence_locator", "input_sha256"):
            assert k in f, k
        assert f["input_sha256"] == sha


@requires_jar
def test_mt566_ok():
    doc, code = parse_mt(_fin("mt566-valid.fin"))
    assert code == swift_mt.EXIT_OK
    assert doc["message_identifier"] == "MT566"
    assert doc["facts"]


@requires_jar
def test_malformed_parse_error():
    doc, code = parse_mt(_fin("malformed.fin"))
    assert code == swift_mt.EXIT_PARSE_ERROR
    assert doc["parse_status"] == "PARSE_ERROR"
    assert doc["facts"] == []


@requires_jar
def test_unsupported_message_type():
    doc, code = parse_mt(_fin("mt103.fin"))
    assert code == swift_mt.EXIT_UNSUPPORTED
    assert doc["parse_status"] == "UNSUPPORTED_MESSAGE_TYPE"
    assert doc["message_identifier"] == "MT103"


@requires_jar
def test_deterministic_except_generated_at():
    a, _ = parse_mt(_fin("mt564-valid.fin"))
    b, _ = parse_mt(_fin("mt564-valid.fin"))
    a.pop("generated_at")
    b.pop("generated_at")
    assert a == b


@requires_jar
def test_no_fin_in_stderr():
    fin = _fin("mt564-valid.fin")
    proc = subprocess.run(
        ["java", "-jar", str(JAR)],
        input=fin.encode(),
        capture_output=True,
        timeout=120,
    )
    stderr = proc.stderr.decode("utf-8", errors="replace")
    for line in fin.splitlines():
        line = line.strip()
        if line:
            assert line not in stderr


@requires_jar
def test_repeated_qualifier_distinguishable():
    doc, _ = parse_mt(_fin("mt564-valid.fin"))
    payd = [
        f for f in doc["facts"]
        if f["source_tag"] == "98A"
        and f["source_qualifier"] == "PAYD"
    ]
    assert len(payd) >= 2
    locators = {f["evidence_locator"] for f in payd}
    assert len(locators) == len(payd)


def test_cli_missing_input(tmp_path, capsys):
    from ca_es.cli import main
    rc = main(["swift-facts", "--fin", str(tmp_path / "nope.fin")])
    out = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert out["status"] == "INVALID_INPUT"


def test_cli_adapter_unavailable(tmp_path, capsys, monkeypatch):
    from ca_es.cli import main
    fin = tmp_path / "m.fin"
    fin.write_text(_fin("mt564-valid.fin"), encoding="utf-8")
    monkeypatch.setenv("CA_ES_SWIFT_ADAPTER_JAR",
                       str(tmp_path / "none.jar"))
    rc = main(["swift-facts", "--fin", str(fin)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert out["status"] == "ADAPTER_UNAVAILABLE"
