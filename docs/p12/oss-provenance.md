# P12.18 — OSS provenance

Procedencia de todo componente externo usado o referenciado en P12.
Sin código copiado sin atribución; dependencias runtime pineadas;
productos propietarios jamás redistribuidos.

## Componentes

| nombre | repo | versión/pin | licencia | uso | runtime dep? | código copiado? |
|---|---|---|---|---|---|---|
| pw-swift-core (Prowide) | prowide/prowide-core | SRU2025-10.3.19 (gradle verification sha256) | Apache-2.0 | parseo FIN service 21 en adapter JVM | sí (adapter JVM ya existente) | no |
| paramiko | paramiko/paramiko | >=3.4,<5 (extra `sftp`) | LGPL-2.1 | cliente SFTP + servidor in-process tests | opcional (extra) | no |
| OpenSSH (sshd/sftp-server) | openssh/openssh-portable | paquete del sistema | BSD-style | servidor SFTP real en lab/CI | no (sistema) | no |
| ibmmq | ibm-messaging/mq-mqi-python | >=2,<3 (extra `mq`) | Python-2.0 | adapter IBM MQ | opcional (extra) | no |
| IBM MQ C client | IBM | >=9.1 redistributable client | IBM | runtime requerido por ibmmq | opt-in local | no (propietario, NO redistribuido) |
| mq-dev-patterns | ibm-messaging/mq-dev-patterns | master | Apache-2.0 | patrones syncpoint/correlación | no | no |
| mq-container | ibm-messaging/mq-container | icr.io/ibm-messaging/mq | Apache-2.0 scripts / IBM MQ Adv for Developers (producto) | lab opt-in local | no | no — imagen nunca vendorizada; LICENSE=accept lo pone el operador |
| swiftinc api-sample-code | swiftinc/api-sample-code | main | SWIFT (LICENSE.pdf) | referencia contrato Messaging API | no | no |
| qpid-proton | apache/qpid-proton | — | Apache-2.0 | evaluado, sin target | no | no |

## Notas de licencia

- **LGPL-2.1 (paramiko)**: usado como dependencia opcional sin
  modificación ni copia de código — compatible con Apache-2.0 del
  proyecto en uso de librería instalada por el usuario.
- **Python-2.0 (ibmmq)**: licencia permissive; el binding es OSS,
  pero requiere el cliente IBM MQ (propietario/redistribuible
  cliente) instalado aparte.
- **IBM MQ Advanced for Developers**: licencia IBM de producto; no
  permite redistribución y restringe uso a máquina de desarrollo.
  `scripts/p12_mq_lab.py` exige `P12_MQ_LIVE=1` y que el operador
  pase `LICENSE=accept` a la imagen por sí mismo. Jamás en CI
  pública.
- **SWIFT LICENSE.pdf (api-sample-code)**: licencia propietaria de
  muestra; solo lectura de referencia.

## Regla

Nada de esto convierte un lab en producción: los adapters están
probados contra implementaciones OSS/oficiales reales (OpenSSH,
Paramiko server, IBM MQ Developer, Prowide), lo cual demuestra
conformidad de protocolo y del contrato P11 — NO compatibilidad
con el perfil concreto de un gateway bancario ni certificación
SWIFT.
