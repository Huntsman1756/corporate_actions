# P6.3 — MT566 Securities Movement Candidate

Status: **FROZEN — PENDING IMPLEMENTATION**.
Parent: P6.1/P6.2 DONE; evidencia SECMOVE en `p60-capability.md`.

Pregunta única:

> Dado un MT566 real, ¿qué movimientos de valores declara
> explícitamente — por SECMOVE, sin combinar ni inferir?

```text
MT566 FIN -> adapter JVM -> CA_ES_SWIFT_MT_FACTS_V1
         -> P4.1 project_ca_message + bind_event (BOUND requerido)
         -> CA_ES_SWIFT_SECURITY_MOVEMENT_CANDIDATE_V1
```

Análogo a P4.2 cash candidate, pero separado: este módulo nunca toca
`19B` ni emite cash movements.

## Mapeo SECMOVE preregistrado (SRU2025-10.3.19 + Euroclear + Erste)

Facts con `sequence == "CACONF/SECMOVE"`; agrupación por ventana de
tag index (`evidence_locator block4.tag[i]`):

- cada SECMOVE empieza por un fact `22H` (primer fieldset-22, M);
- integridad: `count(22H) == count(35B)` en el path — si difiere
  (fieldset-22 repetido, estructura inusual) → doc INDETERMINATE
  `AMBIGUOUS_SECMOVE_STRUCTURE`, sin atribución;
- ventana_i = facts con índice en `[idx(22H_i), idx(22H_{i+1}))`;
- dentro de la ventana debe haber exactamente un `35B` (si no →
  movimiento INDETERMINATE `CONFLICTING_INSTRUMENT`/`MISSING_ISIN`).

Por movimiento:

```text
22H::CRDB//CRED   -> direction RECEIPT
22H::CRDB//DEBT   -> direction DELIVERY
otro qualifier 22H / otro código -> UNSUPPORTED_DIRECTION*
35B .isin         -> isin (explícito; nunca del canon)
36B::PSTA .quantity           -> quantity (Decimal, coma SWIFT)
36B::PSTA .quantity type code -> quantity_type; solo UNIT soportado
                                 (FAMT/otros -> UNSUPPORTED_QUANTITY_TYPE)
98A::POST .date   -> posting_date (efectiva en cuenta; M)
98A::PAYD .date   -> provenance solamente
92D::NEWO         -> provenance solamente (ratio new/old raw)
97A::SAFE         -> account_id (cualquier secuencia; múltiples
                     valores distintos -> CONFLICTING_ACCOUNT)
```

Múltiples `36B::PSTA` en una ventana: mismo valor → una cantidad;
valores distintos → `CONFLICTING_QUANTITY`. Ídem `98A::POST`
(`CONFLICTING_POSTING_DATE`) y `35B` ISIN (`CONFLICTING_INSTRUMENT`).

Cada SECMOVE = un candidato de movimiento. Nunca se combinan.

## Binding de evento

Reutiliza P4.1 sin cambios de semántica: `project_ca_message` +
`bind_event`. Extensión aditiva preregistrada: `CAEV_MAP` gana
`SPLF -> SPLIT` (UHB ISO 15022 CAEV code list); DVCA sigue igual.

`binding_status != BOUND` → movimientos INDETERMINATE con
`EVENT_NOT_BOUND`. `UNSUPPORTED_CA_EVENT` → doc UNSUPPORTED.

## Output

```text
CA_ES_SWIFT_SECURITY_MOVEMENT_CANDIDATE_V1

schema, generated_at, message_identifier "MT566", input_sha256,
canonical_event_id, binding_status, event_type, caev,
caon/caop (raw provenance CACONF), reasons[] (doc-level),
status doc-level:
    PROJECTABLE   todos los movimientos PROJECTABLE y >=1
    INDETERMINATE alguno INDETERMINATE o sin SECMOVE
    UNSUPPORTED   message_type/event no soportado
movements[] (uno por SECMOVE):
  movement_id     "SWIFT-<input_sha16>-SECMOVE<i>"
  account_id, isin, direction (RECEIPT|DELIVERY|null),
  quantity (Decimal str|null), quantity_type, posting_date,
  status (PROJECTABLE|INDETERMINATE|UNSUPPORTED), reasons[],
  provenance[]  (tag/qualifier/sequence/occurrence/locator/raw)
```

## Fuera de alcance

- inferir RECEIPT/DELIVERY del signo, del CAEV o de `92D::NEWO`;
- inferir target ISIN del canon cuando el SECMOVE no lo declara;
- agregar movimientos; usar `93B` balances como cantidad;
- 19B/cash (P4.2 lo cubre aparte); ISO 20022;
- `CA_ES_SECURITY_MOVEMENTS_V1` separado: el candidato PROJECTABLE ya
  es el movimiento estable (como `movement` en P4.2).

## Tests preregistrados

1. MT566 con dos SECMOVE (DEBT old / CRED new, estructura oficial
   USECU/CACONF) → 2 movimientos PROJECTABLE con dirección, ISIN,
   cantidad y posting_date correctos; e2e JVM real (NoSkips).
2. Código CRDB desconocido / qualifier 22H distinto → UNSUPPORTED_*.
3. Cantidad type != UNIT → UNSUPPORTED_QUANTITY_TYPE + raw.
4. Dos 36B::PSTA con valores distintos → CONFLICTING_QUANTITY.
5. Estructura 22H≠35B → doc INDETERMINATE AMBIGUOUS_SECMOVE_STRUCTURE.
6. Sin 97A::SAFE → MISSING_ACCOUNT; dos SAFE distintos →
   CONFLICTING_ACCOUNT.
7. Sin 35B en ventana → MISSING_ISIN; dos ISIN → CONFLICTING_INSTRUMENT.
8. Binding no BOUND → movimientos INDETERMINATE EVENT_NOT_BOUND.
9. Message != MT566 → UNSUPPORTED_MESSAGE_TYPE.
10. Sin SECMOVE → doc INDETERMINATE NO_SECMOVE_BLOCKS.
11. Determinismo, no mutación, provenance con locators.
12. Malformed FIN → PARSE_ERROR por adapter (e2e).
</content>
