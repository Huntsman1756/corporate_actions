# P8.1 — SPLIT / REVERSE_SPLIT end-to-end

Scope preregistrado (docs/p8/p80-capability.md, familia ENABLED).

Cadena:

```text
MT564 SPLF|SPLR (facts genericos, extractor JVM existente)
  -> CA_ES_SWIFT_CA_MESSAGE_V1 (+campos nuevos, CAEV_MAP)
  -> bind_event (BOUND | NO_MATCH -> SWIFT_NOTIFICATION, D2)
  -> CA_ES_EVENT_TERMS_V1        (operandos normalizados)
  -> CA_ES_SECURITIES_ENTITLEMENT_V1  (math por posicion + DISF)
  -> CA_ES_POSITION_IMPACT_V1    (SECURITY_DELIVERY/RECEIPT)
  -> CA_ES_PROJECTED_POSITIONS_V1 (aplicador P6.2, sin cambios)
  -> MT566 SECMOVE actual -> security_recon -> P3.5 cases
```

## Reglas preregistradas

### Proyeccion MT564 (swift_ca.py, aditivo)

- `CAEV_MAP += SPLF->SPLIT, SPLR->SPLIT` (registry PROVEN; SPLI es
  opcion de instruccion, no CAEV — no se mapea).
- `fields.camv`: 22F::CAMV GENL (MAND/VOLU/CHOS).
- `fields.new_for_old_ratio`: 92D::NEWO en cualquier secuencia;
  value `n/m` -> {new: n, old: m} Decimal; varios valores ->
  CONFLICTING.
- `fields.fraction_disposition`: 22F::DISF (CADETL o CAOPTN).
- `fields.target_isin`: 35B en SECMOVE distinto del USECU 35B;
  si todos los 35B SECMOVE == source -> target = source
  (split sin cambio de ISIN es legal).
- `fields.effective_date`: 98A::PAYD/EFFD/POST en CAOPTN/SECMOVE
  (informativo; nunca es basis).
- direction: `caev` SPLF=forward, SPLR=REVERSE_SPLIT (mechanism
  derivado del CAEV, no inferido de nombres BME).

### CA_ES_EVENT_TERMS_V1 (event_terms.py, nuevo)

```json
{
 "schema": "CA_ES_EVENT_TERMS_V1",
 "event_basis": "CANON_BOUND | SWIFT_NOTIFICATION",
 "canonical_event_id": "<id>|null",
 "binding_status": "BOUND|NO_MATCH|...",
 "caev": "SPLF", "camv": "MAND",
 "event_type": "SPLIT", "mechanism": "REVERSE_SPLIT|null",
 "basis_date": {"value": "YYYY-MM-DD", "kind": "RECORD_DATE"},
 "ratio": {"new": "10", "old": "1"},
 "source_isin": "...", "target_isin": "...",
 "fraction_disposition": "STAN|RDDN|RDUP|BUYU|CINL|SECU|DIST|UKNW|null",
 "cash_in_lieu_price": {"normalized","currency"} | null,
 "provenance": {"input_sha256","message_identifier","fields":{...}}
}
```

`terms_status`: `PROVEN` solo si camv presente, basis_date presente,
ratio PRESENT no conflictivo, source_isin presente; si no ->
`INCOMPLETE` con reasons (nunca se rellena).

### CA_ES_SECURITIES_ENTITLEMENT_V1 (securities_entitlement.py)

Por posicion (misma disciplina P2.0: Decimal, fail-closed,
POSITION_AT_RECORD_DATE vs basis_date):

- `status`: ENTITLED / NOT_ENTITLED (qty 0) / INDETERMINATE /
  UNSUPPORTED.
- `delivered`: {isin: source, quantity: qty completa} (split mueve
  todo el saldo).
- `receivable`: {isin: target, quantity: qty x new/old tras DISF}.
- `raw_quantity`: qty x new/old exacto (pre-DISF, audit trail).
- `fraction`: {amount, disposition, cash_in_lieu|null}.
- DISF: RDDN->floor, RDUP->ceil, STAN->round-half-up, SECU/DIST->
  exacto; BUYU/CINL-> floor/ceil + cash leg SOLO si hay precio
  afirmado, si no INDETERMINATE; UKNW/ausente con fraccion real ->
  INDETERMINATE (FRACTION_DISPOSITION_UNKNOWN); sin fraccion
  real -> DISF irrelevante, ENTITLED.
- `basis`: {record_date, position_eligibility:
  POSITION_AT_RECORD_DATE}.

### Impacto (security_impact.py -> CA_ES_POSITION_IMPACT_V1)

- Por celda ENTITLED: dos items —
  `SECURITY_DELIVERY` {source_isin, delta=-qty, target=source},
  `SECURITY_RECEIPT` {source_isin->target_isin, delta=+receivable}.
- `CASH_IN_LIEU_RECEIVABLE` cuando CINL con precio: cash_amount.
- status propagado verbatim (INDETERMINATE/UNSUPPORTED).
- `canonical_event_id` puede ser null (SWIFT-native); provenance =
  event_terms_sha256 + securities_entitlement_sha256.
- `projected_positions` sin cambios: SECURITY_DELIVERY cae sobre
  source_isin (delta -qty -> projected 0); SECURITY_RECEIPT genera
  linea target_isin (NEW_INSTRUMENT_RECEIPT si no hay posicion).

### Reconciliacion

El lado actual ya existe (P6.3 SECMOVE candidates + P6.4
security_recon + P6.5 cases): el expected set se puebla desde los
impact items PROJECTED — DEBT old ISIN qty vs DELIVERY esperado,
CRED new ISIN qty vs RECEIPT esperado.

## Stop conditions

- Ratio ausente/conflictivo, DISF desconocido con fraccion, camv
  ausente -> INCOMPLETE/INDETERMINATE, nunca defaults.
- Eventos electivos (CHOS) quedan fuera: split V1 = MAND solamente.
- BUYU: el coste de compra solo si hay precio afirmado.
- `internal_field` canon para SPLIT existe pero el corpus no tiene
  eventos; el camino probado es SWIFT-native (D2). Si un canon
  SPLIT existiera, bind_event compararia RDTE/PAYD.

## Estado: IMPLEMENTADO

Modulos:

- `swift_ca.py` — `CAEV_MAP += SPLF|SPLR`, `CAEV_MECHANISM
  {SPLR: REVERSE_SPLIT}`; nuevos fields: `camv`,
  `new_for_old_ratio` (92D::NEWO quantity1=new/quantity2=old por
  (sequence, occurrence)), `fraction_disposition` (22F::DISF),
  `target_isin` (35B SECMOVE != USECU), `effective_date`
  (98A::PAYD/EFFD/POST, informativo). `seq_contains` en `_find`.
- `event_terms.py` — `build_event_terms()` ->
  `CA_ES_EVENT_TERMS_V1`; `terms_status` PROVEN/INCOMPLETE/
  UNSUPPORTED con reasons; basis `RECORD_DATE`; `event_basis`
  CANON_BOUND|SWIFT_NOTIFICATION.
- `securities_entitlement.py` — `compute_securities_entitlements()`
  -> `CA_ES_SECURITIES_ENTITLEMENT_V1`; regla
  `SPLIT_POSITION_X_NEW_FOR_OLD_DISF`; POSITION_AT_RECORD_DATE;
  DISF RDDN/RDUP/STAN/SECU/DIST/BUYU/CINL/UKNW segun scope.
- `security_impact.py` — `compute_security_impact()` ->
  `CA_ES_POSITION_IMPACT_V1` con items SECURITY_DELIVERY /
  SECURITY_RECEIPT / CASH_IN_LIEU_RECEIVABLE; binding fail-closed
  por identidad de posicion (mismo criterio P6.1).

Sin cambios: `projected_positions` (P6.2), `swift_securities`
(P6.3), `security_recon` (P6.4), `exceptions` (P6.5) — el split
reutiliza la cadena existente tal cual.

Verificado e2e con JVM real (`mt564-splf.fin` + `mt566-secmove.fin`):
SPLF 10:1 -> terms PROVEN -> entitlement 12500->125000 -> impact
DELIVERY+RECEIPT -> projected 0 viejo / 125000 nuevo
(NEW_INSTRUMENT_RECEIPT) -> recon MATCH x2 -> cero casos; y
QUANTITY_MISMATCH abre caso P3.5 con expected/actual/delta.

Tests: `tests/unit/test_p81_split.py` (36).
