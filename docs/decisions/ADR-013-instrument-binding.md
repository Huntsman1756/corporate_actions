# ADR-013 — Instrument Binding (evento → instrumento)

Status: ACCEPTED (G0-R3, 2026-09-13)

## Context

Un corporate action pertenece a un instrumento. Pero los documentos de la
mayoría de anuncios españoles no repiten el ISIN. Exigir que cada
documento de evento imprima el ISIN es artificialmente restrictivo; la
propiedad necesaria es poder establecer de forma **determinista y
evidenciada** qué instrumento afecta el evento. El matching por nombre
está prohibido en todo el diseño (ADR-006).

## Decision

Precedencia explícita para `event → instrument`:

```text
1. ISIN explicito en el documento del evento
   -> EXPLICIT (SOURCE_ASSERTION)

2. Relacion estructurada documento->instrumento de la MISMA fuente oficial
   p.ej. Portfolio product page (product_id + JSON-LD FinancialProduct)
   -> SOURCE_CARRIED_INSTRUMENT_BINDING

3. Referencia oficial cruzada entre fuentes
   -> CROSS_SOURCE_BINDING

4. Adjudicacion humana
   -> relacion registrada (nunca fact financiero)

5. Nombre
   -> solo generacion de candidatos; JAMAS canonico automatico
```

La relacion documento→instrumento debe ser exacta y auditable (id
estructurado, ruta canónica, relación documental de API o equivalente),
nunca una coincidencia de denominación.

## Evidencia portadora

Una fuente oficial del mismo sistema que publique el instrumento con su
ISIN (y opcionalmente LEI/NIF) es válida como binding, aunque no sea el
documento del evento. En G0-R3: la ficha de Portfolio publica el JSON-LD
`FinancialProduct` con `ISIN=ES0105282000`, `product_id=5` y la lista de
documentos del producto, que incluye el documento 4733.

## Separacion de fuentes

```text
Portfolio   -> event <-> instrument <-> ISIN
ESMA FIRDS  -> ISIN <-> LEI <-> segment MIC <-> validity
CNMV ANCV   -> corroboracion independiente del ISIN (control cruzado)
```

## Consecuencias

- El evento puede enriquecerse point-in-time vía `ListingResolver` sin
  que el PDF del anuncio contenga el ISIN.
- La resolución es auditable: cada eslabón cita su evidencia.
- Si no hay binding, el instrumento queda `UNRESOLVED`; nunca se adivina.

Gates: `LEI_ISIN_MIC_CHAIN_PROVEN` (G0, ya data-driven) y G0-R3
(`REAL_EVENT_TO_ISIN_EXACT`, `ISIN_TO_FIRDS_EXACT`,
`POINT_IN_TIME_MIC_RESOLUTION`, `SECOND_RUN_DETERMINISTIC`).
