# ADR-010 — ISO adapter boundary / Prowide JVM

Status: ACCEPTED (G0 freeze, 2026-09-13)

## Context

La generación ISO 15022/20022 (MT564/565/566, `seev.*`) queda fuera del
alcance de G0, pero el límite debe congelarse ahora.

## Decision

```
ca-es core (Python)
    │  canonical JSON
    ▼
iso-adapter-jvm (Java / Prowide)
    ├── MT564 / MT565 / MT566
    └── seev.*
```

- El core **no** genera ISO (`core_generates_iso = False`).
- Prowide es la implementación prevista (`pw-swift-core`), fuera del core.
- Toda proyección futura exigirá metadata obligatoria:
  `standard_family`, `standard_release`, `release_state_as_of`,
  `library`, `library_version`, `message_identifier`, `schema_version`,
  `generated_at`.
- G0 no fija `SRU2026` como runtime; los estándares 2026 siguen
  evolucionando.

Gates: `ISO_ADAPTER_OUTSIDE_CORE`, `ISO_PROJECTION_BOUNDARY_FROZEN`,
`ISO_RELEASE_METADATA_REQUIRED`, `RELEASE_STATE_AS_OF_REQUIRED`.
