# P6.1 — Expected Position / Security Impact

Status: **FROZEN — PENDING IMPLEMENTATION**.
Parent: P6.0 capability audit DONE (`docs/p6/p60-capability.md`).

Pregunta única:

> Dado un evento canónico y un snapshot de posiciones, ¿qué impacto
> económico esperado puede probarse operando por operando, sin
> inferencia financiera?

```text
canonical event
+ CA_ES_POSITIONS_V1
+ CA_ES_IMPACT_RULES_V1 (explícita)
+ CA_ES_ENTITLEMENT_V1  (solo si la regla lo exige)
        ↓
compute_position_impact()
        ↓
CA_ES_POSITION_IMPACT_V1
```

## Capacidad congelada (P6.0)

Único tipo de impacto implementable en V1:

```text
CASH_RECEIVABLE  (CASH_DIVIDEND)
```

Se compone del resultado ya adjudicado de P2.0: la regla
`CASH_DIVIDEND_GROSS_RECEIVABLE` declara `requires:
CA_ES_ENTITLEMENT_V1`; el impacto no recalcula el entitlement (no hay
segunda fórmula de cash en el repo). Ninguna familia produce impacto
de valores en V1 (SPLIT: basis date no demostrable; resto:
semántica no probada — ver p60-capability.md).

## Rules doc (CA_ES_IMPACT_RULES_V1)

```text
schema: CA_ES_IMPACT_RULES_V1
rules[]:
  rule_id            identificador explícito (caller-provided)
  event_type         CASH_DIVIDEND | SPLIT | ...
  status             SUPPORTED | UNSUPPORTED
  impact_type        CASH_RECEIVABLE (solo SUPPORTED)
  requires[]         ["CA_ES_ENTITLEMENT_V1"]
  reason             código si UNSUPPORTED (documentado en p60)
```

Un `event_type` sin regla → item UNSUPPORTED con reason `NO_RULE`.
Una regla `UNSUPPORTED` → item UNSUPPORTED con su `reason`.

## Binding de inputs (fail closed)

- canon: `schema=CA_ES_OPERATIONAL_CANON_V1`; evento localizado por
  `canonical_event_id` (evento inexistente → error, no doc vacío).
- positions: `CA_ES_POSITIONS_V1`; nunca se muta.
- entitlement doc (cuando la regla lo exige): schema
  `CA_ES_ENTITLEMENT_V1` + `canonical_event_id` igual +
  `event_type` igual → si no, doc-level INDETERMINATE con
  `ENTITLEMENT_EVENT_MISMATCH`. Ausente → `MISSING_ENTITLEMENT_INPUT`.
- binding por posición: exactamente una celda de entitlement con el
  mismo `(account_id, isin, position_quantity, position_as_of)` que la
  posición; 0 → `ENTITLEMENT_CELL_MISSING`, >1 →
  `ENTITLEMENT_CELL_AMBIGUOUS` (item INDETERMINATE).

## Mapeo de status (composición, sin reinterpretar)

```text
entitlement ENTITLED      -> impact PROJECTED (cash_amount=gross_cash)
entitlement NOT_ENTITLED  -> impact PROJECTED (cash_amount=0 — hecho:
                             "nada esperado" es factual)
entitlement INDETERMINATE -> impact INDETERMINATE + reasons verbatim
entitlement UNSUPPORTED   -> impact UNSUPPORTED + reasons verbatim
```

## Impact item

```text
canonical_event_id
account_id
source_isin
target_isin                  null en V1 (cash dividend no tiene)
impact_type                  CASH_RECEIVABLE
status                       PROJECTED | INDETERMINATE | UNSUPPORTED
input_quantity               posición (Decimal string)
output_quantity              null
quantity_delta               null (cash dividend no mueve valores)
cash_amount                  {normalized, currency, scale} | null
currency
rule_id
basis_date                   record_date (del entitlement)
reasons[]
source_canon_logical_sha256
source_positions_logical_sha256
source_entitlement_sha256    sha256 del doc de entitlements usado
evidence                     assertion_ids/source_document_ids/
                             evidence_locators (copiados del cell)
```

Doc-level: `schema`, `generated_at`, `canonical_event_id`,
`event_type`, `positions_as_of`, `source_*_sha256`, `impacts[]`,
`summary` (counts por status).

## Fuera de alcance

- POSITION_TRANSFORM, SECURITY_DELIVERY/RECEIPT, RIGHTS_RECEIPT,
  CASH_PAYABLE: sin semántica demostrada en V1 (p60).
- Rounding, fracciones, cash-in-lieu, retención, FX, netting,
  agregación entre cuentas, short/borrow, settlement.
- Nunca se sustituye el source ISIN por un target ausente.
- El impacto no es una instrucción ni un movimiento: es expectativa.

## Tests preregistrados

1. CASH_DIVIDEND + entitlement ENTITLED → CASH_RECEIVABLE PROJECTED
   con cash_amount = gross_cash exacto (Decimal).
2. ZERO_QUANTITY → PROJECTED cash 0.
3. Entitlement INDETERMINATE → impact INDETERMINATE, reasons verbatim.
4. Event type sin regla → UNSUPPORTED/NO_RULE por posición.
5. Regla UNSUPPORTED (p.ej. SPLIT) → UNSUPPORTED + reason preregistrada.
6. `--entitlements` ausente para regla que lo exige →
   MISSING_ENTITLEMENT_INPUT.
7. Entitlement de otro evento → ENTITLEMENT_EVENT_MISMATCH.
8. Celda ausente/duplicada por posición → ENTITLEMENT_CELL_*.
9. Posición de ISIN ajeno → INDETERMINATE (propagado).
10. Positions/canon/entitlement no mutados; output determinista
    con `--now` fijo; hashes de origen presentes por item.
11. Schema inválido de cualquier input → ValueError.
12. quantity float en positions → item INDETERMINATE (nunca float).
</content>
