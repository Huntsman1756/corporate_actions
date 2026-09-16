# Support matrix — capacidades por fuente

Estado de capacidades tras los veredictos G1 / G1-R / G1-R2. La
política de ingesta autoritativa sigue en `source-policy.json`; esta
matriz congela qué puede emitir cada fuente con evidencia firmada.

| Fuente / capacidad | Estado | Evidencia |
|---|---|---|
| CNMV | seguir desarrollando | oracle G1 56/56; núcleo operativo G2 |
| BME Growth | seguir desarrollando | oracle G1; núcleo operativo G2 |
| BOE/BORME | seguir desarrollando | canary Parlem (`tests/canaries/test_parlem_real.py`) |
| Portfolio — dividendos/reducciones ya cubiertos | mantener como regression | dev oracle + spent evidence |
| Portfolio — capital increases: event detection | usable con cautela | event_type 11/11 correcto en holdout G1-R2 |
| Portfolio — capital increases: `issue_price_per_share` | **QUARANTINED / UNSUPPORTED** | `g1r2/results/holdout-verdict.json`; enforcement `_ISSUE_PRICE_QUARANTINED` en `src/ca_es/sources/parsers/portfolio.py` |
| Portfolio — ISIN role resolution | P2 pendiente | deuda `ISIN_ROLE_DISAMBIGUATION` (POEX-DOC-38393, conflicts=1 explícito) |
| Portfolio — OCR / image-only | fuera / futuro | `SCANNED_PDF_NO_TEXT_LAYER` (G1-R) |
| ESMA/FIRDS | REFERENCE_ONLY | `ListingResolver` (ADR) |
| Iberclear | REFERENCE_ONLY | `PUBLIC_INGEST_INTERFACE_NOT_PROVEN` |

## Gate ledger

```text
G1      FAIL      — histórico
G1-R    FAIL      — histórico (AMOUNT_ROLE_MISBINDING, POEX-DOC-39649)
G1-R2   FAIL      — histórico (ISSUE_PRICE_COMPONENT_CONFUSION +
                    ISSUE_PRICE_LEXEME_VARIANT; holdout SPENT_EVIDENCE)
G2      PASS      — Operational Canon (g2/results/verdict.json;
                    8/8 gates, casos A–E+AUX, export byte-determinista;
                    scope: capacidades soportadas, núcleo CNMV+BME Growth)

PORTFOLIO_CAPITAL_INCREASE_PRICE = QUARANTINED / UNSUPPORTED
```

La cuarentena no es un fix contra el holdout gastado: G1-R2 sigue
siendo FAIL para siempre. Levantarla exige fase nueva con holdout
virgen.

## Siguiente fase

G2 — Operational Canon: **PASS** (`g2/results/verdict.json`,
`g2/state.json`). `CA_ES_OPERATIONAL_CANON_V1` probado end-to-end sobre
el qualification corpus preregistrado para las capacidades soportadas.
El veredicto no afirma recall de parsers ni soporte universal de CAs
españoles — ambos fuera del scope de G2. La siguiente fase se decide
desde producto, no desde parsing.
