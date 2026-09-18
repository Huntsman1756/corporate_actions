# P13.6–P13.10 — cash account observation & binding

```text
CA_ES_SWIFT_MT_FACTS_V1 (MT940/MT950)
CA_ES_SWIFT_MX_FACTS_V1 (camt.053.001.13 / camt.054.001.13)
        │
        ▼
CA_ES_CASH_ACCOUNT_OBSERVATION_V1   ← lo que el feed prueba
        │
        ▼  binding EXPLICITO (referencias, nunca amount/date)
CA_ES_CASH_MOVEMENTS_V2             ← solo entries BOUND
        │
        ▼
CA_ES_CASH_FEED_RECON_V1            ← ¿apareció el movement en el feed?
```

La observación NO es un movement: conserva entries completas con
referencias, reversal, narrativa. `credit` NO significa "receipt
de CA"; `debit` NO significa "pago de suscripción".

## Contrato

```json
{
 "schema": "CA_ES_CASH_ACCOUNT_OBSERVATION_V1",
 "source_standard": "ISO15022|ISO20022",
 "source_message_identifier": "camt.054.001.13|MT940|…",
 "input_sha256": "...",
 "account_id_raw": "id verbatim",
 "entries": [{
   "entry_id": "ACSV ref / NtryRef",
   "debit_credit": "CRDT|DBIT",
   "reversal": false,
   "status": "BOOK|PDNG|null",
   "amount": "1562.50", "currency": "EUR",
   "booking_date": "YYYY-MM-DD|null",
   "value_date": "YYYY-MM-DD|null",
   "account_servicer_reference": "…", "customer_reference": "…",
   "transaction_reference": "…",
   "details": {"CdOrPrtry": "…", "EndToEndId": "…", "InstrId": "…",
               "NtryDtls": "…", "references": {}},
   "narrative": "field 86 / AddtlNtryInf — verbatim, sin parsear",
   "location": "tag 61 k-ésimo / Ntry[k]"
 }],
 "balance_summary": {"opening": "…", "closing": "…"},
 "parse_status": "OK|UNSUPPORTED|PARSE_ERROR"
}
```

## Mapping camt.053/054 (modelo .001.13)

| semantica | elemento |
|---|---|
| cuenta | `Acct/Id/IBAN|Othr/Id`, `Acct/Ccy` |
| statement/notification ref | `Stmt/Id`, `Ntfctn/Id` |
| entry | `Ntry[k]` — locators indexados |
| entry ref | `AcctSvcrRef` → `entry_id` |
| amount | `Amt` + `Ccy` |
| dirección | `CdtDbtInd` |
| reversal | `RvslInd` |
| status | `Sts/Cd` |
| dates | `BookgDt/Dt|DtTm`, `ValDt/Dt|DtTm` |
| refs | `NtryDtls/TxDtls/Refs/{EndToEndId,InstrId,ChqNb,…}` |
| tx code | `BkTxCd/CdOrPrtry` |
| narrativa | `AddtlNtryInf`, `TxDtls/AddtlTxInf` — verbatim |

## Mapping MT940/950 (Prowide Core)

| semantica | campo | notas |
|---|---|---|
| cuenta | `25` | verbatim |
| statement ref | `20` (940: `20C?` no — tag 20; 950: `20`) | |
| entry | `61` — value date, D/C (`C`/`D`/`RC`/`RD`), amount, tx type+customer ref, bank ref | |
| narrativa | `86` asociada al `61` por orden de tags | PROFILE_REQUIRED para semántica |
| opening/closing | `60F`/`60M` / `62F`/`62M` | `balance_summary` |
| status | — | MT no expone booked/pending → null |
| reversal | `RC`/`RD` en D/C mark | `reversal: true` |

Booking date: el año no está en `61` — se deriva SOLO de `60F`/`62F`
del mismo statement (documentado en `booking_date_basis`); si no,
null. Nunca "año actual".

## Binding explícito (custody_bind.py)

Solo `BOUND` emite `CA_ES_CASH_MOVEMENTS_V2`:

1. `reference_map` del profile — una ref de la entry
   (AcctSvcrRef/EndToEndId/InstrId/customer/transaction ref) match
   exacto → event_id.
2. `send_ledger` — AcctSvcrRef corresponde a un delivery registrado
   con correlación conocida.
3. `movement_reference` — la entry cita una referencia única de un
   movement ya conocido.

Suficiencia de identidad primero: sin ref de statement, sin cuenta
y sin entry_id → `INSUFFICIENT_IDENTITY`. Múltiples refs a events
distintos → `AMBIGUOUS`. Referencia sin mapeo → `NO_MATCH` +
`REFERENCE_UNRESOLVED`. Propietario sin profile → `PROFILE_REQUIRED`.

JAMÁS por amount/date/currency/account — aunque el match sea único.

Movements emitidos: `movement_id` determinista
`CMOV-<sha(entry refs)>`, `amount_basis` honesto
(`GROSS`/`NET`/`UNKNOWN` — nunca inferido por comparación),
`sign` desde débito, provenance completa a la entry.

## Cash feed recon (custody_recon.py)

`CA_ES_CASH_FEED_RECON_V1` — capa distinta del P3 económico:

- movements conocidos (e.g. MT566) × entries del feed por ref
  explícita → `MATCH` / `CASH_ACCOUNT_AMOUNT_MISMATCH` /
  `CASH_MISSING_IN_ACCOUNT_FEED`.
- entries del feed sin movement asociado →
  `CASH_UNEXPECTED_ACCOUNT_ENTRY`.
- sin refs emparejables → `INDETERMINATE`.

Comparación Decimal exacta. "Apareció en el feed" ≠ "económicamente
correcto" — eso queda en P3.
