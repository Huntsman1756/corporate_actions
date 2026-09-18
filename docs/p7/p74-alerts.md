# P7.4 — Alert outbox (CA_ES_ALERT_OUTBOX_V1)

Sin envio directo (ni email/Slack/webhook) desde el core: el
outbox es la unica frontera de efectos externos; un conector
futuro consumiria `delivery_state=PENDING_DELIVERY`.

## Modelo

```
alert_key = category | subject_key        (PK, estable)

category          taxonomia operativa preregistered
subject_type      deadline|exception_case|inbox_message|run
subject_key       deadline_key|case_key|input_sha256|run_id
state             OPEN|CLEARED              (ciclo de negocio)
delivery_state    PENDING_DELIVERY|DELIVERED|FAILED_DELIVERY
first_observed_run_id / last_observed_run_id
payload           snapshot determinista del hecho observado
evidence_refs     refs a artefactos que lo evidencian
semantic_sha256   hash del payload (cambio de hechos)
```

`state` (ciclo de vida de la alerta) y `delivery_state` (ciclo de
entrega) son ejes independientes: una alerta puede CLEARse con la
entrega pendiente y viceversa.

## Categorias preregistered (V1)

| category | sujeto | condicion (derivada de artefactos P1-P6) |
|---|---|---|
| DEADLINE_OVERDUE | deadline_key | item action_status=OVERDUE en la queue |
| DEADLINE_DUE_TODAY | deadline_key | item action_status=DUE_TODAY |
| DEADLINE_DUE_SOON | deadline_key | item action_status=DUE_SOON |
| EXCEPTION_CASE | case_key | workflow_status=OPEN en cases doc |
| PROCESSING_FAILURE | input_sha256 | mensaje inbox con status FAILED |
| RUN_FAILED | run_id | run termina FAILED |

Sin "severidad" subjetiva: la categoria es la severidad. Un cambio
de DUE_SOON a OVERDUE genera alerta nueva (subject igual,
categoria distinta -> alert_key distinto); la anterior se CLEARa.

Para EXCEPTION_CASE la categoria registrada en `payload` incluye
el `last_action` del case history (CREATED/REOPENED/
FACT_UPDATED); la identidad de alerta no cambia con el hecho —
cambio de facts = mismo alert_key, payload actualizado y
delivery re-armado (notificacion nueva sin spam de identidades).

## Dedup y ciclo de vida

Por cada run (al final, con los outputs ya persistidos):

1. Derivar candidatos desde queue / cases / inbox / run status.
2. `alert_key` ausente -> INSERT state=OPEN,
   delivery=PENDING_DELIVERY, first=last=run_id.
3. `alert_key` OPEN, mismo semantic_sha256 -> solo
   last_observed_run_id + updated_at. **Segundo run identico no
   rearma delivery**: un conector que ya entrego no re-notifica.
4. `alert_key` OPEN, semantic_sha256 distinto -> payload
   actualizado + delivery=PENDING_DELIVERY (hechos nuevos).
5. `alert_key` CLEARED -> re-OPEN: state=OPEN,
   delivery=PENDING_DELIVERY, first_observed conservado.
6. Clear: alertas OPEN cuya categoria fue evaluada este run y no
   reaparecen -> state=CLEARED (delivery no se toca; V1 no emite
   "clear notifications" — limitacion deliberada).

Categoria "evaluada" = su fuente produjo output este run (queue
SUCCEEDED -> categorias DEADLINE_*; exception_cases -> EXCEPTION;
process_inbox -> PROCESSING_FAILURE). Si la fuente esta BLOCKED,
sus alertas OPEN quedan intactas (nunca se borran por falta de
datos).

## Paso DAG

`alert_outbox` (impuro, obligatorio): depende de
`morning_brief_v2`; lee oportunistamente los outputs opcionales
ya producidos en el ctx (cases, inbox). RUN_FAILED se registra
post-run si el run termina FAILED.
