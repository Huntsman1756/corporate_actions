# Corporate Actions ES (`ca-es`)

Capa abierta, verificable, versionada y evidence-first de corporate
actions para valores vinculados al ecosistema español de negociación y
post-trade.

> No es un scraper de CNMV, ni un clon de BME, ni un calendario de
> dividendos, ni un security master. El evento pertenece al instrumento
> y a la operación societaria, no a una fuente concreta.

> Proyecto en desarrollo, sin declaración de preparación para producción.
> La instalación y los comandos siguientes describen el uso actual;
> la evidencia G0/G0-R se conserva aparte como historia, no como resultado
> de la suite o de los gates actuales.

## Arquitectura

```
SOURCE DOCUMENTS (bytes congelados, sha256)
      │
      ▼
parsers          doc → claims observados (sin decidir verdad)
      │
      ▼
assertions       hechos atómicos con evidence_locator + raw_pointer
      │
      ├──────────────► identity ledger (candidate IDs UUIDv5,
      │                 relaciones, alias, canonical append-only)
      ▼
revisions        supersession explícita (Almirall 55→65)
      │
      ▼
facts            SOURCE_ASSERTION | DETERMINISTIC_DERIVATION |
      │           REFERENCE_ENRICHMENT, con conflictos explícitos
      ▼
reference        ListingResolver (ESMA/FIRDS) point-in-time, segment MIC
```

`src/ca_es/canonical.py` fija `CA_ES_CANONICAL_JSON_V1` (sin floats, sin
claves duplicadas, rechaza NaN/Infinity). Todo hash deriva de ahí.

## Garantías

- Identidad canónica determinista dados raw inputs, config, identity
  ledger y adjudication ledger.
- `candidate_event_id = UUIDv5(ns, source_id + ":" + official_document_id)`.
- Cero merges fuzzy; ante duda, candidatos separados.
- Importes/ratios en `Decimal` con lexema raw y escala publicada.
- Semántica temporal source-scoped sin orden global de fechas.
- Iberclear `REFERENCE_ONLY` (`PUBLIC_INGEST_INTERFACE_NOT_PROVEN`).
- ISO 15022/20022 fuera del core (ADR-010, `adapters/iso-adapter-jvm`
  /Prowide).

## Instalación

Requisito: Python **>= 3.11**. El núcleo `ca_es` es **stdlib-only**
(sin dependencias en runtime); hay extras opcionales:

- `pdf`: `pypdf`, solo para ingerir documentos PDF reales (importación
  perezosa; el core sigue stdlib-only).
- `desk`: `textual`, para la TUI operacional del desk (P1.2).
- `dev`: pytest, build y ruff (desarrollo).
- `tooling`: jsonschema (validación de contratos en tooling/CI).
- Adaptador JVM aparte (`adapters/iso-adapter-jvm`, requiere JDK 11+;
  ver AGENTS.md para el build Gradle del fatJar).

Desde la raíz del checkout, crea el entorno:

```text
python -m venv .venv
```

Actívalo con `source .venv/bin/activate` (POSIX) o
`.\.venv\Scripts\Activate.ps1` (PowerShell). Después:

```text
python -m pip install -e ".[dev,tooling]"
```

Para funciones opcionales, instala `".[pdf]"` o `".[desk]"` en ese
mismo entorno. El adaptador JVM no es un extra de pip.

## Verificar desde el checkout

Con el entorno activado: tests offline sin corpus privado, lint con
Ruff y construcción de sdist/wheel, respectivamente:

```text
python -m pytest --no-private-corpus
ruff check src tests scripts
python -m build
```

`pytest` sin flags ya excluye el corpus privado por defecto;
`--no-private-corpus` lo hace explícito. Las marcas
`private_corpus` requieren `--run-private-corpus` y datos
autorizados `LOCAL_ONLY`.

## CLI instalada y fixtures del repositorio

`ca-es` y `python -m ca_es.cli` exponen la misma CLI. Para trabajar
fuera del checkout, proporciona tus propios inputs autorizados y rutas
explícitas. Ejemplos (sustituye los marcadores `<...>`):

```text
ca-es events --canon <canon.json> --policy <source-policy.json>
ca-es brief --canon <canon.json> --policy <source-policy.json> --as-of 2026-07-15
ca-es entitlement --canon <canon.json> --policy <source-policy.json> --event <id> --positions <posiciones.json>
```

En estos comandos `--canon` es obligatorio; `--policy` es opcional en
el parser, pero su valor por defecto busca
[docs/sources/source-policy.json](docs/sources/source-policy.json) en
el checkout. Pásalo explícitamente al usar la CLI instalada fuera de
él. No todos los subcomandos consumen un canon ni aceptan una política:
consulta `ca-es <subcomando> --help`.

El wheel contiene el paquete `ca_es`, no los corpus, fixtures, políticas ni el
adaptador JVM del repositorio. Los comandos `run`, `gates`, `metrics`,
`event` e `isin` dependen del checkout; no son una ingesta genérica de
ficheros arbitrarios. Desde la raíz del repo:

```text
python -m ca_es.cli run --firds-listings g0/corpus/reference/esma-firds-listings.json
python -m ca_es.cli gates --second-run --firds-listings g0/corpus/reference/esma-firds-listings.json
python -m ca_es.cli metrics --firds-listings g0/corpus/reference/esma-firds-listings.json
```

Las salidas G0 se regeneran en `g0/results/`; no son evidencia nueva
hasta ejecutar y evaluar el pipeline. No sobrescribir evidencia congelada.
La referencia operativa está en [AGENTS.md](AGENTS.md) y la ayuda de
subcomandos en `python -m ca_es.cli --help`.

## Canarios G0 (histórico)

| Canario | Prueba |
|---------|--------|
| Almirall 2026 | misma CA, dos revisiones, ratio 55→65, supersession (retirado tras evidencia real, ver abajo) |
| Parlem BORME-C-2026-4914 | rights issue, Iberclear ISSUER_CSD, entitlement basis temporal |
| P3 Spain SOCIMI | record<ex, payment=ex, Euroclear France, escala 8 |
| SAN (CNMV vs IR) | conflicto explícito, ambas fuentes conservadas |

La evidencia G0 distingue fixtures sintéticos y corpus real `LOCAL_ONLY`
([ADR-011](docs/decisions/ADR-011-raw-source-redistribution-policy.md)).
Esto no acredita la redistribución de todo el checkout: hay corpus
sellado/extraído trackeado cuya publicación requiere autorización
explícita del propietario. No inspeccionarlo para resolver ese permiso;
ver [SECURITY.md](SECURITY.md).

## Evidencia histórica (por fase)

Estos resultados pertenecen a sus informes históricos, no a una
verificación actual de la suite ni de los gates:

- El [informe G0](docs/G0-FINAL-REPORT.md), fechado 2026-09-13,
  registra 53 tests y gates G0 55 PASS / 0 FAIL / 0 INCONCLUSIVE.
  `CNMV_CHANNEL_COVERAGE_P3` quedó resuelto como `NOT_PROVEN`: no
  acredita cobertura positiva del canal.
- G0-R2 (histórico): MFE-MEDIAFOREUROPE `40280 → 40319` revisión
  explícita real; Santander división complementaria reconciliación
  CNMV + IR; P3 Spain SOCIMI con documento Portfolio real (record<ex,
  payment=ex, 0,11840672 EUR, Euroclear France); Parlem BORME real y
  ESMA/FIRDS real (173 listings point-in-time).
- G0-R3 (histórico, cerrado): `EVENTO → INSTRUMENTO → FIRDS` exacto
  (P3: `PORTFOLIO-4733 → ES0105282000 → LEI + segment MIC POSE`), sin
  matching por nombre (ADR-013). El canario sintético Almirall 2026
  queda `RETIRED / INVALIDATED_BY_REAL_EVIDENCE`.

Para el checkpoint aprobado G1-R, consultar `g1r/state.json` siguiendo
el [runbook](docs/gates/g1r-execution-runbook.md), no instrucciones ad hoc.
La preregistración permanece en
[alcance G1](docs/gates/g1-scope.md) y
[protocolo G1](docs/gates/g1-preregistered.json).
HOLDOUT `SEALED`: sin inspección ni parseo hasta parser freeze;
no alterar manifests, bytes ni evidencia congelada.

Referencias: [informe G0](docs/G0-FINAL-REPORT.md),
[validación real G0-R](docs/G0R-FINDINGS.md),
[decisiones](docs/decisions/), [gates](docs/gates/) y
[fuentes](docs/sources/).

## Contribuir

Ver [CONTRIBUTING.md](CONTRIBUTING.md). Reportes de seguridad:
[SECURITY.md](SECURITY.md).
