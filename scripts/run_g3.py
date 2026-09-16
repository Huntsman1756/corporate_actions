# -*- coding: utf-8 -*-
"""Runner G3 Operational Surface.

Verifica sellos de entrada (canon + policy) y freeze, luego ejecuta los
comandos de superficie x2 sobre g3/input/canon.json y almacena las
salidas en g3/results/commands/ para la evaluacion de gates.

    PYTHONPATH=src python scripts/run_g3.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ca_es.export import canon_bytes  # noqa: E402

CANON = REPO / "g3/input/canon.json"
POLICY = REPO / "docs/sources/source-policy.json"
FREEZE_TAG = "g3-protocol"
FROZEN_PATHS = [
    "src/ca_es/sources/parsers/",
    "docs/sources/source-policy.json",
    "docs/sources/*/semantic-contract.json",
    "src/ca_es/identity/",
    "src/ca_es/revisions.py",
    "src/ca_es/provenance.py",
    "src/ca_es/export.py",
    "src/ca_es/pipeline.py",
    "src/ca_es/canonical.py",
    "src/ca_es/namespaces.py",
]
EXPECTED_FILE_SHA = "c0f7dcd5d330ea69168ef90edcb207b561c237a07c5de216c140ef2147a06f0c"
EXPECTED_LOGICAL_SHA = "722c5f2c3a958ed91344b29a93477bbdffd1e55843300dd58c807db1bb7122e1"
EXPECTED_POLICY_SHA = "5ec0136ab3f4d15e435072ed00a7c0417407c0a6de2ef636d6727a9ac6c5dea3"

MFE = "59303c3c-8be7-578f-bc59-8e5e43a1fdf3"
ALMIRALL = "035e32ca-ba61-5105-8756-e0234e5335fc"
BMEG_DIV = "6881d24a-ef46-5053-80ce-1743a1792f8b"
BMEG_CAP = "3c9270d8-76b3-5953-942c-b1f42c1cc56a"
SAN = "6443e2be-b70d-50c7-88d1-4a62f43789e9"
POEX = "e885fff1-0a3b-57d7-a2fa-f51a6e613f10"
BORME = "03888619-246f-58da-850b-1f715ad1008e"

OUT_DIR = REPO / "g3" / "results" / "commands"


def check_freeze() -> list[str]:
    errors = []
    for args in (["diff", f"{FREEZE_TAG}..HEAD", "--"], ["status", "--porcelain", "--"]):
        out = subprocess.run(
            ["git"] + args + FROZEN_PATHS,
            capture_output=True, text=True, cwd=REPO, check=True,
        ).stdout.strip()
        if out:
            errors.append(args[0])
    return errors


def verify_inputs() -> list[str]:
    errors = []
    if not CANON.exists():
        return ["MISSING_CANON"]
    raw = CANON.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED_FILE_SHA:
        errors.append("CANON_FILE_SHA_MISMATCH")
    payload = json.loads(raw)
    logical = payload.pop("logical_sha256", None)
    if hashlib.sha256(canon_bytes(payload)).hexdigest() != EXPECTED_LOGICAL_SHA or logical != EXPECTED_LOGICAL_SHA:
        errors.append("CANON_LOGICAL_SHA_MISMATCH")
    if hashlib.sha256(POLICY.read_bytes()).hexdigest() != EXPECTED_POLICY_SHA:
        errors.append("POLICY_SHA_MISMATCH")
    return errors


def run_command(name: str, argv: list[str]) -> None:
    cmd = [sys.executable, "-m", "ca_es.cli"] + argv
    for idx in (1, 2):
        proc = subprocess.run(
            cmd, capture_output=True, cwd=REPO, env={**__import__("os").environ, "PYTHONPATH": "src"},
        )
        (OUT_DIR / f"{name}.{idx}.stdout").write_bytes(proc.stdout)
        (OUT_DIR / f"{name}.{idx}.rc").write_text(str(proc.returncode), encoding="utf-8")


def main() -> int:
    errors = check_freeze() + verify_inputs()
    if errors:
        print(f"ERROR: {errors}", file=sys.stderr)
        return 2
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    canon = str(CANON)
    commands = {
        "events": ["events", "--canon", canon],
        "events_isin": ["events", "--canon", canon, "--isin", "ES0105448007"],
        "events_type": ["events", "--canon", canon, "--type", "CASH_DIVIDEND"],
        "events_issuer": ["events", "--canon", canon, "--issuer", "advero"],
        "show_mfe": ["show", "--canon", canon, MFE],
        "show_almirall": ["show", "--canon", canon, ALMIRALL],
        "show_bmeg_div": ["show", "--canon", canon, BMEG_DIV],
        "show_bmeg_cap": ["show", "--canon", canon, BMEG_CAP],
        "show_san": ["show", "--canon", canon, SAN],
        "show_poex": ["show", "--canon", canon, POEX],
        "show_borme": ["show", "--canon", canon, BORME],
        "timeline_mfe": ["timeline", "--canon", canon, MFE],
        "timeline_san": ["timeline", "--canon", canon, SAN],
        "conflicts_almirall": ["conflicts", "--canon", canon, ALMIRALL],
        "conflicts_poex": ["conflicts", "--canon", canon, POEX],
        "export_bmeg_div": ["export", "--canon", canon, BMEG_DIV, "--format", "json"],
        "export_poex": ["export", "--canon", canon, POEX, "--format", "json"],
    }
    # evidence: una assertion por caso representativo
    canon_payload = json.loads(CANON.read_text(encoding="utf-8"))
    for event in canon_payload["events"]:
        if event["facts"]:
            aid = event["facts"][0]["assertion_id"]
            commands[f"evidence_{event['canonical_event_id'][:8]}"] = [
                "evidence", "--canon", canon, aid,
            ]

    for name, argv in sorted(commands.items()):
        run_command(name, argv)
    print(f"{len(commands)} comandos x2 -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
