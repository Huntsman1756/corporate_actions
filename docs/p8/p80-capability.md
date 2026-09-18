# P8.0 — Economic Coverage Capability Audit V2

Status: **FROZEN** (preregistro; precede a cualquier implementación).

Pregunta única (misma disciplina que P6.0, pero con el transporte
P4/P5 ya operativo):

> Con el canon, la ingestión MT564/MT566/seev y los contratos P2–P7
> existentes, ¿qué familias de Corporate Actions pueden procesarse
> económicamente de extremo a extremo — entitlement -> impacto
> esperado -> posición proyectada -> movimiento real MT/MX ->
> reconciliación -> casos P3.5 -> runtime P7 — sin inferencia
> financiera?

Diferencia estructural respecto a P6.0: la auditoría P6.0 solo miraba
el canon, y ahí mueren los operandos por-posición. Desde entonces
existe la ingestión de transporte (P4.0/P4.1/P5.x) y el extractor JVM
es **genérico** — todo campo/cualificador del mensaje llega como fact
con secuencia y ocurrencia. El mensaje del custodio es el documento
operativo real; el canon aporta identidad/adjudicación cuando existe.

## Fuentes consultadas

- `docs/p6/p60-capability.md` (bloqueos V1 por familia).
- `docs/semantics/canonical-registry.json` (mappings CAEV por
  familia, mapping_status).
- `g3/input/canon.json` (corpus: 3 CASH_DIVIDEND, 3
  CAPITAL_INCREASE, 1 RIGHTS_ISSUE; 0 SPLIT/STOCK_DIV/SCRIP).
- ISO 15022 UHB (códigos CAEV, cualificadores 22F/92D/98A/69A).
- SMPG/ISITC Global Market Practice (EIG: CAEV x CAMV x CAOP x
  DPRP; grid "Distribution with Option" RHTS vs RHDI+EXRI).
- Euronext CA4U Handbook V04 (RHDI->EXRI etapas enlazadas,
  comunicación basada en holding de la etapa 1).
- Clearstream connectivity notices (EXRI CHOS, linking de eventos).
- CDS Corporate Action guide (RHDI = Rights/Warrants Distribution;
  estructura ≈ stock dividend con indicadores RHDI).
- `vn-corporate-actions` (referencia roadmap): es librería de
  ajuste de precios históricos (backward price/volume); **no**
  aporta math de entitlement por-posición que nos falte — la math
  de posiciones es directa; TERP es convención metodológica, no
  fact, y queda fuera (evidence-first).
- Extractor JVM existente: emite `MT<nnn>.<SEQ>.<tag>:<QUAL>.<field>`
  para TODO campo; cero cambios de adapter necesarios.
- Fixture real MT566 SECMOVE (split Redegal 10:1: DEBT 12500
  ES0105857009 + CRED 125000 ES0105857033) — el lado "actual" ya
  funciona end-to-end (P6.3/P6.4).

## Decisiones de arquitectura (preregistradas)

### D1 — Operandos provienen del mensaje, no del canon

Para familias económicas nuevas, la fuente de operandos es el
mensaje de custodia (`CA_ES_SWIFT_CA_MESSAGE_V1` extendido o sus
facts). El canon solo entra vía `bind_event` (identidad +
comparación AGREES/DIFFERS). Ningún operando se "deduce" del tipo
de evento: si el mensaje no lo afirma, el campo queda ABSENT y la
salida INDETERMINATE.

### D2 — Eventos transport-native

Familias que el canon no puede producir (`internal_field=null`:
STOCK_DIVIDEND, y 0 eventos SPLIT/SCRIP en corpus) se procesan con
`event_basis = "SWIFT_NOTIFICATION"`: provenance explícita,
`canonical_event_id = null`, binding documentado como NO_MATCH en
vez de fallar. NO se sintetizan eventos canónicos: el doc de
entitlement declara que la evidencia es la notificación, no el
canon. Cuando existe evento canónico candidato, el binding P4.1
sigue siendo la vía (BOUND/AMBIGUOUS/NO_MATCH/INSUFFICIENT).

### D3 — Eligibility reutiliza P2.0

`POSITION_AT_RECORD_DATE` ya existe: la posición debe estar datada
exactamente en la fecha base. Para mensajes MAND, `98A::RDTE` es la
fecha base estándar (CADETL). Una posición fechada antes/después no
prueba la posición elegible — misma regla, sin relajación.

### D4 — Electiones reutilizan P5 íntegro

Familias CHOS/VOLU (EXRI, DVOP) no computan outcome en la
notificación: el outcome depende de la instrucción (P5.4 intent ->
MT565 -> MT567 status). La notificación solo produce el opportunity
doc (P5.2) y los términos por opción.

### D5 — Fracciones: whitelist DISF, nunca estimadas

`22F::DISF` -> política explícita. Codes soportados V1:
`RDDN` (floor, descarta fracción), `RDUP` (ceil sin coste),
`STAN` (>=0.5 up else down), `BUYU` (compra hasta entero — coste
fuera de V1 -> solo si hay precio explícito), `CINL` (cash in lieu —
requiere precio in-lieu explícito o INDETERMINATE), `SECU`/
`DIST` (fracción en valores -> Decimal exacto), `UKNW` ->
INDETERMINATE. Cualquier otro -> INDETERMINATE + excepción.

### D6 — Impactos nuevos son aditivos al contrato P6

`CA_ES_POSITION_IMPACT_V1` gana impact_kinds nuevos (mismo schema,
más values en el vocabulario): `SECURITY_RECEIPT`,
`SECURITY_DELIVERY`, `RIGHTS_RECEIPT`, `CASH_PAYABLE`,
`CASH_IN_LIEU_RECEIVABLE`. `projected_positions` ya es aplicador
genérico de deltas por `target_isin` — sin cambio de contrato.

### D7 — TERP / precios teóricos: fuera de scope permanente

Ningún precio teórico (TERP, ex-price) es un hecho de operaciones.
Se computa solo cantidades y cash payable/receivable afirmados por
el mensaje o derivables por identidad exacta (qty x precio
afirmado). La matemática financiera de valoración queda fuera.

## Matriz por familia

| Familia | CAEV | CAMV | Veredicto | Vector |
| --- | --- | --- | --- | --- |
| SPLIT / REVERSE_SPLIT | SPLF / SPLR | MAND | **ENABLED (vía MT564)** | RDTE + NEWO + DISF |
| STOCK_DIVIDEND | DVSE / BONU | MAND | **ENABLED (SWIFT-native)** | RDTE + ratio |
| SCRIP_DIVIDEND | DVOP | CHOS | **ENABLED (vía P5)** | CAOPTN CASH/SECU |
| RIGHTS_ISSUE | RHTS | CHOS | **ENABLED (vía P5)** | single-event |
| RIGHTS_ISSUE | RHDI + EXRI | MAND + CHOS | **ENABLED (2 etapas)** | COAF-linked |
| CAPITAL_INCREASE | según mecanismo | — | **CONDITIONAL** | solo si mecanismo probado |

### SPLIT / REVERSE_SPLIT — ENABLED

P6.0 lo bloqueó por UN solo operando: fecha base de elegibilidad.
El MT564 SPLF/SPLR MAND lo resuelve: `98A::RDTE` en CADETL es la
fecha base estándar del evento mandatorio.

| Operando | Fuente probada | Estado |
| --- | --- | --- |
| source instrument | USECU 35B | PROVEN (extractor genérico) |
| eligibility basis | CADETL 98A::RDTE -> POSITION_AT_RECORD_DATE | **UNBLOCKED** (era el único bloqueo duro) |
| direction | CAEV mismo: SPLF=forward, SPLR=reverse | PROVEN (registry) |
| ratio new-for-old | 92D::NEWO//n/m en CAOPTN/SECMOVE (verificado en spec; consistente con la dirección probada P6.0 en corpus BME) | PROVEN |
| target instrument | SECMOVE 35B explícito (MT564 outturn / MT566 real); fallback canon `instrument.last_isin` | PROVEN/PARTIAL |
| fractions | 22F::DISF whitelist (D5) | PROVEN como contrato |
| cash payable | N/A salvo CINL/BUYU | condicional |
| outcome | SECURITY_DELIVERY(old, qty completa) + SECURITY_RECEIPT(new, qty x ratio, DISF aplicado) | PROVEN (espeja el MT566 real del corpus) |

`new_qty = old_qty x (new/old)` con Decimal exacto; DISF resuelve el
residuo. El MT566 SECMOVE real (DEBT old + CRED new, ya soportado en
P6.3) cierra la reconciliación.

### STOCK_DIVIDEND — ENABLED (SWIFT-native)

`internal_field=null`: el canon nunca lo origina; solo existe vía
notificación (DVSE; BONU cuando el mecanismo es capitalización).
Mismo shape que split pero **aditivo**: SECURITY_RECEIPT sin
SECURITY_DELIVERY del underlying (acciones viejas se conservan).

| Operando | Fuente | Estado |
| --- | --- | --- |
| basis | RDTE -> POSITION_AT_RECORD_DATE | PROVEN |
| ratio | 92D::NEWO en SECMOVE de la opción SECU | PROVEN |
| target ISIN | SECMOVE 35B (típicamente = underlying; bonus shares mismo ISIN) | PROVEN |
| fractions | DISF whitelist | PROVEN |
| outcome | SECURITY_RECEIPT(new, qty x ratio) solamente | PROVEN |

Requiere D2 (event_basis SWIFT_NOTIFICATION): no hay evento
canónico al que bindear.

### SCRIP_DIVIDEND — ENABLED (vía P5)

`DVOP` + `CAMV=CHOS` es exactamente el flujo P5 ya construido:
CAOPTN con CAOP `CASH` y/o `SECU` -> opportunity (P5.2) ->
eligibility (P5.3) -> instruction intent (P5.4) -> MT565 (P5.5) ->
MT567 (P5.6). `holder_choice` — el bloqueo P6.0 — se resuelve por
la instrucción persistida, no por conjetura.

| Operando | Fuente | Estado |
| --- | --- | --- |
| opciones | CAOPTN/CAOP whitelist P5.2 existente | PROVEN |
| outcome CASH | precio por derecho/por acción afirmado en la opción (p.ej. precio fijo de compra de derechos por el emisor — patrón español de dividendo flexible) | PROVEN si el campo existe en el mensaje |
| outcome SECU | 92D::NEWO de la opción + DISF | PROVEN |
| ejercicio por defecto | 17B::DFLT + opción default declarada | PROVEN |

El outcome solo se materializa cuando la instrucción (o el default
trás RDDT) está probado: `NOT_INSTRUCTED -> outcome UNKNOWN`,
nunca la opción "probable".

### RIGHTS_ISSUE — ENABLED (dos sub-caminos)

ISO 15022 distingue: `RHTS` (todo en un evento) vs `RHDI` (etapa 1,
distribución de derechos MAND) + `EXRI` (etapa 2, ejercicio
CHOS/VOLU). Los dos sub-eventos se enlazan por `20C::COAF` /
referencias LINK; mercado europeo confirma RHDI MAND + EXRI CHOS
(Clearstream, Euronext CA4U).

| Operando | Fuente | Estado |
| --- | --- | --- |
| rights instrument | ISIN del intermedio en el mensaje (intermediate security seq / SECMOVE 35B del RHDI) | PROVEN desde mensaje (canon nunca lo tendrá) |
| derechos por acción | ratio afirmado en RHDI/SECMOVE (NO se asume 1:1 por convención) | PROVEN solo si el campo existe; si no -> INDETERMINATE |
| precio de suscripción | precio afirmado en EXRI/CAOPTN (qualifier a preregistrar contra mensaje real: candidatos 90A::PRPP / 19B/92A en CASHMOVE) | PARTIAL — preregistrar contra evidencia |
| ventana de ejercicio | 69A::PWAL / 98A::RDDT | PROVEN |
| outcome etapa 1 | RIGHTS_RECEIPT (interim ISIN) | PROVEN |
| outcome etapa 2 | solo con instrucción: CASH_PAYABLE (precio x nuevas) + SECURITY_DELIVERY(derechos) + SECURITY_RECEIPT(acciones nuevas) | PROVEN vía P5 |

Canon `03888619` (terms 20:39, issue_price 0.80) puede bindear por
ISIN del underlying + comparación de precio/terms — el mensaje
apota los operandos por-posición que el canon no tiene.

### CAPITAL_INCREASE — CONDITIONAL

`event_type=CAPITAL_INCREASE` canónico no dice el mecanismo; el
CAEV del mensaje sí:

- liberada (acciones gratis, MAND) -> mecánica BONU (stock
  distribution); soportable si llega CAEV=BONU/DVSE.
- con derecho preferente -> camino RHDI+EXRI/RHTS.
- sin derechos / con prima / mecanismo no demostrado ->
  **UNSUPPORTED** (se mantiene).

Ninguna variante se proyecta desde el event_type canónico solo:
solo cuando el mecanismo llega por transporte con CAEV probado.
Por eso la familia no tiene fase propia de implementación — se
cubre cuando los mensajes de las otras familias la alcanzan.

## Bloqueos que permanecen (honestos)

| Bloqueo | Familias | Estado |
| --- | --- | --- |
| Canon no produce el evento | STOCK_DIV, SCRIP, SPLIT (0 en corpus) | resuelto por D2 (SWIFT-native), nunca por síntesis de canon |
| ISIN del instrumento de derechos | RIGHTS | resuelto desde mensaje (interim security); si ausente -> MISSING_TARGET_INSTRUMENT |
| Precio de suscripción / in-lieu | RIGHTS, SPLIT(CINL), SCRIP(CASH) | solo si afirmado en mensaje; si no -> INDETERMINATE |
| Vinculación RHDI<->EXRI | RIGHTS 2-etapas | por COAF/RELA explícitos; sin link -> eventos independientes, nunca fusionados |
| holder_choice | SCRIP, RIGHTS ejercicio | resuelto por instrucción P5, no por canon |
| TERP/valoración | todas | fuera de scope (D7) |

## Vertical de implementación (por familia probada)

```text
facts MT564/MX (extractor genérico existente)
  -> CA_ES_SWIFT_CA_MESSAGE_V1 extendido (campos nuevos, CAEV_MAP)
  -> event terms (D2 SWIFT-native o bound)
  -> entitlement/impact rules preregistradas por familia
  -> CA_ES_POSITION_IMPACT_V1 +kinds -> projected positions
  -> MT566/seev.036 actual -> security_recon (P6.4) -> P3.5 cases
  -> P7 DAG (mismos steps; familias nuevas entran por config/rules)
```

Stop conditions (idénticas a P6.0): si un operando no está afirmado
en la evidencia, la salida es INDETERMINATE/UNSUPPORTED — nunca se
rellena por convención de mercado.
