# P7.5 — Operational health (CA_ES_OPERATIONAL_HEALTH_V1)

Responde si el RUNTIME tiene inputs suficientes y actuales para
operar. Nunca afirma completitud de mercado ni resuelve
indeterminacion de negocio: un mismatch de importes puede
coexistir con health=HEALTHY; problemas de negocio != problemas
de runtime.

## Contrato

```
schema: CA_ES_OPERATIONAL_HEALTH_V1
generated_at
status: HEALTHY|DEGRADED|FAILED
checks: [{name, status: OK|DEGRADED|FAILED|INFO, detail}]
```

Overall = el peor check no-INFO. Reglas deterministas, umbrales
solo desde `config.health` (sin defaults con significado).

## Checks V1

| check | regla |
|---|---|
| last_successful_run | no existe ningun run SUCCEEDED -> DEGRADED; si existe -> OK con run_id/edad |
| required_inputs | canon/deadline_rules/calendars ausentes -> FAILED (sin canon no hay runtime) |
| positions_available | input positions ausente -> DEGRADED (rama opcional no puede operar) |
| positions_freshness | positions.as_of mas viejo que health.positions_max_age_days -> DEGRADED; sin umbral configurado -> INFO |
| inbox_failures | mensajes FAILED en el ultimo scan -> DEGRADED |
| stale_running_steps | pasos RUNNING de runs no activos -> DEGRADED (restos de crash) |
| artifact_integrity | artefacto del ultimo run SUCCEEDED inaccesible/corrupto -> FAILED |
| indeterminate_deadlines | count de deadlines INDETERMINATE -> INFO (estado de negocio, nunca degrada) |
| pending_alerts | count outbox PENDING_DELIVERY -> INFO |

`stale_running_steps`: un step RUNNING cuyo run no es el actual
(crash previo) — detectable; nunca se asume exito.

## Paso DAG

`health_report` (impuro en sentido estricto — lee estado mutable
— pero obligatorio): corre tras `alert_outbox` para observar
pending alerts. Siempre se ejecuta; su output es el artefacto
`CA_ES_OPERATIONAL_HEALTH_V1` del run.
