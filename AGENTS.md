# AGENTS.md — Corporate Actions ES (ca-es)

Guía para agentes que trabajen en este repositorio.

## Comandos

```bash
# entorno (stdlib-only en runtime)
export PYTHONPATH=src        # Windows: $env:PYTHONPATH='src'

# tests (offline, sin red, sin credenciales)
python -m pytest

# pipeline canario con enriquecimiento FIRDS
python -m ca_es.cli run --firds-listings g0/corpus/reference/esma-firds-listings.json
python -m ca_es.cli gates --second-run --firds-listings g0/corpus/reference/esma-firds-listings.json
python -m ca_es.cli metrics --firds-listings g0/corpus/reference/esma-firds-listings.json
python -m ca_es.cli event <event-id>
python -m ca_es.cli isin <isin>

# superficie operacional (G3/P1): consumen un canon ya generado
python -m ca_es.cli events|show|timeline|conflicts|evidence|export \
    --canon g3/input/canon.json ...
python -m ca_es.cli brief --canon g3/input/canon.json --as-of 2026-07-15 \
    [--previous-canon p1/smoke/previous-canon.json] [--format text|json]
python -m ca_es.cli desk --canon g3/input/canon.json --as-of 2026-07-15
    # requiere extra [desk] (textual); read-only sobre brief()

# P2.0 entitlements (posiciones = input separado CA_ES_POSITIONS_V1)
python -m ca_es.cli entitlement --canon g3/input/canon.json \
    --event <canonical_event_id> --positions p1/smoke/positions.json

# P3 reconciliación cash (CA_ES_CASH_MOVEMENTS_V2 con amount_basis
# GROSS/NET/UNKNOWN; V1 aceptado, basis ausente = UNKNOWN y nunca
# se asume bruto; --entitlements acepta un doc CA_ES_ENTITLEMENT_V1
# ya calculado, sin canon)
python -m ca_es.cli reconcile --canon g3/input/canon.json \
    --event <canonical_event_id> --positions p1/smoke/positions.json \
    --cash p1/smoke/cash-movements.json

# P3.5 casos de excepción (CA_ES_EXCEPTION_CASES_V1; consume el recon
# sin reinterpretarlo; --cases mergea con el store previo)
python -m ca_es.cli exceptions --recon recon.json --now <iso> \
    [--cases prev-cases.json]
python -m ca_es.cli case-transition --cases cases.json \
    --case-key <key> --to IN_REVIEW --actor <quien> --now <iso> \
    [--resolution-code CORRECTED] [--note "..."] [--out cases.json]

# P4.0 ingestión SWIFT MT564/MT566 read-only (subproceso JVM/Prowide)
# build del adapter (requiere JDK 11+; dependencias fijadas con
# verification-metadata sha256):
cd adapters/iso-adapter-jvm && ./gradlew build fatJar
# uso (FIN raw -> CA_ES_SWIFT_MT_FACTS_V1 por stdout):
python -m ca_es.cli swift-facts --fin <fichero.fin>
# exit codes: 0 OK / 2 PARSE_ERROR / 3 UNSUPPORTED_MESSAGE_TYPE /
# 4 ADAPTER_ERROR; CA_ES_SWIFT_ADAPTER_JAR sobreescribe la ruta del jar

# P4.1 proyección semántica + binding a canon (read-only, canon intacto)
python -m ca_es.cli swift-project --fin <fichero.fin> [--now <iso>]
python -m ca_es.cli swift-bind --fin <fichero.fin> --canon g3/input/canon.json
#   (o --facts <doc CA_ES_SWIFT_MT_FACTS_V1>)
```

No hay linter/formatter configurado; el estilo es PEP 8 + stdlib.

## Reglas no negociables

1. No usar `float` para valores financieros canónicos: `Decimal` +
   `raw_lexeme` + `scale` (`ca_es.numeric`).
2. No fusionar identidades sin evidencia determinista o adjudicación
   registrada. Ante la duda: candidatos separados.
3. No derivar `event_id`/`candidate_event_id` de fecha, importe, ratio,
   ticker o nombre.
4. No inferir fechas: `EXPLICIT`, `DERIVED_BY_DEFINITION` o `UNKNOWN`.
   Sin orden global de fechas.
5. No sobrescribir fuentes en silencio: usar `CONFLICTING` + `Conflict`.
6. La adjudicación humana solo escribe **relaciones**, nunca facts.
7. Iberclear es `REFERENCE_ONLY` (`PUBLIC_INGEST_INTERFACE_NOT_PROVEN`).
8. FIRDS pertenece a la capa ESMA externa; ca-es solo define el contrato
   `ListingResolver`.
9. La génération ISO queda fuera del core (ADR-010).
10. No añadir funcionalidad fuera de G0.

## Flujo de cambio

- Cambios pequeños, verificables y trazables; tests junto al
  comportamiento.
- Un gate solo pasa si hay evidencia; `NOT_RUN` ≠ `PASS`.
- No reescribir historia ni artefactos congelados.

## G1-R

G1-R se ejecuta por runbook, nunca por prompt ad hoc:

- Protocolo: `docs/gates/g1r-execution-runbook.md`.
- Estado: `g1r/state.json` (checkpoint aprobado, clases
  resolved/in_review/queue, HOLDOUT=SEALED).
- Driver: `python scripts/g1r_next.py status|next|begin|gates`.
- HOLDOUT: sin inspeccion ni parseo hasta parser freeze; los gates
  abortan si git reporta cambios en sus paths.

## Estructura

```
src/ca_es/        núcleo (canonical, numeric, identity, assertions,
                  provenance, revisions, temporal, entitlement,
                  reference, sources, pipeline, metrics, gates, cli)
schemas/          contratos JSON de artefactos
tests/            unit / integration / canaries
docs/             architecture / decisions (ADR) / gates / sources
g0/               corpus (synthetic) / manifests / results (regenerables)
```
