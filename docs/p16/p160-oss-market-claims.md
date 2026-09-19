# P16.0 — OSS survey / fuentes publicas: Market Claims

## Estandar

- **ISO 20022 catalogue**: message set Market Claims separado de
  Corporate Actions: seev.050 MarketClaimCreation, seev.051
  MarketClaimCancellationRequest, seev.052
  MarketClaimStatusAdvice, seev.053
  MarketClaimCancellationRequestStatusAdvice. Publicar version
  nueva no obliga a adoptarla.
- **SR2026**: seev.050.001.04 anade indicador detection-vs-
  settlement; fuera del pin, documentado como gap (p160).
- **Buyer Protection seev.060-067**: familia del catalogo 2026
  (instruction, status, cancellation, allegement, report).
  Ausente del pin SRU2025 -> entrada de roadmap P17 candidata,
  sin implementacion.

## OSS

- **Prowide ISO 20022** (`pw-iso20022-SRU2025-10.3.10`,
  pinneado): `MxSeev05000101-03`, `MxSeev05100101-02`,
  `MxSeev05200101-03`, `MxSeev05300101-03` verificados por
  javap. ADOPT — facts genericos via adapter existente.
- **FINOS CDM**: modela el lifecycle economico de claims;
  REFERENCE_ONLY (sin dependencia runtime, consistente con la
  decision de roadmap).
- **Open-source settlement/claims engines**: no se adopta
  ninguno; la logica diferencial es la regla de mercado
  explicita + evidence binding, no un motor generico.

## Invariante de dominio

```text
corporate-action entitlement != market claim entitlement
trade before ex-date + settlement after record date
    != automaticamente market claim
```

La claim exige regla de mercado explicita
(`CA_ES_MARKET_CLAIM_RULES_V1`): tipo de evento, ventana
trade/settlement, direccion buyer/seller, settlement status,
regimen de market claim, instrumento, cantidad y basis del
entitlement. Sin regla -> `MARKET_PRACTICE_REQUIRED`, nunca
claim inventada.

## Decisiones

1. MX-only para mensajes de claim (no hay MT equivalente);
   la liquidacion se observa via movimientos P13/P4 existentes.
2. Whitelist `SUPPORTED` en MxFactsAdapter con las versiones
   presentes en el pin; sin perseguir .001.04.
3. Refund/settlement cash binding solo por referencia explicita
   (claim_id / TxRef / RltdSttlmInstrId), nunca amount+date.
4. Cancelacion como intent separado del estado del claim:
   CANCELLED solo con evidencia explicita (seev.053 aceptada o
   seev.052 Canc).
