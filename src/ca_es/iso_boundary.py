"""Limite de proyeccion ISO (ISO 15022 / ISO 20022).

G0 NO implementa generacion ISO. La arquitectura queda congelada:

    ca-es core (Python)
        │  canonical JSON
        ▼
    iso-adapter-jvm (Java / Prowide)
        ├── MT564 / MT565 / MT566
        └── seev.*

Este modulo solo declara el contrato y valida que toda proyeccion futura
porte la metadata obligatoria de release. No genera mensajes.

Por que Prowide: cubre ISO 15022/20022 con release pinning, mantenimiento
activo y estrategia de salida clara (JVM aislada, sin acoplarse al core).
"""
from __future__ import annotations

REQUIRED_PROJECTION_METADATA = (
    "standard_family",
    "standard_release",
    "release_state_as_of",
    "library",
    "library_version",
    "message_identifier",
    "schema_version",
    "generated_at",
)

ISO_ADAPTER_BOUNDARY = {
    "boundary_version": "CA_ES_ISO_BOUNDARY_V1",
    "core_language": "Python",
    "adapter_language": "Java",
    "adapter_location": "iso-adapter-jvm (fuera del core)",
    "implementation": {
        "vendor": "Prowide",
        "artifact": "pw-swift-core",
        "version": "UNPINNED",
        "release_pinning": "REQUIRED_AT_PROJECTION_TIME",
    },
    "core_generates_iso": False,
    "release_state_as_of_required": True,
}


def validate_projection_metadata(metadata: dict) -> list[str]:
    """Devuelve los campos obligatorios ausentes (vacio = valido)."""
    return [field for field in REQUIRED_PROJECTION_METADATA if not metadata.get(field)]


def projection_enabled_in_core() -> bool:
    return bool(ISO_ADAPTER_BOUNDARY["core_generates_iso"])
