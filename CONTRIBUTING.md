# Contribuir a `ca-es`

Cambios pequeños, verificables y trazables; no se declara preparación
para producción. Las [reglas de AGENTS.md](AGENTS.md) son normativas.

## Entorno y verificación

Python >= 3.11; runtime del core stdlib-only. Desde la raíz del checkout:

```text
python -m venv .venv
```

Activa con `source .venv/bin/activate` (POSIX) o
`.\.venv\Scripts\Activate.ps1` (PowerShell). Después:

```text
python -m pip install -e ".[dev,tooling]"
python -m pytest --no-private-corpus
ruff check src tests scripts
python -m build
```

`dev` instala pytest, Ruff y build; `tooling`, jsonschema. `pdf` (pypdf)
y `desk` (textual) son extras opcionales con importación perezosa. El
[adaptador JVM/Prowide](adapters/iso-adapter-jvm) requiere JDK 11+ y un
build Gradle separado; comandos en [AGENTS.md](AGENTS.md).

Estilo PEP 8 + stdlib; Ruff usa la selección de reglas de
[pyproject.toml](pyproject.toml). No hay formatter ni typechecker
configurados. El build Python no construye el adaptador JVM.

La suite pública excluye por defecto los tests `private_corpus`;
`--no-private-corpus` lo explicita. `--run-private-corpus` exige datos
autorizados y no concede permiso para abrir el holdout ni publicar datos.
La CLI instalada y sus inputs explícitos `--canon`/`--policy` se explican
en [README.md](README.md); las fixtures del checkout no vienen en el wheel.

## Flujo de contribución

- Explica el problema, alcance y evidencia del cambio; añade tests junto
  al comportamiento y respeta las convenciones existentes.
- Conserva las reglas de identidad, `Decimal` + `raw_lexeme` + `scale`,
  fechas explícitas, conflictos y adjudicación solo de relaciones.
- Indica comandos ejecutados y resultados, incluidos skips y limitaciones.
  `NOT_RUN` no equivale a `PASS`; un gate requiere evidencia.
- No incluyas secretos, documentos sensibles ni muestras reales sin
  autorización en commits, issues, PRs o logs. Usa reproducciones
  sintéticas mínimas.

## Corpus, holdout y congelación

G1-R se ejecuta por el
[runbook](docs/gates/g1r-execution-runbook.md), nunca ad hoc; el estado
aprobado se registra en `g1r/state.json`. HOLDOUT permanece `SEALED`:
sin inspección manual ni parseo, ni cambios a raw bytes o manifests
hasta `g1r-parser-freeze`. Los gates abortan ante cambios en sus paths.
El opt-in de pytest no sustituye el freeze ni la autorización del runbook.
No reescribir historia, checkpoints ni artefactos congelados; seguir la
secuencia de implementación, evaluación y aprobación del protocolo.
Las salidas regenerables G0 no deben confundirse con evidencia congelada.

## Revisión y publicación

Antes de una release, solicitar revisión del alcance, contratos, cambios
incompatibles y evidencia de tests/lint/build del commit candidato.
Revisar qué entra en sdist/wheel y qué se comparte como repositorio o
artefacto: un build correcto no demuestra permiso de redistribución.

Existe clearance pendiente para corpus sellado/extraído trackeado.
La publicación requiere aprobación explícita del propietario sobre su
alcance y derechos, sin inspeccionar los artefactos sellados. No retirar,
reescribir ni regenerar esa evidencia como parte de una contribución
ordinaria. Véase [SECURITY.md](SECURITY.md).

Esta política no afirma que haya publicaciones en PyPI, releases
automáticas, protecciones de ramas ni checks obligatorios habilitados
en GitHub; no garantiza soporte productivo. La autorización de una
release y su canal de distribución deben acordarse explícitamente.
