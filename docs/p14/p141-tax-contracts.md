# P14 — contratos: Tax, Withholding & Net Entitlement V1

Cadena:

```text
facts (MT564/seev.031 | MT566/seev.036)
    -> CA_ES_TAX_EVIDENCE_V1            (tax_evidence.py)
CA_ES_ENTITLEMENT_V1 + evidence
    + CA_ES_TAX_PROFILE_V1 + CA_ES_TAX_RULES_V1
    -> CA_ES_TAX_ENTITLEMENT_V1         (tax_entitlement.py)
    -> CA_ES_EXPECTED_CASH_V1           (expected_cash)
CA_ES_TAX_ENTITLEMENT_V1 vs evidence ACTUAL
    -> CA_ES_TAX_RECON_V1               (tax_recon.py)
    -> CA_ES_EXCEPTION_CASES_V1         (exceptions.py, scope tax)
CA_ES_EXPECTED_CASH_V1 + movements V2
    -> CA_ES_CASH_RECON_V1 (NET)        (reconciliation.py)
```

## CA_ES_TAX_EVIDENCE_V1

Evidencia, no calculo. `evidence_role`: `EXPECTED` (MT564,
seev.031) / `ACTUAL` (MT566, seev.036). `scopes[]` con
`scope`: `EVENT`/`OPTION`/`CASH_MOVEMENT`, `option_number`,
`option_type`, `sequence[_occurrence]`, `items[]`.

Item: `tax_type` (`WITHHOLDING_PRIMARY`,
`WITHHOLDING_SECOND_LEVEL`, `TAX_CREDIT`, `TAX_FREE`,
`TAX_RECLAIM`, `TAXABLE_BASIS`, `GROSS_AMOUNT`, `NET_AMOUNT`,
`EXEMPTION_TYPE`, `JURISDICTION`, `INCOME_TYPE`,
`OTHER_EXPLICIT`, `UNCLASSIFIED`), `raw_qualifier`, `kind`
(`rate`/`amount`/`selector`/`other`), `rate` + `rate_lexeme` +
`rate_unit` (`PERCENTAGE`), `rate_type`, `amount` +
`amount_lexeme` + `currency`, `jurisdiction_code`,
`selector_value`, `provenance[]`.

Sin aritmetica; ocurrencias repetidas -> items repetidos.

## CA_ES_TAX_PROFILE_V1

`profiles[]` por `account_id` con `valid_from`/`valid_to` y campos
explicitos (`tax_residency`, `entity_person_classification`,
`beneficial_owner_category`, `tax_exempt_status`, `treaty_profile`,
`relief_at_source_status`, `reclaim_status`, `provider_profile`,
`source`, `evidence_refs`). Campo desconocido -> error. Nada se
infiere (ni residencia por IBAN/BIC/emisor). Ventanas duplicadas
por cuenta -> conflicto.

## CA_ES_TAX_RULES_V1

`rules[]` con `rule_id`, `jurisdiction`, `income_type`,
`valid_from`/`valid_to`, `conditions` (listas por campo de
perfil), `rate_source` (`CONFIGURED_STATUTORY_RATE`,
`CONFIGURED_TREATY_RATE`, `SOURCE_DECLARED_RATE`, `EXEMPT`),
`rate`+`rate_unit`, `calculation_basis`
(`GROSS_ENTITLEMENT`|`EXPLICIT_BASIS`+`basis_tax_type`),
`rounding` (`mode` `HALF_UP|HALF_EVEN|DOWN|UP|NONE`, `scale`,
`currency`), `authority`, `evidence_refs`.

Validacion estatica: campos obligatorios, enums, ventanas
coherentes, solapes no disjuntos rechazados. Sin `eval()`.

## CA_ES_TAX_ENTITLEMENT_V1

Por entitlement `ENTITLED`: `gross_entitlement`,
`tax_components[]` (`component_type`, `basis`, `rate_fraction`,
`rate_source`, `amount`, `currency`, `rule_id`,
`evidence_refs`), `total_withholding`, `expected_net_cash`,
`status` (`CALCULATED`/`INDETERMINATE`/`UNSUPPORTED`/
`CONFLICTING`/`PENDING_ELECTION`), `reason_codes`, `conflicts`,
`trace` estructurado (gross, rule, rate, basis, raw_tax,
rounding, withholding, net, fecha, campos de perfil usados),
`rule_id`, `ruleset_sha256`, `profile_sha256`.

Formula: `withholding = basis x rate_fraction` (Decimal, ctx 40),
`net = gross - withholding`. Rounding solo segun `rule.rounding`.
Segunda capa sin basis probada -> `UNSUPPORTED_MULTI_LEVEL_TAX`.
Rate fuente != regla -> `CONFLICTING` (`SOURCE_RULE_RATE_CONFLICT`
o `MULTIPLE_TAX_RATES`). Divisa basis != bruto -> `FX_REQUIRED`.

## CA_ES_EXPECTED_CASH_V1

`items[]` por cuenta: `gross_expected`, `tax_expected`,
`other_deductions_expected`, `net_expected` (null si no
CALCULATED), `currency`, `gross_basis_status`, `tax_status`,
`net_status` (`AVAILABLE`/`NOT_AVAILABLE`), `reason_codes`,
`evidence_refs`. Lado esperado del recon NET; el movimiento V2 es
el actual.

## CA_ES_TAX_RECON_V1

`items[]` por componente: `MATCH`, `WITHHOLDING_AMOUNT_MISMATCH`,
`WITHHOLDING_RATE_MISMATCH`, `MISSING_TAX_COMPONENT`,
`UNEXPECTED_TAX_COMPONENT`, `INDETERMINATE`. Solo compara
componentes explicitos; `gross - net` nunca se interpreta como
impuesto. `case_scope: "tax"`; INDETERMINATE no produce caso.

## NET cash recon (aditivo P3)

`reconcile(entitlement, movements, expected_cash_doc=None)`:
movimiento `NET` con `net_expected` disponible -> MATCH/
AMOUNT_MISMATCH exacto (Decimal, sin tolerancia). Sin doc ->
`NET_EXPECTED_NOT_AVAILABLE` (comportamiento P3 intacto).

## P7

Step `tax_events` (deps: `entitlements` + `process_inbox`;
`uses_inputs`: `canon`, `source_policy`, `tax_profile`,
`tax_rules`; `config_section: tax`): evidencia ligada por binder
canonico (MT564/seev.031) o por referencia de evento compartida
(MT566/seev.036), entitlement fiscal, expected cash (alimenta
`cash_reconciliation` via `_expected_cash`), tax recon y casos en
el mismo indice. `inputs.tax_profile`/`inputs.tax_rules` en la
config del run; `config.tax.jurisdiction`.
