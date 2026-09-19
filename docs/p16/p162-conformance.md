# P16 — conformidad: acceptance M1-M15 y mapa de subfases

## Acceptance (tests/unit/test_p16_market_claims.py + demo e2e)

| req | comportamiento verificado | test / leg |
|---|---|---|
| M0 | seev.050/051/052/053 reales via pin SRU2025 -> facts -> proyeccion | MarketClaimFactsTest (JVM) / leg M0 |
| M1 | CA cash obligatoria + tx elegible -> PROVEN, expected_amount trazable | test_m1* / leg M1 |
| M2 | misma CA sin basis suficiente -> INDETERMINATE, 0 claims | test_m2* / leg M2 |
| M3 | seev.050 incoming -> claim bound determinista (referencia explicita) | test_m3* / leg M3 |
| M4 | seev.050 desconocida/ambigua -> NO_MATCH / AMBIGUOUS | test_m4* / leg M4 |
| M5 | cash claim expected 125 + actual 125 -> MATCH | test_m5* / leg M5 |
| M6 | actual 120 -> AMOUNT_MISMATCH + caso P3.5 | test_m6* / leg M6 |
| M7 | securities claim -> expected delivery/receipt -> recon | test_m7* / leg M7 |
| M8 | seev.052 accepted/pending/rejected -> status lifecycle | test_m8* / leg M8 |
| M9 | seev.051 -> CANCELLATION_REQUESTED, intent != estado | test_m9* / leg M9 |
| M10 | seev.053 accepted -> CANCELLED solo con evidencia explicita | test_m10* / leg M10 |
| M11 | seev.050 duplicada -> DUPLICATE_IGNORED | test_m11* / leg M11 |
| M12 | amount cambiado -> CONFLICTING_NOTIFICATION, nunca overwrite | test_m12* / leg M12 |
| M13 | tx desaparece del feed -> evidencia previa preservada | test_m13* / leg M13 |
| M14 | sin regla de mercado -> MARKET_PRACTICE_REQUIRED | test_m14* / leg M14 |
| M15 | run identico -> determinista, sin claims/casos duplicados | test_m15* / leg M15 |

Extras: validacion estatica del ruleset (metodo/eligibility/
deadline/solape), transiciones invalidas -> REJECTED_EVENT,
skip-transition NOTIFIED->SETTLED permitida solo via settlement
observado, settlement gating por estado, terminal settlement,
PrtrySts -> PROPRIETARY sin mapeo, choice conflictivo ->
CONFLICTING_CHOICE.

## Invariante central

```
corporate-action entitlement != market claim entitlement
```

Una claim NUNCA se infiere de `trade before ex-date + settlement
after record date`: exige regla de mercado explicita
(`CA_ES_MARKET_CLAIM_RULES_V1`) con eligibility demostrada
(trade_date_relation, settlement_status, settlement_date_relation).
Sin regla -> `MARKET_PRACTICE_REQUIRED`; basis insuficiente ->
`INDETERMINATE`. Nunca se fabrica una claim.

## Mapa de subfases

- P16.0 capability audit + OSS survey -> p160-capability.md,
  p160-oss-market-claims.md (seev.050-053 verificado contra el jar
  SRU2025 pinneado via javap; seev.060-067 Buyer Protection =
  documentado, NO implementado; SR2026 .001.04 fuera del pin)
- P16.1 basis -> market_claim_basis.py
  (CA_ES_MARKET_CLAIM_BASIS_V1)
- P16.2 seev.050-053 -> market_claim_messages.py + whitelist JVM
- P16.3 assessment -> market_claim_assessment.py
  (CA_ES_MARKET_CLAIM_ASSESSMENT_V1) + market_claim_rules.py
  (CA_ES_MARKET_CLAIM_RULES_V1)
- P16.4 recon -> market_claim_recon.py
  (CA_ES_MARKET_CLAIM_RECON_V1)
- P16.5 status -> market_claim_status.py + market_claim_case.py
  (CA_ES_MARKET_CLAIM_V1 / STATUS_V1)
- P16.6 cancelacion -> market_claim_cancellation.py
  (CA_ES_MARKET_CLAIM_CANCELLATION_V1)
- P16.7 P3.5 cases + P7 DAG `market_claims` + CLI mc-* (8 cmds)
- P16.8 tests M1-M15 + e2e + conformidad -> este doc,
  p16_e2e_demo.py (18 PASS / 0 SKIP / 0 FAIL)
- P16.9 regression + CI

## Limites (congelados)

- Sin nuevo settlement engine: recon reutiliza boundaries P3/P6/P13.
- Binding SOLO por referencia explicita (claim_id, TxRef,
  RltdSttlmInstrId, transaction_id). Nunca importe+fecha.
- CANCELLED solo con evidencia explicita: seev.053
  CANCEL_ACCEPTED/CANCEL_COMPLETED o seev.052 Canc.
- Cancel intent separado del estado del claim: seev.051 ->
  CANCELLATION_REQUESTED; el claim sigue vivo hasta outcome.
- Amounts/quantities observados que difieren del expected ->
  CONFLICTING_NOTIFICATION auditado; expected nunca se
  sobrescribe.
- Claims previas se mergean sin borrar evidencia; tx que
  desaparece del feed no elimina claims.
- Versiones soportadas = las del pin SRU2025:
  seev.050.001.01-03, seev.051.001.01-02, seev.052.001.01-03,
  seev.053.001.01-03. SR2026 .001.04 (detection-vs-settlement
  indicator) = forward-compatible, fuera del pin.
- Buyer Protection seev.060-067: NO implementado (candidato P17;
  exige audit + posible migracion de pin).
- FX: fail-closed, boundary explicito.
- seev.050-053 NO se reutilizan para tax reclaim (P15 separado).
- Decimal-only; sin floats en valores financieros.
