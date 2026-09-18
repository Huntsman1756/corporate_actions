# P9.6 — Integración source/canon refresh en el DAG P7

Estado: implementado.

## DAG resultante (orden de lista = orden de ejecución)

```text
validate_inputs
source_refresh        impuro, opcional — red + estado mutable
canon_refresh         impuro, opcional — early-return por evidence set
process_inbox
compute_deadlines
build_action_queue
morning_brief_v2
entitlements
cash_reconciliation
exception_cases
securities_events
alert_outbox
health_report
lineage_export
```

## Decisiones

1. **`source_refresh` depende de `validate_inputs`** (necesita el doc
   `source_policy` para clasificar adquisición). Sin policy input →
   `BLOCKED` (fail-closed: sin política autoritativa no se adquiere).

2. **`canon_refresh` NO tiene edge hacia `source_refresh`.** Un
   `FAILED`/`BLOCKED` de adquisición no impide reconstruir el canon
   sobre la evidencia durable acumulada — invariante "una caída de
   fuente nunca es evidencia de desaparición". El orden lo da la
   posición en la lista (el engine ejecuta secuencialmente).

3. **`canon_refresh` no es pure** pero implementa early-return: si
   `semantic_sha256({documents:(source,doc,chosen_sha), policy_sha})`
   coincide con el rebuild anterior, devuelve el **mismo artefacto**
   byte-idéntico → mismo semantic hash → los pasos puros downstream
   (`compute_deadlines`, `morning_brief_v2`, `entitlements`, ...)
   obtienen `SKIPPED_UNCHANGED` gratis vía cache key.

4. **Inyección del canon.** Cuando `canon_refresh` produce/persiste
   canon acumulado con evidencia, sobrescribe `ctx.input_docs["canon"]`
   y `ctx.input_refs["canon"]` → los `uses_inputs=("canon",)` de los
   pasos downstream invalidan selectivamente al cambiar el canon.
   Un canon acumulado **vacío nunca pisa al canon de config** (los
   runs pueden seguir operando con un canon suministrado mientras la
   adquisición aún no aporta evidencia parseable).

5. **Sin edge desde consumidores de canon hacia `canon_refresh`.**
   Si el rebuild falla (opcional), el run continúa sobre el canon de
   config — degradación operacional explícita, no bloqueo. La salud
   de la cadena de fuentes se reporta en P9.7, no como bloqueo.

6. **Config `sources` (CA_ES_OPS_CONFIG_V1, aditivo):**

   ```json
   "sources": {
     "enabled": true,
     "timeout_seconds": 90,
     "retries": 3,
     "politeness_seconds": 0.35,
     "max_bytes": 67108864,
     "adapters": {
       "cnmv_oir": {"adapter": "cnmv", "portal": "oir",
                    "source_id": "CNMV", "surface_id": "OIR",
                    "enabled": true, "required": false,
                    "desde": "2024-01-01", "overlap_days": 14}
     }
   }
   ```

   `required` declara que un fallo técnico de la fuente degrada la
   salud del runtime (P9.7); **nunca** significa que la ausencia de
   la fuente borre evidencia. Sin credenciales en config. Claves
   desconocidas → `INVALID_OPS_CONFIG` (fail-closed, igual que el
   resto de secciones).

7. **`sources.enabled` ausente/false** → `source_refresh` devuelve un
   doc `UNCHANGED` con `enabled=false` — el DAG sigue siendo válido
   sin adquisición configurada.

8. **Fetchers inyectables** (`run_ops(..., source_fetchers=...)`):
   canal de tests/offline; `None` construye los fetchers urllib
   reales por adapter. El config JSON de `ops-run` nunca lleva
   fetchers — siempre live.
