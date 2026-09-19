# P15 — contratos: Tax Recovery Lifecycle V1

Cadena:

```text
CA_ES_TAX_ENTITLEMENT_V1 + evidencia ACTUAL (P14)
    + CA_ES_TAX_PROFILE_V1 + CA_ES_TAX_RECOVERY_RULES_V1
    -> CA_ES_TAX_RECOVERY_ASSESSMENT_V1     (tax_recovery_assessment)
    -> CA_ES_TAX_RECOVERY_CASE_V1           (claims; tax_recovery_case)
CA_ES_TAX_RECOVERY_CASE_V1 + rules + provided/TARE/BORE
    -> CA_ES_TAX_RECOVERY_DOCUMENT_SET_V1   (tax_recovery_docs)
claims READY_TO_SUBMIT + doc set COMPLETE + provider?
    -> CA_ES_TAX_RECOVERY_INSTRUCTION_V1    (tax_recovery_instruction)
status events (provider/manual/expiry)
    -> CA_ES_TAX_RECOVERY_STATUS_V1         (tax_recovery_status)
claims + instructions + refund cash (P13/P4)
    -> CA_ES_TAX_RECOVERY_RECON_V1          (tax_recovery_recon)
    -> CA_ES_EXCEPTION_CASES_V1             (exceptions, scope tax-recovery)
```

## Regla esencial

`recoverable_amount` NUNCA se deriva de
`actual tax > P14 expected tax`. El gap esperado-vs-actual puede
ser mismatch, perfil incorrecto, relief no aplicado o reclaim
real. Solo existe importe recuperable cuando una regla recovery,
un perfil y la evidencia ACTUAL lo demuestran:

```text
recoverable = withheld_evidenced - entitled(rule)   sobre gross
```

Separacion semantica:

```text
WITHHOLDING_MISMATCH != RECOVERY_ELIGIBLE
RECOVERY_ELIGIBLE    != READY_TO_SUBMIT
SUBMITTED            != ACCEPTED
ACCEPTED             != REFUND_PAID
```

## CA_ES_TAX_RECOVERY_RULES_V1

Datos, no codigo; validacion estatica; effective-dating
[valid_from, valid_to]; solapes por (jurisdiction, income_type,
recovery_method) exigen conditions disjuntas.

Regla: `rule_id`, `jurisdiction`, `income_type`, `valid_from`,
`valid_to`, `recovery_method`
(`RELIEF_AT_SOURCE`/`QUICK_REFUND`/`STANDARD_RECLAIM`),
`entitled_rate` + `rate_unit`, `conditions` (vocabulario P14),
`deadline` `{basis: PAYMENT_DATE, months: N}` (statutory,
nunca generico), `required_documents` (DOC_TYPES),
`submission.channel` (`MANUAL`|`PROVIDER_PROFILE`).

## CA_ES_TAX_RECOVERY_ASSESSMENT_V1

Un item por (cuenta, regla candidata). `status`:

- `ELIGIBLE`: regla+perfil+evidencia demuestran base recuperable.
  `claim_kind`: `CASH_REFUND` (quick/standard) o `RATE_RELIEF`
  (relief at source). `recoverable_amount` solo en CASH_REFUND;
  `prospective_amount` (evitado) en RATE_RELIEF.
- `NOT_APPLICABLE`: conditions no cumplidas, `NO_RECOVERABLE_*`,
  `PAYMENT_ALREADY_EVIDENCED` (relief cerrado por evidencia
  ACTUAL — el exceso pasa a las vias refund).
- `INDETERMINATE`: perfil/evidencia/deadline insuficientes
  (reason_codes explicitos; NUNCA genera claim).
- `EXPIRED`: assessment_date > deadline effective-dated.

`claim_reference` determinista: `event|account|rule|method`.

## CA_ES_TAX_RECOVERY_CASE_V1

Claims vivos; nacen SOLO de ELIGIBLE. Maquina de estados
validada (EDGES), history por transicion (at/actor/reason/
event_ref):

```text
ASSESSED -> PENDING_DOCUMENTATION -> READY_TO_SUBMIT
         -> SUBMITTED -> ACKNOWLEDGED -> ACCEPTED
         -> PARTIALLY_PAID -> PAID
REJECTED / PAID / APPLIED / EXPIRED = terminales
```

`APPLIED`: terminal para RATE_RELIEF (la reduccion se aplico;
no hay refund leg). PARTIALLY_PAID es estructural: el primer
abono no liquida el claim.

## CA_ES_TAX_RECOVERY_DOCUMENT_SET_V1

Checklist por claim: `required_documents` de la regla +
documentos aportados. Fuentes: `provided_documents` (manifiesto)
y facts FIN `20C:TARE` -> `RECLAIM_DOCUMENTATION_REFERENCE`,
`20C:BORE` -> `BENEFICIAL_OWNER_REFERENCE`. `set_status`:
COMPLETE solo si todos los required son PRESENT. UNCLAIMED se
preserva con reason.

## CA_ES_TAX_RECOVERY_INSTRUCTION_V1

Artefacto interno (no existe mensaje publico de reclaim):
`payload_format=INTERNAL_V1` con claim/importe/referencias de
documentos. `status`: READY (provider demostrado),
MANUAL_SUBMISSION_REQUIRED (channel MANUAL o fallback con
FELL_BACK_TO_MANUAL), BLOCKED (claim no READY/doc set
incompleto). Provider: `CA_ES_TAX_RECOVERY_PROVIDER_V1`
(provider_id, channel SFTP|MQ|API, endpoint_ref — referencia a
destino configurado, nunca credenciales). Nunca fabrica MT/MX.

## CA_ES_TAX_RECOVERY_STATUS_V1

Eventos: SUBMISSION_RECORDED, RECEIPT, ACCEPTANCE, REJECTION,
APPLIED, EXPIRY_CHECK, QUERY. Cada evento valida la transicion;
saltos invalidos -> REJECTED_EVENT con reason (no se aplican en
silencio). EXPIRY_CHECK evalua deadline vs `at` -> EXPIRED.

## CA_ES_TAX_RECOVERY_RECON_V1

Refund cash ligado SOLO por referencia explicita: claim_id,
instruction_id, referencias TARE del doc set. Un movimiento con
el mismo importe sin referencia -> NO_REFUND_OBSERVED (nunca
bind por amount+date). Estados: PAID, PARTIALLY_PAID, OVERPAID,
NO_REFUND_OBSERVED, NOT_SUBMITTED, NOT_APPLICABLE (RATE_RELIEF),
REJECTED, EXPIRED, INDETERMINATE (FX_REQUIRED / claim amount
ausente). Casos P3.5: REJECTED/OVERPAID HIGH,
PARTIALLY_PAID/EXPIRED MEDIUM; pendientes/informativos filtrados.

## P7

`tax_recovery` (v1, opcional/impuro): deps `tax_events` +
`cash_reconciliation`; `config_section=tax_recovery`;
`uses_inputs=(tax_profile, tax_recovery_rules,
tax_recovery_provider, cash_movements)`; `uses_as_of=True`
(expiry depende de as_of). Sin `tax_recovery_rules` -> indice
minimo estable que no invalida downstream. Claims persisten via
`merge_claims` contra el ultimo run exitoso.
