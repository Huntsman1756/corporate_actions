# P14.0 — Capability audit (pinned Prowide SRU2025)

Verification method: `javap`/`jar tf` over the pinned jars
(`pw-swift-core-SRU2025-10.3.19.jar`,
`pw-iso20022-SRU2025-10.3.10.jar`) plus live probes of the JVM
adapter. All fields below were emitted as transport facts by the
existing generic walkers — **no new parser was built**.

## FIN — MT564 (notification)

Facts path: `...CAOPTN[n]/...` (option-scoped via `facts[].path`).

| qualifier | fact key | meaning (SWIFT MRG) | scope | contributes to |
|---|---|---|---|---|
| `:19B::TAXR//EURx` | `19B:TAXR.amount` | tax amount | CASHMOVE of a CAOPTN | EXPECTED_TAX / ACTUAL_TAX |
| `:92A::TAXR//x%` | `92A:TAXR.rate` | taxation rate | CASHMOVE of a CAOPTN | EXPECTED_TAX |
| `:92A::WITL//x%` | `92A:WITL.rate` | second-level withholding rate | CASHMOVE | EXPECTED_TAX (component) |
| `:19B::NETT//EURx` | `19B:NETT.amount` | net cash amount | CASHMOVE | NET_EXPECTED (source-declared) |
| `:19B::GRSS//EURx` | `19B:GRSS.amount` | gross amount | CASHMOVE | gross basis |
| `:19B::TXDF//x` | `19B:TXDF.amount` | tax-free amount | CASHMOVE | EXPECTED_TAX (component) |
| `:19B::TXRC//x` | `19B:TXRC.amount` | tax reclaim amount | CASHMOVE | INFORMATION_ONLY (reclaim lifecycle, not arithmetic on initial payment) |
| `:19B::TAXC//x` | `19B:TAXC.amount` | tax credit | CASHMOVE | EXPECTED_TAX (component) |
| `:19B::WTAX//x` | `19B:WTAX.amount` | withholding tax amount | CASHMOVE | EXPECTED_TAX |
| `:19B::NRAT//x` | `19B:NRAT.rate_or_amount` | non-distributed rate | CASHMOVE | INFORMATION_ONLY |
| `:92A::FISC//x` | `92A:FISC.rate` | fiscal stamp | CASHMOVE | INFORMATION_ONLY |
| `:19B::TAXB//x` | `19B:TAXB.amount` | taxable basis | CASHMOVE | EXPECTED_TAX (basis override) |

Repeatability: TAXR/WITL repeat inside CASHMOVE; multiple
occurrences produce multiple facts (never "first wins").

## FIN — MT566 (confirmation of movement)

Same qualifier space; additionally `CASHMOVE`/`STAT` sequences.
`19B:NETT`, `19B:GRSS`, `19B:TAXR`, `19B:WTAX`, `19B:FETC`,
`19B:OTHR`, `19B:CHAR` observed as distinct components —
explicit component identity, never gross−net inference.
P4.2 whitelist already maps `PSTA/NETO/GRSS` for the movement
basis.

## ISO 20022 — seev.031 (notification)

Verified paths on `MxSeev03100115` (fixture probe):

| model path | fact key | meaning | contributes to |
|---|---|---|---|
| `.../AmtDtls/GrssAmt/Amt` | `GrssAmt` | gross amount | basis |
| `.../AmtDtls/NetCshAmt/Amt` | `NetCshAmt` | net amount | NET_EXPECTED (source-declared) |
| `.../AmtDtls/WhldgTaxAmt/Amt` | `WhldgTaxAmt` | withholding tax amount | ACTUAL/EXPECTED_TAX |
| `.../AmtDtls/TaxCdtAmt/Amt` | `TaxCdtAmt` | tax credit amount | EXPECTED_TAX (component) |
| `.../AmtDtls/TaxRclmAmt/Amt` | `TaxRclmAmt` | reclaim amount | INFORMATION_ONLY |
| `.../AmtDtls/ScndLvlTax/Amt` | `ScndLvlTax` | second-level tax amount | component |
| `.../WhldgTaxRate/Rate` | `WhldgTaxRate` | withholding rate (choice) | EXPECTED_TAX |
| `.../ScndLvlTax/Rate` | `ScndLvlTax` | second-level rate | component |
| `.../WhldgTaxRate/NotSpcfdRate` | `NotSpcfdRate` | declared-but-unspecified rate | INDETERMINATE evidence |
| `.../CtryOfIncmSrc` | `CtryOfIncmSrc` | source country selector | jurisdiction selector |
| `.../XmptnTp` | `XmptnTp` | exemption type (explicit) | exemption evidence |
| `.../IncmTp/Id` | `IncmTp` | income type code | rule predicate input |
| `.../TaxVchrDtls/*` | `TaxVchrDtls` | voucher details | INFORMATION_ONLY |

## ISO 20022 — seev.036 (movement confirmation)

Same `AmtDtls` family + `TaxVchrDtls`; components are explicit.
`WhldgTaxAmt` here is **actual** tax evidence (movement, not
notification).

## Gaps / asymmetries (documented, not forced to parity)

- MT carries `TAXR` both as rate (`92A`) and amount (`19B`); seev
  splits them cleanly (`WhldgTaxRate/Rate` vs `WhldgTaxAmt`).
- `CtryOfIncmSrc` (seev) has no direct FIN selector; jurisdiction
  comes from rule `jurisdiction` + account profile.
- `FISC`, `NRAT`, `TXDF` exist only in FIN.
- Second-level tax hierarchy/basis is **not** defined by either
  standard at the field level → structural support only,
  `UNSUPPORTED_MULTI_LEVEL_TAX` when basis is unproven.
