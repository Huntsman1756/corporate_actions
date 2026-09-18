# P9.1 — Contratos de observación de fuente (preregistro)

## `CA_ES_SOURCE_OBSERVATION_V1`

Una observación por evento de retrieval (o de discovery sin fetch).
Misma identidad de fuente + mismos bytes → un artefacto blob, pero la
observación es un evento propio (puede repetirse entre refreshes).

```json
{
  "schema": "CA_ES_SOURCE_OBSERVATION_V1",
  "observation_id": "sha256(source_id|surface_id|source_document_id|content_sha256|refresh_id)",
  "refresh_id": "...",
  "source_id": "CNMV",
  "surface_id": "OIR",
  "source_document_id": "CNMV-OIR-40280",
  "source_locator": "https://www.cnmv.es/webservices/...",
  "discovered_at": "ISO",
  "retrieved_at": "ISO|null",
  "retrieval_status": "OK|FETCH_FAILED|DISCOVERY_ONLY",
  "http_status": 200,
  "media_type": "application/pdf",
  "content_sha256": "…|null",
  "byte_length": 0,
  "raw_ref": "blobs/xx/sha.bin|null",
  "source_metadata": {"registration_number": "…", "category": "…", "relations": []},
  "redistribution": "NOT_REDISTRIBUTED",
  "raw_storage": "LOCAL_ONLY",
  "previous_content_sha256": "…|null",
  "change_status": "NEW_DOCUMENT|SAME_BYTES|CONTENT_CHANGED|FETCH_FAILED|DISCOVERY_ONLY"
}
```

- `CONTENT_CHANGED` = misma `source_document_id`, bytes distintos.
  Nunca se llama "revisión" salvo semántica oficial de la fuente.
- `DISCOVERY_ONLY`: documento ya conocido re-observado en discovery
  sin refetch (política `refetch_known=false`).
- `FETCH_FAILED`: retrieval fallido; la evidencia previa del documento
  (si existe) permanece intacta.

## `CA_ES_SOURCE_REFRESH_V1`

Artefacto agregado por refresh (output del step `source_refresh`):

```json
{
  "schema": "CA_ES_SOURCE_REFRESH_V1",
  "refresh_id": "sha256 determinista (run_id + sources + started_at)",
  "started_at": "…", "completed_at": "…",
  "source_results": [
    {
      "source_id": "CNMV", "surface_id": "OIR",
      "status": "SUCCESS|PARTIAL|FAILED|UNCHANGED",
      "discovered": 0, "new_documents": 0,
      "same_bytes": 0, "content_changed": 0,
      "fetch_failed": 0, "discovery_only": 0,
      "pagination": {"complete": true, "pages_fetched": 0,
                     "max_page": 0},
      "observations": ["obs_id", "…"],
      "error": null
    }
  ],
  "summary": {
    "status": "SUCCESS|PARTIAL|FAILED|UNCHANGED",
    "sources_ok": 0, "sources_failed": 0,
    "documents_new": 0, "documents_changed": 0,
    "documents_unchanged": 0
  }
}
```

Reglas:

- Un fallo de fuente queda aislado en su `source_results[]`; no
  descarta observaciones de otras fuentes.
- `UNCHANGED` solo cuando todas las fuentes enumeraron con éxito y no
  hubo `NEW_DOCUMENT`/`CONTENT_CHANGED`.
- `PARTIAL` cuando alguna fuente falló o `pagination.complete=false`.
- Sin fuentes configuradas → `source_results=[]`, status
  `UNCHANGED`, reason `NO_SOURCES_CONFIGURED` (SUCCEEDED, no BLOCKED).
