"""P4.0 — thin adapter Python -> iso-adapter-jvm (Prowide).

Invoca el adapter JVM como subproceso: FIN raw por stdin, doc
CA_ES_SWIFT_MT_FACTS_V1 por stdout. El core sigue stdlib-only; la
dependencia JVM/Prowide vive fuera (ADR-010, docs/p4/p40-scope.md).

El FIN raw viaja SOLO por stdin del subproceso: nunca por argv,
nunca a logs. stdout del adapter es exclusivamente JSON del contrato;
stderr del adapter son diagnosticos sin contenido FIN.

parse_status textual (dentro del doc) != exit code numerico:
0 OK / 2 PARSE_ERROR / 3 UNSUPPORTED_MESSAGE_TYPE / 4 ADAPTER_ERROR.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

FACTS_SCHEMA = "CA_ES_SWIFT_MT_FACTS_V1"

EXIT_OK = 0
EXIT_PARSE_ERROR = 2
EXIT_UNSUPPORTED = 3
EXIT_ADAPTER_ERROR = 4


class AdapterUnavailable(RuntimeError):
    """El jar del adapter o java no estan disponibles."""


def default_adapter_jar() -> Path:
    env = os.environ.get("CA_ES_SWIFT_ADAPTER_JAR")
    if env:
        return Path(env)
    root = Path(__file__).resolve().parents[2]
    return (
        root / "adapters" / "iso-adapter-jvm" / "build" / "libs"
        / "iso-adapter.jar"
    )


def parse_mt(fin: str, jar: Path | None = None,
             timeout: int = 120) -> tuple[dict, int]:
    """FIN raw -> (doc CA_ES_SWIFT_MT_FACTS_V1, exit_code).

    No reinterpreta el doc: lo devuelve tal cual lo emite el adapter.
    """
    jar = jar or default_adapter_jar()
    if not jar.is_file():
        raise AdapterUnavailable(f"adapter jar no encontrado: {jar}")
    try:
        proc = subprocess.run(
            ["java", "-jar", str(jar)],
            input=fin.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise AdapterUnavailable("java no esta en PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise AdapterUnavailable(f"adapter timeout ({timeout}s)") from exc
    try:
        doc = json.loads(proc.stdout.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AdapterUnavailable(
            f"stdout del adapter no es JSON del contrato: {exc}"
        ) from exc
    return doc, proc.returncode
