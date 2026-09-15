# G1-R2 — AMOUNT_ROLE_MISBINDING: corrección y generalización (Portfolio)

Status: **DRAFT — PENDING APPROVAL, NOT YET TAGGED** (2026-09-15).
El tag `g1r2-protocol` solo se crea tras aprobación humana del diff
final. Parent: G1-R cerrado en FAIL —
`docs/gates/g1r-closure-report.md` (`725da2e`). Parser congelado de
referencia: `a6a0674 / g1r-parser-freeze`.

G1-R2 es un gate nuevo. El namespace `g1r/` queda congelado como
evidencia; `g1r/` no se modifica salvo, como máximo, una referencia
documental al sucesor.

## Pregunta de G1-R2

> ¿Corrige el parser `AMOUNT_ROLE_MISBINDING` en la fuente Portfolio y
> generaliza a documentos nuevos sin reintroducir ningún P0 conocido?

## Target failure class (de G1-R holdout, firmado)

```
AMOUNT_ROLE_MISBINDING — P0
  en CAPITAL_INCREASE / RIGHTS_ISSUE, el precio de suscripción/emisión
  por acción publicado por la fuente se emite como
  amount.gross_per_share en lugar de amount.issue_price_per_share
  (canonical-registry: AMOUNT_ROLE.ISSUE_PRICE_PER_SHARE separado de
  GROSS_UNIT_AMOUNT; ADR-017; precedente oracle iter-1 IP-2670)

  evidencia: POEX-DOC-39649 (spent holdout, adjudicado FAIL)
```

Relacionados pero **fuera del target P0** (medidos, no ampliados):

```
ratio.terms 2:1 publicado no emitido (39649)        -> P1 missing
event_type CAPITAL_INCREASE abstenido (39649)       -> P1 missing
ISIN_ROLE_DISAMBIGUATION (3 ISIN etiquetados)       -> P2 medido
SCANNED_PDF_NO_TEXT_LAYER                          -> gate propio, fuera
```

## Anti-PASS-vacío (hard, preregistrado)

```
target_opportunity =
  documento cuya fuente publica, para un CAPITAL_INCREASE o
  RIGHTS_ISSUE, precio de suscripción/emisión por acción

minimum_target_opportunities = 3   (sobre CAs distintas, ver dedup)

si opportunities < 3  ->  verdict = INCONCLUSIVE
                           (el holdout se gasta igualmente; ver abajo)

por oportunidad:
  PASS: amount.issue_price_per_share == valor publicado
        Y el mismo lexema NO aparece como amount.gross_per_share
  FAIL: slot incorrecto | valor incorrecto | abstención/missing
        del precio publicado

  -> SAFE_ABSTENTION no existe para el target principal
```

## Corpus — restricción descubierta y decisión pendiente

Hechos verificados sobre el universo congelado (2026-09-14):

```
frame G1 (1419 items): 934 MAIN_MARKET / 446 BME_GROWTH_MTF / 39 PORTFOLIO
PORTFOLIO consumido:   10 G1 (8 dev + 2 holdout) + 10 G1-R = 20
PORTFOLIO virgen restante en frame: 19

snapshot Portfolio congelado (g1/corpus/raw/frame/, 630 doc rows):
  ampliación/suscripción-titled docs ≈ 5
  CAs distintas de ampliación: ~2
    - NEXTLOG (ES0105969002): 39660/61/62, 40163, 40189
      -> MISMA CA que el spent POEX-DOC-39649 (lifecycle docs)
    - ORION (ES0105829008):  39939 (fase resultado)
```

Consecuencia: el diseño original de 24 PORTFOLIO no cabe en el frame
(19), y un holdout Portfolio aleatorio tiene densidad de oportunidad
esperada ~1 — el guard `min 3` lo convertiría casi seguro en
INCONCLUSIVE y gastaría el estrato.

### Opción recomendada — snapshot nuevo + estrato enriquecido por metadatos

```
1. nuevo snapshot de fuentes (G1-R2 frame, retrieved_at nuevo)
   — frame drift aceptado y preregistrado: la pregunta es nueva;
     el frame G1 estaba congelado para la pregunta de G1-R
2. target stratum PORTFOLIO = docs cuya metadata OFICIAL
   (type/subtype/title de la fuente, p. ej. subtype
   "Ampliación de capital") indica CAPITAL_INCREASE/RIGHTS_ISSUE
   — selección por metadata publicada, sin leer contenido;
     precedente: eligibility INCL_TITLE_KEYWORDS de G1
3. exclusión: los 190 IDs vistos (150 G1 + 40 G1-R)
   Y dedup contra CAs ya vistas por metadata estructurada
   (mismo ISIN + familia de evento + ventana temporal;
    p. ej. la cadena NEXTLOG 39660/61/62/40163/40189 colapsa con 39649)
   — mismo permitted_evidence que pre_split_dedup de G1-R;
     ante la duda, ambos permanecen (duplicado documentado)
4. sentinels: N MAIN_MARKET + N BME_GROWTH_MTF del frame congelado
   (quedan ~924 / ~436 sin ver)
5. sample_score = SHA256("CA_ES_G1R2_SAMPLE_V1" + stratum + id)
   split_score = SHA256("CA_ES_G1R2_SPLIT_V1" + id)
   split determinista DENTRO de cada estrato
6. precondition del sorteo: si el estrato target elegible tiene
   < MIN_STRATUM_CAS CAs distintas -> no se sortea; el gate espera
   un snapshot posterior (acumulación), nunca se quema un holdout débil
```

### Alternativa — frame congelado puro

```
holdout = 19 PORTFOLIO restantes (+ sentinels)
desarrollo sobre G1-R DEV existente (sigue siendo DEV)
riesgo aceptado: opportunities esperadas ~1 -> INCONCLUSIVE probable
y estrato Portfolio agotado para siempre
```

**DECISION_REQUIRED: opción recomendada vs alternativa.**

## Regression evidence (tres capas, todo ya pagado)

```
G1 regression oracle        -> 56/56 obligatorio (artefacto congelado)
G1-R DEV (25)               -> sin regresiones sobre claims firmados
G1-R spent holdout (15)     -> REGRESSION ONLY, nunca generalization:
   POEX-DOC-39649 target explícito:
     required: amount.issue_price_per_share = 4 EUR
     forbidden: amount.gross_per_share = 4 EUR
   (enmienda de oracle con aprobación humana, como iter-1/3)
```

## Gates del HOLDOUT virgen G1-R2

```
PASS requiere simultáneamente:

  AMOUNT_ROLE_MISBINDING        = 0
  inherited P0 classes          = 0   (las 5 clases G1-R)
  target opportunities         >= 3
  target opportunity recall     = 1.0  (sin SAFE_ABSTENTION en target)
  p0_review_coverage            = 1.0
  second_run_determinism        = 1.0
  G1 regression                 = 56/56
  G1-R regression               = clean
  field_provenance_rate         = 1.0
  silent_conflicts              = 0
  unproven_auto_merges          = 0
  human_authored_facts          = 0

INCONCLUSIVE si opportunities < 3 (holdout gastado; siguiente sorteo
excluye también estos IDs)

ISIN_ROLE_DISAMBIGUATION: medido P2, no bloquea
SCANNED_PDF_NO_TEXT_LAYER: fuera de G1-R2 (gate propio)
```

## Automatización (sin refactor de lo congelado)

```
docs/gates/g1r2-scope.md              (este documento)
docs/gates/g1r2-preregistered.json    (tras aprobación)
g1r2/state.json | g1r2/manifests/ | g1r2/results/
scripts/build_g1r2_corpus.py
scripts/run_g1r2.py
scripts/g1r2_next.py
```

`g1r_next.py`, `run_g1r.py` y `build_g1r_corpus.py` permanecen
intactos para auditabilidad histórica.

## Secuencia

```
aprobación de este scope -> spec -> g1r2-preregistered.json
  -> tag g1r2-protocol
snapshot/frame G1-R2 + exclusion-set (190 + CAs vistas)
selección DEV/HOLDOUT dentro de estrato + sellado
baseline DEV con parser a6a0674
desarrollo AMOUNT_ROLE_MISBINDING (regla genérica de la clase;
  prohibido condicionar por seed/issuer/URL/hash;
  la etiqueta de la fuente es fenómeno documental, no identidad)
legacy regression tras cada iteración
g1r2-parser-freeze
HOLDOUT virgen x2 (determinism)
adjudicación humana (PROPOSED hasta firma)
veredicto: PASS / FAIL / INCONCLUSIVE
```

## Out of scope

- OCR / PDFs image-only (`SCANNED_PDF_NO_TEXT_LAYER`): gate propio.
- Resolución automática de roles de ISIN (`ISIN_ROLE_DISAMBIGUATION`):
  medido como P2, sin gate.
- discovery recall, expansiones de producto, ISO.
- Reescribir los veredictos G1 / G1-R (ambos permanentes).
