# P14.0 — OSS / standards survey: withholding tax

Scope: calcular la retención *operativa* esperada sobre un pago de
corporate action (expected withholding → expected net), nunca la
responsabilidad fiscal final del inversor.

## Candidatos

| fuente | licencia | alcance | mantenimiento | decisión |
|---|---|---|---|---|
| prowide/prowide-core SRU2025-10.3.19 | Prowide | modelos MT + Field92A/19B genéricos | activo, pinneado | **ADOPT** — ya boundary de facts; TAXR/WITL/NETT salen por el walker genérico |
| prowide/prowide-iso20022 SRU2025-10.3.10 | Prowide | modelos seev.031/036 con WhldgTaxRate, AmtDtls tax | activo, pinneado | **ADOPT** — mismo |
| SWIFT MT MRG (us5mb) / ISO 20022 e-repository | propietario/público | semántica de qualifiers y elementos | normativa | REFERENCE — fuente de verdad semántica |
| FINOS CDM | Community Spec License | tax/withholding en eventos de ciclo de vida | activo | REFERENCE — modelo demasiado amplio; no hay mapeo 1:1 con nuestros contratos |
| OpenFisca (openfisca-core) | AGPL-3.0 | rules-as-code con parametros versionados por fecha | activo | **REFERENCE** — no existe paquete ES de withholding sobre CA; su modelo de `parameters(period)` confirma el diseño efective-dated que adoptamos como datos, sin adoptar el motor |
| AEAT sede electrónica (manual IRPF/IS/IRNR, cuadro tipos retención 2026) | oficial | tipo retención capital mobiliario ES | oficial | **ADOPT como evidencia** — parámetros legales V1 |
| BOE (L35/2006 art.101, RDL 20/2011, Ley 48/2015, RDL 9/2015, RDL 4/2004 TRLIS, Ley 27/2014 LIS, RD 1776/2004 LIRNR) | oficial | effective dates de tipos | oficial | **ADOPT como evidencia** |
| github search: "withholding engine", "dividend tax" | varias | nada maduro para CA withholding ES | — | REJECT — no hay motor reusable con licencia y dominio adecuados |

## Conclusión de estrategia (P14.7)

**Opción A — pequeño evaluador declarativo ca-es.** Las reglas son
datos JSON (`CA_ES_TAX_RULES_V1`) con predicados explícitos
(`residency`, `beneficial_owner_category`, `income_type`,
`valid_from/to`), rate explícita o referencia a
`SOURCE_DECLARED_RATE`, basis explícita, rounding explícito.
Sin `eval`, sin código en config, validación estática del ruleset.
OpenFisca queda como referencia arquitectónica del
versionado-por-fecha; adoptar el motor entero para ~6 reglas ES
sería desproporcionado y AGPL.

## Evidencia legal ES (V1, solo dividendos cash)

| periodo (fecha de exigibilidad) | tipo retención | autoridad |
|---|---|---|
| 2010-01-01 → 2011-12-31 | 19% | Ley 39/2010 |
| 2012-01-01 → 2014-12-31 | 21% | RDL 20/2011 (DA35 LIRPF), prorrogado 2014 por Ley 17/2012 |
| 2015-01-01 → 2015-07-11 | 20% | Ley 48/2014 |
| 2015-07-12 → 2015-12-31 | 19,5% | RDL 9/2015 |
| 2016-01-01 → | 19% | Ley 48/2015 / L35/2006 art.101 (AEAT cuadro 2026) |

Mismo tipo para perceptor persona física residente (IRPF),
entidad residente (IS — retención sobre dividendos percibidos) y
no residente sin convenio acreditado (IRNR art.25.1.f/31 — 19%).
Solo se soportan esos tres perfiles explícitos; convenios,
exenciones parciales y entidades exentas → PROFILE_REQUIRED.
