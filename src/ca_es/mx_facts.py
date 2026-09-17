"""P4.3 — thin adapter Python -> iso-adapter-jvm (Prowide ISO 20022).

Invoca el adapter JVM en modo ``mxfacts``: XML raw por stdin, doc
CA_ES_SWIFT_MX_FACTS_V1 por stdout. Mismo boundary que swift_mt:
el XML crudo viaja solo por stdin; stdout es exclusivamente el JSON
del contrato; stderr son diagnosticos sin contenido del mensaje.

PARSE_OK significa unicamente parsing — nunca validacion de
schema/red/SWIFT.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .swift_mt import AdapterUnavailable, default_adapter_jar

FACTS_SCHEMA = "CA_ES_SWIFT_MX_FACTS_V1"


def parse_mx(xml: str | bytes, jar: Path | None = None,
             timeout: int = 120) -> tuple[dict, int]:
    """XML raw -> (doc CA_ES_SWIFT_MX_FACTS_V1, exit_code).

    No reinterpreta el doc: lo devuelve tal cual lo emite el adapter.
    """
    jar = jar or default_adapter_jar()
    if not jar.is_file():
        raise AdapterUnavailable(f"adapter jar no encontrado: {jar}")
    raw = xml.encode("utf-8") if isinstance(xml, str) else xml
    try:
        proc = subprocess.run(
            ["java", "-jar", str(jar), "mxfacts"],
            input=raw,
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
