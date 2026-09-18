# P8.4 — STOCK_DIVIDEND (DVSE) end-to-end

Scope preregistrado (docs/p8/p80-capability.md, familia
CONDITIONAL — desbloqueada por evidencia de transporte).

Un stock dividend es una distribucion obligatoria de valores
(identica forma matematica que la etapa RHDI de P8.2): el holder
recibe `posicion x NEWO` valores adicionales, sin delivery del
saldo preexistente. El instrumento recibido suele ser el mismo
ISIN (bonus issue sobre la misma accion) o un ISIN nuevo
(stock dividend en otra clase) — ambos casos ya los cubre
`target_isin` de P8.1.

```text
MT564 DVSE MAND
  -> CA_ES_EVENT_TERMS_V1 (mechanism STOCK_DIVIDEND)
  -> CA_ES_SECURITIES_ENTITLEMENT_V1
     (STOCK_DIVIDEND_POSITION_X_NEWO: receipt-only + DISF)
  -> SECURITY_UNCHANGED (delta 0, subyacente) + SECURITY_RECEIPT
  -> projection / recon / cases (cadena P6/P8.1 sin cambios)
```

## Reglas preregistradas

- `CAEV_MAP += DVSE -> STOCK_DIVIDEND`; `CAEV_MECHANISM +=
  DVSE: STOCK_DIVIDEND`. `camv` MAND requerido (un DVSE electivo
  es un SCRIP, no un stock dividend — CHOS/VOLU ->
  NON_ADMISSIBLE_CAMV).
- Entitlement `STOCK_DIVIDEND_POSITION_X_NEWO`: misma funcion
  receipt-only que `RIGHTS_DISTRIBUTION_POSITION_X_NEWO`
  (posicion x new/old, DISF identico), regla nombrada distinta
  para audit trail.
- `basis_date` = RDTE (POSITION_AT_RECORD_DATE).
- `receivable.isin` = 35B SECMOVE explicito; si todos los 35B
  SECMOVE == source -> mismo ISIN (bonus en la misma accion).
- Todo lo demas heredado de P8.1/P8.2: ratio conflictivo ->
  INCOMPLETE; DISF desconocida con fraccion real ->
  INDETERMINATE; nunca defaults.

## Stop conditions

- Sin fixture canon DVSE en el corpus: camino probado
  SWIFT-native (como SPLIT/RHDI).
- DVOP (scrip) NO se mapea aqui: eleccion cash/valores es P8.5.
- Si el DVSE no trae SECMOVE/35B destino -> INCOMPLETE
  (MISSING_TARGET_INSTRUMENT), nunca se asume el source.

## Estado: IMPLEMENTADO

- `swift_ca.py`: `CAEV_MAP += DVSE -> STOCK_DIVIDEND`;
  `CAEV_MECHANISM += DVSE: STOCK_DIVIDEND` (camv MAND via
  `_MECHANISM_CAMV`; CHOS/VOLU -> NON_ADMISSIBLE_CAMV).
- `securities_entitlement.py`: `STOCK_DIVIDEND_POSITION_X_NEWO`
  reutiliza la funcion receipt-only de RIGHTS_DISTRIBUTION con
  regla nombrada propia.
- `security_impact.py`: rule_id propio; items
  SECURITY_UNCHANGED + SECURITY_RECEIPT.
- Fixture `mt564-dvse.fin` (bonus 1:20 mismo ISIN, DISF RDDN).
- e2e JVM: 125000 -> receivable 6250 -> projected 131250.
- Tests: `tests/unit/test_p84_stock_dividend.py` (7).
