# G1-R execution runbook

Protocolo estable de iteracion G1-R. El repositorio decide que toca;
ninguna failure class se abre por instruccion ad hoc. Estado vivo:
`g1r/state.json`. Driver: `scripts/g1r_next.py`.

## Principios

- Una failure class abierta a la vez (`in_review` maximo 1).
- Reglas genericas del fenomeno documental; prohibido condicionar por
  seed, issuer, URL o hash (dev-failure-catalog, `rule`).
- OSS adaptadores solo proponen evidencia/candidatos; `ca-es` es la
  unica autoridad de promocion canonica (ADR-016, ADR-017).
- Ante span/roto no reconstruible con evidencia suficiente: ABSTAIN.
- Precision primero: una regla nueva no amplia recall si puede emitir
  un hecho falso.

## Secuencia

`g1r_next.py status` informa el estado; `next` selecciona la primera
clase de `queue`. Orden preregistrado (P0 primero):

```text
FALSE_FINANCIAL_SEMANTIC_ANCHOR   resolved (dev-iter-1, aprobado)
DECIMAL_SPLIT_PDF                 in_review (dev-iter-2)
EVENT_TYPE_FAMILY_BOUNDARY        queue
DATE_MISBINDING                   queue
FALSE_POSITIVE_EVENT              queue
<P1/P2 backlog>                   tras los P0
parser freeze -> HOLDOUT virgin
```

## Ciclo por clase

1. `python scripts/g1r_next.py begin` — abre siempre `queue[0]` y la
   mueve a `in_review`. Sin seleccion: el repo decide que toca.
2. Inspeccionar la evidencia (spans extraidos, anchors, texto). Disenar
   la regla generica; abstencion si el canal no es reconstruible.
3. Implementar en `src/` + tests junto al comportamiento.
4. Commit de implementacion (arbol limpio: el runner lo exige).
5. `python scripts/run_g1r.py --set development --phase dev-iter-N`
   — regenera `<phase>-<parser_commit>-results.json`.
6. `python scripts/g1r_next.py gates --phase dev-iter-N`
   — ejecuta pytest + regression oracle (congela
   `<phase>-g1-oracle-eval.json`) + DEV oracle (regenera
   `<phase>-dev-oracle-eval.json` ligado al parser actual) + chequeo
   HOLDOUT (working tree + `git diff freeze_ref..HEAD` + sha256 de raw
   vs manifest) + targets de la clase activa.
7. Actualizar `g1r/results/g1r-changes.jsonl` (generic_rule, root cause,
   tests, commits, evals, artefactos) y `g1r/state.json`.
8. Commit de artefactos + push. El checkpoint queda en `in_review`
   hasta firma externa; solo entonces la clase pasa a `resolved`.

## Stop conditions (bloquean el checkpoint)

- Cualquier FAIL nuevo en el regression oracle fuera de
  `g1_oracle.known_open_failures` (los targets de la clase activa ya
  no son "conocidos": deben pasar, no seguir fallando).
- `targets.<clase_activa>` no resueltos: cada target DEV debe ser
  `P0_CORRECTED`/`P0_SAFE_ABSTENTION`/`CORRECTED` y cada target G1REG
  debe pasar el check del oracle. Una clase no se resuelve por
  ausencia de errores nuevos sino por targets demostrados.
- `REGRESSED`, `EMITTED_OTHER` o `NOW_ABSENT` > 0 en el DEV oracle;
  `P0_UNRESOLVED` en los targets activos; `P0_CHANGED_OTHER` en
  cualquier fila.
- HOLDOUT: `git status` o `git diff freeze_ref..HEAD` toca
  `sealed_git_paths`, o el sha256 de un raw difiere de su manifest.
- Fallo no preregistrado en `dev-failure-catalog.json`.
- La regla necesita excepciones por seed/issuer/documento.

## Fail-closed del driver

- Los evaluadores borran su artefacto previo antes de ejecutarse y el
  gate exige artefacto nuevo; un JSON viejo nunca satisface el gate.
- Todo subprocess/git con rc inesperado es `STOP` (nunca "sin
  diferencias" por fallo). G1 eval admite rc 0/1 (1 = FAILs del
  oracle, que los targets deciden); DEV eval exige rc 0.
- El results artifact debe estar ligado a HEAD: unico
  `<phase>-<commit>-results.json`, `parser_commit_dirty=false`,
  sha256 valido, y `git diff parser_commit..HEAD` vacio sobre los
  inputs de la corrida (`src/`, `g1r/manifests`, `g1r/corpus`,
  `g0/corpus/reference`, `run_g1r.py`, `fetch_cnmv.py`). Cualquier
  cambio en esos paths invalida el artefacto: hay que re-correr.
- Un target ausente del reporte es `STOP: target missing`, no un
  `KeyError` ni un PASS.

## Artefactos por iteracion (congelados, con valores reales)

```text
g1r/results/<phase>-<parser_commit>-results.json   (+ .sha256)
g1r/results/<phase>-dev-oracle-eval.json           (valores por claim)
g1r/results/<phase>-g1-oracle-eval.json            (filas OK/FAIL)
g1r/results/g1r-changes.jsonl                       (entrada iter-N)
```

`parser_commit` en el nombre = commit del parser que genero la
corrida; el baseline `c431830` solo aplica a la fase `baseline`.

## HOLDOUT

`SEALED`: sin inspeccion manual, sin parseo, sin modificacion de raw
bytes ni manifests hasta `g1r-parser-freeze`. `g1r_next.py gates`
aborta si git reporta cambios en esos paths.
