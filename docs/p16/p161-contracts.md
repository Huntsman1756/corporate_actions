# P16 — contratos: Market Claims Lifecycle V1

Transport-neutral: la familia seev.050-053 (facts MX genericos
via adapter Prowide) y los inputs declarados convergen en los
mismos documentos de dominio. Ningun contrato genera XML/MT —
la generacion ISO queda fuera del core (ADR-010).

## CA_ES_SECURITIES_TRANSACTIONS_V1 (input)

Transacciones de valores declaradas por el operator/feed:
`transaction_id`, `settlement_instruction_id`, `account_id`,
`isin`, `quantity`, `direction` (BUY|SELL), `trade_date`,
`settlement_date`, `settlement_status` (PENDING|SETTLED|
SETTLED_LATE|FAILED|CANCELLED), `counterparty_ref`,
`provenance[]`. Sin feed real pinneado: formato declarado,
provenance obligatoria.

## CA_ES_MARKET_CLAIM_BASIS_V1

`market_claim_basis.claim_basis(transactions_doc, canonical_event_id,
event_type, ex_date, record_date, payment_date)`. Por tx:
facts normalizados + `trade_date_relation` (BEFORE_EX_DATE|
ON_OR_BEFORE_EX_DATE|ON_OR_AFTER_EX_DATE|AFTER_EX_DATE|UNKNOWN)
+ `settlement_date_relation` (AFTER_RECORD_DATE|
ON_OR_AFTER_RECORD_DATE|ON_OR_BEFORE_RECORD_DATE|
BEFORE_RECORD_DATE|UNKNOWN) + `facts_proven` + `reason_codes` +
`provenance`. Fechas ausentes -> relation UNKNOWN, nunca inferidas.

## CA_ES_MARKET_CLAIM_RULES_V1

Ruleset estatico, validado (`mc-rules-validate`), sin codigo
ejecutable. Por regla: `rule_id`, `jurisdiction`, `event_type`,
`valid_from`/`valid_to`, `claim_type` (MKTC|RVMC),
`claim_direction` (BUYER_COMPENSATED|SELLER_COMPENSATED),
`eligibility` {trade_date_relation, settlement_status[],
settlement_date_relation}, `proceeds` {kind: CASH|SECURITIES},
`deadline` {basis: RECORD_DATE|PAYMENT_DATE, days}. Solapes
misma (jurisdiction, event_type, direction, vigencia) -> error.

## CA_ES_MARKET_CLAIM_ASSESSMENT_V1

`claim_assessment(basis, rules, jurisdiction, assessment_date,
proceeds_rate, proceeds_currency, proceeds_quantity_ratio,
proceeds_target_isin)`. Items: `status` PROVEN | INDETERMINATE |
MARKET_PRACTICE_REQUIRED | NOT_APPLICABLE + `claim_id`
determinista (`MC-<hash16>` de event+tx+rule) +
`expected_amount`/`expected_quantity` (Decimal, proceeds
explicito) + `proceeds_direction` (RECEIPT|DELIVERY) +
`deadline_date` + `reason_codes` + `evidence_refs`.
Reglas: basis sin facts_proven -> INDETERMINATE; sin ruleset o
sin regla vigente -> MARKET_PRACTICE_REQUIRED; >1 regla ->
INDETERMINATE (AMBIGUOUS_CLAIM_RULES); eligibility fallida ->
NOT_APPLICABLE; proceeds ausente -> INDETERMINATE
(PROCEEDS_BASIS_REQUIRED).

## CA_ES_MARKET_CLAIM_V1

`open_claims(assessment)` — solo PROVEN abre claim `EXPECTED`.
`merge_claims(previous, new)` — merge por claim_id: conserva
status/history/binding refs de la viva; tx desaparecida no borra
la claim. `transition()` — maquina de estados auditada:

```
EXPECTED -> NOTIFIED -> PENDING/MATCHING/ACCEPTED/REJECTED
         |  (todos) -> CANCELLATION_REQUESTED -> CANCELLED
         |  NOTIFIED+ -> PARTIALLY_SETTLED -> SETTLED
ACCEPTED -> solo CANCELLATION_REQUESTED/CANCELLED/
            PARTIALLY_SETTLED/SETTLED (no rechazable)
REJECTED/CANCELLED/SETTLED = terminal
```

Cada claim: `binding_references[]` (claim_id + TxRef +
RltdSttlmInstrId + transaction_id), `notification_refs[]`,
`history[]` auditada, `pre_cancellation_status` durante cancel.

## CA_ES_MARKET_CLAIM_MESSAGE_V1

Proyecciones normalizadas desde facts MX (`project_market_claim`,
`project_claim_status`, `project_claim_cancellation`):
`kind` CLAIM_CREATION|CLAIM_STATUS|CANCELLATION_REQUEST|
CANCELLATION_STATUS + `status` PROJECTED|UNSUPPORTED +
`projection` {references (AcctSvcr/MktInfrstrctr/Prcr/Cre/CxlReq
ids), canonical_event_reference, event_type_code, isin,
safekeeping_account, market_claim_type, transfer_of_proceeds,
cash/securities_movements, status_choice + internal_status}.
`bind_claim` -> BOUND (exactamente 1 candidato) | AMBIGUOUS |
NO_MATCH. Choices seev.052: AccptdForFrthrPrcg->ACCEPTED,
Pdg->PENDING, MtchgSts->MATCHING, Rjctd->REJECTED,
Canc->CANCELLED, PrtrySts->PROPRIETARY (sin mapeo). seev.053:
CxlCmpltd->CANCEL_COMPLETED, Accptd->CANCEL_ACCEPTED,
Rjctd->CANCEL_REJECTED, PdgCxl->CANCEL_PENDING.

## CA_ES_MARKET_CLAIM_STATUS_V1

`apply_claim_events(claims, events)` — eventos NOTIFICATION |
STATUS | CANCELLATION_REQUEST | CANCELLATION_STATUS |
SETTLEMENT_OBSERVED. Outcomes: APPLIED | REJECTED_EVENT |
DUPLICATE_IGNORED | CONFLICTING_NOTIFICATION. Idempotencia por
`source_ref`. Conflicto de amount/quantity observado vs expected:
auditado, nunca overwrite.

## CA_ES_MARKET_CLAIM_CANCELLATION_V1

`cancellation_doc(claims, cancel_events)` — intents
(CANCELLATION_REQUEST) vs outcomes (CANCELLATION_STATUS) por
claim; `current_outcome` REQUESTED|ACCEPTED|REJECTED|PENDING|
NO_OUTCOME. Intent separado del estado del claim.

## CA_ES_MARKET_CLAIM_RECON_V1

`claim_recon(claims, movements_docs)` — cash (CASH_MOVEMENTS_V2)
y securities (SECURITIES_MOVEMENTS_V1) ligados SOLO por
referencia explicita (claim_id / binding refs / source_reference).
Statuses: MATCH | AMOUNT_MISMATCH | QUANTITY_MISMATCH |
NO_SETTLEMENT_OBSERVED | NOT_NOTIFIED | REJECTED | CANCELLED |
SETTLED | INDETERMINATE. Over/under settlement via reason_codes
SETTLEMENT_EXCEEDS/BELOW_EXPECTED + outstanding_amount/quantity.
Claims no settleable (EXPECTED sin notificar, terminales) no
producen mismatch. FX divergente -> INDETERMINATE (FX_REQUIRED).

## P3.5

`exceptions.classify_cases(recon)` — case_key estable
`market-claim|<event>|<claim>`; filtra NO_SETTLEMENT_OBSERVED,
NOT_NOTIFIED, INDETERMINATE, SETTLED (informativos). Mismatches
-> prioridad segun mapa; desconocidos -> LOW con reason.
