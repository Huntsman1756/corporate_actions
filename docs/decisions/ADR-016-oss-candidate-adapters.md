# ADR-016 — Adaptadores OSS de candidatos (extracción ≠ canonical facts)

Status: PROPOSED (G1-R, 2026-09-14)

## Context

G1 falló con errores de precisión financiera (`0,53 → 53`) y el baseline
congelado `c431830` sobre los 25 DEV de G1-R muestra que la extracción
basada en regex propias no generaliza: 26 MISSING, 4 WRONG_EVENT_TYPE,
3 DATE_MISBINDING, 1 FALSE_FINANCIAL_FACT, 1 FALSE_POSITIVE_EVENT.

El bake-off `g1r/results/spike-bakeoff.json` evaluó librerías OSS
maduras contra el ground truth DEV:

| Librería | Resultado DEV |
|---|---|
| pdfplumber 0.11.10 | 5.231 palabras con bbox/página, determinista |
| docling-parse 7.19.1 | 5.313 celdas con bbox — equivalente |
| price-parser 0.5.1 | 25/29 importes GT; **fallo crítico: `21,335 → 21335`** |
| recognizers-text-suite 1.0.2a2 | débil en importes ES (4/29) |
| dateparser 1.4.3 | 23/33 fechas (misses = `yyyymmdd` ya estructurado) |
| spaCy 3.8.16 Matcher `blank("es")` | 127 role matches, sin modelo ML |
| python-stdnum 2.2 | 12/12 ISINs válidos en doc, 0 checksums inválidos |

El hallazgo decisivo: price-parser interpreta `21,335` (precio OPA =
21,335 EUR) como `21335` — **reproduce el modo de fallo DECIMAL_SPLIT
que hundió G1**. Ninguna librería genérica conoce la semántica de
corporate actions: a qué evento pertenece un importe, qué rol tiene una
fecha, qué instrumento está afectado, o si el documento es siquiera
una CA.

## Decision

```text
OSS adapters may propose evidence/candidates.
No third-party parser may directly emit canonical facts.
```

Arquitectura:

```text
raw document (PDF/HTML/JSON)
    │
    ▼
EvidenceSpan[]              text + page + bbox + neighbours
    │  (adapter: pdfplumber | docling-parse | existing)
    ▼
CandidateFact[]             value + span + lexical context
    │  (adapters: price-parser, dateparser, spaCy Matcher,
    │   python-stdnum, …)
    ▼
ca-es semantic attribution  family / role / lifecycle / compatibility
    │  (core stdlib-only, reglas genéricas por failure_class)
    ▼
canonical facts             solo con validación + provenance completa
```

Reglas:

1. **Core stdlib-only.** Los adaptadores son opcionales y viven detrás
   de una interfaz `CandidateExtractor`; `src/ca_es` núcleo no importa
   dependencias externas. Los tests offline no pueden requerirlas
   (fixtures/candidatos pregrabados).
2. **Determinismo.** Solo se admiten componentes deterministas
   (sin inferencia ML en el camino crítico). `spaCy` se usa con
   pipeline `blank("es")` — tokenizador + Matcher, sin modelo.
3. **Provenance hasta el span.** Todo `CandidateFact` referencia su
   `EvidenceSpan` (página, bbox, lexema) — un candidato sin span no
   puede promoverse.
4. **Validación financiera propia.** La normalización de importes
   conserva `raw_lexeme` + `scale` + `Decimal` (ADR-008); un candidato
   `price-parser` con coma de 3 decimales NO se reinterpreta como
   separador de miles — la semántica decimal es de ca-es.
5. **Identity sin relajar.** `python-stdnum` valida checksums ISIN;
   `RapidFuzz` solo genera candidatos de búsqueda. El binding
   evento→instrumento sigue ADR-013: name-only nunca auto-binding.
6. **Sin condiciones específicas de documento.** Las reglas de
   atribución se escriben por `failure_class` genérica
   (`dev-failure-catalog.json`), nunca por seed/issuer/URL/hash.
7. **Licencias registradas.** MIT/BSD: pdfplumber, docling-parse,
   spaCy, dateparser, RapidFuzz, price-parser. **LGPL-2.1+**:
   python-stdnum — uso vía import (dynamic), sin vendoring; permanece
   opcional y fuera del import graph del core.
8. **Degradación explícita y determinista.**
   ```text
   core importable/runnable sin extras
   lazy imports de adapters
   versión del adapter/dependencia registrada en la salida
   ausencia de dependencia = comportamiento determinista
     (candidatos no propuestos), nunca crash oculto
   ```

## Consequences

- La capa de extracción se vuelve reemplazable; la autoridad canónica
  no se delega.
- `FALSE_FINANCIAL_FACT` por ambigüedad decimal queda atacado por la
  validación propia, no por la librería.
- Cada regla genérica G1-R registra en `g1r-changes.jsonl` su
  `trigger_failure_class` del catálogo congelado.
- El corpus HOLDOUT (15) permanece sellado: ninguna regla se diseña
  con su contenido.

## Out of scope

- Splink / linkage probabilístico: solo investigación offline, nunca
  canonical binding.
- Docling completo (pipeline ML): innecesario; basta `docling-parse`.
- Cualquier modelo ML no determinista en el camino crítico.
