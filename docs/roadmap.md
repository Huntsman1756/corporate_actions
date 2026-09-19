# Roadmap de producto — Corporate Actions Operations Workbench

Post-G3 (ciclo de gates G0–G3 cerrado). El canon
`CA_ES_OPERATIONAL_CANON_V1` y la superficie `CA_ES_OPERATIONAL_SURFACE_V1`
están probados; a partir de aquí el proyecto crece verticalmente en
valor operativo, no horizontalmente en parsers ni en gates.

```text
CNMV / BME / BORME / Portfolio
             │
             ▼
      ca-es canonical core       ← PROBADO (G2)
             │
     ┌───────┼───────────┐
     ▼       ▼           ▼
 Ops Desk  Entitlements  Messaging
 / Brief   / Recon       MT / MX  (seev.*)
     │       │
     ▼       ▼
 Deadlines  Exceptions
 Evidence   Expected vs actual
 Conflicts  Payment / instruction
```

## Regla build vs adopt

Si una pieza genérica existe madura en OSS, se integra; ca-es solo
construye la lógica diferencial española, la provenance y el workflow
operacional. Sin reinventar piezas básicas.

## Adopciones OSS decididas

| Pieza | Proyecto | Decisión |
|---|---|---|
| Cockpit operativo | Textual | ADOPT |
| Web/API instantáneo del canon | Datasette + SQLite | ADOPT |
| SWIFT MT564/565/566/567/568 | Prowide Core | ADOPT (adapter, no generador propio) |
| ISO 20022 seev.* | Prowide ISO20022 | ADOPT (adapter) |
| Cálculos CA / TERP / ajustes | vn-corporate-actions (MIT) | PORT selectivo de fórmulas + tests; Decimal-only, nunca float |
| Reconciliación cash entitlement | corp_action_recon_cash (MIT) | REFERENCIA + ampliar |
| Lifecycle financiero | FINOS CDM | REFERENCE / mapping, sin dependencia runtime |
| ISIN validation | python-stdnum | ADOPT como utility de validación (no fuente de identidad) |
| Calendarios/deadlines | pandas_market_calendars | ADOPT como utility, no fuente autoritativa |
| Lineage externo | OpenLineage | LATER / adapter |
| Desktop financiero | FDC3 | LATER / interop |
| Diseño de CA desk | CA Alpha Dashboard | BENCHMARK de producto (dataset sintético; nuestro diferencial = canon evidence-first) |

## Fases

```text
P1  Ops Desk
    P1.0 morning brief (ca-es brief --as-of ...)        DONE
    P1.1 snapshot delta (--previous-canon,             DONE
         NEW/CHANGED/REMOVED_*, conflictos, UNSUPPORTED)
    P1.2 Textual Ops Desk (ca-es desk, read-only        DONE
         sobre brief(); extra `desk`)                    — P1 CLOSED
    deadline queue

P2  Entitlements
    P2.0 cash dividend entitlement                      DONE
         (ca-es entitlement --event <id> --positions p.json
          CA_ES_POSITIONS_V1 / CA_ES_ENTITLEMENT_V1;
          POSITION_AT_RECORD_DATE; INDETERMINATE nunca estima)
    split / stock dividend / rights issue             -> P8
    Decimal-only; fórmulas portadas y testeadas desde vn-corporate-actions

P3  Reconciliation / Exceptions
    P3.0 cash reconciliation                              DONE
         (ca-es reconcile; CA_ES_CASH_MOVEMENTS_V1;
          MATCH / AMOUNT_MISMATCH / MISSING_CASH /
          UNEXPECTED_CASH / INDETERMINATE; sin tolerancias
          ni agregación silenciosa)
    P3.1 cash basis semantics                             DONE
         (CA_ES_CASH_MOVEMENTS_V2: amount_basis =
          GROSS/NET/UNKNOWN; V1 aceptado con basis
          UNKNOWN implícito — nunca se asume bruto;
          GROSS reconcilia contra gross_cash, NET ->
          INDETERMINATE/NET_EXPECTED_NOT_AVAILABLE,
          UNKNOWN -> INDETERMINATE/UNKNOWN_AMOUNT_BASIS;
          sin withholding ni net-to-gross.
          ADR-018: compat V1 = solo ingestión, NO
          resultado — un MATCH V1 anterior pasa a
          INDETERMINATE; es corrección, no regresión)
    P3.5 exceptions / workflow                            DONE
         (ca-es exceptions / case-transition;
          CA_ES_EXCEPTION_CASES_V1: case_key estable,
          factual_status ≠ workflow_status, audit trail
          append-only, REOPENED/NOT_OBSERVED trazables,
          queue determinista; docs/p3/p35-scope.md)

P4  SWIFT / ISO adapters
    P4.0 MT564/MT566 read-only ingest                  DONE
         (docs/p4/p40-scope.md; adapters/iso-adapter-jvm:
          subprocess JVM + Gradle Wrapper +
          pw-swift-core SRU2025-10.3.19 +
          verification-metadata sha256; ca-es swift-facts
          -> CA_ES_SWIFT_MT_FACTS_V1; sin proyección a
          canon; MT565 OUT)
    P4.1 SWIFT semantic projection + event bind         DONE
         (docs/p4/p41-scope.md; ca-es swift-project /
          swift-bind -> CA_ES_SWIFT_CA_MESSAGE_V1 +
          CA_ES_SWIFT_EVENT_BINDING_V1; DVCA->
          CASH_DIVIDEND; BOUND/AMBIGUOUS/NO_MATCH/
          INSUFFICIENT_IDENTITY; AGREES/DIFFERS/
          CANON_MISSING/SWIFT_MISSING/CANON_CONFLICTING;
          canon nunca mutado, cero fuzzy matching)
    P4.2 MT566 -> cash movement candidate               DONE
         (docs/p4/p42-scope.md; ca-es
          swift-cash-candidate ->
          CA_ES_SWIFT_CASH_CANDIDATE_V1; whitelist
          cerrada 19B PSTA/NETO/GRSS ->
          UNKNOWN/NET/GROSS, nunca inferida;
          PROJECTABLE/INDETERMINATE/UNSUPPORTED;
          solo PROJECTABLE emite movement V2;
          MT566-only)
    P4.3 ISO20022 capability + MX facts adapter         DONE
         (docs/p4/p43-see-v-capability.md; decision
          .001/.002 por evidencia javap: lectura ambas,
          escritura .002; pw-iso20022 SRU2025-10.3.10 +
          verification sha256; modo mxfacts ->
          CA_ES_SWIFT_MX_FACTS_V1 con model_path/
          evidence_locator deterministicos; XXE/DOCTYPE/
          malformed fail-closed; PARSE_OK nunca
          SCHEMA/NETWORK/SWIFT_VALID)
    P4.4 seev.031 -> dominio existente                  DONE
         (docs/p4/p44-seev031-scope.md; mx-project/
          mx-bind/mx-election -> mismos contratos
          CA_ES_SWIFT_CA_MESSAGE_V1 / BINDING /
          ELECTION_OPPORTUNITY_V1; paridad MT564)
    P4.5 seev.033 instruction writer                    DONE
         (docs/p4/p45-seev033-scope.md; seev033-project/
          seev033-write -> CA_ES_SEEV033_PROJECTION_V1 /
          CA_ES_SEEV033_XML_V1; BAH head.001.001.02 via
          CA_ES_SWIFT_MX_ENVELOPE_V1 sin defaults;
          BizMsgIdr=instruction_id; round-trip Prowide)
    P4.6 seev.034 status -> instruction binding         DONE
         (docs/p4/p46-seev034-scope.md; mx-status ->
          CA_ES_ELECTION_INSTRUCTION_STATUS_V1 (mismo
          contrato P5.6); binding por InstrId/Id;
          choice status AccptdForFrthrPrcg/Rjctd/Pdg/
          DfltActn -> ACCEPTED/REJECTED/PENDING/
          DEFAULT_ACTION_APPLIED; resto UNSUPPORTED raw;
          paridad MT567)
    P4.7 seev.036 -> cash/security candidates           DONE
         (docs/p4/p47-seev036-scope.md;
          mx-cash-candidate / mx-security-candidate ->
          mismos contratos P4.2/P6.3; basis
          PstngAmt/NetAmt/GrssAmt = UNKNOWN/NET/GROSS
          (prioridad 19B); CdtDbtInd CRDT/DBIT =
          RECEIPT/DELIVERY; PstngQty/Qty/Unit; sin
          agregacion; paridad MT566 e2e)
    P4.8 Cross-transport conformance                    DONE
         (docs/p4/seev-conformance.md; 12 escenarios
          MT<->MX sobre mismos outcomes de dominio;
          diferencias legitimas documentadas)
         — P4 CLOSED (MT + ISO 20022 seev.*)

P5  Elections / deadlines
    P5.0 Operational deadlines                          DONE
         (docs/p5/p50-scope.md; ca-es deadlines ->
          CA_ES_OPERATIONAL_DEADLINE_V1; SOURCE/DERIVED/
          INDETERMINATE; calendar_id explicito via
          CA_ES_CALENDARS_V1, nunca Mon-Fri por defecto;
          reglas preregistradas CA_ES_DEADLINE_RULES_V1;
          canon intacto)
    P5.1 Action Queue + Morning Brief V2                DONE
         (docs/p5/p51-scope.md; ca-es action-queue ->
          CA_ES_ACTION_QUEUE_V1; OVERDUE/DUE_TODAY/
          DUE_SOON/UPCOMING con umbrales explicitos;
          INDETERMINATE aparte; brief --queue ->
          CA_ES_MORNING_BRIEF_V2 donde action_required
          consume deadlines, no date.* por proximidad;
          V1 intacto)
    P5.2 Election Opportunity (MT564 CAOPTN)            DONE
         (docs/p5/p52-scope.md; ca-es swift-election ->
          CA_ES_ELECTION_OPPORTUNITY_V1; CAON/CAOP/DFLT/
          RDDT evidenciados en SRU2025-10.3.19; whitelist
          CASH/SECU; deadline operativo via queue,
          nunca el mas temprano; sin positions ni
          instrucciones)
    P5.3 Election Eligibility (positions x options)     DONE
         (docs/p5/p53-scope.md; ca-es election-eligibility
          -> CA_ES_ELECTION_ELIGIBILITY_V1; reglas
          explicitas CA_ES_ELECTION_ELIGIBILITY_RULES_V1;
          solo POSITION_AT_DATE_FIELD + FULL_POSITION;
          snapshot antes/despues nunca prueba titularidad;
          opportunity bind fail-closed al canon; sin
          eleccion del cliente ni MT565)
    P5.4 Election Instruction Intent                    DONE
         (docs/p5/p54-scope.md; ca-es election-instruction
          -> CA_ES_ELECTION_INSTRUCTION_V1; request
          explicita con instruction_id del caller;
          requested == eligible unicamente (parcial
          UNSUPPORTED, nunca inferido); binding
          fail-closed eligibility<->opportunity; sin
          workflow ni MT565)
    P5.5 MT565 Projection / Serialization               DONE
         (docs/p5/p55-scope.md; ca-es mt565-project ->
          CA_ES_MT565_PROJECTION_V1 con mapping preregistrado
          (SEME=instruction_id, CORP/CAEV/SEME desde facts
          MT564, 13A::CAON + 22F::CAOP + 36B::QINS en CAINST);
          adapter JVM modo "mt565" -> CA_ES_MT565_FIN_V1;
          envelope de transporte explicito, sin defaults;
          solo SERIALIZABLE llega al writer)
    P5.6 MT567 status/advice ingest + binding           DONE
         (docs/p5/p56-scope.md; adapter SUPPORTED +=567
          (extractor generico, sin parser nuevo);
          ca-es instruction-status ->
          CA_ES_ELECTION_INSTRUCTION_STATUS_V1; binding
          solo por LINK 20C::PREV (=SEME=instruction_id),
          BOUND/AMBIGUOUS/NO_MATCH/INSUFFICIENT_IDENTITY;
          whitelist IPRC PACK/REJT/PEND/DFLA; raw siempre
          preservado; instruccion nunca mutada)

P6  Positions / impact
    P6.0 Capability audit / semantic freeze             DONE
         (docs/p6/p60-capability.md; matriz por familia:
          solo CASH_DIVIDEND SUPPORTED; SPLIT UNSUPPORTED
          V1 — factor direction probada en corpus real
          (dividing/multiplying = posterior/anterior) pero
          sin fecha canonica de posicion pre-evento)
    P6.1 Expected position impact                       DONE
         (docs/p6/p61-scope.md; ca-es position-impact ->
          CA_ES_POSITION_IMPACT_V1; solo CASH_RECEIVABLE
          por composicion de CA_ES_ENTITLEMENT_V1, sin
          formula duplicada; reglas explicitas
          CA_ES_IMPACT_RULES_V1; binding por celda)
    P6.2 Projected post-event positions                 DONE
         (docs/p6/p62-scope.md; ca-es project-positions ->
          CA_ES_PROJECTED_POSITIONS_V1; aplicador generico
          de deltas, en V1 solo delta=0; binding por hash
          de positions; nunca fusiona instrumentos)
    P6.3 MT566 security movement candidate              DONE
         (docs/p6/p63-scope.md; ca-es swift-security-candidate
          -> CA_ES_SWIFT_SECURITY_MOVEMENT_CANDIDATE_V1;
          un candidato por SECMOVE (ventanas por 22H);
          whitelist CRDB CRED->RECEIPT DEBT->DELIVERY;
          cantidad solo 36B::PSTA//UNIT; CAEV_MAP +=SPLF;
          ISIN de binding = underlying USECU/USEQ)
    P6.4 Securities reconciliation                      DONE
         (docs/p6/p64-scope.md; ca-es security-reconcile ->
          CA_ES_SECURITY_RECON_V1; clave
          (account,isin,direction); Decimal exacto sin
          tolerancia; UNEXPECTED solo si expected set
          authoritative)
    P6.5 Security exceptions -> P3.5                    DONE
         (classify_cases consume CA_ES_SECURITY_RECON_V1;
          taxonomia aditiva QUANTITY_MISMATCH/
          MISSING/UNEXPECTED_SECURITY_MOVEMENT; case_key
          por sujeto nunca por factual_status)

P7  Automation / operational runtime
    P7.0 Semantic hash policy                            DONE
         (docs/p7/p70-runtime-model.md; canonical JSON;
          timestamps execution-only excluidos —
          generated_at/executed_at/started_at/completed_at/
          run_id; timestamps de negocio semanticos)
    P7.1 SQLite state store                              DONE
         (docs/p7/p71-state-store.md; runs/run_steps/
          artifacts content-addressed + inbox_messages/
          outbox/run_lock; escritura atomica tmp+fsync+
          replace; verificacion sha256 en lectura)
    P7.2 DAG + cache + resume                            DONE
         (docs/p7/p72-dag.md; ca-es ops-init/ops-run
          [--resume]; cache key = step+version+inputs sem+
          config seccion+schema[+as_of]; SKIPPED_UNCHANGED
          solo pasos puros con artefacto re-verificado;
          single-writer BEGIN IMMEDIATE + checkpoints)
    P7.3 MT/MX inbox                                     DONE
         (docs/p7/p73-inbox.md; ca-es ops-inbox;
          detect_family por contenido; boundary JVM;
          EXACT_DUPLICATE por byte sha256 nunca reprocesa;
          DUPLICATE_SEMANTIC por fingerprint de facts
          retenido+clasificado; blobs byte-exactos
          <state>/blobs/; observaciones append-only)
    P7.4 Alert outbox                                    DONE
         (docs/p7/p74-alerts.md; CA_ES_ALERT_OUTBOX_V1;
          alert_key determinista + dedup; PENDING_DELIVERY;
          deadline/exception/inbox-failure/RUN_FAILED)
    P7.5 Operational health                              DONE
         (docs/p7/p75-health.md;
          CA_ES_OPERATIONAL_HEALTH_V1; HEALTHY/DEGRADED/
          FAILED; runtime no verdad de negocio; freshness
          vs as_of del run actual)
    P7.6 Scheduler adapters                              DONE
         (docs/p7/p76-scheduling.md; deploy/systemd|cron|
          windows + .github/workflows/ops-run-example.yml;
          el scheduler externo solo dispara; GHA sintetico
          manual, nunca sube el state store)
    P7.7 OpenLineage export                              DONE
         (docs/p7/p77-openlineage.md; JSONL determinista
          stdlib; datasets artifact:<sha256>/
          cachekey:<sha256>; sin contenido de negocio)
    P7.8 Read surfaces + Desk                            DONE
         (docs/p7/p78-desk-latest.md; ca-es ops-status/
          ops-latest/ops-export-run + desk --latest;
          read-only sobre ultimo run SUCCEEDED; export sin
          inputs confidenciales por defecto)
         — P7 CLOSED
    FDC3 interop (read-only export aislado, opcional)

P8  Economic coverage expansion
    P8.0 Capability audit V2                            DONE
         (docs/p8/p80-capability.md; desbloqueo via
          transporte MT564/MX — el extractor JVM genérico
          ya emite RDTE/NEWO/35B destino/DISF/PRPP;
          canon intacto; familias ENABLED/CONDITIONAL/
          UNSUPPORTED por evidencia)
    P8.1 SPLIT / REVERSE_SPLIT                          DONE
         (docs/p8/p81-split.md; SPLF+SPLR; basis
          RECORD_DATE via 98A::RDTE; ratio 92D::NEWO;
          DISF RDDN/RDUP/STAN/SECU/DIST/BUYU/CINL/UKNW;
          target ISIN via SECMOVE 35B; impact
          SECURITY_DELIVERY+RECEIPT+CASH_IN_LIEU;
          MT566 real MATCH + mismatch -> P3.5;
          CHOS splits fuera de V1)
    P8.2 RIGHTS_ISSUE staged                            DONE
         (docs/p8/p82-rights.md; RHDI MAND =
          distribución de derechos receipt-only;
          EXRI CHOS/VOLU = ejercicio gated por elección
          explícita; subscription_price 90B::PRPP/OFFR;
          nuevas acciones = electos x NEWO; cash payable;
          RELA enlaza etapas; sin elección ->
          PENDING_ELECTION)
    P8.3 CAPITAL_INCREASE (parcial)                     DONE
         (docs/p8/p83-capital-increase.md; solo BONU
          bonus issue receipt-only con instrumento
          destino evidenciado; CAPI/CAPG/PRIO quedan
          UNSUPPORTED_CA_EVENT)
    P8.4 STOCK_DIVIDEND                                 DONE
         (docs/p8/p84-stock-dividend.md; DVSE MAND
          receipt-only position x NEWO, destino explicito)
    P8.5 SCRIP_DIVIDEND                                 DONE
         (docs/p8/p85-scrip-dividend.md; DVOP solo
          CHOS/VOLU; ambas piernas demostrables (cash
          gross_per_share + securities NEWO/destino) o
          INCOMPLETE; elección explicita CASH/SECU;
          MAND no admisible en V1)
    P8.6 DAG integration                                DONE
         (docs/p8/p86-dag-integration.md; step
          securities_events tras process_inbox: dos
          pasadas MT566-candidates -> MT564-cadena;
          solo BOUND reconcilia; elections input
          explicito; casos mergeados con run previo;
          alertas EXCEPTION_CASE desde valores)
         — P8 CLOSED (V1; CAEV no demostrados quedan
           explícitamente UNSUPPORTED)

P9  Live Source Refresh
    P9.1/P9.2/P9.3 source state, live adapters, orchestrator DONE
         (695ffef; source_documents/observations/parse_results
          en schema v2; adapters BME/CNMV/Portfolio con fetch
          byte-exacto + discovery; ausencia en snapshot !=
          desaparición de evidencia previa)
    P9.5/P9.6 canon refresh acumulado + DAG integration     DONE
         (cb2228e; refresh UNCHANGED -> skips downstream;
          doc nuevo -> +1 evento + invalidación selectiva)
    P9.7 source health + availability alerts                DONE
         (0de4956)
    P9.8 backfill/replay + CLI de fuentes                   DONE
         (d2f3ebb)
    P9.9 live smoke opt-in + adapter hardening              DONE
         (3d57bba; floats API -> lexemas sin debilitar la
          regla no-float; shell SPA -> INDEX_NO_PRODUCTS)
    P9.10 e2e demo + live hardening                         DONE
         (f15a838; sanitización de path solo en el componente
          físico, identidad documental intacta; LEG1 167
          docs/eventos, LEG2 UNCHANGED mismo canon,
          LEG3 +1 evento + invalidación selectiva;
          CI run 35346315360 success sobre f15a838)
         — P9 CLOSED

P10 Alert Delivery Boundary
    P10.0-P10.3 arquitectura + contratos + ledger + policy  DONE
         (d018cf3; docs/p10/p100-p103; schema v3 aditivo:
          deliveries + delivery_attempts +
          delivery_transitions; payload_json persistido en
          derivación)
    P10.4-P10.6 FILE + WEBHOOK + SMTP adapters              DONE
         (file atómico/idempotente con DELIVERY_KEY_COLLISION;
          webhook HTTPS http.client con fase pre/post-send
          distinguida, sin redirects por defecto, same-origin
          only, Idempotency-Key; SMTP stdlib STARTTLS con
          Message-ID determinista y transport inyectable)
    P10.7-P10.13 dispatcher + retry + operator control      DONE
         (run_alert_deliver con STARTED durable antes del
          side effect; orphan STARTED -> UNKNOWN_OUTCOME sin
          auto-retry; backoff scheduler-driven sin sleep;
          delivery-status/show/retry/abandon con auditoría
          append-only; agregado outbox.delivery_state sobre
          generación vigente × destinos habilitados)
    P10.11/P10.15 health + live smoke                       DONE
         (bloque delivery en CA_ES_OPS_STATUS_V1 +
          CA_ES_DELIVERY_STATUS_V1; tests/live opt-in file +
          webhook con CA_ES_TEST_WEBHOOK_URL)
    P10.14/P10.16 suite + cross-platform                    DONE
         (tests nuevos: ledger, migración v1/v2->v3, config
          fail-closed/secretish, file, webhook con servidor
          HTTP local, SMTP con transport inyectado,
          dispatcher, CLI; scripts/p10_e2e_demo.py con los
          6 legs de aceptación)
         — P10 CLOSED

P11 Instruction Send Boundary (FileSpoolTransport)
    P11.0-P11.1 arquitectura + contratos                    DONE
         (docs/p11/p110-p113; PREPARED->SPOOLED->
          GATEWAY_*|SWIFT_* separado de MT567/seev.034;
          delivery_id/message_reference/transport_reference/
          content_sha256 como campos distintos;
          CA_ES_TRANSPORT_RECEIPT_V1 como protocolo de
          adapter propio, no estándar SWIFT)
    P11.2 schema v4 aditivo                                 DONE
         (sends + send_attempts + send_transitions +
          send_receipts; migración v1/v2/v3->v4)
    P11.3 FileSpoolTransport                                DONE
         (outbox/receipts/quarantine; tmp->fsync->os.replace;
          .msg antes que .meta (commit); replay idempotente
          con hash binding sobre bytes reales; COLLISION
          fail-closed; verify() post-crash)
    P11.4-P11.6 dispatcher + receipts + config + CLI        DONE
         (orphan recovery con verify; receipt ingestion ->
          GATEWAY_ACCEPTED/REJECTED + transport_reference +
          processed/; quarantine de malformed/duplicados/
          conflictivos; sección send fail-closed;
          send-prepare/dispatch/status/show/retry/abandon +
          bloque send en ops-status)
    P11.7-P11.8 suite + e2e demo                            DONE
         (tests: migración, adapter atómico/idempotente/
          colisión/concurrencia, dispatcher, retry, orphan
          recovery, receipts, config, CLI;
          scripts/p11_e2e_demo.py con los 8 legs;
          docs/ops/instruction-send.md)
         — P11 CLOSED

P12 External Gateway Adapters & Transport Conformance Lab
    P12.0 OSS survey + evidence model                     DONE
         (docs/p12/p120-* + oss-provenance; Paramiko ADOPT,
          ibmmq ADOPT/WRAP, Prowide ADOPT, mq-container
          REFERENCE/opt-in, swiftinc REFERENCE_ONLY,
          qpid-proton DEFERRED_NO_TARGET_PROFILE)
    P12.1-P12.2 SFTP adapter + receipt polling            DONE
         (src/ca_es/transport/sftp.py sobre Paramiko real;
          host verification obligatoria (known_hosts o
          fingerprint pineado), atomic tmp->rename->meta,
          read-back sha, REMOTE_PERSISTED; poll remoto ->
          staging -> validador P11 -> archive/keep;
          40 tests contra servidor SSH/SFTP in-process real)
    P12.3-P12.4 IBM MQ adapter + lab opt-in               DONE
         (src/ca_es/transport/mq.py sobre ibmmq lazy;
          CorrelId "CAES"+sha256(delivery_id)[:20], MQPUT
          bajo syncpoint+commit -> MQ_PUT_CONFIRMED, MQRC
          clasificado permanente/retryable/UNKNOWN;
          scripts/p12_mq_lab.py opt-in P12_MQ_LIVE+LICENSE)
    P12.5-P12.6 FIN service ACK/NAK                       DONE
         (JVM `finsvc` mode -> CA_ES_FIN_SERVICE_RECEIPT_V1;
          correlacion MIR+SEME determinista -> SWIFT_ACKED/
          NAKED; NO_MATCH/AMBIGUOUS/CONFLICTING/DUPLICATE
          fail-closed; sin parser FIN en Python)
    P12.7 SWIFT Messaging API                             DONE
         (p127: IMPLEMENTABLE_BUT_REQUIRES_CREDENTIALS ->
          REFERENCE_ONLY, sin adapter sin sandbox real)
    P12.13-P12.14 send-poll CLI + transport health        DONE
         (send-poll una pasada idempotente; send-status con
          swift_acked/naked por destino)
    P12.15-P12.16 conformance labs + e2e                  DONE
         (scripts/p12_e2e_demo.py legs S1-S5+F1-F4 verde)
         — P12 CLOSED

P13 Custody Position / Cash Feeds
    P13.6-P13.11 cash observation + binding + recons + cases  DONE
         (9d1f204; CA_ES_CASH_MOVEMENTS_V2 como contrato de
          observacion; binding explicito nunca por amount+date;
          recons de posicion/cash feed + health)
    P13.12+P13.15-P13.17 custody inbox P7 + CLI + e2e        DONE
         (497f8dd; conformance + scripts/p13_e2e_demo.py
          legs S1-S7)
         — P13 CLOSED

P14 Tax / Withholding / Net Entitlement
    P14.0 capability audit + OSS survey                     DONE
         (5d06a5a; AEAT/BOE como fuentes efectivo-datadas;
          OpenFisca evaluado y rechazado para V1)
    P14.1-P14.14 tax evidence/profile/rules/entitlement/recon DONE
         (1bf8e3f; CA_ES_TAX_EVIDENCE_V1 EXPECTED/ACTUAL con
          scopes por opcion; CA_ES_TAX_PROFILE_V1;
          CA_ES_TAX_RULES_V1 estatico; CA_ES_TAX_ENTITLEMENT_V1;
          CA_ES_EXPECTED_CASH_V1; CA_ES_TAX_RECON_V1; actual
          nunca inferido de gross-net; NET cash recon cierra
          NET_EXPECTED_NOT_AVAILABLE de forma opt-in)
    P14.18 P7 tax_events DAG step                            DONE
         (34fbd13; sin profile/rules -> indice minimo estable,
          no invalida cache downstream)
    P14 JVM facts + fixtures + docs + e2e                    DONE
         (c60839e+51635eb; MT566/seev.036 ACTUAL verificados
          contra Prowide pinneado; scripts/p14_e2e_demo.py
          10 legs; CI run 35390408395 success)
         — P14 CLOSED

P15 Tax Recovery Lifecycle
    P15.0 capability audit + OSS survey                      DONE
         (9c78f83; TARE/BORE/TXRC como facts FIN genericos en
          pin SRU2025 sin tocar adapter; MX TARE/BORE = SR2026,
          gap forward-compatible documentado; seev.050-053
          market claims NO reutilizados para tax reclaim)
    P15.1-P15.7 lifecycle core                               DONE
         (9148840; CA_ES_TAX_RECOVERY_RULES/ASSESSMENT/CASE/
          DOCUMENT_SET/INSTRUCTION/STATUS/RECON_V1;
          RELIEF_AT_SOURCE/QUICK_REFUND/STANDARD_RECLAIM;
          recoverable_amount solo con regla+perfil+evidencia,
          nunca de actual>expected; refund cash ligado solo
          por referencia explicita)
    P15.8-P15.9 P7 tax_recovery step + recovery CLI          DONE
         (2bacd98; excepciones recovery -> P3.5)
    P15.10-P15.11 R1-R12 + e2e + docs                        DONE
         (3396eff; 30 tests + scripts/p15_e2e_demo.py 15 legs;
          docs/p15/p150-p152; CI run 35420623083 success)
         — P15 CLOSED

P16 Market Claims Lifecycle V1
    P16.0 capability audit + OSS survey                      DONE
         (df7776a; seev.050.001.01-03/051.001.01-02/052-053
          .001.01-03 verificados contra pin SRU2025 via javap;
          seev.060-067 Buyer Protection = doc-only, candidato
          P18; SR2026 .001.04 fuera del pin)
    P16.1-P16.6 lifecycle core                               DONE
         (2ecc000; CA_ES_MARKET_CLAIM_BASIS/RULES/ASSESSMENT/
          CLAIM/MESSAGE/STATUS/CANCELLATION/RECON_V1; claim
          nunca inferida de trade-before-ex + settlement-after-
          record; sin regla -> MARKET_PRACTICE_REQUIRED)
    P16.7 P7 market_claims step + CLI mc-* + P3.5            DONE
         (06f0439; indice minimo estable sin rules/tx)
    P16.8-P16.9 M1-M15 + e2e + JVM whitelist + docs          DONE
         (f6ea9a4; 30 tests + scripts/p16_e2e_demo.py 18 legs
          con seev.050-053 reales; docs/p16/p160-p162;
          CI run 35426091227 success)
         — P16 CLOSED
```

## Prioridad actual

P1–P16 cerrados (incl. P4 MT + ISO 20022 seev.* con conformance
MT<->MX verificada, P7 daily operations end-to-end, P8 economic
coverage V1 para SPLIT/REVERSE_SPLIT, RIGHTS_ISSUE staged,
STOCK_DIVIDEND, SCRIP_DIVIDEND y CAPITAL_INCREASE=BONU, P9 live
source refresh, P10 alert delivery boundary con FILE/WEBHOOK/
SMTP, P11 instruction send boundary con FileSpoolTransport,
P12 transport conformance lab con SFTP/IBM-MQ/FIN-ACK-NAK
reales sobre OSS, P13 custody position/cash feeds, P14 tax/
withholding/net entitlement con evidencia EXPECTED/ACTUAL y
NET cash recon, P15 tax recovery lifecycle completo
RELIEF_AT_SOURCE/QUICK_REFUND/STANDARD_RECLAIM con
recoverable_amount solo por regla+perfil+evidencia, y P16
market claims lifecycle seev.050-053 con claim nunca inferida
de trade-before-ex + settlement-after-record).
SPOOLED/MQ_PUT_CONFIRMED/REMOTE_PERSISTED no son submission
SWIFT; GATEWAY_* requiere receipt externo real + trust
boundary operacional; SWIFT_ACKED/NAKED requiere service
message FIN 21 correlado. Lo que sigue sin demostrar: compat
con el perfil concreto de Alliance/middleware de una entidad —
requiere ese boundary real.
Siguiente: P17 Securities Transaction & Settlement Feed V1
(MT540-548/536/537 + sese.023-025 -> CA_ES_SETTLEMENT_
OBSERVATION/TRANSACTION/STATUS/RECON -> SECURITIES_
TRANSACTIONS_V1 output compatible P16; identidad solo por
referencias explicitas, nunca ISIN+qty+fecha; partial
settlement cumulative; FX queda como boundary explicito
pendiente).
Sin nuevos gates formales (G4+ no existen); cada fase con tests
y preregistro de scope.

## Deuda conocida (no bugs)

- El join SAN→posición usa `isin='ESTIMACIONES'` (quirk del canon):
  demuestra cálculo y trazabilidad, no una cadena de identificación
  de instrumento realista. Deuda del corpus / instrument binding,
  no del entitlement engine.
