# ADR-007 — Source roles and Iberclear REFERENCE_ONLY

Status: ACCEPTED (G0 freeze, 2026-09-13)

## Context

`country = ES` no implica `CSD = Iberclear`, y un venue no determina el
CSD. Además, no se ha demostrado una interfaz pública de ingesta de
Iberclear.

## Decision

- Los roles de infraestructura se modelan explícitamente:
  `ISSUER_CSD`, `INVESTOR_CSD`, `SETTLEMENT_SYSTEM`, `TRADING_VENUE`,
  `CORPORATE_ACTION_AGENT`, `PAYING_AGENT`, `PAYMENT_CHANNEL`.
- Un rol solo se asigna con evidencia explícita.
- Nunca se eleva `PAYMENT_CHANNEL` a `ISSUER_CSD` (`NO_ROLE_UPCASTING`).
- Iberclear entra como:
  ```yaml
  ingestion_status: REFERENCE_ONLY
  availability_claim: PUBLIC_INGEST_INTERFACE_NOT_PROVEN
  ```
  No se afirma que carezca de feed, solo que no hay interfaz pública
  demostrada.

Parlem aporta evidencia explícita de registro contable en Iberclear
(`ISSUER_CSD=IBERCLEAR`). P3 aporta `PAYMENT_CHANNEL=EUROCLEAR_FRANCE`,
que no implica CSD.

Gates: `CSD_NOT_ASSUMED_FROM_VENUE`, `INFRASTRUCTURE_ROLE_EXACT`,
`NO_ROLE_UPCASTING`, `SOURCE_ROLE_EXPLICIT`, `IBERCLEAR_SOURCE_AVAILABILITY`.
