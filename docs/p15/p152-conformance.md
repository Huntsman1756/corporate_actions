# P15 — conformidad: acceptance R1-R12 y mapa de subfases

## Acceptance (tests/unit/test_p15_recovery.py + demo e2e)

| req | comportamiento verificado | test / leg |
|---|---|---|
| R1 | 19% correcto desde origen -> NOT_APPLICABLE | test_r1 / leg R1 |
| R2 | 21% withheld, regla 19% -> ELIGIBLE, claim 2% trazable | test_r2* / leg R2 |
| R3 | diferencia fiscal + perfil incompleto -> INDETERMINATE, 0 claims | test_r3* / leg R3 |
| R4 | relief at source pre-pago -> ELIGIBLE RATE_RELIEF | test_r4* / leg R4 |
| R5 | docs incompletos -> PENDING_DOCUMENTATION, instruccion BLOCKED | test_r5* / leg R5 |
| R6 | docs completos -> READY_TO_SUBMIT | test_r6 / leg R6 |
| R7 | provider ausente -> MANUAL_SUBMISSION_REQUIRED, no MT/MX fabricado | test_r7* / leg R7 |
| R8 | receipt -> SUBMITTED/ACKNOWLEDGED | test_r8 / leg R8 |
| R9 | rechazo explicito -> REJECTED + caso P3.5 HIGH | test_r9 / leg R9 |
| R10 | refund con referencia explicita -> PARTIALLY_PAID -> PAID | test_r10* / leg R10 |
| R11 | mismo importe sin referencia -> NO_REFUND_OBSERVED | test_r11* / leg R11 |
| R12 | deadline effective-dated -> EXPIRED | test_r12* / leg R12 |

Extras: evidencia a nivel amount (single account), conflicting
actual rates -> INDETERMINATE, sin evidencia ACTUAL ->
INDETERMINATE, FX divergente -> FX_REQUIRED, OVERPAID -> caso
HIGH, merge_claims no reabre claims vivos, TARE -> binding de
refund, validacion estatica del ruleset (metodo/deadline/solape),
transiciones invalidas -> REJECTED_EVENT.

## Mapa de subfases

- P15.0 capability audit + OSS survey -> p150-capability.md,
  p150-oss-recovery.md (TARE/BORE FIN verificado; MX SR2026 = gap
  documentado; pin SRU2025 mantenido)
- P15.1 rules -> tax_recovery_rules.py
- P15.2 assessment -> tax_recovery_assessment.py
- P15.3 claims/lifecycle -> tax_recovery_case.py
- P15.4 document sets -> tax_recovery_docs.py
- P15.5 instruction + provider -> tax_recovery_instruction.py
- P15.6 status events -> tax_recovery_status.py
- P15.7 refund recon -> tax_recovery_recon.py + exceptions.py
- P15.8 P7 DAG -> ops_dag.py (_step_tax_recovery)
- P15.9 CLI -> recovery-* (8 comandos)
- P15.10 tests + e2e -> test_p15_recovery.py, p15_e2e_demo.py
- P15.11 docs -> p151/p152
- P15.12 regression + CI

## Limites (congelados)

- Sin motor legal de treaties: reglas + perfil explicito.
- Sin generacion de certificados/formularios: checklist + refs.
- Submission: MANUAL siempre; PROVIDER_PROFILE solo con
  CA_ES_TAX_RECOVERY_PROVIDER_V1 valido (SFTP|MQ|API via P11).
- Refund binding: solo referencia explicita (claim_id /
  instruction_id / TARE). Nunca importe+fecha.
- FX: fail-closed.
- seev.050-053 (market claims): no reutilizados.
- MX TARE/BORE: SR2026, fuera del pin; aceptados via
  provided_documents. Migracion de pin exige audit + regression.
- Partial refund estructural: PARTIALLY_PAID no liquida.
