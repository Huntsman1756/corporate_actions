# P14.20 — cross-transport tax conformance

Comparacion de evidencia fiscal equivalente entre FIN y
ISO 20022 sobre los modelos pinneados (Prowide SRU2025).

## MT564 ↔ seev.031 (notificacion, role=EXPECTED)

| semantica | FIN | seev.031 | notas |
|---|---|---|---|
| withholding rate | `:92A::TAXR//r` (pct) | `WhldgTaxRate/Rate` o `RateTpAndRate/Rate` | mismo tipo normalized; rate_type solo en seev |
| withholding amount | `:19B::TAXR//CCYa` / `:19B::WTAX//CCYa` | `WhldgTaxRate/Amt` / `AmtDtls/WhldgTaxAmt` | FIN TAXR ambiguo rate/amount por tag; seev los separa |
| second-level | `:92A::WITL//r` | `ScndLvlTax/{Rate,Amt}` | basis/hierarchy no definida en ninguno -> UNSUPPORTED |
| gross | `:19B::GRSS//CCYa`, `:92J::GRSS//` | `AmtDtls/GrssAmt`, `GrssDstrbtnRate` | rate vs amount segun contexto |
| net | `:19B::NETT//CCYa` | `AmtDtls/NetAmt`, `NetDstrbtnRate` | declarado en fuente, nunca derivado |
| tax credit | `:19B::TAXC//` | `TaxCdtAmt`, `TaxCdtRate` | |
| reclaim | `:19B::TXRC//` | `TaxRclmAmt`, `TaxRclmRate` | INFORMATION_ONLY (lifecycle, no aritmetica) |
| tax-free | `:19B::TXDF//` | `TaxFreeAmt` | |
| taxable basis | `:19B::TAXB//` | `TaxblIncmPerDvddShr`, `TaxblIncmPerShrCaltd` | |
| jurisdiction selector | (ninguno directo) | `CtryOfIncmSrc` | asimetria legitima: FIN no lo lleva |
| income type | (CAEV) | `IncmTp/Id` | |
| exemption | `:70E::TXPR` narrativa | `XmptnTp/{Cd,Id}` | seev estructurado; FIN solo texto |
| option scope | CAOPTN[k]/CACASH[k]/CSMV | CorpActnOptnDtls[k]/CshMvmntDtls | mapeo 1:1 por ocurrencia |
| voucher | (ninguno) | `TaxVchrDtls` | INFORMATION_ONLY |

## MT566 ↔ seev.036 (confirmacion, role=ACTUAL)

| semantica | FIN | seev.036 |
|---|---|---|
| gross | `19B:GRSS` (CSHMOVE) | `AmtDtls/GrssAmt` |
| net | `19B:NETT` | `AmtDtls/NetAmt` |
| tax explicito | `19B:TAXR`, `19B:WTAX`, `19B:WHHO` | `AmtDtls/WhldgTaxAmt`, `ScndLvlTaxAmt` |
| tax rate actual | `92A:TAXR` | `WhldgTaxRate/Rate` |
| otros componentes | `19B:CHAR`, `19B:OTHR`, `19B:FETC` | `SlctnFees`, `SndryOrOthrAmt`, `ChrgsFees` |
| option scope | CACONF[k]/CSHMOVE | CorpActnConfDtls/CshMvmntDtls |

## Reglas de paridad

- La proyeccion a `CA_ES_TAX_EVIDENCE_V1` produce los mismos
  `tax_type` para pares exactos (TAXR↔WhldgTaxRate,
  WITL↔ScndLvlTax, WTAX↔WhldgTaxAmt, NETT↔NetAmt,
  GRSS↔GrssAmt).
- No se fuerza paridad donde el estandar difiere: `CtryOfIncmSrc`,
  `XmptnTp`, `TaxVchrDtls`, `AddtlTax*` solo existen en seev;
  `FISC`, `NRAT`, `TXDF`, `SOIC` solo en FIN. Esas asimetrias son
  evidencia legitima, no error.
- Rates FIN (92x) y PercentageRate ISO se expresan ambos en
  puntos porcentuales -> `rate_unit: "PERCENTAGE"` uniforme; la
  conversion a fraccion es responsabilidad del calculo, no de la
  evidencia.
- `NotSpcfdRate` -> item rate con `rate_type: NOT_SPECIFIED`:
  evidencia declarada sin valor usable; no se interpreta.
