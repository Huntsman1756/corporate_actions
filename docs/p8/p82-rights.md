# P8.2 — RIGHTS_ISSUE end-to-end (staged RHDI + EXRI)

Scope preregistrado (docs/p8/p80-capability.md, familia
CONDITIONAL — desbloqueada por semantica transporte en dos etapas).

La investigacion ISO (P8.0) demostro que una emision de derechos
esquiable se representa como **dos eventos enlazados**:

```text
RHDI MAND  (etapa 1: distribucion de derechos / intermediate sec)
   derechos = posicion en record date x NEWO (derechos por accion)
   -> receipt del rights ISIN (sin delivery del subyacente)
        |
EXRI CHOS  (etapa 2: call/exercise sobre los derechos)
   eleccion EXER por cuenta (P5: opportunity -> eligibility ->
   instruction MT565)
   -> delivery de derechos ejercidos (+ lapse de los no ejercidos)
   -> receipt de nuevas acciones = ejercidos x NEWO
   -> cash payable = nuevas acciones x subscription_price
```

`RHTS` (evento combinado) y `PRIO` (oferta prioritaria, otra cosa)
quedan **UNMAPPED**: no hay fixture ni semantica demostrable en V1.

## Reglas preregistradas

### Proyeccion MT564 (swift_ca.py, aditivo)

- `CAEV_MAP += RHDI->RIGHTS_ISSUE, EXRI->RIGHTS_ISSUE`.
- `CAEV_MECHANISM += RHDI->RIGHTS_DISTRIBUTION,
  EXRI->RIGHTS_EXERCISE`.
- `fields.subscription_price`: 90B::PRPP (o OFFR) en CASHMOVE —
  amount + currency por (sequence, occurrence); ausente en RHDI.
- Reutiliza `new_for_old_ratio`, `target_isin`, `fraction_disposition`,
  `basis_date` (RDTE), `camv` de P8.1.

### event_terms (RIGHTS_ISSUE)

- RHDI: `camv` MAND requerido; terms_status como SPLIT.
- EXRI: `camv` CHOS/VOLU requerido (un EXER MAND no existe);
  terms_status PROVEN si basis + ratio + price + source/target
  estan; la **eleccion no es un operando del terms** — la aporta la
  instruccion (P5), no la notificacion.

### CA_ES_SECURITIES_ENTITLEMENT_V1 — nuevas reglas

`RIGHTS_DISTRIBUTION_POSITION_X_NEWO` (RHDI):
- `receivable`: {isin: rights_isin, quantity: posicion x new/old
  tras DISF}; **sin delivered** (el subyacente se conserva).
- POSITION_AT_RECORD_DATE vs basis_date (RDTE), igual que SPLIT.

`RIGHTS_EXERCISE_ELECTED_X_NEWO_X_PRICE` (EXRI):
- requiere `election` input explicito por cuenta
  ({account_id: elected_quantity} o doc de instruccion); ausente ->
  INDETERMINATE `PENDING_ELECTION`, nunca "ejercer todo por defecto"
  (la fuente puede afirmar un default option, pero el movimiento
  esperado depende de la eleccion real registrada).
- `delivered`: derechos ejercidos + lapse del resto (DELIVERY total
  de la posicion de derechos si la eleccion esta cerrada).
- `receivable`: {isin: new_shares_isin, quantity: elected x new/old}.
- `payable`: {normalized: receivable x price, currency} — cash a
  pagar (movimiento esperado, no entitlement cash P2.0).
- elected > posicion de derechos -> INDETERMINATE
  `ELECTED_EXCEEDS_RIGHTS`; elected no entero -> INDETERMINATE.

### Impacto

- RHDI: `SECURITY_RECEIPT` sobre rights_isin (+receivable); sin
  DELIVERY (posicion de acciones intacta).
- EXRI: `SECURITY_DELIVERY` sobre rights_isin (-posicion derechos),
  `SECURITY_RECEIPT` sobre new_isin (+nuevas acciones),
  `CASH_PAYABLE` (cash_amount; impact_type nuevo, direction cash —
  security_recon lo ignora; la reconciliacion cash del payable se
  resuelve en la fase de integracion P8, no aqui).

### Reconciliacion

- Leg securities: P6.3/P6.4 sin cambios (candidates MT566 SECMOVE:
  CRED rights ISIN en etapa 1; DEBT rights + CRED acciones en etapa 2).
- Leg cash: el payable es expectativa emitida; `swift_cash` (P4.2)
  ya produce candidates CASH desde MT566. El matching
  payable-vs-actual se formaliza en P8-integracion.

## Stop conditions

- `RHTS`/`PRIO`: UNSUPPORTED (sin fixture/semantica demostrable).
- EXER sin election registrada -> INDETERMINATE PENDING_ELECTION.
- Subscription price ausente/conflictivo -> INCOMPLETE/INDETERMINATE.
- Oversuscripcion (OVER) fuera de V1: option_code_raw preservado,
  entitlement del tramo OVER -> UNSUPPORTED.
- El rights ISIN nunca se infiere: 35B SECMOVE explicito o
  INCOMPLETE/INDETERMINATE.

## Estado: IMPLEMENTADO

- `swift_ca.py`: `CAEV_MAP += RHDI|EXRI -> RIGHTS_ISSUE`;
  `CAEV_MECHANISM += RHDI: RIGHTS_DISTRIBUTION,
  EXRI: RIGHTS_EXERCISE`; `fields.subscription_price`
  (90B::PRPP|OFFR price+currency por ocurrencia). `RHTS`/`PRIO`
  permanecen UNMAPPED.
- `event_terms.py`: RIGHTS_ISSUE admitido; camv por mechanism
  (RHDI=MAND, EXRI=CHOS|VOLU); `subscription_price` requerido
  para RIGHTS_EXERCISE; `cash_in_lieu_price` siempre null en
  terms (sin campo probado).
- `securities_entitlement.py`: dispatch por mechanism;
  `RIGHTS_DISTRIBUTION_POSITION_X_NEWO` (receipt-only, DISF);
  `RIGHTS_EXERCISE_ELECTED_X_NEWO_X_PRICE` (param `election`
  explicito; PENDING_ELECTION / ELECTED_EXCEEDS_RIGHTS /
  NON_INTEGRAL_ELECTION / ZERO_ELECTION_LAPSE; payable =
  receivable x price).
- `security_impact.py`: items por componente de celda
  (delivered opcional); `SECURITY_UNCHANGED` delta-0 para
  posiciones explicitamente inalteradas y NOT_ENTITLED;
  `CASH_PAYABLE` para el payable EXRI.
- `security_recon.py`: items con `quantity_delta` 0 excluidos
  del expected set (delta-0 = sin movimiento, nunca MISSING).

Fixtures: `mt564-rhdi.fin` (distribucion 1 derecho/10 acciones,
DISF RDDN) y `mt564-exri.fin` (ejercicio EXER/LAPS, NEWO 1/10,
PRPP EUR1,5) — continuidad narrativa con el split Redegal.

Verificado e2e JVM: RHDI -> receipt 12500 derechos; EXRI con
election {A001: 12500} -> delivery 12500 derechos + receipt 1250
acciones + payable 1875.0 EUR -> projected 0 derechos / 1250
acciones.

Tests: `tests/unit/test_p82_rights.py` (22).
