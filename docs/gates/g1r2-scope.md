# G1-R2 — AMOUNT_ROLE_MISBINDING: corrección y generalización (Portfolio)

Status: **DRAFT v2 — PENDING APPROVAL, NOT YET TAGGED** (2026-09-15).
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

## Target stratum — población explícita (no búsqueda oportunista)

```
ELIGIBILITY_V1  (sobre la fila de metadata {document_id, title,
                 subtype, type, section, date, product} que produce
                 enumerate_portfolio, scripts/build_g1_frame.py)

normalize(s) = literal de build_g1_frame.py:138:
               NFKD -> strip combining marks -> collapse whitespace
               -> lowercase -> strip

TYPE_LIST_V1    = []          # el vocabulario type observado no porta
                              # familia de evento; cualquier valor
                              # futuro no es elegible hasta
                              # ELIGIBILITY_V2 + re-tag
SUBTYPE_LIST_V1 = ["ampliacion de capital"]
TITLE_REGEX_V1  = "ampliacion de capital|aumento de capital|"
                  "suscripcion preferente|derechos de suscripcion"
                  (re.search sobre normalize(title))

eligible iff normalize(type)    in TYPE_LIST_V1
          or normalize(subtype) in SUBTYPE_LIST_V1
          or re.search(TITLE_REGEX_V1, normalize(title))

NO (señales de selección prohibidas):
  contenido PDF
  importe
  parser output
  resultado esperado

 Cambiar cualquier lista/regex = nueva versión de ELIGIBILITY + tag.
```

El claim de G1-R2 es deliberadamente limitado: **generalización dentro
del estrato enriquecido de operaciones de capital de Portfolio** — no
estimación de prevalencia sobre todo Portfolio.

Precedente: la eligibility `INCL_TITLE_KEYWORDS` de G1 ya usaba
metadata oficial (title) antes de leer documentos.

## CA-group partitioning — la unidad de selección es la CA, no el doc

La cadena NEXTLOG lo demuestra: cinco `frame_item_id` de lifecycle
pueden ser la misma operación. Si uno cae en DEV y otro en HOLDOUT, el
holdout deja de ser independiente aunque los IDs difieran.

```
CA_GROUP_V1  (función literal y versionada)

inputs por documento (metadata estructurada congelada solamente):
  isin   = ES[A-Z0-9]{10} extraído del product slug
           (PORTFOLIO_PRODUCT_RE); null si ausente
  family = "CAPITAL_INCREASE" si el doc satisface ELIGIBILITY_V1;
           "CAPITAL_REDUCTION" si
           normalize(subtype)=="reduccion del capital social";
           "OTHER" en cualquier otro caso
  date   = date (ISO day del metadata)
  document_id

algoritmo:
  1. isin null -> ca_group_id = "DOC:" + document_id  (singleton)
  2. agrupar docs por (isin, family)
  3. dentro de cada grupo: ordenar por date y aplicar
     single-linkage — docs consecutivos se fusionan si
     gap <= 62 días
  4. ca_group_id = SHA256("CA_ES_G1R2_CAGROUP_V1|" + isin + "|"
                          + family + "|" + min(date del cluster))

partition(ca_group_id), nunca partition(document_id)

spent-equivalence usa EXACTAMENTE la misma función, aplicada
conjuntamente a docs nuevos elegibles + docs ya vistos con metadata:
todo cluster que contenga >= 1 doc visto queda excluido del
generalization set.

NO:
  inspección del PDF
  parser output
  adjudicación
  ajuste manual posterior

Sin metadata suficiente para demostrar misma-CA -> grupos distintos.
Cambiar la función = CA_GROUP_V2 + re-tag.
```

## Restricción descubierta (verificada sobre el universo congelado)

```
frame G1 (1419): 934 MAIN / 446 BMEG / 39 PORTFOLIO
PORTFOLIO consumido: 10 G1 + 10 G1-R = 20 -> quedan 19
snapshot Portfolio congelado (630 doc rows): ~5 docs
  ampliación-titled = ~2 CAs distintas (NEXTLOG = spent 39649; ORION)
densidad observada de target_opportunity: ~1 por 19 docs adjudicados
```

Por eso se rechaza el frame puro: un holdout aleatorio de ese universo
tendría ~1 oportunidad esperada y se gastaría en INCONCLUSIVE.

## Corpus G1-R2 — aprobado

```
NEW PORTFOLIO SNAPSHOT (versionado, acumulable)
        ↓
metadata-only eligibility (G1R2_TARGET_STRATUM_V1)
        ↓
exclude 190 IDs vistos (150 G1 + 40 G1-R)
+ exclude proven spent CA groups (NEXTLOG ≡ 39649, etc.)
        ↓
group by CA — frozen metadata only
        ↓
PRECONDITION: eligible distinct unseen CA-groups >= 8
   si no: WAITING_FOR_CORPUS — no split, no holdout consumption
        ↓
hash selection:  CA_ES_G1R2_SAMPLE_V1 sobre ca_group_id
        ↓
HOLDOUT ONLY — los nuevos target CAs no se gastan en DEV
```

`MIN_STRATUM_CAS = 8`, `HOLDOUT_TARGET_CAS = 8`. No garantiza 3
oportunidades — el anti-PASS-vacío real sigue siendo `>= 3` — pero por
debajo el gate sería demasiado pequeño antes incluso de mirar
contenido.

Sin nuevos sentinels MAIN/BME: innecesarios (tres capas de regression
pagadas) y gastarían evidencia virgen de otras fuentes reservable para
futuros gates. G1-R2 es deliberadamente Portfolio-specific.

## Development evidence (sin evidencia virgen nueva)

```
POEX-DOC-39649     -> SPENT_EVIDENCE / regression target:
                      required:  amount.issue_price_per_share = 4 EUR
                      forbidden: amount.gross_per_share = 4 EUR
tests sintéticos   -> regla genérica de la clase
G1 regression      -> 56/56
G1-R DEV (25)      -> sin regresiones sobre claims firmados
G1-R spent holdout -> REGRESSION ONLY (15 docs)
```

## Anti-PASS-vacío (hard, preregistrado)

```
target_opportunity =
  CA-group cuyo documento publica, para CAPITAL_INCREASE o
  RIGHTS_ISSUE, precio de suscripción/emisión por acción

minimum_target_opportunities = 3   (sobre CA-groups distintas)

si opportunities < 3  ->  verdict = INCONCLUSIVE
                           holdout = SPENT_EVIDENCE igualmente
                           (el umbral no se mueve)

por oportunidad:
  PASS: amount.issue_price_per_share == valor publicado
        Y el mismo lexema NO aparece como amount.gross_per_share
  FAIL: slot incorrecto | valor incorrecto | abstención/missing
        del precio publicado

  -> SAFE_ABSTENTION no existe para el target principal
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
  G1-R regression               = clean (incl. target 39649)
  field_provenance_rate         = 1.0
  silent_conflicts              = 0
  unproven_auto_merges          = 0
  human_authored_facts          = 0

INCONCLUSIVE si opportunities < 3
FAIL si cualquier P0 o invariante se rompe

ISIN_ROLE_DISAMBIGUATION: medido P2, no bloquea
SCANNED_PDF_NO_TEXT_LAYER: fuera de G1-R2 (gate propio)
```

## Automatización (sin refactor de lo congelado)

```
docs/gates/g1r2-scope.md              (este documento)
docs/gates/g1r2-preregistered.json
g1r2/state.json | g1r2/manifests/ | g1r2/results/
scripts/build_g1r2_corpus.py
scripts/run_g1r2.py
scripts/g1r2_next.py
```

`g1r_next.py`, `run_g1r.py` y `build_g1r_corpus.py` permanecen
intactos para auditabilidad histórica.

`AGENTS.md` transición:

```
G1-R == CLOSED ; G1-R2 == ACTIVE
"continúa corporate_actions" -> leer g1r2/state.json
  -> siguiente transición -> STOP solo en firma externa / gate fail
```

## Cambios de código — solo reglas genéricas

Prohibido condicionar por `frame_item_id`, issuer, URL, hash o
documento concreto. La etiqueta de la fuente es fenómeno documental,
no identidad. Cada entrada de `g1r2/results/g1r2-changes.jsonl` exige
`generic_rule`, `trigger_failure_class`, `root_cause`, `tests_added`,
`commit`.

## Secuencia

```
aprobación humana de este scope + preregistered -> tag g1r2-protocol
snapshot G1-R2 (versionado) + exclusion-set + CA-grouping
PRECONDITION >= 8 distinct unseen CA-groups
sellado HOLDOUT (8 CA-groups; adquisición auto para sha256 permitida)
desarrollo AMOUNT_ROLE_MISBINDING sobre evidence existente
legacy regression tras cada iteración (G1 56/56 + G1-R DEV + spent)
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
