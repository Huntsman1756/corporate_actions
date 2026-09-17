# P6.0 — Capability Audit / Semantic Freeze (Positions & Impact)

Status: **DONE — FROZEN**.

Pregunta única:

> Con los hechos canónicos y la semántica de fuente demostrados hoy,
> ¿qué impacto sobre posiciones puede probarse — operando por operando
> — sin inferencia financiera?

Método: inspección de `g3/input/canon.json` (corpus canónico),
`docs/semantics/canonical-registry.json`, parsers de fuente
(`bme_growth`, `borme`, `base`), contratos P2.0 (`entitlement_engine`),
P5.x (eligibility/instruction), modelo Prowide SRU2025-10.3.19
(`MT566.java` del tag pinneado), fixtures MT566 existentes y ejemplos
reales del estándar (Euroclear MT566 spec, Erste Bank SR sample, CDS
CA guide). `vn-corporate-actions` solo existe como referencia de
roadmap (no vendored); es irrelevante para V1 porque el bloqueo es
prueba semántica, no disponibilidad de fórmulas.

Corpus canónico observado:

```text
CASH_DIVIDEND      3 eventos
CAPITAL_INCREASE   3 eventos
RIGHTS_ISSUE       1 evento
SPLIT              0 eventos canónicos (solo raw frames BME Growth)
STOCK_DIVIDEND     0 (internal_field=null: nunca alcanza canon)
SCRIP_DIVIDEND     0
```

## Matriz de capacidad por familia

| Familia | Clasificación | Razón dominante |
| --- | --- | --- |
| CASH_DIVIDEND | **SUPPORTED** | CASH_RECEIVABLE = composición de `CA_ES_ENTITLEMENT_V1` (P2.0); sin delta de valores |
| SPLIT | **UNSUPPORTED** (V1) | factor direction probada; basis date NO demostrable |
| STOCK_DIVIDEND | **UNSUPPORTED** | `internal_field=null`; inalcanzable y sin ratio probado |
| SCRIP_DIVIDEND | **UNSUPPORTED** | electivo (P5); `holder_choice` no demostrable; sin eventos |
| RIGHTS_ISSUE | **UNSUPPORTED** | instrumento de derechos ausente del canon; ejercicio electivo; sin basis date |
| CAPITAL_INCREASE | **UNSUPPORTED** | facts a nivel emisión, no transformación por posición |

Detalle por operando (qué está demostrado y qué no):

### CASH_DIVIDEND — SUPPORTED

| Operando | Estado | Evidencia |
| --- | --- | --- |
| source instrument | PROVEN | `affected_instrument.isin` / `instrument.isin` (EXPLICIT) |
| eligibility basis | PROVEN | `date.record_date` + regla P2.0 `POSITION_AT_RECORD_DATE` (snapshot debe igualar record_date; antes/después no prueba) |
| input quantity | PROVEN | posición `CA_ES_POSITIONS_V1` (Decimal) |
| cash amount | PROVEN | `amount.gross_per_share` × entitled qty vía `compute_entitlements` — se compone el doc P2.0, **no se reimplementa la fórmula** |
| effective date | PROVEN | `date.payment_date` (informativa, value date del cash) |
| security delta | N/A | dividendo cash no mueve valores: delta 0 |
| target instrument | N/A | no hay instrumento destino |
| rounding/fractions | N/A | multiplicación exacta Decimal |

Impacto V1: `CASH_RECEIVABLE` por posición ENTITLED; el estado del
entitlement se propaga verbatim (INDETERMINATE/NOT_ENTITLED → el item
de impacto conserva el status, no se reinterpreta).

### SPLIT — UNSUPPORTED (V1)

Factor direction **probada empíricamente** contra dos eventos reales
del corpus BME Growth (no contra el nombre del campo API, que es
engañoso):

```text
Redegal (Splits,  splitDate 2026-06-09):
    dividingFactor=10, multiplyingFactor=1
    realidad: SPLIT 10:1 forward — "10 acciones nuevas por cada
    acción antigua" (OIR 2026-05-07; cfr. BORME-C-2026-527)
Vanadi  (Mergers, splitDate 2025-03-27):
    dividingFactor=1,  multiplyingFactor=10
    realidad: CONTRASPLIT — "1 acción nueva de 0,50 € por cada
    10 antiguas de 0,05 €" (AVISO BME Growth 2025-03-25)
```

Única fórmula consistente con ambas filas:

```text
new_quantity = old_quantity × dividing_factor / multiplying_factor
(dividing_factor ≡ proporción posterior; multiplying_factor ≡
 proporción anterior)
```

Aun así, la familia queda UNSUPPORTED en V1:

| Operando | Estado | Evidencia |
| --- | --- | --- |
| source instrument | PROVEN | `instrument.isin` |
| target instrument | PARTIAL | `instrument.last_isin` cuando presente (Redegal sí; Vanadi no → `MISSING_TARGET_INSTRUMENT`) |
| ratio/factor | PROVEN | fórmula anterior, verificada en 2 eventos reales |
| **eligibility basis** | **NOT PROVEN** | único campo: `date.split_effective_date`. Un snapshot custodiado en la fecha efectiva ya es post-canje; no existe campo canónico para la posición pre-evento (último cum) y antes/después no prueba la posición canjeada (regla POSITION_AT_*) |
| fraction treatment | NOT PROVEN | contrasplit de saldo no múltiplo → fracción sin semántica de cash-in-lieu en canon → `FRACTION_TREATMENT_UNKNOWN` |
| effective date | PROVEN | `date.split_effective_date` |
| cash payable | N/A | split no genera cash per se |

Sin basis date demostrable no hay input quantity probado → sin
`POSITION_TRANSFORM` implementable. La fórmula queda registrada aquí
para un scope futuro cuando exista campo de fecha pre-evento.

### STOCK_DIVIDEND — UNSUPPORTED

`internal_field=null` en el registry: ninguna fuente lo materializa
como `event_type` canónico; sin eventos ni ratio probado. Inalcanzable.

### SCRIP_DIVIDEND — UNSUPPORTED

Registry: PROVEN solo condicionado a `holder_choice=PROVEN`. Es
electivo: el impacto depende de la elección (flujo P5) y ningún campo
canónico prueba la elección del tenedor. Sin eventos en corpus.

### RIGHTS_ISSUE — UNSUPPORTED

Canon `03888619` lleva `ratio.terms {new_shares:20, old_shares:39}`
(probado: "N nuevas por cada M antiguas", BORME),
`entitlement_basis.eligible_shares` (total assertado,
SUBJECT_TO_ADJUSTMENT — no es base por posición),
`amount.issue_price_per_share` (capability QUARANTINED_UNSUPPORTED en
source-policy) y `date.period_*`/`admission_date`.

Bloqueos por posición: identidad del instrumento de derechos ausente
del canon (`MISSING_TARGET_INSTRUMENT`); la asignación "1 derecho por
acción" es convención, no claim del canon; la suscripción es electiva
(P5) → ni `RIGHTS_RECEIPT` ni `CASH_PAYABLE` son automáticos; sin
basis date canónico.

### CAPITAL_INCREASE — UNSUPPORTED

Facts a nivel emisión (`shares.new_shares`, `shares.old_shares`,
`amount.liberated_percentage`, `amount.rights_price`,
`date.period_*`), no transformación por posición:

- con derecho preferente → electivo (P5);
- con exclusión del derecho (`035e32ca`) → el tenedor no recibe nada;
- liberado pro-rata → `shares.new_shares/old_shares` son totales de la
  emisión, no un ratio por posición probado.

Ninguna variante es demostrable por posición con los campos actuales.

## Consecuencia para la vertical P6

```text
P6.1  CA_ES_POSITION_IMPACT_V1        -> CASH_RECEIVABLE solamente,
                                       componiendo CA_ES_ENTITLEMENT_V1
P6.2  CA_ES_PROJECTED_POSITIONS_V1    -> aplicador genérico de deltas;
                                       en V1 solo se alcanza delta=0
                                       (CASH_DIVIDEND); el contrato
                                       soporta SECURITY_* para
                                       familias futuras
P6.3  MT566 SECMOVE candidate         -> implementable de forma
                                       independiente (evidencia
                                       entrante, no depende de P6.1)
P6.4  securities reconciliation       -> implementable a nivel de
                                       contrato; con reglas V1 el lado
                                       esperado nunca lleva impactos
                                       de valores -> outcomes reales:
                                       UNEXPECTED_SECURITY_MOVEMENT /
                                       INDETERMINATE; MATCH/
                                       QUANTITY_MISMATCH/MISSING se
                                       ejercitan a nivel de contrato
P6.5  excepciones P3.5                -> extensión aditiva si P6.4 existe
```

## Evidencia MT566 SECMOVE (para P6.3)

Modelo Prowide SRU2025-10.3.19 (`MT566.java` del tag pinneado):
`D=CACONF` > `D1=SECMOVE` (O, repetitivo) > `D1b=RECDEL` (O).

Spec Euroclear MT566 (guía de implementación) + ejemplo real Erste
Bank SR:

```text
SECMOVE (por ocurrencia = un movimiento de valores):
    22H::CRDB//CRED|DEBT   (M)  dirección: CRED=abono(recibo),
                                DEBT=cargo(entrega) — verificado en
                                muestra real: DEBT old qty + CRED new
                                qty para un split 10:1
    35B:ISIN               (M)  instrumento movido — EXPLÍCITO en el
                                mensaje (no se infiere del canon)
    36B::PSTA//<qty>       (M)  posting quantity (qty movida real)
    92D::NEWO//<n>/<m>     (O)  ratio new-for-old (provenance, no usado
                                para status)
    98A::POST//<date>      (M)  posting date (fecha efectiva en cuenta)
    98A::PAYD//<date>      (M)  payment date (provenance)
USECU: 97A::SAFE//<acct>   cuenta de custodia del mensaje (la cuenta no
                            vive dentro de SECMOVE)
```

Whitelist preregistrada P6.3: `CRDB//CRED`→RECEIPT,
`CRDB//DEBT`→DELIVERY; cualquier otro indicador/código →
`UNSUPPORTED_DIRECTION`. Cantidad solo `36B::PSTA`; otros qualifiers
(`93B` balances, `92D` ratios) nunca son cantidad de movimiento.

## Stop conditions evaluadas

- SPLIT requeriría un campo de fecha pre-evento que no existe →
  semántica no demostrada → UNSUPPORTED documentado (STOP #1/#3 del
  mandato, resuelto honestamente).
- Ninguna fórmula se implementa "porque el campo existe".
</content>
