"""Regression tests del driver G1-R (scripts/g1r_next.py): el motor de
gobernanza debe ser fail-closed — artefacto viejo, rc inesperado,
JSON manipulado, target ausente o drift de inputs = STOP, nunca PASS.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import g1r_next  # noqa: E402
from ca_es.canonical import sha256_hex  # noqa: E402


class _Proc:
    def __init__(self, rc, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


def _write_results(tmp_path, name="dev-iter-9-abcdef1-results.json",
                   tamper=False):
    body = {
        "results_version": "CA_ES_G1R_RESULTS_V1",
        "phase": "dev-iter-9",
        "seed_set": "development",
        "parser_commit": "abcdef1" + "0" * 33,
        "parser_commit_dirty": False,
        "seeds": 25,
        "funnel": {"seeds": 25},
        "results": [{"event_detected": True}],
    }
    body["batch_sha256"] = sha256_hex(body)
    if tamper:
        body["funnel"]["seeds"] = 26  # manipulado tras el run:
        # el sha almacenado ya no recalcula desde el cuerpo
    results = tmp_path / name
    results.write_text(json.dumps(body), encoding="utf-8")
    results.with_suffix(".sha256").write_text(
        f"{body['batch_sha256']}  {name}\n", encoding="utf-8")
    return results


def test_git_rc_no_cero_es_gate_error():
    with patch.object(g1r_next.subprocess, "run",
                      return_value=_Proc(128, err="fatal")):
        with pytest.raises(g1r_next.GateError):
            g1r_next._git("status")


def test_run_rc_no_permitido_es_gate_error():
    with patch.object(g1r_next.subprocess, "run",
                      return_value=_Proc(2, err="crash")):
        with pytest.raises(g1r_next.GateError):
            g1r_next._run(["x"], {}, allowed=(0, 1))
    with patch.object(g1r_next.subprocess, "run",
                      return_value=_Proc(1, out="fails")):
        g1r_next._run(["x"], {}, allowed=(0, 1))  # rc 1 permitido


def test_results_artifact_valido_pasa(tmp_path):
    _write_results(tmp_path)
    with patch.object(g1r_next, "RESULTS", tmp_path), \
            patch.object(g1r_next, "_git", return_value=""):
        assert g1r_next.results_artifact_problems(
            "dev-iter-9", "abcdef1" + "0" * 33) == []


def test_results_artifact_manipulado_stop(tmp_path):
    _write_results(tmp_path, tamper=True)
    with patch.object(g1r_next, "RESULTS", tmp_path), \
            patch.object(g1r_next, "_git", return_value=""):
        problems = g1r_next.results_artifact_problems(
            "dev-iter-9", "abcdef1" + "0" * 33)
    assert any("batch_sha256" in p for p in problems)


def test_results_artifact_ambiguo_stop(tmp_path):
    _write_results(tmp_path)
    _write_results(tmp_path, name="dev-iter-9-0000000-results.json")
    with patch.object(g1r_next, "RESULTS", tmp_path), \
            patch.object(g1r_next, "_git", return_value=""):
        problems = g1r_next.results_artifact_problems(
            "dev-iter-9", "abcdef1" + "0" * 33)
    assert any("ambiguo" in p for p in problems)


def test_results_artifact_ausente_stop(tmp_path):
    with patch.object(g1r_next, "RESULTS", tmp_path), \
            patch.object(g1r_next, "_git", return_value=""):
        problems = g1r_next.results_artifact_problems(
            "dev-iter-9", "abcdef1" + "0" * 33)
    assert any("ausente" in p for p in problems)


def test_results_artifact_drift_stop(tmp_path):
    _write_results(tmp_path)
    with patch.object(g1r_next, "RESULTS", tmp_path), \
            patch.object(g1r_next, "_git",
                         return_value="src/ca_es/sources/parsers/cnmv.py\n"):
        problems = g1r_next.results_artifact_problems(
            "dev-iter-9", "abcdef1" + "0" * 33)
    assert any("run inputs" in p for p in problems)


def test_dev_target_missing_es_stop_no_keyerror():
    rows = {"CNMV-OIR-40758 :: event_type": {"status": "P0_CORRECTED"}}
    bad = g1r_next._dev_target_problems(
        rows, {"CNMV-OIR-40758 :: event_type",
               "CNMV-OIR-99999 :: event_type"})
    assert bad == ["CNMV-OIR-99999 :: event_type (target missing)"]


def test_dev_target_unresolved_es_stop():
    rows = {"CNMV-OIR-40758 :: event_type": {"status": "P0_UNRESOLVED"}}
    assert g1r_next._dev_target_problems(
        rows, {"CNMV-OIR-40758 :: event_type"}) != []


def test_begin_abre_siempre_queue0(tmp_path):
    state = {"failure_classes": {"resolved": [], "in_review": [],
                                 "queue": ["CLASS_A", "CLASS_B"]},
             "targets": {}}
    with patch.object(g1r_next, "save_state", lambda s: None), \
            patch.object(g1r_next, "print_class", lambda s, n: None):
        assert g1r_next.cmd_begin(state) == 0
    assert state["failure_classes"]["in_review"] == ["CLASS_A"]
    assert state["failure_classes"]["queue"] == ["CLASS_B"]


def test_begin_bloqueado_si_in_review():
    state = {"failure_classes": {"resolved": [], "in_review": ["CLASS_X"],
                                 "queue": ["CLASS_A"]},
             "targets": {}}
    assert g1r_next.cmd_begin(state) == 2
    assert state["failure_classes"]["queue"] == ["CLASS_A"]
