# P4.0 — SWIFT MT ingestión read-only via Prowide (subproceso JVM)

Status: **FROZEN — PENDING IMPLEMENTATION**.
Parent: P3.5 cerrado. Frontera fijada por ADR-010.
Probe de entorno: JDK Temurin 17.0.17 (java+javac) OK; Gradle/Maven no
instalados → Gradle Wrapper (no requiere Gradle previo, sólo JDK).

## Arquitectura congelada

```text
ca-es Python
  -> subprocess stdin/stdout JSON
  -> iso-adapter-jvm
  -> Prowide Core
  -> JSON normalizado read-only
```

Alternativas descartadas:

- **HTTP shim**: sólo tendría sentido con ejecución persistente y
  volumen medido; añade lifecycle/puertos/errores de red sin valor.
- **Parser FIN propio en Python**: duplica semántica SWIFT y
  contradice ADR-010; Prowide Core ya parsea FIN con modelos
  específicos por mensaje.
- **`toJson()` de Prowide como contrato externo**: es representación
  propietaria con historial de cambios de serialización. Puede usarse
  internamente si facilita el adapter, pero la salida estable es
  `CA_ES_SWIFT_MT_FACTS_V1`.

## Scope P4.0

- INPUT: SWIFT FIN MT564 o MT566 raw (stdin).
- Sólo ingestión/read-only. Un mensaje por invocación.
- **MT565 OUT** (instrucciones, fase posterior).
- Sin generación SWIFT. Sin modificar canon. Sin HTTP/servicio.
  Sin parser FIN propio.
- stdout = exclusivamente JSON del contrato; diagnósticos a stderr.
- Exit codes deterministas (`OK`, `PARSE_ERROR`,
  `UNSUPPORTED_MESSAGE_TYPE`, `ADAPTER_ERROR`).
- El raw SWIFT nunca termina en logs ni stderr.

## Metadata obligatoria del output (ADR-010 + adapter)

```text
standard_family        ISO15022
standard_release       SRU2025
release_state_as_of    fecha de corte del release
library                prowide-core
library_version        SRU2025-10.3.19
message_identifier     MT564 | MT566
schema_version         CA_ES_SWIFT_MT_FACTS_V1
generated_at           timestamp de la invocación

adapter_version        versión del iso-adapter-jvm
input_sha256           sha256 del FIN raw recibido
parse_status           OK | PARSE_ERROR | UNSUPPORTED_MESSAGE_TYPE
```

## `CA_ES_SWIFT_MT_FACTS_V1`

Cada fact normalizado conserva como mínimo:

```text
message_identifier    MT564 | MT566
field_path            semántico (ca-es)
value
source_tag            tag FIN origen
source_qualifier      cuando aplique
sequence              posición/path dentro del MT
evidence_locator      provenance determinista (tag+seq+offset lógico)
input_sha256
```

## Frontera

```text
FIN -> Prowide parse -> messaging facts + provenance
```

Los facts **no se proyectan al canon en P4.0**. La reconciliación
`messaging facts -> canon` será una decisión posterior separada.

## Dependencia

- `com.prowidesoftware:pw-swift-core:SRU2025-10.3.19` (OSS Apache-2.0,
  Maven Central, Java 11+).
- **Gradle Wrapper** (`gradlew` + `gradle-wrapper.jar`/`properties`
  commiteados): reproducible sin Gradle preinstalado; no vendorizar
  jars manualmente en git.
- **Dependency verification**: `gradle/verification-metadata.xml` con
  checksums SHA-256 fijados; el build falla si un artefacto no coincide.
- `library_version` se reporta en cada output (trazabilidad del
  release Prowide usado).
- JDK requerido: 11+ (probe local: 17.0.17 OK).

## Fixtures / tests preregistrados

- MT564 válido → facts con tag/path/qualifier esperados.
- MT566 válido → idem.
- Mensaje malformado → `PARSE_ERROR`, diagnóstico a stderr, nada de
  raw FIN en stderr/logs.
- Tipo distinto de 564/566 (p.ej. MT103) → `UNSUPPORTED_MESSAGE_TYPE`.
- Tag/qualifier repetido → facts distinguibles por `sequence`.
- Campo opcional ausente → sin fact, sin error.
- Mismo input → mismos facts salvo `generated_at` (determinismo).
- `input_sha256` estable y correcto.
- Cada fact trae `source_tag` + `sequence` (provenance completa).
- Prowide parse → JSON → Python sin pérdida de provenance.

## Fuera de alcance

- MT565, generación SWIFT, proyección a canon, reconciliación
  messaging↔canon, seev.* (ISO 20022), TUI, workflow.
