# Fuentes — roles y política

La política autoritativa está en `docs/sources/source-policy.json`
(`CA_ES_SOURCE_POLICY_V1`).

## Roles

| Fuente | Rol | Ingesta |
|--------|-----|---------|
| CNMV | `PRIMARY_REGULATORY_DISCLOSURE` | ACTIVE |
| BOE/BORME | `PRIMARY_OFFICIAL_GAZETTE` | ACTIVE |
| Portfolio Stock Exchange | `VENUE_DISCLOSURE` | ACTIVE |
| Investor relations | `ISSUER_DISCLOSURE` | ACTIVE |
| ESMA/FIRDS | `REFERENCE_DATA_ENRICHMENT` | REFERENCE_ONLY |
| Iberclear | `LIFECYCLE_REFERENCE`, `TERMINOLOGY_REFERENCE`, `ISO_MAPPING_REFERENCE` | REFERENCE_ONLY |

## Iberclear

Afirmación admitida, y solo esta:

```
PUBLIC_INGEST_INTERFACE_NOT_PROVEN
```

No se afirma que Iberclear carezca de feed. Iberclear sirve para
entender eventos obligatorios/voluntarios, la cadena emisor → agente →
CSD → participante, semántica de fechas, instrucciones, Golden
Operational Record e ISO 15022/20022. No aparece como fuente ingerible
en G0 sin evidencia nueva.

## Redistribución

Ver ADR-011. `raw_storage=LOCAL_ONLY` para todas las fuentes;
`redistribution` varía (`NOT_REDISTRIBUTED` o
`HASH_AND_METADATA_ONLY`). El directorio `raw/` permanece fuera de Git.

## Coverage investigation

`docs/gates/p3-cnmv-channel-coverage.json` — resultado actual
`INCONCLUSIVE` (G0 offline); no se convierte "no encontrado en el
corpus" en "no existe".
