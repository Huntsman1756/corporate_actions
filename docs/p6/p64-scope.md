# P6.4 — Securities Reconciliation

Status: **FROZEN — PENDING IMPLEMENTATION**.
Parent: P6.1 (expected impacts) + P6.3 (actual movements) DONE.

Pregunta única:

> Dado el conjunto esperado de impactos de valores ya adjudicado y los
> movimientos observados (candidatos PROJECTABLE), ¿qué casa, qué
> difiere y qué falta — sin tolerancia ni agregación implícita?

```text
CA_ES_POSITION_IMPACT_V1  (expected, adjudicado)
+ CA_ES_SWIFT_SECURITY_MOVEMENT_CANDIDATE_V1[] (actual, P6.3)
        ↓
reconcile_security_movements()
        ↓
CA_ES_SECURITY_RECON_V1
```

## Expected set (derivado del doc de impacto, no recalculado)

Un item de impacto genera expectativa de movimiento si y solo si
`status=PROJECTED` y `quantity_delta` no es null:

```text
impact_type SECURITY_DELIVERY -> direction DELIVERY,
    isin = source_isin, quantity = |delta|
impact_type SECURITY_RECEIPT  -> direction RECEIPT,
    isin = target_isin (o source_isin si null), quantity = |delta|
otro impact_type con delta    -> expectation INDETERMINATE
                               (UNSUPPORTED_IMPACT_TYPE)
```

`expected_set_authoritative` = true solo si **ningún** item del doc es
INDETERMINATE/UNSUPPORTED — si la adjudicación del evento es
incompleta, no se puede afirmar que un movimiento sobra.

## Matching (clave justificada)

Clave: `(account_id, isin, direction)` — cuenta porque el movimiento
se anota por cuenta; instrumento porque la cantidad no es comparable
entre ISINs; dirección porque RECIBIR y ENTREGAR el mismo ISIN son
hechos distintos (un split real: DEBT old + CRED new).

```text
1 expected + 1 actual, qty iguales    -> MATCH
1 expected + 1 actual, qty distintas  -> QUANTITY_MISMATCH
                                        (delta = actual - expected)
1 expected + 0 actual                 -> MISSING_SECURITY_MOVEMENT
n expected o m actual (>1) en clave   -> INDETERMINATE
                                        MULTIPLE_EXPECTED /
                                        MULTIPLE_SECURITY_MOVEMENTS
0 expected + 1 actual:
    expected authoritative            -> UNEXPECTED_SECURITY_MOVEMENT
    expected no authoritative         -> INDETERMINATE
                                        EXPECTED_SET_INCOMPLETE
```

Comparación Decimal exacta. Sin tolerancia. Sin agregación entre
claves. La moneda nunca se reutiliza como semántica de valores.

## Recon item

```text
account_id, isin, direction
status              MATCH | QUANTITY_MISMATCH |
                    MISSING_SECURITY_MOVEMENT |
                    UNEXPECTED_SECURITY_MOVEMENT | INDETERMINATE
expected_quantity   (Decimal str | null)
actual_quantity     (Decimal str | null)
delta               (actual - expected | null)
expected_ref        "impacts[i]" | null
movement_ids[]      ids de los actual emparejados
reasons[]
evidence            expected: item.evidence; actual: provenance[]
                    (bilateral, verbatim)
```

Doc-level: `schema`, `generated_at`, `canonical_event_id`,
`event_type`, `source_impact_sha256`, `source_candidate_sha256s[]`,
`expected_set_authoritative`, `items[]`, `summary`.

Fail closed: schema incorrecto de cualquier input → ValueError;
candidate doc con `binding_status != BOUND` o `canonical_event_id`
distinto → ValueError (`CANDIDATE_NOT_BOUND` / `EVENT_MISMATCH`).

## Tests preregistrados

1. Expected DELIVERY 100 + actual DELIVERY 100 → MATCH.
2. Actual 90 vs expected 100 → QUANTITY_MISMATCH delta=-10.
3. Expected sin actual → MISSING_SECURITY_MOVEMENT.
4. Actual sin expected, expected authoritative →
   UNEXPECTED_SECURITY_MOVEMENT.
5. Ídem con expected no authoritative → INDETERMINATE
   EXPECTED_SET_INCOMPLETE.
6. Dos actual misma clave → INDETERMINATE MULTIPLE_SECURITY_MOVEMENTS.
7. Dos expected misma clave → INDETERMINATE MULTIPLE_EXPECTED.
8. CASH_DIVIDEND (impactos sin delta) + SECMOVE observado →
   UNEXPECTED_SECURITY_MOVEMENT (expected vacío autoritativo).
9. Evento con items UNSUPPORTED + actual → INDETERMINATE
   EXPECTED_SET_INCOMPLETE.
10. Candidate doc no BOUND → ValueError; evento distinto →
    ValueError.
11. Provenance bilateral preservada; determinismo; sin mutación.
</content>
