# P15.0 — capability audit: Tax Recovery Lifecycle

Verificado contra el pin actual `pw-iso20022-SRU2025-10.3.10`
(jar inspeccionado + adapter ejecutado) y el extractor FIN
generico del boundary JVM.

## Hallazgo central

No existe un mensaje publico separado "Tax Reclaim Instruction".
El set Corporate Actions sigue siendo la familia `seev.031-044`;
SR2026 anade referencias de documentacion fiscal (`TARE`,
`BORE`) dentro de la confirmacion `seev.036`/MT566, no un canal
nuevo. Los mensajes `seev.050-053` son **market claims** —
otra problematica de securities events; el nombre "claim" no los
convierte en tax claims. P15 no los usa.

Consecuencia: la instruccion de recovery es un artefacto interno
(`CA_ES_TAX_RECOVERY_INSTRUCTION_V1`) con submission `MANUAL` o
`PROVIDER_PROFILE` demostrado. Nunca se fabrica un MT/MX.

## Matriz de capacidad (pin SRU2025)

| semantica | FIN (MT564/566) | MX (seev.031/036) | estado en pin |
|---|---|---|---|
| reclaim amount | `19B:TXRC//CCYa` | `AmtDtls/TaxRclmAmt` | SOPORTADO (P14 ya proyecta) |
| reclaim doc reference | `20C:TARE//ref` | `TaxRclmDocRef` (SR2026) | FIN: facts genericos OK; MX: NO en pin |
| beneficial owner ref | `20C:BORE//ref` | `BnfclOwnrRef` (SR2026) | FIN: facts genericos OK; MX: NO en pin |
| reclaim status | narrativa `70E` / codigos propietarios | `TaxVchrDtls`, status en seev.033/036 | parcial: facts genericos |
| clase `TaxRclm*`/`BnfclOwnr*` en jar | — | — | 0 clases (verificado `unzip -l`) |

Verificacion ejecutada: `mt566-tare.fin` con
`20C:TARE`/`20C:BORE`/`19B:TXRC` -> facts emitidos sin cambio de
adapter (Prowide MT es qualifier-agnostico).

## Decision sobre el pin

NO migrar a SRU2026 solo por TARE/BORE:

- El pin SRU2025 esta verificado end-to-end (P4-P14); una revision
  anual nueva exige capability audit completo + regression de
  P1-P14 antes de adoptarse.
- La semantica TARE/BORE se consume hoy por FIN con coste cero.
- En MX, P15 acepta referencias de documentos via
  `provided_documents` (manifiesto explicito) — el modelo de
  documentos es agnostico al transporte. Cuando el pin migre,
  `_SEEV_TAX_PATHS`/paths de referencia se extienden con audit.

## Boundaries confirmados

- Relief at source / quick refund / standard reclaim son METODOS
  de un mismo lifecycle, no pipelines separados.
- `WITHHOLDING_MISMATCH != RECOVERY_ELIGIBLE != READY_TO_SUBMIT
  != SUBMITTED != ACCEPTED != REFUND_PAID`.
- `recoverable_amount` solo existe cuando (regla recovery +
  perfil + evidencia ACTUAL) lo demuestran. Nunca de
  `actual > P14 expected` a secas.
- Refund cash se liga SOLO por referencia explicita
  (claim/instruction/TARE), nunca por importe+fecha.
- Deadlines: effective-dated en la regla (`deadline.months` +
  `basis`), nunca plazo generico.
- FX: fail-closed (moneda divergente -> FX_REQUIRED).
- seev.050-053 (market claims): fuera de scope, no reutilizar.
