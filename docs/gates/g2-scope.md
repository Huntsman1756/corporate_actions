# G2 — Operational Canon (CNMV + BME Growth)

Status: **DRAFT v1 — PENDING APPROVAL, NOT YET TAGGED** (2026-09-16).
Parent: G1-R2 cerrado en FAIL — `g1r2/results/holdout-verdict.json`
(`996f214`). Matriz de capacidades: `docs/sources/support-matrix.md`.

G2 no es un gate de parser: es una fase de producto. Los namespaces
`g1r/` y `g1r2/` quedan congelados como evidencia.

## Por qué G2 y no G1-R3

Dos holdouts vírgenes consecutivos (G1-R, G1-R2) han demostrado que la
semántica documental de Portfolio en ampliaciones de capital es
demasiado heterogénea para seguir gastando holdouts en perfeccionar el
price extraction. La capacidad queda en cuarentena fail-closed
(`PORTFOLIO_CAPITAL_INCREASE_PRICE = QUARANTINED/UNSUPPORTED`); el
valor marginal vuelve a crecer consolidando las fuentes que sí tienen
evidencia firmada.

## Pregunta de G2

> ¿Podemos construir, con las capacidades/fuentes declaradas seguras,
> un corporate action canónico de principio a fin?

```
source document
→ event candidate
→ affected instrument
→ canonical CA
→ revisions / conflicts
→ operational dates & amounts
→ provenance
→ deterministic export
```

## Alcance

Dentro:

- Núcleo operativo: **CNMV** + **BME Growth** (evidencia firmada en
  oracle G1 y dev oracle). BOE/BORME como fuente oficial de soporte.
- Lifecycle/revisions, identidad del evento, affected instrument,
  fechas e importes operacionales con provenance.
- Salida operacional/export determinista sobre el canon.

Fuera:

- Portfolio `issue_price_per_share` en ampliaciones/derechos:
  QUARANTINED hasta fase nueva con holdout virgen (veredicto G1-R2
  SPENT_EVIDENCE; prohibido remediar contra ese holdout).
- Portfolio `ISIN_ROLE_DISAMBIGUATION`: P2 pendiente, no binding.
- OCR / image-only: fuera (`SCANNED_PDF_NO_TEXT_LAYER`).
- Generación ISO 15022/20022: fuera del core (ADR-010).

## Backlog heredado (no binding en G2 salvo decision humana)

```
ISSUE_PRICE_COMPONENT_CONFUSION (P0, Portfolio)   -> cuarentena activa
ISSUE_PRICE_LEXEME_VARIANT       (recall, Portfolio) -> cuarentena activa
ISIN_ROLE_DISAMBIGUATION         (P2)             -> abierto
SCANNED_PDF_NO_TEXT_LAYER        (P1_PENDING)     -> OCR fuera
```

## Formalización pendiente

Antes de ejecutar: preregistered `docs/gates/g2-preregistered.json`
(gates, oráculos, criterios de PASS/FAIL/INCONCLUSIVE) y aprobación
humana con tag `g2-protocol`, siguiendo el patrón G1-R2. Sin gates
preregistrados no hay evaluación: `NOT_RUN` != `PASS`.
