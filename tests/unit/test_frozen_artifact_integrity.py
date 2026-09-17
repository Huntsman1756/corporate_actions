"""Integridad byte-exacta de artefactos congelados.

Los documentos fuente y la evidencia son "bytes congelados, sha256":
el hash preregistrado en los sidecars ``*.sha256`` y en manifests de
adjudicacion es la autoridad sobre los bytes commiteados. Este test
verifica en el checkout actual que:

- todo sidecar con compañero tracked reproduce su hash grabado;
- todo fichero del manifest de adjudicacion reproduce su hash;
- ``.gitattributes`` mantiene reglas ``-text`` sobre los paths
  byte-pinned (sin -text, un checkout con ``core.autocrlf=true``
  corromperia los bytes y, con ellos, los hashes).

Cuarentena documentada (defecto preexistente al control de EOL):
los sidecars listados en ``KNOWN_STALE_SIDECARS`` registran hashes de
bytes que nunca se commitearon (ninguna variante raw/LF/canonica del
blob reproduce el valor; p.ej. contenido regenerado tras el hash).
No se modifican artefacto ni sidecar para forzar coincidencia: el
test exige que sigan siendo mismatch — si alguien los repara de
forma legitima, debe actualizar la lista en el mismo commit.
``KNOWN_UNVERIFIABLE_SIDECARS`` lista sidecars cuyo compañero no es un
artefacto congelado (ausente del checkout o output regenerable no
trackeado); si su compañero se commitea, pasa a ser verificable y la
cuarentena debe actualizarse.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

PINNED_ROOTS = ("g0", "g1", "g1r", "g1r2", "g2", "g3", "p1")

_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

# sidecar -> compañero tracked cuyo hash grabado NO corresponde a los
# bytes commiteados (ni raw ni LF-normalizado). Registro historico;
# ver docstring del modulo.
KNOWN_STALE_SIDECARS = {
    "g1/results/adversarial-results.sha256": "adversarial-results.json",
    "g1/results/final-run-results.sha256": "final-run-results.json",
    "g1/results/first-run-results.sha256": "first-run-results.json",
    "g1/results/holdout-results.sha256": "holdout-results.json",
    "g1r/results/baseline-c431830-results.sha256": "baseline-c431830-results.json",
    "g1r/results/dev-iter-1-results.sha256": "dev-iter-1-results.json",
    "g1r/results/dev-iter-2-0b557b0-results.sha256": "dev-iter-2-0b557b0-results.json",
    "g1r/results/dev-iter-3-fea0f3e-results.sha256": "dev-iter-3-fea0f3e-results.json",
    "g1r/results/dev-iter-4-bd4cfb3-results.sha256": "dev-iter-4-bd4cfb3-results.json",
    "g1r/results/dev-iter-5-d819f7f-results.sha256": "dev-iter-5-d819f7f-results.json",
    "g1r/results/holdout-run-1-a6a0674-results.sha256": "holdout-run-1-a6a0674-results.json",
    "g1r/results/holdout-run-2-a6a0674-results.sha256": "holdout-run-2-a6a0674-results.json",
    "g1r2/results/iter1-spent-holdout-results.sha256": "iter1-spent-holdout-results.json",
}

# sidecar -> compañero que no es artefacto congelado: ausente del
# checkout o output regenerable no trackeado. No hay bytes commiteados
# contra los que verificar.
KNOWN_UNVERIFIABLE_SIDECARS = {
    "g1/manifests/sampling-frame.sha256": "sampling-frame.items",
    "g1/results/_dbg.sha256": "_dbg.json",
    "g1/results/dev-check.sha256": "dev-check.json",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tracked_files() -> set[str]:
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        # sin git: aproximacion — solo el compañero existente cuenta
        return None
    return set(proc.stdout.split())


def _sidecars():
    return sorted(
        path
        for path in REPO_ROOT.rglob("*.sha256")
        if not any(part.startswith(".") for part in path.parts)
    )


def _parse_sidecar(path: Path) -> list[tuple[str, str | None]]:
    """Devuelve (hexdigest, nombre|None) por linea.

    Formato sha256sum: ``<hex>  <nombre>``. Formato bare: solo ``<hex>``
    (el compañero se infiere como ``<stem>.json``).
    """
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if not _HEX_RE.match(parts[0]):
            raise ValueError(f"linea no parseable en {path}: {line!r}")
        name = parts[1] if len(parts) > 1 else None
        entries.append((parts[0], name))
    return entries


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def test_sidecars_verify_against_committed_bytes():
    tracked = _tracked_files()
    stale_seen: set[str] = set()
    unverifiable_seen: set[str] = set()
    for sidecar in _sidecars():
        rel = _rel(sidecar)
        for expected, name in _parse_sidecar(sidecar):
            companion = sidecar.parent / (name or f"{sidecar.stem}.json")
            companion_rel = _rel(companion)
            is_frozen = companion.is_file() and (
                tracked is None or companion_rel in tracked
            )
            if not is_frozen:
                assert rel in KNOWN_UNVERIFIABLE_SIDECARS, (
                    f"{rel}: compañero no congelado no documentado: "
                    f"{companion_rel}"
                )
                unverifiable_seen.add(rel)
                continue
            assert rel not in KNOWN_UNVERIFIABLE_SIDECARS, (
                f"{rel}: compañero ahora congelado; actualizar "
                "KNOWN_UNVERIFIABLE_SIDECARS"
            )
            actual = _sha256(companion)
            if rel in KNOWN_STALE_SIDECARS:
                assert name == KNOWN_STALE_SIDECARS[rel]
                assert actual != expected, (
                    f"{rel}: el artefacto ahora verifica; actualizar "
                    "KNOWN_STALE_SIDECARS"
                )
                stale_seen.add(rel)
            else:
                assert actual == expected, (
                    f"{rel}: sha256 de {companion.name} no reproduce el "
                    f"hash preregistrado ({actual} != {expected})"
                )
    assert stale_seen == set(KNOWN_STALE_SIDECARS), (
        "sidecars stale no observados: "
        f"{sorted(set(KNOWN_STALE_SIDECARS) - stale_seen)}"
    )
    assert unverifiable_seen == set(KNOWN_UNVERIFIABLE_SIDECARS), (
        "sidecars no verificables no observados: "
        f"{sorted(set(KNOWN_UNVERIFIABLE_SIDECARS) - unverifiable_seen)}"
    )


def test_holdout_adjudication_manifest_verifies():
    manifest = json.loads(
        (REPO_ROOT / "g1r/manifests/holdout-adjudication-sha256.json")
        .read_text(encoding="utf-8")
    )
    for relpath, expected in manifest["files"].items():
        path = REPO_ROOT / relpath
        assert path.is_file(), f"artefacto adjudicado ausente: {relpath}"
        actual = _sha256(path)
        assert actual == expected, (
            f"{relpath}: sha256 no reproduce el hash adjudicado "
            f"({actual} != {expected})"
        )


def test_gitattributes_freezes_pinned_paths():
    rules = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    for root in PINNED_ROOTS:
        assert re.search(rf"^{re.escape(root)}/\*\*\s+-text\s*$", rules, re.M), (
            f".gitattributes: falta regla -text para {root}/**"
        )
    assert re.search(r"^\*\.fin\s+-text\s*$", rules, re.M), (
        ".gitattributes: falta regla -text para *.fin"
    )
