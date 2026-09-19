# P15.0 — OSS / fuentes publicas: tax recovery

## Consultado

- **Prowide Core / ISO 20022** (pin SRU2025-10.3.10): extraccion
  FIN generica por qualifier — `20C:TARE`, `20C:BORE`, `19B:TXRC`
  salen como facts sin cambio de adapter. En MX, `TaxRclmAmt`
  existe en `CorporateActionAmounts*` del pin; `TaxRclmDocRef`/
  `BnfclOwnrRef` son incorporaciones SR2026 (0 clases en el jar).
- **ISO 20022 catalogue** (iso20022.org): el set CA es
  seev.031-044; no hay mensaje "Tax Reclaim Instruction".
  SR2026 (restricted/external download) documenta TARE/BORE en
  la documentacion fiscal de confirmaciones. `seev.050-053` =
  market claims, set separado — no reutilizable para tax.
- **AEAT / IRNR (modelo 210)**: reclaims de retencion espanola a
  no residentes siguen via de autoliquidacion/devolucion ante
  AEAT con certificado de residencia fiscal — soporte a la
  decision de submission `MANUAL`/`PROVIDER_PROFILE` y a los
  doc types declarados (RESIDENCE_CERTIFICATE, TAX_RECLAIM_FORM).
- **OpenFisca**: sigue fuera de scope (motor de politica fiscal,
  no lifecycle operacional). Rechazado igual que en P14.
- **Custodios (Euroclear/Clearstream)**: tax services publican
  relief-at-source/quick-refund/standard-reclaim como tiers —
  el modelo de 3 metodos del assessment refleja esa taxonomia
  publica, sin adoptar campos propietarios.

## Decisiones

1. Lifecycle interno propio (contratos CA_ES_TAX_RECOVERY_*):
   el estandar publico no ofrece canal de instruccion; inventar
   un MT/MX seria peor que `MANUAL_SUBMISSION_REQUIRED`.
2. Documentos = checklist + referencias (TARE/BORE/manifiesto),
   nunca generacion de certificados/formularios legales.
3. Treaties = reglas effective-dated + perfil explicito; no hay
   motor legal automatico.
4. Refund cash binding solo por referencia explicita
   (claim_id / instruction_ref / TARE) — P13 observa, P15 liga.
