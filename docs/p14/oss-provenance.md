# P14.27 — OSS / source provenance

| componente/fuente | version/fecha | licencia | rol | runtime dep? | reference only? | codigo copiado? |
|---|---|---|---|---|---|---|
| prowide-core | SRU2025-10.3.19 | Prowide (ver build.gradle.kts) | facts FIN (92A/19B TAXR, WITL, NETT, WTAX…) | si (adapter JVM, ya pinneado) | no | no |
| prowide-iso20022 | SRU2025-10.3.10 | Prowide | facts seev (WhldgTaxRate, ScndLvlTax, AmtDtls tax) | si (mismo) | no | no |
| SWIFT MT MRG (us5mb) | SRU2025 | propietario/público | semantica qualifiers FIN | no | si | no |
| ISO 20022 e-repository / modelo Prowide | SRU2025 | público | semantica paths seev | no | si | no |
| FINOS CDM | actual | Community Spec License | referencia de modelado tax | no | si | no |
| OpenFisca Core | evaluada, no adoptada | AGPL-3.0 | referencia arquitectonica (parametros effective-dated) | no | si | no |
| AEAT — tipos de retención capital mobiliario | cuadro 2026 | oficial | parametro legal ES 19% | no (es dato en ruleset) | si | no |
| BOE L35/2006 art.101; RDL 20/2011 DA35; Ley 48/2014; RDL 9/2015; Ley 48/2015; Ley 17/2012 | vigentes/históricos | oficial | effective dates de tipos ES | no | si | no |
| RDL 4/2004 TRLIS; Ley 27/2014 LIS; RD 1776/2004 LIRNR | vigentes | oficial | soporte del 19% para IS/IRNR | no | si | no |

Reglas:

- Ninguna tabla fiscal vendorada de webs secundarias; los
  parametros del ruleset ES citan autoridad oficial por regla
  (`authority` + `evidence_refs` en `CA_ES_TAX_RULES_V1`).
- Los datos fiscales viven en `CA_ES_TAX_RULES_V1` (config), no en
  el codigo: cambiar la regla no requiere release.
- Fuentes secundarias (guias de custodio, agregadores) solo
  sirvieron para descubrir; nunca como evidencia de parametro.
