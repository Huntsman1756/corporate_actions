# AGENTS.md — Corporate Actions ES (ca-es)

Guía para agentes que trabajen en este repositorio.

## Comandos

```bash
python -m venv .venv
```

Python >= 3.11; core stdlib-only. Activar con
`source .venv/bin/activate` (POSIX) o
`.\.venv\Scripts\Activate.ps1` (PowerShell), desde la raíz del checkout.
Extras opcionales: `pdf` (pypdf), `desk` (textual); JVM/Prowide aparte.

```bash
python -m pip install -e ".[dev,tooling]"
python -m pytest --no-private-corpus
ruff check src tests scripts
python -m build

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

# P4.2 MT566 -> CA_ES_SWIFT_CASH_CANDIDATE_V1 (MT566-only)
python -m ca_es.cli swift-cash-candidate --fin <fichero.fin> \
    --canon g3/input/canon.json [--now <iso>]
#   (o --facts); whitelist 19B: PSTA->UNKNOWN / NETO->NET /
#   GRSS->GROSS; solo PROJECTABLE emite movement CA_ES_CASH_MOVEMENTS_V2

# P5.0 deadlines operativos (calendario explicito, nunca por defecto)
python -m ca_es.cli deadlines --canon <canon.json> \
    --rules <CA_ES_DEADLINE_RULES_V1.json> \
    --calendars <CA_ES_CALENDARS_V1.json> [--event <id>] [--now <iso>]

# P5.1 action queue (umbrales obligatorios) + brief V2
python -m ca_es.cli action-queue --deadlines <deadlines.json> \
    --as-of <fecha> --window-days N --due-soon-days N [--now <iso>]
python -m ca_es.cli brief --canon <canon.json> --as-of <fecha> \
    --queue <CA_ES_ACTION_QUEUE_V1.json>   # -> CA_ES_MORNING_BRIEF_V2
python -m ca_es.cli desk --canon <canon.json> --as-of <fecha> \
    --queue <CA_ES_ACTION_QUEUE_V1.json>

# P7 runtime operativo (state store SQLite; scheduler externo)
python -m ca_es.cli ops-init --state <dir>
python -m ca_es.cli ops-run --state <dir> --config <ops.json> \
    --as-of <YYYY-MM-DD>          # exit 0 SUCCEEDED/PARTIAL,
                                  # 2 FAILED/input, 3 writer activo
python -m ca_es.cli ops-run --state <dir> --config <ops.json> \
    --resume <RUN_ID>             # as_of recuperado del run
python -m ca_es.cli ops-inbox --state <dir> [--path <dir>]
python -m ca_es.cli ops-status --state <dir>          # read-only
python -m ca_es.cli ops-latest --state <dir>          # read-only
python -m ca_es.cli ops-export-run --state <dir> --run-id <id> \
    --output <dir> [--include-inputs]
python -m ca_es.cli desk --state <dir> --latest       # requiere
                                  # extra [desk]; ultimo run OK

# P8: el step `securities_events` del DAG procesa facts MT564/MT566
# del inbox (SPLIT/REVERSE_SPLIT, RIGHTS_ISSUE RHDI+EXRI,
# STOCK_DIVIDEND, SCRIP_DIVIDEND, CAPITAL_INCREASE=BONU) ->
# terms/entitlement/impact/security recon/cases por evento.
# Input opcional `elections` en ops config:
#   {"<canonical_event_id>": {"<account_id>": <qty> | "CASH"|"SECU"}}
# — explícito, nunca DFLT; sin elección -> PENDING_ELECTION.

# P5.2 election opportunity (MT564 CAOPTN; --queue requiere --deadline-type)
python -m ca_es.cli swift-election --fin <fichero.fin> \
    --canon g3/input/canon.json \
    [--queue <CA_ES_ACTION_QUEUE_V1.json> --deadline-type <T>] \
    [--now <iso>]

# ISO 20022 / seev (P4.3-P4.8): mismo adapter JVM, modo mxfacts.
# XML crudo solo por stdin; stdout = CA_ES_SWIFT_MX_FACTS_V1.
python -m ca_es.cli mx-facts --mx <fichero.xml>
# seev.031 -> CA_ES_SWIFT_CA_MESSAGE_V1 / binding / election (P4.4)
python -m ca_es.cli mx-project --mx <seev031.xml> [--now <iso>]
python -m ca_es.cli mx-bind --mx <seev031.xml> --canon <canon.json>
python -m ca_es.cli mx-election --mx <seev031.xml> --canon <canon.json>
# seev.033 writer (P4.5): intent + facts + CA_ES_SWIFT_MX_ENVELOPE_V1
python -m ca_es.cli seev033-project --instruction <inst.json> \
    [--mx <seev031.xml> | --fin <mt564.fin> | --facts <facts.json>] \
    --envelope <CA_ES_SWIFT_MX_ENVELOPE_V1.json>
python -m ca_es.cli seev033-write --projection <CA_ES_SEEV033_PROJECTION_V1.json>
# seev.034 status -> CA_ES_ELECTION_INSTRUCTION_STATUS_V1 (P4.6)
python -m ca_es.cli mx-status --mx <seev034.xml> --instruction <inst.json>
# seev.036 -> candidates cash/security (P4.7, mismos contratos P4.2/P6.3)
python -m ca_es.cli mx-cash-candidate --mx <seev036.xml> --canon <canon.json>
python -m ca_es.cli mx-security-candidate --mx <seev036.xml> --canon <canon.json>

# P5.3 election eligibility (positions x options; opportunity bind
# fail-closed al canon via source_canon_logical_sha256)
python -m ca_es.cli election-eligibility \
    --opportunity <CA_ES_ELECTION_OPPORTUNITY_V1.json> \
    --canon g3/input/canon.json \
    --positions p1/smoke/positions.json \
    --rules <CA_ES_ELECTION_ELIGIBILITY_RULES_V1.json> [--now <iso>]

# P5.4 election instruction intent (artefacto interno; no MT565;
# requested == eligible unicamente)
python -m ca_es.cli election-instruction \
    --eligibility <CA_ES_ELECTION_ELIGIBILITY_V1.json> \
    --opportunity <CA_ES_ELECTION_OPPORTUNITY_V1.json> \
    --request <instruction-request.json> [--now <iso>]

# P5.5 MT565: projection en core -> FIN via adapter JVM (ADR-010)
python -m ca_es.cli mt565-project \
    --instruction <CA_ES_ELECTION_INSTRUCTION_V1.json> \
    --envelope <CA_ES_SWIFT_MT565_ENVELOPE_V1.json> \
    (--fin <mt564.fin> | --facts <CA_ES_SWIFT_MT_FACTS_V1.json>) \
    [--now <iso>]                    # -> CA_ES_MT565_PROJECTION_V1
python -m ca_es.cli mt565-write \
    --projection <CA_ES_MT565_PROJECTION_V1.json>
                                     # -> CA_ES_MT565_FIN_V1 (fin+sha)

# P5.6 MT567 status/advice -> binding a instruccion por PREV explícito
python -m ca_es.cli instruction-status \
    (--fin <mt567.fin> | --facts <CA_ES_SWIFT_MT_FACTS_V1.json>) \
    --instruction <CA_ES_ELECTION_INSTRUCTION_V1.json> [--now <iso>]
                                     # -> CA_ES_ELECTION_INSTRUCTION_STATUS_V1

# P6 positions/impact (capacidad auditada en docs/p6/p60-capability.md:
# solo CASH_DIVIDEND SUPPORTED -> CASH_RECEIVABLE; SPLIT UNSUPPORTED V1)
python -m ca_es.cli position-impact --canon <canon.json> \
    --event <id> --positions <CA_ES_POSITIONS_V1.json> \
    --rules <CA_ES_IMPACT_RULES_V1.json> \
    [--entitlements <CA_ES_ENTITLEMENT_V1.json>] [--now <iso>]
                                     # -> CA_ES_POSITION_IMPACT_V1
python -m ca_es.cli project-positions \
    --positions <CA_ES_POSITIONS_V1.json> \
    --impact <CA_ES_POSITION_IMPACT_V1.json> [--now <iso>]
                                     # -> CA_ES_PROJECTED_POSITIONS_V1

# P6.3 MT566 SECMOVE -> candidate (un candidato por SECMOVE; whitelist
# 22H::CRDB CRED->RECEIPT DEBT->DELIVERY; qty solo 36B::PSTA//UNIT)
python -m ca_es.cli swift-security-candidate \
    (--fin <mt566.fin> | --facts <CA_ES_SWIFT_MT_FACTS_V1.json>) \
    --canon <canon.json> [--now <iso>]
                                     # -> CA_ES_SWIFT_SECURITY_MOVEMENT_CANDIDATE_V1
# P6.4 recon valores: expected = doc de impacto, actual = candidates
python -m ca_es.cli security-reconcile \
    --impact <CA_ES_POSITION_IMPACT_V1.json> \
    [--candidates <cand1.json> <cand2.json> ...] [--now <iso>]
                                     # -> CA_ES_SECURITY_RECON_V1
# P6.5: `exceptions` acepta también --recon CA_ES_SECURITY_RECON_V1

# P11 send ledger (MT565/seev.033 -> transport adapter; estados
# PREPARED/SPOOLED/GATEWAY_*/UNKNOWN_OUTCOME/ABANDONED; receipt
# contract receipts/<delivery_id>.(ack|nak).json)
python -m ca_es.cli send-prepare --state <dir> --config <ops.json> \
    --message <CA_ES_MT565_FIN_V1.json> --instruction-id <id>
python -m ca_es.cli send-dispatch --state <dir> --config <ops.json> \
    [--delivery-id <id>]
python -m ca_es.cli send-status --state <dir> [--config <ops.json>]
python -m ca_es.cli send-show --state <dir> --delivery-id <id>
python -m ca_es.cli send-retry --state <dir> --delivery-id <id> \
    [--force-unknown] [--actor <quien>]
python -m ca_es.cli send-abandon --state <dir> --delivery-id <id> \
    [--actor <quien>] [--note "..."]

# P12 transportes reales (adapters `sftp`/`mq` en send config;
# extras opcionales: [sftp]=paramiko, [mq]=ibmmq, ambos lazy —
# faltan -> PARAMIKO_UNAVAILABLE/IBMMQ_UNAVAILABLE fail-closed)
python -m ca_es.cli send-poll --state <dir> --config <ops.json>
    # una pasada: receipts filespool + poll remoto SFTP -> ingest
python -m ca_es.cli send-ingest-fin --state <dir> --fin <svc.fin>
    # service message FIN 21 -> Prowide -> SWIFT_ACKED/NAKED
# lab MQ real opt-in (IBM MQ Developer, licencia IBM del operador):
#   P12_MQ_LIVE=1 LICENSE=accept python scripts/p12_mq_lab.py

# P13 custody input feeds (MT535/semt.002 -> positions;
# MT940/950/camt.053/054 -> cash observation -> binding explicito;
# mapping de cuentas/referencias SOLO via CA_ES_CUSTODY_PROFILE_V1;
# nunca binding por amount/date)
python -m ca_es.cli custody-observe --fin <mt535.fin|mt940.fin>
python -m ca_es.cli custody-observe --mx <semt002.xml|camt05x.xml>
python -m ca_es.cli custody-observe --facts <facts.json>
    # -> CA_ES_POSITION_OBSERVATION_V1 | CA_ES_CASH_ACCOUNT_OBSERVATION_V1
python -m ca_es.cli custody-snapshot --obs <obs.json> [<obs2.json> ...] \
    [--profile <CA_ES_CUSTODY_PROFILE_V1.json>] [--now <iso>]
    # -> CA_ES_POSITION_SNAPSHOT_V1 + positions si COMPLETE
python -m ca_es.cli custody-bind --obs <cash-obs.json> \
    [--refs <reference-map.json>] [--profile <profile.json>] [--now <iso>]
    # -> CA_ES_CASH_BINDING_V1 + CA_ES_CASH_MOVEMENTS_V2 (solo BOUND)
python -m ca_es.cli custody-recon --expected <positions.json> \
    --snapshot <custody-positions-doc.json> [--now <iso>]
    # -> CA_ES_POSITION_RECON_V1 (ambos lados CA_ES_POSITIONS_V1)
python -m ca_es.cli custody-recon --cash --movements <movs.json> \
    --obs <cash-obs.json> [--now <iso>]
    # -> CA_ES_CASH_FEED_RECON_V1
python -m ca_es.cli custody-inbox --state <state-dir> [--path <inbox>]
python -m ca_es.cli custody-build --state <state-dir> [--profile <p.json>]
    # -> CA_ES_CUSTODY_FEED_STATE_V1 (snapshots+movements en artifacts)
python -m ca_es.cli custody-health --state <state-dir> \
    [--required-account <acct>] [--max-age-days N] [--now <iso>]
    # -> CA_ES_CUSTODY_FEED_HEALTH_V1
# e2e demo S1-S7 (requiere fatJar):
#   python scripts/p13_e2e_demo.py <work_dir>
```

Ruff está configurado en `pyproject.toml`; ejecutar
`ruff check src tests scripts`. Estilo PEP 8 + stdlib; no hay formatter
ni typechecker configurados.

Los ejemplos con fixtures son relativos al checkout. Fuera de él,
la CLI instalada requiere inputs propios: para comandos de superficie,
usar `ca-es events --canon <canon.json> --policy <source-policy.json>`.
`--policy` es opcional en el parser, pero su valor por defecto busca
`docs/sources/source-policy.json` en el checkout; el wheel no incluye
esa política ni los corpus. Consultar `ca-es <subcomando> --help` para
los argumentos de cada comando.

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
