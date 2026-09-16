# P4.2 — MT566 -> cash movement candidate

Status: **FROZEN — PENDING IMPLEMENTATION**.
Parent: P4.1 DONE (`4c54644`).

Cierra el circuito operativo:

```text
MT566 FIN
  -> CA_ES_SWIFT_MT_FACTS_V1          (P4.0)
  -> CA_ES_SWIFT_CA_MESSAGE_V1
     + CA_ES_SWIFT_EVENT_BINDING_V1   (P4.1)
  -> CA_ES_SWIFT_CASH_CANDIDATE_V1    (P4.2)
  -> CA_ES_CASH_MOVEMENTS_V2          (solo si PROJECTABLE)
  -> P3 reconcile -> P3.5 cases
```

## Frontera intermedia

No se proyecta directamente a `CA_ES_CASH_MOVEMENTS_V2`. El candidate
es un artefacto propio que demuestra explícitamente:

- `binding_status == BOUND`;
- cuenta/custody identificable (`97A::SAFE` account);
- importe único y moneda única;
- `amount_basis` derivable de un qualifier SWIFT **preregistrado**;
- sin contradicción entre occurrences del mismo qualifier;
- provenance completa hasta tag/sequence.

## Whitelist SRU2025 de qualifiers de importe (19B)

Preregistrada, cerrada. Sólo estos qualifiers son elegibles como
importe del posting; cualquier otro `19B` (WITD, TAXR, CHAR, INTR,
SOIC...) **no** es importe reconciliable.

```text
PSTA  (posted amount) -> amount_basis UNKNOWN
NETO  (net amount)    -> amount_basis NET
GRSS  (gross amount)  -> amount_basis GROSS
```

Regla crítica:

```text
qualifier explícito gross -> GROSS
qualifier explícito net   -> NET
sin evidencia suficiente  -> UNKNOWN
```

Nunca `MT566 => NET`, nunca `actual < gross => NET`.

Selección determinista del importe del posting: `PSTA > NETO > GRSS`
(el importe efectivamente abonado primero; GRSS es el importe bruto
del movimiento declarado). Varias occurrences del qualifier elegido
con valores distintos -> `CONFLICTING_AMOUNT`. Más de una sub-secuencia
CSMV con importe elegible -> `MULTIPLE_CASH_MOVEMENTS` (P3 no agrega).

## Estados del candidato

```text
PROJECTABLE / INDETERMINATE / UNSUPPORTED
```

`INDETERMINATE` conserva razones:

```text
EVENT_NOT_BOUND
MISSING_ACCOUNT
MISSING_AMOUNT
CONFLICTING_AMOUNT
MISSING_CURRENCY
UNKNOWN_AMOUNT_BASIS
MULTIPLE_CASH_MOVEMENTS
```

Extensiones implementadas sobre la lista mínima: `CONFLICTING_ACCOUNT`
(varias cuentas `97A::SAFE` distintas), `CONFLICTING_CURRENCY`.
`UNSUPPORTED` cubre `UNSUPPORTED_MESSAGE_TYPE` (cualquier mensaje que
no sea MT566 — el candidate es MT566-only) y `UNSUPPORTED_CA_EVENT`.

Sólo `PROJECTABLE` emite el objeto `movement` (shape
`CA_ES_CASH_MOVEMENTS_V2`). `UNKNOWN_AMOUNT_BASIS` (p.ej. PSTA) **sí**
puede ser PROJECTABLE con `amount_basis: UNKNOWN` — P3.1 ya lo trata
honestamente como `INDETERMINATE` en recon; el candidato deja constancia
de la razón en vez de bloquear la conversión.

## Fuera de alcance

ISO 20022, MT565, agregación/netting, elección de importe fuera de la
whitelist, mutación del canon, proyección de MT566 a otras cosas que
no sean cash candidates, workflow nuevo.
