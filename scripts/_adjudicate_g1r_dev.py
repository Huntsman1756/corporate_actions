# -*- coding: utf-8 -*-
"""Adjudicacion DEV G1-R (propuesta, pendiente de firma humana).

Genera:
  g1r/adjudication/dev-seed-review.jsonl        verdicts por seed
  g1r/adjudication/dev-missingness-review.jsonl ground truth por campo critico
  g1r/adjudication/dev-instrument-review.jsonl  resolucion de instrumento
  g1r/results/dev-failure-catalog.json          clases de fallo genericas
  g1r/manifests/dev-adjudication-sha256.json    SHA256 de los 4 artefactos

Los valores esperados proceden de la lectura del documento oficial
(g1r/adjudication/dev-text/<id>.txt); nunca del parser.
"""
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from ca_es.canonical import canonical_bytes  # noqa: E402

TS = '2026-09-14'
REV = 'devin-agent'
FACTS = json.loads(
    (REPO / 'g1r/adjudication/_dev_facts.json').read_text(encoding='utf-8'))

FIELDS = ['event_type', 'ex_date', 'record_date', 'payment_date',
          'amount_or_ratio', 'currency']

FIELD_NS = {
    'event_type': ['event_type'],
    'ex_date': ['date.ex_date'],
    'record_date': ['date.record_date'],
    'payment_date': ['date.payment_date'],
    'amount_or_ratio': None,   # cualquier amount.*/ratio.*
    'currency': ['instrument.currency'],
}


def emitted(fid, field):
    f = FACTS.get(fid, {})
    if field == 'amount_or_ratio':
        return {k: v for k, v in f.items() if k.startswith(('amount.', 'ratio.'))}
    if field == 'currency':
        out = {}
        if 'instrument.currency' in f:
            out['instrument.currency'] = f['instrument.currency']
        for k, v in f.items():
            if k.startswith(('amount.', 'ratio.')) and isinstance(v, dict) and v.get('__financial__'):
                out[k + '.currency'] = v['currency']
        return out
    return {k: f[k] for k in FIELD_NS[field] if k in f}


def fin(normalized, currency='EUR'):
    return {'normalized': normalized, 'currency': currency}


# =========================================================================
# SEED VERDICTS  (verdict, family, lifecycle, affected_note, quote)
# Fronteras de taxonomia FIRMADAS por el revisor:
#   scrip via aumento liberado -> SCRIP_DIVIDEND con lifecycle distinto
#   admision BMEG post-ampliacion -> CAPITAL_INCREASE/ADMISSION
#   solicitud de dispensa OPA -> NOT_CA
# =========================================================================
SEEDS = {
 'BMEG-CapitalIncreases-ES0105561007-2025-01-13': (
   'ACTUAL_CA', 'CAPITAL_INCREASE', 'COMPLETION',
   'affected = ES0105561007 (fila BMEG)',
   'AMPL. CAPITAL COMPENSACION CREDITO DIC 24; disbursement 3.3795 EUR; admission 20250113'),
 'BMEG-CapitalIncreases-ES0105606190-2025-04-07': (
   'ACTUAL_CA', 'CAPITAL_INCREASE', 'COMPLETION',
   'affected = ES0105606190 (fila BMEG)',
   'AMPL. CONV. OBLG. MAR 25; price 0.08 EUR; admission 20250407'),
 'BMEG-Dividends-ES0105224002-2025-05-08': (
   'ACTUAL_CA', 'CASH_DIVIDEND', 'EXECUTION',
   'affected = ES0105224002 (fila BMEG)',
   'A CUENTA gross 0.02756119 EUR exDate 20250508 payment 20250512'),
 'BMEG-Dividends-ES0105290003-2025-06-25': (
   'ACTUAL_CA', 'CASH_DIVIDEND', 'EXECUTION',
   'affected = ES0105290003 (fila BMEG)',
   'A CUENTA gross 0.33473427 EUR exDate 20250625 payment 20250627'),
 'BMEG-Dividends-ES0105407003-2026-09-11': (
   'ACTUAL_CA', 'CASH_DIVIDEND', 'EXECUTION',
   'affected = ES0105407003 (fila BMEG)',
   'A CUENTA gross 0.0612 EUR exDate 20260911 payment 20260915'),
 'BMEG-Dividends-ES0105659009-2025-07-03': (
   'ACTUAL_CA', 'CASH_DIVIDEND', 'EXECUTION',
   'affected = ES0105659009 (fila BMEG)',
   'A CUENTA gross 0.74 EUR exDate 20250703 payment 20250717'),
 'BMEG-NewListings-ES0105650008-2026-03-06': (
   'ACTUAL_CA', 'CAPITAL_INCREASE', 'ADMISSION',
   'affected = ES0105650008 (fila BMEG). SIGNED: admision de acciones fungibles de ampliacion previa NO es NEW_LISTING (NEW_LISTING reservado a incorporacion inicial de instrumento/emisor)',
   'admissionType Integration "AMP. CAPITAL NOV 2025": 9601365 acciones, nominal 960136.5'),
 'BMEG-OtherPayments-ES0105323002-2025-01-08': (
   'ACTUAL_CA', 'OTHER_PAYMENT', 'EXECUTION',
   'affected = ES0105323002 (fila BMEG)',
   'PRIMA DE EMISION gross 0.1484908 EUR exDate 20250108 payment 20250110'),
 'CNMV-IP-3011': (
   'ACTUAL_CA', 'TENDER', 'TERMS_MODIFICATION',
   'affected = AEDAS Homes (acciones sobre las que recae la OPA); el emisor del comunicado (Neinor) NO es el instrumento afectado',
   'OPA voluntaria sobre la totalidad de las acciones de AEDAS; precio mantenido 21,335 euros; posible OPA obligatoria a 24 euros'),
 'CNMV-OIR-32783': (
   'ACTUAL_CA', 'CASH_DIVIDEND', 'PROPOSAL',
   'affected = Aena S.M.E. S.A.',
   'propuesta a Junta: dividendo de 9,76 euros brutos por accion; pago el 24 de abril de 2025 si se aprueba'),
 'CNMV-OIR-35005': (
   'ACTUAL_CA', 'CASH_DIVIDEND', 'EXECUTION',
   'affected = ES0173093024 (ISIN explicito en documento)',
   'dividendo complementario 0,6000 euros bruto/accion; ex date 4 julio 2025; record 7 julio; pago 8 julio'),
 'CNMV-OIR-35263': (
   'ACTUAL_CA', 'SPLIT', 'REGISTRATION',
   'affected = ES0105046017 (ISIN en la pagina de registro)',
   'pagina oficial derechos de voto/capital AENA: capital 1.500.000.000,00 / 1.500.000.000 acciones, inscripcion 12/06/2025; titulo oficial "desdoblamiento (split)"'),
 'CNMV-OIR-36798': (
   'ACTUAL_CA', 'TENDER', 'SUSPENSION',
   'affected = Banco de Sabadell (acciones objeto de la OPA de BBVA)',
   'CNMV: suspendido el computo del plazo de aceptacion de la OPA sobre Sabadell presentada por BBVA'),
 'CNMV-OIR-37702': (
   'ACTUAL_CA', 'CASH_DIVIDEND', 'EXECUTION',
   'affected = MERLIN Properties SOCIMI',
   'dividendo a cuenta 20 centimos (0,20) brutos/accion; record 24-nov-2025; ex 21-nov-2025; pago 10-dic-2025'),
 'CNMV-OIR-37970': (
   'NOT_CA', None, None,
   'n/a. SIGNED: solicitud de dispensa de OPA obligatoria (CNMV autorizo la dispensa); no llego a existir oferta sobre holders',
   'solicitud de autorizacion de DISPENSA de la obligacion de formular OPA sobre Arima: procedimiento regulatorio, no hay oferta ni efecto sobre accionistas'),
 'CNMV-OIR-39819': (
   'ACTUAL_CA', 'CASH_DIVIDEND', 'EXECUTION',
   'affected = Naturhouse Health SA',
   'dividendo a cuenta 0,05 euros brutos/accion (3.000.000 total); last trading 15-abr-2026; ex 16-abr-2026; record 17-abr-2026; pago 20-abr-2026'),
 'CNMV-OIR-40758': (
   'ACTUAL_CA', 'SCRIP_DIVIDEND', 'TERMS_CALENDAR',
   'affected = Almirall S.A. SIGNED: dividendo flexible implementado via aumento liberado; familia SCRIP_DIVIDEND con mechanism BONUS_CAPITAL_INCREASE',
   'calendario dividendo flexible: last trading 13-may-2026; record Iberclear 15-may-2026; ex-cupon 14-may-2026; pago efectivo 3-jun-2026'),
 'CNMV-OIR-41381': (
   'ACTUAL_CA', 'SCRIP_DIVIDEND', 'EXECUTION',
   'affected = Reig Jofre. SIGNED: ampliacion liberada = fase EXECUTION del scrip; mechanism BONUS_CAPITAL_INCREASE (cadena OIR 40958->41381->41640)',
   'cierre ampliacion liberada: 664.162 acciones nuevas; dividendo en efectivo total 135.770,59 euros liquidado 8-jun-2026'),
 'CNMV-OIR-41640': (
   'ACTUAL_CA', 'SCRIP_DIVIDEND', 'ADMISSION',
   'affected = Reig Jofre. SIGNED: inicio de cotizacion de acciones del dividendo flexible = ADMISSION/TRADING_START del scrip',
   'inicio cotizacion 1-jul-2026 de 664.162 acciones nuevas del dividendo flexible; capital resultante 41.441.701,50 EUR'),
 'CNMV-OIR-41981': (
   'ACTUAL_CA', 'REVERSE_SPLIT', 'REGISTRATION',
   'affected = ES0109260291 (nueva fila ISIN; agrupacion ~25:1 desde ES0109260531)',
   'pagina derechos de voto/capital AMPER: nueva inscripcion 14/07/2026, 91.044.963 acciones, ISIN ES0109260291'),
 'POEX-DOC-21984': (
   'ACTUAL_CA', 'CAPITAL_INCREASE', 'COMPLETION',
   'affected = ES0105801007 (ISIN explicito en el aviso)',
   'ampliacion de capital por aumento de nominal 10->22 EUR; importe 6.003.600,00 EUR; efectiva 08-ene-2026'),
 'POEX-DOC-22422': (
   'ACTUAL_CA', 'CASH_DIVIDEND', 'EXECUTION',
   'affected = AOFI SHENI SOCIMI',
   'dividendo a cuenta bruto total 600.000,00 EUR; 1,19928043/accion; ex 20/01/2026; record 19/01/2026; pago 20/01/2026'),
 'POEX-DOC-36171': (
   'ACTUAL_CA', 'CAPITAL_INCREASE', 'COMPLETION',
   'affected = DARIA 323 Corporate Services SOCIMI',
   'aumento de capital 87.690 EUR mediante 87.690 acciones de 1 EUR; capital resultante 5.087.690 EUR'),
 'POEX-DOC-4666': (
   'ACTUAL_CA', 'CASH_DIVIDEND', 'EXECUTION',
   'affected = AOFI SHENI SOCIMI',
   'dividendo bruto total 747.877,72 EUR; 1,49485852/accion; ex 16/07/2025; record 15/07/2025; pago 16/07/2025'),
 'POEX-DOC-7021': (
   'ACTUAL_CA', 'CAPITAL_REDUCTION', 'EXECUTION',
   'affected = AC RESIDENCIAL SOCIMI',
   'reduccion de capital 2.389.825,92 EUR devolviendo aportaciones; bruto 0,08/accion; ex 27-ago-2025; record 26-ago-2025; pago 27-ago-2025'),
}

# =========================================================================
# GROUND TRUTH por campo critico.
#   status: CORRECT | MISSING | FALSE_FINANCIAL_FACT | UNKNOWN |
#           NOT_APPLICABLE | AMBIGUOUS
#   published: PUBLISHED | NOT_PUBLISHED | N/A | AMBIGUOUS_SOURCE
#   expected: claims esperados cuando la fuente los publica
# =========================================================================
GT = {
 'BMEG-CapitalIncreases-ES0105561007-2025-01-13': {
   'event_type': ('CORRECT', 'PUBLISHED', {'event_type': 'CAPITAL_INCREASE'}, 'oficial_category=CapitalIncreases'),
   'ex_date': ('NOT_APPLICABLE', 'N/A', None, 'CAPITAL_INCREASE sin derechos: no hay ex_date; la fila publica startingDate/admissionDate'),
   'record_date': ('NOT_APPLICABLE', 'N/A', None, 'sin derechos: no aplica'),
   'payment_date': ('NOT_APPLICABLE', 'N/A', None, 'desembolso ya ejecutado en admissionDate'),
   'amount_or_ratio': ('CORRECT', 'PUBLISHED', {'amount.disbursement_per_share': fin('3.3795'), 'amount.nominal_total': fin('8992.5')}, 'disbursement=3.3795, nominalAmount=8992.5'),
   'currency': ('CORRECT', 'PUBLISHED', {'instrument.currency': 'EUR'}, 'currency=EUR'),
 },
 'BMEG-CapitalIncreases-ES0105606190-2025-04-07': {
   'event_type': ('CORRECT', 'PUBLISHED', {'event_type': 'CAPITAL_INCREASE'}, 'oficial_category=CapitalIncreases'),
   'ex_date': ('NOT_APPLICABLE', 'N/A', None, 'sin derechos'),
   'record_date': ('NOT_APPLICABLE', 'N/A', None, 'sin derechos'),
   'payment_date': ('NOT_APPLICABLE', 'N/A', None, 'ejecutado en admissionDate'),
   'amount_or_ratio': ('CORRECT', 'PUBLISHED', {'amount.price': fin('0.08'), 'amount.nominal_total': fin('312500.0')}, 'price=0.08, nominalAmount=312500.0'),
   'currency': ('CORRECT', 'PUBLISHED', {'instrument.currency': 'EUR'}, 'currency=EUR'),
 },
 'BMEG-Dividends-ES0105224002-2025-05-08': {
   'event_type': ('CORRECT', 'PUBLISHED', {'event_type': 'CASH_DIVIDEND'}, 'category=Dividends, concept A CUENTA'),
   'ex_date': ('CORRECT', 'PUBLISHED', {'date.ex_date': '2025-05-08'}, 'exDate=20250508'),
   'record_date': ('UNKNOWN', 'NOT_PUBLISHED', None, 'la fila no publica recordDate'),
   'payment_date': ('CORRECT', 'PUBLISHED', {'date.payment_date': '2025-05-12'}, 'paymentDate=20250512'),
   'amount_or_ratio': ('CORRECT', 'PUBLISHED', {'amount.gross_per_share': fin('0.02756119'), 'amount.net_per_share': fin('0.02232456')}, 'grossAmount/netAmount'),
   'currency': ('CORRECT', 'PUBLISHED', {'instrument.currency': 'EUR'}, 'currency=EUR'),
 },
 'BMEG-Dividends-ES0105290003-2025-06-25': {
   'event_type': ('CORRECT', 'PUBLISHED', {'event_type': 'CASH_DIVIDEND'}, 'category=Dividends'),
   'ex_date': ('CORRECT', 'PUBLISHED', {'date.ex_date': '2025-06-25'}, 'exDate=20250625'),
   'record_date': ('UNKNOWN', 'NOT_PUBLISHED', None, 'sin recordDate'),
   'payment_date': ('CORRECT', 'PUBLISHED', {'date.payment_date': '2025-06-27'}, 'paymentDate=20250627'),
   'amount_or_ratio': ('CORRECT', 'PUBLISHED', {'amount.gross_per_share': fin('0.33473427'), 'amount.net_per_share': fin('0.27113476')}, 'grossAmount/netAmount'),
   'currency': ('CORRECT', 'PUBLISHED', {'instrument.currency': 'EUR'}, 'currency=EUR'),
 },
 'BMEG-Dividends-ES0105407003-2026-09-11': {
   'event_type': ('CORRECT', 'PUBLISHED', {'event_type': 'CASH_DIVIDEND'}, 'category=Dividends'),
   'ex_date': ('CORRECT', 'PUBLISHED', {'date.ex_date': '2026-09-11'}, 'exDate=20260911'),
   'record_date': ('UNKNOWN', 'NOT_PUBLISHED', None, 'sin recordDate'),
   'payment_date': ('CORRECT', 'PUBLISHED', {'date.payment_date': '2026-09-15'}, 'paymentDate=20260915'),
   'amount_or_ratio': ('CORRECT', 'PUBLISHED', {'amount.gross_per_share': fin('0.0612'), 'amount.net_per_share': fin('0.049572')}, 'grossAmount/netAmount'),
   'currency': ('CORRECT', 'PUBLISHED', {'instrument.currency': 'EUR'}, 'currency=EUR'),
 },
 'BMEG-Dividends-ES0105659009-2025-07-03': {
   'event_type': ('CORRECT', 'PUBLISHED', {'event_type': 'CASH_DIVIDEND'}, 'category=Dividends'),
   'ex_date': ('CORRECT', 'PUBLISHED', {'date.ex_date': '2025-07-03'}, 'exDate=20250703'),
   'record_date': ('UNKNOWN', 'NOT_PUBLISHED', None, 'sin recordDate'),
   'payment_date': ('CORRECT', 'PUBLISHED', {'date.payment_date': '2025-07-17'}, 'paymentDate=20250717'),
   'amount_or_ratio': ('CORRECT', 'PUBLISHED', {'amount.gross_per_share': fin('0.74')}, 'grossAmount=0.74 (net 0.0)'),
   'currency': ('CORRECT', 'PUBLISHED', {'instrument.currency': 'EUR'}, 'currency=EUR'),
 },
 'BMEG-NewListings-ES0105650008-2026-03-06': {
   'event_type': ('MISSING', 'PUBLISHED', {'event_type': 'CAPITAL_INCREASE'}, 'observations="AMP. CAPITAL NOV 2025" + admissionType=Integration: admision de acciones de una ampliacion; emitido NEW_LISTING [SIGNED: CAPITAL_INCREASE/ADMISSION]'),
   'ex_date': ('NOT_APPLICABLE', 'N/A', None, 'admision post-ampliacion: no aplica'),
   'record_date': ('NOT_APPLICABLE', 'N/A', None, 'no aplica'),
   'payment_date': ('NOT_APPLICABLE', 'N/A', None, 'no aplica'),
   'amount_or_ratio': ('CORRECT', 'PUBLISHED', {'amount.nominal': {'normalized': '960136.5', 'currency': None}}, 'nominal=960136.5 (9.601.365 acciones x 0,10); emitido como amount.nominal + amount.turnover 750826.743; currency no declarada por la fuente'),
   'currency': ('UNKNOWN', 'NOT_PUBLISHED', None, 'la fila NewListings no declara currency; los amounts se emiten con currency=null'),
 },
 'BMEG-OtherPayments-ES0105323002-2025-01-08': {
   'event_type': ('CORRECT', 'PUBLISHED', {'event_type': 'OTHER_PAYMENT'}, 'PRIMA DE EMISION'),
   'ex_date': ('CORRECT', 'PUBLISHED', {'date.ex_date': '2025-01-08'}, 'exDate=20250108'),
   'record_date': ('UNKNOWN', 'NOT_PUBLISHED', None, 'sin recordDate'),
   'payment_date': ('CORRECT', 'PUBLISHED', {'date.payment_date': '2025-01-10'}, 'paymentDate=20250110'),
   'amount_or_ratio': ('CORRECT', 'PUBLISHED', {'amount.gross_per_share': fin('0.1484908'), 'amount.effective_total': fin('5004739.71')}, 'grossAmount/effectiveAmount'),
   'currency': ('CORRECT', 'PUBLISHED', {'instrument.currency': 'EUR'}, 'currency=EUR'),
 },
 'CNMV-IP-3011': {
   'event_type': ('CORRECT', 'PUBLISHED', {'event_type': 'TAKEOVER_BID'}, '"oferta publica voluntaria de adquisicion de acciones ... sobre la totalidad de las acciones de AEDAS"'),
   'ex_date': ('NOT_APPLICABLE', 'N/A', None, 'TENDER: sin ex_date'),
   'record_date': ('NOT_APPLICABLE', 'N/A', None, 'TENDER: record no aplica a aceptacion'),
   'payment_date': ('UNKNOWN', 'NOT_PUBLISHED', None, 'plazo de aceptacion/liquidacion remitido al folleto'),
   'amount_or_ratio': ('MISSING', 'PUBLISHED', {'amount.gross_per_share': fin('21.335')}, 'precio de la OPA mantenido = 21,335 euros/accion; el parser emitio 27,15 que es el limite inferior del rango de cotizacion del 13-jun-2025, no el precio de la oferta'),
   'currency': ('CORRECT', 'PUBLISHED', {'instrument.currency': 'EUR'}, 'precios declarados en euros'),
 },
 'CNMV-OIR-32783': {
   'event_type': ('CORRECT', 'PUBLISHED', {'event_type': 'CASH_DIVIDEND'}, '"distribucion de un dividendo ... con cargo a los beneficios de 2024"'),
   'ex_date': ('UNKNOWN', 'NOT_PUBLISHED', None, 'propuesta a Junta: sin ex_date'),
   'record_date': ('UNKNOWN', 'NOT_PUBLISHED', None, 'sin record_date'),
   'payment_date': ('CORRECT', 'PUBLISHED', {'date.payment_date': '2025-04-24'}, '"se realizara el proximo 24 de abril de 2025" (condicionado a aprobacion)'),
   'amount_or_ratio': ('CORRECT', 'PUBLISHED', {'amount.gross_per_share': fin('9.76')}, '"9,76 euros brutos por accion"'),
   'currency': ('CORRECT', 'PUBLISHED', {'instrument.currency': 'EUR'}, 'euros explicitos'),
 },
 'CNMV-OIR-35005': {
   'event_type': ('CORRECT', 'PUBLISHED', {'event_type': 'CASH_DIVIDEND'}, '"Pago de dividendo complementario"'),
   'ex_date': ('CORRECT', 'PUBLISHED', {'date.ex_date': '2025-07-04'}, '"ex date: 4 de julio de 2025"'),
   'record_date': ('CORRECT', 'PUBLISHED', {'date.record_date': '2025-07-07'}, '"record date: 7 de julio de 2025"'),
   'payment_date': ('CORRECT', 'PUBLISHED', {'date.payment_date': '2025-07-08'}, '"Fecha de pago: 8 de julio de 2025"'),
   'amount_or_ratio': ('MISSING', 'PUBLISHED', {'amount.gross_per_share': fin('0.60')}, '"Dividendo complementario bruto por accion: 0,6000 euros" no extraido'),
   'currency': ('MISSING', 'PUBLISHED', {'instrument.currency': 'EUR'}, 'euros declarados; no emitido'),
 },
 'CNMV-OIR-35263': {
   'event_type': ('AMBIGUOUS', 'AMBIGUOUS_SOURCE', None, 'titulo oficial: anuncio de fecha de efectos del desdoblamiento (split); el artefacto registro no declara el evento como lexema (precedente CNMV-OIR-36507)'),
   'ex_date': ('NOT_APPLICABLE', 'N/A', None, 'REGISTRATION: la pagina publica fecha de inscripcion (12/06/2025), no ex_date'),
   'record_date': ('NOT_APPLICABLE', 'N/A', None, 'REGISTRATION: no aplica'),
   'payment_date': ('NOT_APPLICABLE', 'N/A', None, 'SPLIT: sin pata de efectivo'),
   'amount_or_ratio': ('UNKNOWN', 'NOT_PUBLISHED', None, 'la pagina publica capital/acciones como estado; no el factor de desdoblamiento como claim'),
   'currency': ('NOT_APPLICABLE', 'N/A', None, 'SPLIT: currency no aplica'),
 },
 'CNMV-OIR-36798': {
   'event_type': ('CORRECT', 'PUBLISHED', {'event_type': 'TAKEOVER_BID'}, '"oferta publica de adquisicion de acciones de Banco de Sabadell ... presentada por BBVA"'),
   'ex_date': ('NOT_APPLICABLE', 'N/A', None, 'TENDER: sin ex_date'),
   'record_date': ('NOT_APPLICABLE', 'N/A', None, 'TENDER: no aplica'),
   'payment_date': ('UNKNOWN', 'NOT_PUBLISHED', None, 'periodo de aceptacion suspendido; calendario pendiente de resolucion'),
   'amount_or_ratio': ('UNKNOWN', 'NOT_PUBLISHED', None, 'el aviso no publica precio de oferta'),
   'currency': ('UNKNOWN', 'NOT_PUBLISHED', None, 'no declarado en este aviso'),
 },
 'CNMV-OIR-37702': {
   'event_type': ('CORRECT', 'PUBLISHED', {'event_type': 'CASH_DIVIDEND'}, '"distribucion de un dividendo a cuenta"'),
   'ex_date': ('CORRECT', 'PUBLISHED', {'date.ex_date': '2025-11-21'}, '"ex date sera el 21 de noviembre de 2025"'),
   'record_date': ('CORRECT', 'PUBLISHED', {'date.record_date': '2025-11-24'}, '"record date: 24 de noviembre de 2025"'),
   'payment_date': ('CORRECT', 'PUBLISHED', {'date.payment_date': '2025-12-10'}, '"payment date: 10 de diciembre de 2025"'),
   'amount_or_ratio': ('MISSING', 'PUBLISHED', {'amount.gross_per_share': fin('0.20')}, '"20 centimos de euro (0,20) brutos por accion" no extraido'),
   'currency': ('MISSING', 'PUBLISHED', {'instrument.currency': 'EUR'}, 'euros declarados; no emitido'),
 },
 'CNMV-OIR-39819': {
   'event_type': ('MISSING', 'PUBLISHED', {'event_type': 'CASH_DIVIDEND'}, '"distribuir tres millones de euros ... como dividendos a cuenta": evento detectado pero sin claim canonico de event_type'),
   'ex_date': ('MISSING', 'PUBLISHED', {'date.ex_date': '2026-04-16'}, 'doc: "siendo el dia 16 de abril de 2026 el ex-date"; el parser emitio 2026-04-17 (el record-date)'),
   'record_date': ('MISSING', 'PUBLISHED', {'date.record_date': '2026-04-17'}, '"17 de abril de 2026, la fecha de corte o record-date" no extraido'),
   'payment_date': ('MISSING', 'PUBLISHED', {'date.payment_date': '2026-04-20'}, '"el pago se efectuara el proximo dia 20 de abril de 2026" no extraido'),
   'amount_or_ratio': ('CORRECT', 'PUBLISHED', {'amount.gross_per_share': fin('0.05')}, '"0,05 euros brutos por accion"'),
   'currency': ('CORRECT', 'PUBLISHED', {'instrument.currency': 'EUR'}, 'euros explicitos'),
 },
 'CNMV-OIR-40758': {
   'event_type': ('MISSING', 'PUBLISHED', {'event_type': 'SCRIP_DIVIDEND'}, '"dividendo flexible (scrip dividend)" implementado via aumento liberado; emitido CAPITAL_INCREASE [SIGNED: SCRIP_DIVIDEND]'),
   'ex_date': ('MISSING', 'PUBLISHED', {'date.ex_date': '2026-05-14'}, 'doc: "14 de mayo de 2026 ... las acciones de Almirall cotizan ex-cupon (ex date)"; el parser emitio 2026-05-25 (fin del plazo de solicitud de efectivo)'),
   'record_date': ('MISSING', 'PUBLISHED', {'date.record_date': '2026-05-15'}, 'doc: "legitimados como accionistas en los registros de Iberclear el 15 de mayo de 2026 (record date)"; el parser emitio 2026-06-01 (fin del periodo de negociacion de derechos)'),
   'payment_date': ('MISSING', 'PUBLISHED', {'date.payment_date': '2026-06-03'}, '"3 de junio de 2026. Pago de efectivo ..." no extraido'),
   'amount_or_ratio': ('UNKNOWN', 'NOT_PUBLISHED', None, 'precio del compromiso de compra definido por formula (media 5 sesiones); sin importe fijo publicado'),
   'currency': ('UNKNOWN', 'NOT_PUBLISHED', None, 'no declarado como campo del evento'),
 },
 'CNMV-OIR-41381': {
   'event_type': ('MISSING', 'PUBLISHED', {'event_type': 'SCRIP_DIVIDEND'}, '"dividendo mediante un scrip dividend o dividendo flexible"; emitido CASH_DIVIDEND [SIGNED: SCRIP_DIVIDEND]'),
   'ex_date': ('NOT_APPLICABLE', 'N/A', None, 'COMPLETION del scrip: ex_date pertenecio a la fase de derechos'),
   'record_date': ('NOT_APPLICABLE', 'N/A', None, 'COMPLETION: no aplica'),
   'payment_date': ('MISSING', 'PUBLISHED', {'date.payment_date': '2026-06-08'}, '"liquidacion de dicho dividendo en efectivo ... con fecha 8 de junio de 2026" no extraido'),
   'amount_or_ratio': ('MISSING', 'PUBLISHED', {'amount.gross_total': fin('135770.59')}, '"distribucion de dividendo en efectivo ... por importe total de 135.770,59 euros" no extraido'),
   'currency': ('MISSING', 'PUBLISHED', {'instrument.currency': 'EUR'}, 'euros explicitos; no emitido'),
 },
 'CNMV-OIR-41640': {
   'event_type': ('MISSING', 'PUBLISHED', {'event_type': 'SCRIP_DIVIDEND'}, '"nuevas acciones resultantes de la conversion de los derechos ... dividendo flexible (scrip dividend)"; emitido CASH_DIVIDEND [SIGNED: SCRIP_DIVIDEND]'),
   'ex_date': ('NOT_APPLICABLE', 'N/A', None, 'ADMISSION: no aplica'),
   'record_date': ('NOT_APPLICABLE', 'N/A', None, 'ADMISSION: no aplica'),
   'payment_date': ('NOT_APPLICABLE', 'N/A', None, 'la pata de efectivo se liquido en la fase anterior'),
   'amount_or_ratio': ('UNKNOWN', 'NOT_PUBLISHED', None, 'el ratio de canje pertenecio a la fase de derechos; aqui solo capital resultante (estado)'),
   'currency': ('NOT_APPLICABLE', 'N/A', None, 'los euros mencionados son nominal/capital, no contraprestacion'),
 },
 'CNMV-OIR-41981': {
   'event_type': ('AMBIGUOUS', 'AMBIGUOUS_SOURCE', None, 'titulo oficial: actualizacion de acciones/derechos de voto tras admision; la pagina no declara el evento como lexema; ISIN nuevo + acciones ~25:1 sugiere agrupacion'),
   'ex_date': ('NOT_APPLICABLE', 'N/A', None, 'REGISTRATION: no aplica'),
   'record_date': ('NOT_APPLICABLE', 'N/A', None, 'REGISTRATION: no aplica'),
   'payment_date': ('NOT_APPLICABLE', 'N/A', None, 'sin pata de efectivo'),
   'amount_or_ratio': ('UNKNOWN', 'NOT_PUBLISHED', None, 'la pagina publica capital/acciones como estado; no el factor'),
   'currency': ('NOT_APPLICABLE', 'N/A', None, 'capital en EUR implicito como estado'),
 },
 'POEX-DOC-21984': {
   'event_type': ('MISSING', 'PUBLISHED', {'event_type': 'CAPITAL_INCREASE'}, '"AMPLIACION DE CAPITAL MEDIANTE AUMENTO DE NOMINAL" no extraido'),
   'ex_date': ('NOT_APPLICABLE', 'N/A', None, 'aumento de nominal sin nuevas acciones ni derechos'),
   'record_date': ('NOT_APPLICABLE', 'N/A', None, 'no aplica'),
   'payment_date': ('NOT_APPLICABLE', 'N/A', None, 'sin desembolso a accionistas (cargo a reservas)'),
   'amount_or_ratio': ('MISSING', 'PUBLISHED', {'amount.nominal_total': fin('6003600.00')}, '"aumento de capital ... por importe de 6.003.600,00 euros" no extraido'),
   'currency': ('MISSING', 'PUBLISHED', {'instrument.currency': 'EUR'}, 'euros explicitos; no emitido'),
 },
 'POEX-DOC-22422': {
   'event_type': ('CORRECT', 'PUBLISHED', {'event_type': 'CASH_DIVIDEND'}, '"reparto de dividendos a cuenta"'),
   'ex_date': ('CORRECT', 'PUBLISHED', {'date.ex_date': '2026-01-20'}, 'Ex-Date 20/01/2026'),
   'record_date': ('CORRECT', 'PUBLISHED', {'date.record_date': '2026-01-19'}, 'Record Date 19/01/2026'),
   'payment_date': ('CORRECT', 'PUBLISHED', {'date.payment_date': '2026-01-20'}, 'payment date 20/01/2026'),
   'amount_or_ratio': ('CORRECT', 'PUBLISHED', {'amount.gross_per_share': fin('1.19928043'), 'amount.gross_total': fin('600000.00')}, 'tabla de importes extraida'),
   'currency': ('CORRECT', 'PUBLISHED', {'instrument.currency': 'EUR'}, 'euros explicitos'),
 },
 'POEX-DOC-36171': {
   'event_type': ('MISSING', 'PUBLISHED', {'event_type': 'CAPITAL_INCREASE'}, '"Aumento de capital social ... mediante aportacion dineraria" no extraido'),
   'ex_date': ('NOT_APPLICABLE', 'N/A', None, 'suscripcion por accionista unico/tercero; sin derechos negociables publicados'),
   'record_date': ('NOT_APPLICABLE', 'N/A', None, 'no aplica'),
   'payment_date': ('NOT_APPLICABLE', 'N/A', None, 'desembolso por transferencia ya realizado'),
   'amount_or_ratio': ('MISSING', 'PUBLISHED', {'amount.nominal_total': fin('87690.00')}, '"capital ... se aumento en 87.690 euros" no extraido'),
   'currency': ('MISSING', 'PUBLISHED', {'instrument.currency': 'EUR'}, 'euros explicitos; no emitido'),
 },
 'POEX-DOC-4666': {
   'event_type': ('CORRECT', 'PUBLISHED', {'event_type': 'CASH_DIVIDEND'}, '"reparto de dividendos con cargo al resultado del ejercicio 2024"'),
   'ex_date': ('CORRECT', 'PUBLISHED', {'date.ex_date': '2025-07-16'}, 'Ex-Date 16/07/2025'),
   'record_date': ('CORRECT', 'PUBLISHED', {'date.record_date': '2025-07-15'}, 'Record Date 15/07/2025'),
   'payment_date': ('CORRECT', 'PUBLISHED', {'date.payment_date': '2025-07-16'}, 'payment 16/07/2025'),
   'amount_or_ratio': ('CORRECT', 'PUBLISHED', {'amount.gross_per_share': fin('1.49485852'), 'amount.gross_total': fin('747877.72')}, 'tabla extraida'),
   'currency': ('CORRECT', 'PUBLISHED', {'instrument.currency': 'EUR'}, 'euros explicitos'),
 },
 'POEX-DOC-7021': {
   'event_type': ('CORRECT', 'PUBLISHED', {'event_type': 'CAPITAL_REDUCTION'}, '"reduccion de capital por un total de 2.389.825,92"'),
   'ex_date': ('CORRECT', 'PUBLISHED', {'date.ex_date': '2025-08-27'}, 'Ex-date 27 de agosto de 2025'),
   'record_date': ('CORRECT', 'PUBLISHED', {'date.record_date': '2025-08-26'}, 'Record-date 26 de agosto de 2025'),
   'payment_date': ('CORRECT', 'PUBLISHED', {'date.payment_date': '2025-08-27'}, 'Fecha de pago 27 de agosto de 2025'),
   'amount_or_ratio': ('MISSING', 'PUBLISHED', {'amount.gross_per_share': fin('0.08'), 'amount.reduction_total': fin('2389825.92'), 'amount.net_per_share': fin('0.0792')}, 'per-share extraido (0,08); reduction_total 2.389.825,92 y net 0,0792 no extraidos'),
   'currency': ('CORRECT', 'PUBLISHED', {'instrument.currency': 'EUR'}, 'euros explicitos'),
 },
}

# =========================================================================
# EJE P0 ORTOGONAL: estos campos son MISSING (completeness) y ADEMAS
# llevan su error P0 desagregado (convencion de cierre G1).
# =========================================================================
P0_ERROR = {
 ('CNMV-IP-3011', 'amount_or_ratio'): 'FALSE_FINANCIAL_FACT',
 ('CNMV-OIR-39819', 'ex_date'): 'DATE_MISBINDING',
 ('CNMV-OIR-40758', 'ex_date'): 'DATE_MISBINDING',
 ('CNMV-OIR-40758', 'record_date'): 'DATE_MISBINDING',
 ('CNMV-OIR-40758', 'event_type'): 'WRONG_EVENT_TYPE',
 ('CNMV-OIR-41381', 'event_type'): 'WRONG_EVENT_TYPE',
 ('CNMV-OIR-41640', 'event_type'): 'WRONG_EVENT_TYPE',
 ('BMEG-NewListings-ES0105650008-2026-03-06', 'event_type'): 'WRONG_EVENT_TYPE',
}

# mechanism firmado para scrip implementado via aumento liberado
MECHANISM = {
 'CNMV-OIR-40758': 'BONUS_CAPITAL_INCREASE',
 'CNMV-OIR-41381': 'BONUS_CAPITAL_INCREASE',
 'CNMV-OIR-41640': 'BONUS_CAPITAL_INCREASE',
}

# =========================================================================
# INSTRUMENT REVIEW
# Regla: RESOLVABLE_VIA_OFFICIAL_CROSS_REFERENCE solo si la cadena es
# exacta y verificable con identificadores oficiales (ADR-013).
# issuer_raw del registro CNMV es atribucion oficial a nivel NOMBRE;
# sin NIF/ISIN en doc ni en metadata congelada -> no es cross-reference
# exacta -> HUMAN_RELATION_REQUIRED.
# POEX: metadata.product_url porta el ISIN (structured source
# identifier oficial) -> cadena exacta.
# =========================================================================
INSTR = {
 'CNMV-IP-3011': ('HUMAN_RELATION_REQUIRED', 'AEDAS Homes (nombre en doc). PELIGRO: affected != reporter; issuer_raw=NEINOR ligaria el instrumento equivocado; resolver exige relacion adjudicada al instrumento de la OPA', 'doc sin ISIN/NIF; name-only del objeto de la OPA'),
 'CNMV-OIR-32783': ('HUMAN_RELATION_REQUIRED', 'Aena S.M.E. (name-only; issuer_raw oficial a nivel nombre, sin identificador)', 'sin cadena exacta nombre->ISIN verificable'),
 'CNMV-OIR-35263': ('RESOLVABLE_AUTOMATICALLY', 'ES0105046017 presente en la tabla de la pagina; no extraido por el parser', 'EXPLICIT_SOURCE_ASSERTION: ISIN en documento no explotado'),
 'CNMV-OIR-36798': ('HUMAN_RELATION_REQUIRED', 'Banco de Sabadell = affected (issuer_raw oficial); el doc nombra Sabadell+BBVA', 'name-only; binding issuer->ISIN requiere lookup oficial no congelado'),
 'CNMV-OIR-37702': ('HUMAN_RELATION_REQUIRED', 'MERLIN (name-only)', 'sin identificador oficial en doc ni metadata'),
 'CNMV-OIR-37970': ('NOT_APPLICABLE', 'seed NOT_CA', 'sin evento sobre el titulo'),
 'CNMV-OIR-39819': ('HUMAN_RELATION_REQUIRED', 'Naturhouse (name-only)', 'sin identificador oficial en doc ni metadata'),
 'CNMV-OIR-40758': ('HUMAN_RELATION_REQUIRED', 'Almirall (name-only)', 'sin identificador oficial en doc ni metadata'),
 'CNMV-OIR-41381': ('HUMAN_RELATION_REQUIRED', 'Reig Jofre (name-only)', 'sin identificador oficial en doc ni metadata'),
 'CNMV-OIR-41640': ('HUMAN_RELATION_REQUIRED', 'Reig Jofre (name-only)', 'sin identificador oficial en doc ni metadata'),
 'CNMV-OIR-41981': ('RESOLVABLE_AUTOMATICALLY', 'pagina porta ISINs; la fila mas reciente (ES0109260291, inscripcion 14/07/2026) es el instrumento post-agrupacion', 'EXPLICIT_SOURCE_ASSERTION: ISIN en documento; multi-fila requiere regla determinista (fila vigente)'),
 'POEX-DOC-22422': ('RESOLVABLE_AUTOMATICALLY', 'ES0105801007 via metadata.product_url oficial POEX', 'SOURCE_CARRIED_INSTRUMENT_BINDING (ADR-013 nivel 2): product page oficial porta ISIN en slug'),
 'POEX-DOC-36171': ('RESOLVABLE_AUTOMATICALLY', 'ES0105902003 via metadata.product_url oficial POEX', 'SOURCE_CARRIED_INSTRUMENT_BINDING (ADR-013 nivel 2): product page oficial porta ISIN en slug'),
 'POEX-DOC-4666': ('RESOLVABLE_AUTOMATICALLY', 'ES0105801007 via metadata.product_url oficial POEX', 'SOURCE_CARRIED_INSTRUMENT_BINDING (ADR-013 nivel 2): product page oficial porta ISIN en slug'),
 'POEX-DOC-7021': ('RESOLVABLE_AUTOMATICALLY', 'ES0105746004 via metadata.product_url oficial POEX', 'SOURCE_CARRIED_INSTRUMENT_BINDING (ADR-013 nivel 2): product page oficial porta ISIN en slug'),
}


def seed_row(fid):
    verdict, fam, stage, affected, quote = SEEDS[fid]
    return {
        'frame_item_id': fid,
        'seed_verdict': verdict,
        'family': fam,
        'lifecycle_stage': stage,
        'affected_instrument_note': affected,
        'implementation_mechanism': MECHANISM.get(fid),
        'evidence': {'quote': quote, 'title': None},
        'evidence_locator': f'g1r/adjudication/dev-text/{fid}.txt',
        'proposed_at': TS, 'proposed_by': REV, 'status': 'PROPOSED',
    }


def miss_row(fid):
    verdict, fam, stage, _, _ = SEEDS[fid]
    rows = []
    if verdict == 'NOT_CA':
        for f in FIELDS:
            rows.append({
                'frame_item_id': fid, 'seed_verdict': 'NOT_CA', 'family': None,
                'field': f, 'applicability': 'NOT_APPLICABLE',
                'classification': 'NOT_APPLICABLE',
                'p0_error': ('FALSE_POSITIVE_EVENT' if f == 'event_type'
                             and emitted(fid, f) else None),
                'pipeline': {'populated': bool(emitted(fid, f)),
                             'emitted_claims': emitted(fid, f)},
                'expected_claims': None,
                'source_review': {'published_status': 'N/A',
                                  'evidence_locator': 'seed_verdict=NOT_CA: no hay evento sobre el titulo',
                                  'reviewed_at': TS, 'reviewer': REV,
                                  'source_document_id': fid},
                'status': 'PROPOSED'})
        return rows
    for f in FIELDS:
        cls, pub, expected, loc = GT[fid][f]
        em = emitted(fid, f)
        app = 'NOT_APPLICABLE' if cls == 'NOT_APPLICABLE' else (
              'UNDETERMINED' if cls == 'AMBIGUOUS' else 'APPLICABLE')
        rows.append({
            'frame_item_id': fid, 'seed_verdict': verdict, 'family': fam,
            'field': f, 'applicability': app, 'classification': cls,
            'p0_error': P0_ERROR.get((fid, f)),
            'pipeline': {'populated': bool(em), 'emitted_claims': em},
            'expected_claims': expected,
            'source_review': {'published_status': pub,
                              'evidence_locator': loc,
                              'reviewed_at': TS, 'reviewer': REV,
                              'source_document_id': fid},
            'status': 'PROPOSED'})
    return rows


def instr_row(fid):
    base = json.loads((REPO / 'g1r/results/baseline-c431830-results.json')
                      .read_text(encoding='utf-8'))
    e = {x['frame_item_id']: x for x in base['results']}[fid]
    f = FACTS.get(fid, {})
    if e['instrument_resolved']:
        # nivel ADR-013 del binding que el baseline ya emitio
        if fid.startswith('BMEG-'):
            lvl = 'SOURCE_CARRIED_INSTRUMENT_BINDING'
            src = 'fila BMEG estructurada porta ISIN'
        else:
            lvl = 'EXPLICIT_SOURCE_ASSERTION'
            src = 'ISIN explicito en el documento'
        cls, expected, note = ('RESOLVED_BASELINE',
                               f.get('affected_instrument.isin'),
                               f'{lvl}: {src}')
    else:
        cls, expected, note = INSTR[fid]
    return {
        'frame_item_id': fid,
        'baseline_resolved': bool(e['instrument_resolved']),
        'bound_isin': f.get('affected_instrument.isin'),
        'expected_affected': expected,
        'resolution_class': cls,
        'adr013_note': note,
        'evidence_locator': f'g1r/adjudication/dev-text/{fid}.txt',
        'reviewed_at': TS, 'reviewer': REV, 'status': 'PROPOSED',
    }


# clases de fallo genericas (fenomeno documental, no seed)
CATALOG = [
 {'failure_class': 'FALSE_FINANCIAL_SEMANTIC_ANCHOR',
  'seeds': ['CNMV-IP-3011'],
  'description': 'un importe del contexto (limite del rango de cotizacion) se promueve a amount del evento; el precio de la oferta (21,335) queda sin extraer',
  'safety': 'P0'},
 {'failure_class': 'DATE_MISBINDING',
  'seeds': ['CNMV-OIR-39819', 'CNMV-OIR-40758'],
  'description': 'fecha de un rol adyacente (record, fin de plazo) se emite como ex_date/record_date; el documento publica varias fechas etiquetadas y el parser captura la incorrecta',
  'safety': 'P0'},
 {'failure_class': 'EVENT_TYPE_FAMILY_BOUNDARY',
  'seeds': ['CNMV-OIR-40758', 'CNMV-OIR-41381', 'CNMV-OIR-41640',
            'BMEG-NewListings-ES0105650008-2026-03-06'],
  'description': 'el parser emite el tipo del mecanismo/fase (CAPITAL_INCREASE, CASH_DIVIDEND, NEW_LISTING) en lugar del tipo economico canonico del evento (SCRIP_DIVIDEND; CAPITAL_INCREASE/ADMISSION para admisiones post-ampliacion). Fronteras FIRMADAS: scrip via aumento liberado = SCRIP_DIVIDEND; admision de acciones fungibles != NEW_LISTING',
  'safety': 'P0 -> WRONG_EVENT_TYPE'},
 {'failure_class': 'FALSE_POSITIVE_EVENT',
  'seeds': ['CNMV-OIR-37970'],
  'description': 'documento regulatorio procedural (solicitud de dispensa de OPA obligatoria) sin evento sobre el titulo; el parser emite TAKEOVER_BID',
  'safety': 'P0'},
 {'failure_class': 'CENTS_PER_SHARE_LEXEME',
  'seeds': ['CNMV-OIR-37702'],
  'description': '"20 centimos de euro (0,20EUR) brutos por accion" no reconocido como gross_per_share',
  'safety': 'P1'},
 {'failure_class': 'STRUCTURED_AMOUNT_LABEL_VARIANT',
  'seeds': ['CNMV-OIR-35005'],
  'description': '"Dividendo complementario bruto por accion: 0,6000 euros" en lista de terminos no mapeado',
  'safety': 'P1'},
 {'failure_class': 'UNLABELED_TOTAL_AMOUNT',
  'seeds': ['CNMV-OIR-41381', 'POEX-DOC-21984', 'POEX-DOC-36171'],
  'description': 'importe total en prosa ("por importe total de", "se aumento en", numeros en letra) no extraido',
  'safety': 'P1'},
 {'failure_class': 'CROSS_DOC_LIFECYCLE_EVENT_TYPE',
  'seeds': ['CNMV-OIR-41381', 'CNMV-OIR-41640'],
  'description': 'documento de fase posterior (cierre/admision) que referencia el evento por OIR anterior; el tipo se infiere de la cadena documental, no del lexema local',
  'safety': 'P1'},
 {'failure_class': 'REGISTRY_ARTIFACT_NO_LEXEME',
  'seeds': ['CNMV-OIR-35263', 'CNMV-OIR-41981'],
  'description': 'pagina oficial derechos de voto/capital: publica estado (capital/acciones/ISIN), no el evento como lexema',
  'safety': 'limitacion de fuente / P1'},
 {'failure_class': 'SOURCE_CARRIED_INSTRUMENT_NOT_USED',
  'seeds': ['CNMV-OIR-35263', 'CNMV-OIR-41981'],
  'description': 'el propio documento porta ISIN en su tabla y el pipeline no lo explota para el binding',
  'safety': 'P2'},
 {'failure_class': 'PARTIAL_AMOUNT_EXTRACTION',
  'seeds': ['POEX-DOC-7021'],
  'description': 'se extrae gross_per_share pero no reduction_total ni net_per_share publicados en la misma tabla',
  'safety': 'P1'},
 {'failure_class': 'INSTRUMENT_NAME_ONLY',
  'seeds': ['CNMV-IP-3011', 'CNMV-OIR-32783', 'CNMV-OIR-36798', 'CNMV-OIR-37702',
            'CNMV-OIR-39819', 'CNMV-OIR-40758', 'CNMV-OIR-41381', 'CNMV-OIR-41640',
            'POEX-DOC-22422', 'POEX-DOC-36171', 'POEX-DOC-4666', 'POEX-DOC-7021'],
  'description': 'el documento identifica al emisor por nombre, sin ISIN; ADR-013 exige cross-reference oficial para el binding',
  'safety': 'P2'},
]


def main():
    out_adj = REPO / 'g1r/adjudication'
    out_adj.mkdir(parents=True, exist_ok=True)

    with (out_adj / 'dev-seed-review.jsonl').open('w', encoding='utf-8', newline='\n') as fh:
        for fid in sorted(SEEDS):
            fh.write(json.dumps(seed_row(fid), ensure_ascii=False, sort_keys=True) + '\n')

    n = 0
    with (out_adj / 'dev-missingness-review.jsonl').open('w', encoding='utf-8', newline='\n') as fh:
        for fid in sorted(SEEDS):
            for r in miss_row(fid):
                fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n')
                n += 1

    with (out_adj / 'dev-instrument-review.jsonl').open('w', encoding='utf-8', newline='\n') as fh:
        for fid in sorted(SEEDS):
            fh.write(json.dumps(instr_row(fid), ensure_ascii=False, sort_keys=True) + '\n')

    catalog = {
        'catalog_version': 'CA_ES_G1R_DEV_FAILURE_CATALOG_V1',
        'frozen_at': TS,
        'baseline': 'c431830de42acef3d108525edb575ed83be4fc13',
        'baseline_results': 'g1r/results/baseline-c431830-results.json',
        'rule': 'clases genericas del fenomeno documental; prohibido condicionar por seed/issuer/documento',
        'p0_axis': 'los errores P0 son ortogonales a MISSING: el campo correcto publicado no extraido cuenta como MISSING en completeness y ademas registra su p0_error desagregado',
        'p0_summary': {'FALSE_FINANCIAL_FACT': 1, 'DATE_MISBINDING': 3,
                       'WRONG_EVENT_TYPE': 4, 'FALSE_POSITIVE_EVENT': 1},
        'failures': CATALOG,
    }
    res_dir = REPO / 'g1r/results'
    (res_dir / 'dev-failure-catalog.json').write_text(
        json.dumps(catalog, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')

    manifest = {'manifest_version': 'CA_ES_G1R_DEV_ADJUDICATION_V1',
                'frozen_at': TS, 'status': 'PROPOSED_PENDING_HUMAN_SIGN',
                'files': {}}
    for p in [out_adj / 'dev-seed-review.jsonl',
              out_adj / 'dev-missingness-review.jsonl',
              out_adj / 'dev-instrument-review.jsonl',
              res_dir / 'dev-failure-catalog.json']:
        manifest['files'][str(p.relative_to(REPO)).replace('\\', '/')] = \
            hashlib.sha256(canonical_bytes(json.loads('[' + p.read_text(encoding='utf-8').replace('\n', ',')[:-1] + ']')
                                         if p.suffix == '.jsonl' else
                                         json.loads(p.read_text(encoding='utf-8')))).hexdigest()
    (REPO / 'g1r/manifests/dev-adjudication-sha256.json').write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')

    print('seeds:', len(SEEDS), 'missingness rows:', n)
    from collections import Counter
    print(Counter(r['classification'] for fid in SEEDS for r in miss_row(fid)))
    print(manifest['files'])


if __name__ == '__main__':
    main()
