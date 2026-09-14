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

1. `python scripts/g1r_next.py begin --class <NAME>` — mueve la clase
   de `queue` a `in_review`.
2. Inspeccionar la evidencia (spans extraidos, anchors, texto). Disenar
   la regla generica; abstencion si el canal no es reconstruible.
3. Implementar en `src/` + tests junto al comportamiento.
4. Commit de implementacion (arbol limpio: el runner lo exige).
5. `python scripts/run_g1r.py --set development --phase dev-iter-N`
   — regenera `<phase>-<parser_commit>-results.json`.
6. `python scripts/_eval_dev_oracle.py --phase dev-iter-N
   --out g1r/results/<phase>-dev-oracle-eval.json`.
7. `python scripts/g1r_next.py gates --phase dev-iter-N`
   — ejecuta pytest + regression oracle (congela
   `<phase>-g1-oracle-eval.json`) + chequeo HOLDOUT + DEV oracle.
8. Actualizar `g1r/results/g1r-changes.jsonl` (generic_rule, root cause,
   tests, commits, evals, artefactos) y `g1r/state.json`.
9. Commit de artefactos + push. El checkpoint queda en `in_review`
   hasta firma externa; solo entonces la clase pasa a `resolved`.

## Stop conditions (bloquean el checkpoint)

- Cualquier FAIL nuevo en el regression oracle fuera de
  `g1_oracle.known_open_failures`.
- `REGRESSED` o `EMITTED_OTHER` > 0 en el DEV oracle.
- `git status` toca `holdout.paths` (raw/manifests G1-R y G1).
- Fallo no preregistrado en `dev-failure-catalog.json`.
- La regla necesita excepciones por seed/issuer/documento.

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
