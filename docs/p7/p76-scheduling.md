# P7.6 — Scheduling adapters

El scheduler esta FUERA de la semantica del core: solo invoca
`ca-es ops-run` sobre un state store. Sin daemon, sin framework
de scheduling, sin dependencias.

## Concurrencia

Un solo writer por state store. El scheduler puede solapar
ejecuciones (timer anterior lento); el segundo writer falla
rapido con `OPS_RUN_ALREADY_ACTIVE` (exit 3). Eso es correcto:
la siguiente invocacion programada lo reintentara. Nunca se
espera ni se serializa por cola externa.

## Adapters entregados

| adapter | fichero |
|---|---|
| systemd | `deploy/systemd/ca-es-ops.service` + `ca-es-ops.timer` |
| cron | `deploy/cron/ca-es-ops.cron` |
| Windows Task Scheduler | `deploy/windows/Register-CaEsOpsTask.ps1` |
| GitHub Actions | `.github/workflows/ops-run-example.yml` (manual/sintetico) |

Todos invocan la misma secuencia:

```bash
ca-es ops-run --state <state> --config <ops.json> --as-of <fecha>
ca-es ops-status --state <state>
```

Exit codes: 0 SUCCEEDED|PARTIAL · 2 FAILED/invalid ·
3 OPS_RUN_ALREADY_ACTIVE. El scheduler solo programa; el estado
del run queda en el manifest/ops-status.

## GitHub Actions

Solo con datos sinteticos. NUNCA subir `<state>` como artifact
(posiciones/cuentas/SWIFT). El workflow de ejemplo usa
`workflow_dispatch` y fixtures del repo.
