# Seguridad

## Alcance y soporte

Proyecto en desarrollo: no se declara preparación para producción ni
se garantiza que los parsers sean seguros para cualquier entrada hostil.
PDF, mensajes SWIFT y otros documentos externos requieren cautela;
el adaptador JVM/Prowide y los extras tienen dependencias propias.
Esta política no promete SLA, plazos de respuesta ni una matriz de
versiones con mantenimiento de seguridad.

## Reportar de forma privada

Si el alojamiento tiene habilitado el reporte privado de vulnerabilidades,
úsalo (en GitHub: *Security → Report a vulnerability*). No se presupone
que esté habilitado ni se inventa una dirección de contacto.

Si no está disponible, solicita al propietario un canal privado sin
publicar detalles de la vulnerabilidad. Espera a disponer de ese canal
antes de enviar información sensible; no abras un reporte público con
muestras reales, secretos o detalles explotables.

Incluye versión/commit, componente afectado, entorno, impacto observado
y una reproducción sintética mínima. No adjuntes documentos `LOCAL_ONLY`,
datos personales, credenciales, posiciones o movimientos reales ni
muestras selladas/extraídas, tampoco en logs o capturas. Describe el
patrón de forma abstracta si no puedes producir una muestra inocua.

## Corpus y publicación pendiente de autorización

La política [ADR-011](docs/decisions/ADR-011-raw-source-redistribution-policy.md)
distingue evidencia real y materiales redistribuibles; no debe interpretarse
como autorización para publicar todo el checkout. Existe corpus
sellado/extraído trackeado con clearance de publicación pendiente del
propietario. Estar en Git o superar tests no acredita derechos de
redistribución ni ausencia de datos sensibles.

Antes de publicar el repositorio, paquetes o artefactos derivados, obtener
aprobación explícita del propietario sobre los materiales incluidos y su
redistribución. No inspeccionar, parsear ni alterar el corpus sellado para
resolver este permiso. Preservar las restricciones HOLDOUT, el parser
freeze y los artefactos congelados definidos en [AGENTS.md](AGENTS.md) y
el [runbook G1-R](docs/gates/g1r-execution-runbook.md).

La configuración del paquete puede excluir corpus del wheel, pero eso
no da clearance a un checkout, archivo del repositorio o adjunto de una
release. Esta política no afirma presencia ni ausencia de paquetes en
PyPI ni protecciones activas del alojamiento. Véase también
[CONTRIBUTING.md](CONTRIBUTING.md).
