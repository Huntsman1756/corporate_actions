# P8.3 — CAPITAL_INCREASE (parcial, solo mecanismos demostrados)

Scope preregistrado (docs/p8/p80-capability.md, familia
CONDITIONAL — solo si mecanismo + instrumento destino probados).

Una ampliacion de capital no es un unico mecanismo economico; en
ISO 15022 llega por varios CAEV. V1 conecta **solo** los dos
cuya semantica esta demostrada con fixtures reales:

```text
BONU MAND   ampliacion liberada (bonus issue sobre reservas)
            -> receipt-only, forma identica a DVSE (P8.4)
RHDI+EXRI   ampliacion con suscripcion preferente
            -> ya cubierto por RIGHTS_ISSUE (P8.2): economicamente
               ES una capital increase con desembolso
```

`CAPI` (capitalization issue generico), `CAPG` (distribucion de
plusvalias, pierna cash distinta) y `PRIO` (oferta prioritaria)
quedan **UNMAPPED**: sin fixture ni mecanismo unico demostrable
— un CAPI puede ser liberado o con desembolso, y el CAEV solo no
lo decide.

## Reglas preregistradas

- `CAEV_MAP += BONU -> CAPITAL_INCREASE`;
  `CAEV_MECHANISM += BONU: BONUS_ISSUE`; camv MAND.
- Entitlement `BONUS_ISSUE_POSITION_X_NEWO`: receipt-only con
  DISF (misma funcion que RIGHTS_DISTRIBUTION/STOCK_DIVIDEND,
  regla nombrada propia para audit trail).
- `target_isin` = 35B SECMOVE explicito (mismo ISIN o clase
  nueva); basis RDTE; resto identico a P8.1/P8.4.
- CAPI/CAPG/PRIO -> UNSUPPORTED_CA_EVENT con razon en el doc:
  mecanismo no demostrado en V1.

## Stop conditions

- Nunca se asume "ampliacion = gratis": BONU es el unico CAEV
  con semantica gratuita demostrada; CAPI con posible desembolso
  no se computa a medias -> UNSUPPORTED.
- La via suscripcion no se duplica: quien emite RHDI/EXRI ya es
  procesado por P8.2; este batch solo añade la via liberada.

## Estado: IMPLEMENTADO (parcial, segun scope)

- `BONU -> CAPITAL_INCREASE` + mechanism `BONUS_ISSUE`
  (camv MAND); `CAPI`/`CAPG`/`PRIO` permanecen UNMAPPED ->
  `UNSUPPORTED_CA_EVENT` verificado en test.
- `BONUS_ISSUE_POSITION_X_NEWO` reutiliza la funcion
  receipt-only; rule_id propio.
- Fixture `mt564-bonu.fin` (1:10 mismo ISIN); e2e JVM
  125000 -> +12500 -> projected 137500.
- Tests: `tests/unit/test_p83_capital_increase.py` (5).
