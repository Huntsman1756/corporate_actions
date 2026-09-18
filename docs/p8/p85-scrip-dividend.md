# P8.5 — SCRIP_DIVIDEND (DVOP) end-to-end

Scope preregistrado (docs/p8/p80-capability.md, familia
CONDITIONAL — requiere eleccion probada por cuenta).

Un scrip dividend es un dividendo electivo: el holder elige entre
la pierna CASH (dividendo ordinario) o SECU (acciones nuevas).
DVOP es `CHOS` por definicion; P5.2 ya whitelistea ambos
`option_kind` (CASH/SECU) y el flujo opportunity -> eligibility
-> instruction MT565 existe.

```text
MT564 DVOP CHOS
  CAOPTN CASH: CASHMOVE CRED + 92J::GRSS + 19B::GRSS currency
  CAOPTN SECU: SECMOVE CRED + 35B target + 92D::NEWO
  -> CA_ES_EVENT_TERMS_V1 (mechanism SCRIP_DIVIDEND)
     terms PROVEN solo si AMBAS piernas tienen operandos
  -> CA_ES_SECURITIES_ENTITLEMENT_V1
     (SCRIP_ELECTION_CASH_OR_SECU, election por cuenta)
  -> impact: SECU -> UNCHANGED + RECEIPT;
             CASH -> UNCHANGED + CASH_RECEIVABLE
```

## Reglas preregistradas

- `CAEV_MAP += DVOP -> SCRIP_DIVIDEND`;
  `CAEV_MECHANISM += DVOP: SCRIP_DIVIDEND`; camv CHOS|VOLU.
- terms PROVEN requiere basis + source + target + ratio
  (pierna SECU) + gross_per_share + currency (pierna CASH).
  Una pierna sin operandos -> INCOMPLETE con reason de la pierna
  (`MISSING_RATIO` / `MISSING_GROSS_PER_SHARE`): la eleccion no
  puede evaluarse si un outcome no es demostrable.
- `election` input: {account_id: "CASH"|"SECU"} — explicito,
  nunca el default de la fuente (17B::DFLT informa, no decide).
  Ausente -> INDETERMINATE `PENDING_ELECTION`; codigo invalido
  -> `INVALID_ELECTION`.
- Pierna SECU: `receivable` = posicion x new/old + DISF (misma
  math que P8.4).
- Pierna CASH: `receivable_cash` = posicion x gross_per_share
  (Decimal, misma forma que P2.0; NO es CA_ES_ENTITLEMENT_V1 —
  la cell es de la familia securities porque comparte contrato).
- Impact: `SECURITY_UNCHANGED` siempre (la posicion no se
  entrega); SECU -> `SECURITY_RECEIPT`; CASH ->
  `CASH_RECEIVABLE` (cash_amount). El matching cash-vs-MT566 se
  formaliza en P8-integracion, igual que el payable EXRI.

## Stop conditions

- Election ausente/invalida -> INDETERMINATE, nunca el DFLT.
- Solo una pierna demostrable -> INCOMPLETE (ambas opciones
  deben ser economicamente evaluables).
- `elected` quantity en scrip: la eleccion es de opcion, no de
  cantidad (todo el saldo sigue la misma opcion; elecciones
  parciales quedan fuera de V1 -> INVALID_ELECTION si llegan).

## Estado: IMPLEMENTADO

- `DVOP -> SCRIP_DIVIDEND` + mechanism `SCRIP_DIVIDEND`
  (camv CHOS|VOLU; MAND -> NON_ADMISSIBLE_CAMV).
- terms PROVEN solo con AMBAS piernas: ratio+target (SECU) y
  gross_per_share+currency (CASH); una pierna sin operandos ->
  INCOMPLETE (`MISSING_GROSS_PER_SHARE` / `MISSING_CURRENCY`).
- `SCRIP_ELECTION_CASH_OR_SECU`: `election` {account: "CASH"|
  "SECU"}; PENDING_ELECTION / INVALID_ELECTION; nunca el DFLT.
- SECU -> SECURITY_UNCHANGED + SECURITY_RECEIPT (+DISF);
  CASH -> SECURITY_UNCHANGED + CASH_RECEIVABLE
  (receivable_cash = qty x gross).
- Fixture `mt564-dvop.fin` (CASH EUR0,15/acc vs SECU 1:50).
- e2e JVM: CASH -> 18750.00 EUR receivable; SECU -> +2500 acc.
- Tests: `tests/unit/test_p85_scrip.py` (9).
