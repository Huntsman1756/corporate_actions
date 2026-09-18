# P9.5 — Canon refresh sobre evidencia acumulada

Estado: PREREGISTRADO → implementado en `src/ca_es/ops_canon.py`.

## Contrato

`CA_ES_CANON_REFRESH_V1`

```text
canon_refresh_id
previous_canon_logical_sha256 | null
new_canon_logical_sha256

source_refresh_id | null          # refresh que motiva este rebuild

documents_considered
documents_new
documents_changed
documents_unchanged
documents_failed

parse_promotions      [ {document_id, from, to} ]
parse_failures        [ {document_id, content_sha256, error} ]

events_added
events_changed
events_unchanged

refresh_status: SUCCESS | UNCHANGED | FAILED
reasons[]
canon_artifact_sha256
```

## Reglas no negociables

1. **No hay segundo canonicalizer.** El refresh materializa un corpus
   scratch sobre los blobs `chosen` y ejecuta exactamente
   `parse_manifest_corpus → build_identity → build_event_views →
   operational_canon → canon_payload`. Misma función que el pipeline
   histórico, refactorizada sin cambio semántico.

2. **La evidencia acumulada es durable.** El canon se reconstruye
   sobre TODOS los `source_documents` con `chosen_content_sha256`,
   no sobre los descargados hoy. Una caída de CNMV no borra
   aserciones previas.

3. **`latest` ≠ `chosen`.** `latest_content_sha256` = último blob
   observado. `chosen_content_sha256` = último blob cuyo parse devolvió
   OK. El canon se construye SIEMPRE sobre `chosen`.

4. **Promoción explícita.** Si `latest != chosen`, canon_refresh
   intenta parsear `latest`:
   - parse OK → `chosen = latest` + `source_parse_results OK`;
   - parse ERROR → `source_parse_results PARSE_FAILED`, `chosen`
     intacto, el canon sigue usando la evidencia buena previa y el
     fallo queda en `parse_failures[]` (alerta P9.7).

5. **`CONTENT_CHANGED` nunca sobrescribe.** Ambos blobs coexisten;
   la adjudicación de facts resultantes la hace la maquinaria de
   revisiones/provenance existente, no el refresh.

6. **Determinismo del corpus scratch.** `raw_relpath` =
   `raw/<source_id>/<source_document_id>/<sha>.bin`. `retrieved_at`
   del `SourceDocument` = `retrieved_at` de la primera observación
   que produjo ese `chosen` sha (estable entre rebuilds). `corpus_id`
   fijo (`live-accumulated`): el canon no lleva timestamps de
   ejecución.

7. **`UNCHANGED`.** Si el conjunto `(document_id, chosen_sha)` es
   idéntico al del rebuild anterior, `new_canon == previous` y el
   doc lo declara `UNCHANGED` — el step P9.6 podrá marcar
   `SKIPPED_UNCHANGED` sin recomputar downstream.

8. **`documents_failed` nunca silencia.** Un documento con
   `PARSE_FAILED` cuenta en `documents_failed` y NO entra al corpus
   del rebuild — pero su `chosen` anterior, si existe, sí entra.

## Identidad de documentos

`official_document_id` del `SourceDocument` canónico = el
`source_document_id` operacional del refresh (`CNMV-OIR-<reg>`,
`BMEG-<kind>-<isin>-<fecha>`, `POEX-DOC-<id>`): la misma cadena con
la que los manifests G1/G1-R2 ya identifican estos documentos.

Las `relations` oficiales capturadas en discovery (p.ej. OIR
"Relacionado con la comunicación anterior") se conservan en
`source_documents.metadata_json` y se re-inyectan como
`SourceDocument.relations`, alimentando `_merge_manifest_relations`
exactamente como en los manifests congelados.
