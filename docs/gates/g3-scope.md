# G3 — Operational Surface

Status: **DRAFT v1 PENDING APPROVAL**.
Preregistro pendiente: `docs/gates/g3-preregistered.json` — el tag
`g3-protocol` solo se crea tras firma humana de ese diff.
Parent: G2 cerrado en PASS — `g2/results/verdict.json` (`5d715f0`).
Matriz de capacidades: `docs/sources/support-matrix.md`.

G3 no es un gate de parsing ni de canonicalización: G2 ya demostró el
canon interno end-to-end. G3 es una fase de producto — capa de consumo
sobre el canon probado.

## Pregunta de G3

> ¿Puede un usuario de operaciones consumir el canon G2 y entender un
> corporate action, su estado vigente, su historial y su evidencia sin
> volver a inspeccionar manualmente los documentos fuente?

## Superficie congelada

Durante G3 no pueden cambiar:

```
src/ca_es/sources/parsers/**
docs/sources/source-policy.json
identidad / revisions / provenance
CA_ES_OPERATIONAL_CANON_V1 (src/ca_es/export.py)
```

Permitido: capa de consumo (queries, vistas operativas, CLI,
presentación, export operacional), runner/evaluador/tests G3.

## Vertical slice mínimo

La superficie debe permitir a un operador:

- buscar un evento por ISIN / emisor / tipo;
- obtener la vista vigente del evento;
- ver el timeline de revisiones y qué cambió;
- distinguir hechos vigentes, anteriores y conflictivos;
- abrir la provenance hasta el documento/fragmento fuente;
- exportar JSON (y posiblemente CSV operacional);
- mostrar explícitamente capacidades `UNSUPPORTED/QUARANTINED`,
  nunca rellenarlas silenciosamente.

CLI inicial antes que web:

```text
ca-es events --isin ES...
ca-es show <canonical_event_id>
ca-es timeline <canonical_event_id>
ca-es conflicts <canonical_event_id>
ca-es evidence <assertion_id>
ca-es export <canonical_event_id> --format json
```

## Casos de producto (evidencia ya pagada en G2)

- **Almirall** (`CNMV-IP-1884/1885`): conflicto `announcement_date` y
  múltiples documentos sobre un evento.
- **MFE** (`CNMV-OIR-40280/40319`): revisiones — valor vigente vs
  histórico, qué cambió entre gen0 y gen1.
- **BME Growth**: evento operacional limpio (dividendo + ampliación).
- **Portfolio `POEX-DOC-39649`**: la superficie debe declarar el precio
  de ampliación como `UNSUPPORTED`, no como dato ausente accidental.

## Fuera de scope

- Nuevas fuentes de ingesta.
- OCR / image-only.
- ISO 15022/20022.
- Levantar la cuarentena de Portfolio.
- Web UI amplia.

## Criterio de éxito (gates G3)

```text
current-state correctness          = 1.0
revision-timeline correctness      = 1.0
conflict visibility                = 1.0
provenance navigability            = 1.0
unsupported-capability honesty     = 1.0
canonical/export fidelity          = 1.0
deterministic presentation         = 1.0
```

Más un test humano: para 4–5 corporate actions preregistrados,
responder desde la superficie G3 preguntas operativas concretas
("¿qué se paga?", "¿cuándo?", "¿qué cambió?", "¿qué dato está en
conflicto?", "¿de dónde sale?") sin abrir directamente los raws.

## Formalización

Siguiente paso: `docs/gates/g3-preregistered.json` (casos de producto,
gates, superficie congelada, contrato de la superficie operativa) →
firma humana → tag `g3-protocol` → ejecución. Sin gates preregistrados
no hay evaluación: `NOT_RUN` != `PASS`.
