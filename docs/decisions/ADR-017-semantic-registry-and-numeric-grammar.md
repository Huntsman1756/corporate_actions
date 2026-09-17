# ADR-017 — Semantic registry canónico, NumericGrammar y oracle con provenance

Status: PROPOSED (G1-R, 2026-09-14)

## Context

La iter-1 de G1-R (`FALSE_FINANCIAL_SEMANTIC_ANCHOR`) resolvió sus
objetivos pero la revisión sacó tres deudas estructurales:

1. **Field semantics**: `"0,37 euros por acción"` en un
   `CAPITAL_INCREASE` se emitió como `amount.gross_per_share` cuando el
   modelo ya dispone de `amount.issue_price_per_share`. El número era
   correcto; el fact era incorrecto por `field_path`. El oracle G1
   heredó ese error de GT al construirse re-ejecutando `c431830`
   (erratum documentado en V2.1).
2. **Auditabilidad**: el resultado del rerun congelaba `result_sha` y
   `populated_fields` pero no los valores — la afirmación
   `27,15 → 21,335` no era reconstruible desde el artefacto.
3. **Semántica inventada**: la taxonomía propia de `ca-es` (event
   types, date roles, amount roles) no está anclada a referencias
   externas verificables. ADR-009 fijó el patrón
   (`UNMAPPED` por defecto, `PROVEN` solo con extracto verificado)
   pero el registry quedó limitado a event_type/FIBO.

En paralelo, la especificación BME/Iberclear «Machine Readable
Corporate Actions Technical Specifications» ed. 1.01 (2024-07-19)
aporta un field model nativo (AMP, DAC, DEE, FUS, FVL, OPA, SPC, SPL…)
con campos explícitos de fecha por rol, ratios (`DEE-PROPORCIÓN-
ANTERIOR/POSTERIOR`, `DEE-PICOS`, `DEE-PRECIO-PICOS`) y acción de
registro (`IND-ACT` A/B/M/R, `COD5-VERSION`), además de
representaciones ISO I564/O564/I568.

## Decision

### 1. Semantic registry versionado (extiende ADR-009)

`docs/semantics/canonical-registry.json` es el registro versionado de
conceptos canónicos. Cada entrada:

```text
CanonicalConcept
  canonical_id          p.ej. EVENT_TYPE.SCRIP_DIVIDEND
  domain                EVENT_TYPE | DATE_ROLE | AMOUNT_ROLE |
                        RATIO | SOURCE_ACTION
  internal_field        field_path / enum value ca-es
  iso15022_ref          CAEV / qualifier (XDTE, RDTE, PAYD...)
  iso20022_ref          si aplica
  bme_native_refs[]     campos del field model BME (solo autoridad
                        para BME/Iberclear)
  market_scope          ALL | ES | BME | PORTFOLIO | ...
  mapping_status        PROVEN | UNMAPPED | CONFLICTING | NOT_APPLICABLE
  reference_version     especificación/edición usada como evidencia
  evidence / rationale
```

Reglas:

- Los nombres físicos ISO/BME **no invaden la API** de `ca-es`; viven
  en el registry como referencias.
- `PROVEN` exige referencia citada (edición + sección o documento
  oficial). En duda: `UNMAPPED`.
- Dos campos de fuente con descripciones casi idénticas **no se
  colapsan** (`bme.DAC.FECHA_DESCUENTO` vs `bme.DAC.FECHA_EXDATE`
  siguen siendo source semantics distintas; la relación con
  `DATE_ROLE.EX_DATE` requiere mapping demostrado).
- `MappingStatus` de `vocab.py` se extiende con `CONFLICTING`.

### 2. Source semantic contracts por fuente

`docs/sources/<source>/semantic-contract.json` declara, por fuente:

- la gramática numérica contractual (ver §3);
- los mappings `source semantic → canonical concept` con
  `mapping_status` y evidencia;
- el mapping de acciones de registro (ver §4).

El field model BME es autoridad de semántica de fuente **solo para
BME/Iberclear**. Portfolio, CNMV y BORME tienen sus propios contratos;
un mapping nunca transita por el modelo BME:

```text
PORTFOLIO "Ex-Date" → DATE_ROLE.EX_DATE → ISO XDTE   (PROVEN)
NO: PORTFOLIO "Ex-Date" → BME AMP-FECHA-EXDATE → XDTE
```

Si una fuente no permite demostrar el mapping ISO, el concepto queda
`UNMAPPED` (p.ej. Portfolio `OTHER_CASH_DISTRIBUTION` → `CAEV
UNMAPPED` aunque fechas/importe/ISIN sean `PROVEN`).

### 3. NumericGrammar: gate DOCUMENT_NUMERIC_GRAMMAR_PROVEN

Lo que debe demostrarse no es el idioma del documento sino **la
gramática numérica relevante** para cada importe:

```text
locale_profile      decimal_separator, thousands_separator, locale
locale_provenance   DECLARED_BY_SOURCE_CONTRACT
                    | DECLARED_IN_DOCUMENT
                    | DERIVED_FROM_DOCUMENT
                    | CONFLICTING
                    | UNKNOWN
locale_evidence     spans[], source_contract_ref?
```

`DERIVED_FROM_DOCUMENT` exige evidencia suficiente en contexto
numérico (p.ej. `19.865.753`, `21,335`, `0,53` consistentes), no un
token aislado: una sola aparición de `19.865.753` demuestra la
convención de miles, no necesariamente la decimal.

Prioridad de provenance:

```text
document evidence
  > specific source/field contract
  > source-wide convention
  > UNKNOWN
```

(un documento puede contener tablas importadas con otra convención).

**Contradicción congelada de referencia (BME spec 1.01)**: §1.1 afirma
`.` como separador decimal; §1.3 dice `.` o `,`; §1.3.1 vuelve a `.`
y afirma ausencia de separadores de miles. Conclusión: `source==BME`
no implica `decimal_separator=="."` sin evidencia más específica. Se
registra como `CONFLICTING` en el contrato BME.

Regla de promoción canónica (complementa el flujo de ADR-016):

```text
EvidenceSpan.integrity == INTACT
AND NumericGrammar.status == PROVEN
AND SemanticRole.status   == PROVEN
AND InstrumentBinding.allowed == true
─────────────────────────────────────
canonical financial fact
```

Ejemplos:

```text
"21,335" + grammar es-ES PROVEN  → Decimal("21.335")
"21,335" + grammar UNKNOWN       → NUMERIC_AMBIGUOUS
"0. 53"  + span CORRUPTED        → SPAN_CORRUPTED → no parse
```

### 4. Acción de fuente: assertion/document layer

`NEWM/REPL/CANC` (ISO message function) y `A/B/M/R` (BME `IND-ACT`)
describen la **comunicación o el registro**, no la corporate action
económica:

```text
SOURCE_DOCUMENT
  → SOURCE_ASSERTION
      source_action    = NEW | MODIFY | CANCEL | REMINDER
      message_function = NEWM | REPL | CANC | ...
  → EVENT_REVISION      (derivado de evidencia)
  → CORPORATE_ACTION
```

Nunca `CORPORATE_ACTION.message_function`. Se preserva
`documento ≠ revisión ≠ evento`.

Análogamente, en fuentes con estructura padre/hijo (BME FUS/FVL):
`source_record_parent_id` proviene de la estructura de la fuente;
`parent_event_id` solo se crea cuando la semántica demuestra eventos
operativos ligados (p.ej. RHDI/DVOP/EXOF multi-event).

### 5. Oracle con provenance simétrico

El oracle obedece los mismos principios que evalúa: una etiqueta
`CORRECT` sin provenance equivale a un canonical fact sin provenance.
Formato `ORACLE_CLAIM`:

```text
oracle_claim_id
frame_item_id
canonical_concept        (registry)
expected_value
mapping_status
evidence_locator
source_content_sha256
semantic_reference
review_status            (SIGNED / PROPOSED / ERRATUM)
reviewed_at
```

Los checkpoints congelan el **delta de valores** (expected / baseline
/ current), no solo `result_sha`. Implementado en iter-1 por
`scripts/_eval_dev_oracle.py` → `dev-iter-1-dev-oracle-eval.json`;
la migración formal a ORACLE_CLAIM la realiza
`scripts/_migrate_oracle_v2.py` sobre DEV + regression oracle.

### 6. HOLDOUT inmutable

El G1-R HOLDOUT (15 documentos, selección mecánica,
`no_manual_holdout_inspection=true`) queda sellado: ni contenido ni
parseo hasta `g1r-parser-freeze`. ADR-017, el registry, la migración
del oracle y las reglas siguientes operan exclusivamente sobre DEV y
los manifests sellados G1 (holdout/adversarial ya adjudicados). No se
selecciona ni se sustituye holdout alguno.

## Consequences

- `ca-es` pasa de «parser con taxonomía propia» a capa de
  normalización evidencial: `source semantics → canonical concepts →
  referencias ISO/BME`, con provenance hasta el span.
- `DATE_MISBINDING` pasa a ser un problema de mapping verificable
  (¿qué source semantic demuestra qué date role?), no una heurística
  textual.
- Añadir fuentes futuras (Euroclear, Euronext, DTCC…) solo requiere
  un nuevo `SourceContract` + mappings, sin rediseñar el dominio.
- La promoción canónica exige ahora cuatro gates demostrables;
  `UNMAPPED`/`UNKNOWN`/`CONFLICTING` son salidas válidas y no
  bloquean el resto del pipeline.

## References

- BME/Iberclear, «Machine Readable Corporate Actions — Technical
  Specifications», ed. 1.01 (2024-07-19): field model AMP/DAC/DEE/
  FUS/FVL/OPA/SPC/SPL, `IND-ACT`, `COD5-VERSION`, I564/O564/I568.
- Clearstream CAH functional specs (OneCAS): multi-event processing
  RHDI/DVCA/DVOP/EXOF; SR2025 introduce `DVOP/MAND` — `DVOP ⇒ CHOS`
  no es regla universal.
- ADR-008 (decimal/scale), ADR-009 (semantic alignment),
  ADR-013 (instrument binding), ADR-016 (OSS candidate adapters).
