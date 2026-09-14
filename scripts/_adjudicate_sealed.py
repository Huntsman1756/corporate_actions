import json
TS = '2026-09-14'
REV = 'devin-agent'
matrix = json.load(open('g1/manifests/metric-applicability.json', encoding='utf-8'))
FAMILY = {'CASH_DIVIDEND': 'CASH_DIVIDEND', 'SCRIP_DIVIDEND': 'SCRIP_DIVIDEND', 'RIGHTS_ISSUE': 'RIGHTS_ISSUE', 'CAPITAL_INCREASE': 'CAPITAL_INCREASE', 'CAPITAL_REDUCTION': 'CAPITAL_REDUCTION', 'SPLIT': 'SPLIT', 'MERGER_OR_EXCHANGE': 'MERGER', 'TAKEOVER_BID': 'TENDER', 'EARLY_REDEMPTION': 'REDEMPTION'}


def populated(fields, f):
    if f == 'event_type':
        return 'event_type' in fields
    if f == 'amount_or_ratio':
        return any(x.startswith('amount.') or x.startswith('ratio.') for x in fields)
    if f == 'currency':
        return any(x.startswith('amount.') for x in fields) or 'instrument.currency' in fields
    return 'date.' + f in fields


A = {
    # ---- HOLDOUT ----
    ('BMEG-CapitalIncreases-ES0105606190-2025-03-27', 'ex_date'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'row BMEG: sin exDate; publica startingDate/finishDate/admissionDate'),
    ('BMEG-CapitalIncreases-ES0105606190-2025-03-27', 'record_date'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'row BMEG: sin recordDate'),
    ('BMEG-CapitalIncreases-ES0105606190-2025-03-27', 'payment_date'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'row BMEG: sin paymentDate'),
    ('BMEG-Dividends-ES0105448007-2026-07-08', 'record_date'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'row BMEG: publica exDate/paymentDate/gross/net; sin recordDate'),
    ('BMEG-OtherPayments-ES0105273009-2026-01-02', 'record_date'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'row BMEG: sin recordDate'),
    ('BMEG-OtherPayments-ES0105389003-2025-05-22', 'record_date'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'row BMEG: sin recordDate'),
    ('CNMV-IP-2594', 'ex_date'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'propuesta a Junta; sin ex_date publicada'),
    ('CNMV-IP-2594', 'record_date'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'sin record_date publicada'),
    ('CNMV-IP-2594', 'payment_date'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: "a satisfacer en efectivo el proximo 28 de marzo de 2025"; no extraido (fraseo no etiquetado)'),
    ('CNMV-IP-2594', 'amount_or_ratio'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: "12,44 centimos de euro brutos por accion"; parser extrajo amount.max_total=755M que pertenece al programa de recompra, no al dividendo'),
    ('CNMV-IP-2594', 'currency'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc declara centimos de euro; el unico importe capturado pertenece al programa de recompra'),
    ('CNMV-OIR-35466', 'ex_date'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: "el canje ... se realice el 2 de julio de 2025, fecha tentativa de inscripcion"; publicado como fecha efectiva tentativa, no extraido'),
    ('CNMV-OIR-35466', 'record_date'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: "accionistas de FCYC que figuren en el libro registro ... el 2 de julio de 2025"; no extraido'),
    ('CNMV-OIR-35466', 'payment_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'canje integramente en acciones: sin contraprestacion en efectivo'),
    ('CNMV-OIR-35466', 'amount_or_ratio'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: "tipo de canje ... 19,916 acciones de Realia por cada (1) accion de FCYC"; ratio explicito no extraido'),
    ('CNMV-OIR-35466', 'currency'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc declara euros (nominal 0,24/1 euro); no emitido'),
    ('CNMV-OIR-35946', 'ex_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'CAPITAL_INCREASE/COMPLETION: sin derechos en este aviso; ex_date no aplica'),
    ('CNMV-OIR-35946', 'record_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'COMPLETION: no aplica'),
    ('CNMV-OIR-35946', 'payment_date'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'periodos de suscripcion finalizados (preferente el 16/07/2025); no publica fecha de desembolso/admision'),
    ('CNMV-OIR-35946', 'amount_or_ratio'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: precio de suscripcion exacto 0,13 EUR/accion y nominales acotados "hasta 29.678.964,75/77.165.308,35 EUR"; no extraido (guardas de qualifier sin mapeo a bound/price)'),
    ('CNMV-OIR-35946', 'currency'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc declara euros explicitamente; no emitido'),
    ('CNMV-OIR-36141', 'ex_date'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: "Fecha ex date: 11 de agosto de 2025"; variante de etiqueta no reconocida'),
    ('CNMV-OIR-36141', 'amount_or_ratio'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: "Importe bruto unitario (Descontando autocartera): EUR 0,15" y neto 0,1215; formato EUR-prefijo no extraido'),
    ('CNMV-OIR-36141', 'currency'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc declara EUR explicitamente; no emitido'),
    ('CNMV-OIR-36507', 'event_type'): ('AMBIGUOUS', 'AMBIGUOUS', 'UNDETERMINED', 'pagina oficial derechos de voto/capital: la categoria CNMV es inscripcion de reduccion de capital, pero el artefacto no declara el evento como lexema (precedente CNMV-OIR-33627)'),
    ('CNMV-OIR-36507', 'ex_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'CAPITAL_REDUCTION/REGISTRATION: el artefacto confirma inscripcion; ex_date no aplica a esta fase'),
    ('CNMV-OIR-36507', 'record_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'REGISTRATION: no aplica'),
    ('CNMV-OIR-36507', 'payment_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'REGISTRATION: no aplica'),
    ('CNMV-OIR-36507', 'amount_or_ratio'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'la pagina publica capital social/acciones como estado, no el importe de la reduccion'),
    ('CNMV-OIR-36507', 'currency'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'capital social en EUR implicito, no declarado como campo del evento'),
    ('CNMV-OIR-36680', 'event_type'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: "fusion por absorcion JSS Real Estate SOCIMI ... Proyecto comun de Fusion"; parser observo CASH_DIVIDEND por lexemas espurios de "dividendo" dentro del documento de fusion'),
    ('CNMV-OIR-36680', 'ex_date'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'proyecto de fusion pre-Junta; fechas de efectos no fijadas en el documento'),
    ('CNMV-OIR-36680', 'record_date'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'sin record_date publicada'),
    ('CNMV-OIR-36680', 'payment_date'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'sin fecha de efectos/canje publicada'),
    ('CNMV-OIR-36680', 'amount_or_ratio'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: canje "9 acciones de Arima ... por cada una de las acciones de JSS ... de 1,00 euro"; ratio explicito no extraido'),
    ('CNMV-OIR-36680', 'currency'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc declara euros (nominales 10,00/1,00); no emitido'),
    ('CNMV-OIR-38190', 'ex_date'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: "ex -date 14 enero 2026"; variante con espacio/guion y sin "de" no reconocida'),
    ('CNMV-OIR-38190', 'record_date'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'sin record_date publicada'),
    ('CNMV-OIR-38190', 'payment_date'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: "se hara efectivo el dia 16 de enero de 2026 (payment date)"; no extraido'),
    ('CNMV-OIR-38190', 'amount_or_ratio'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: "0. 53 euros brutos por accion"; parser extrajo 53 en lugar de 0,53 (artefacto de salto decimal en PDF)'),
    ('CNMV-OIR-38190', 'currency'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc declara euros; importe extraido con valor incorrecto'),
    ('CNMV-OIR-41467', 'ex_date'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: "Fecha Ex-Date: 3 de julio de 2026"; variante de etiqueta no reconocida'),
    ('CNMV-OIR-41467', 'amount_or_ratio'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: "0, 47 euros brutos por accion"; parser extrajo 47 en lugar de 0,47 (salto decimal en PDF)'),
    ('CNMV-OIR-41467', 'currency'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc declara euros; importe extraido con valor incorrecto'),
    ('CNMV-OIR-41942', 'ex_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'EARLY_REDEMPTION de cedulas: sin ex-date'),
    ('CNMV-OIR-41942', 'record_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'amortizacion total: sin record date separada'),
    ('CNMV-OIR-41942', 'payment_date'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: "amortizacion anticipada total ... con fecha de efectos el 29 de julio de 2026"; no extraido'),
    ('CNMV-OIR-41942', 'amount_or_ratio'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: nominal 1.000.000.000 EUR y "valor nominal unitario de 100.000 EUR"; formato simbolo EUR/variante "valor nominal" no extraido'),
    ('CNMV-OIR-41942', 'currency'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc declara EUR; no emitido'),
    ('POEX-DOC-18666', 'ex_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'CAPITAL_REDUCTION/REGISTRATION: aviso de ejecucion; sin ex-date'),
    ('POEX-DOC-18666', 'record_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'ejecucion ya efectuada: no aplica'),
    ('POEX-DOC-18666', 'payment_date'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'publica fecha efectiva 24/12/2025, no fecha de pago de la devolucion (precedente POEX-DOC-41986)'),
    ('POEX-DOC-4662', 'event_type'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc anuncia "pago del dividendo" y "distribucion parcial de prima de emision" con calendarios; parser devolvio event_type UNKNOWN'),
    # ---- ADVERSARIAL ----
    ('CNMV-IP-2670', 'ex_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'CAPITAL_INCREASE ABB/COMPLETION: sin derechos; ex_date no aplica'),
    ('CNMV-IP-2670', 'record_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'COMPLETION: no aplica'),
    ('CNMV-IP-2670', 'payment_date'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'colocacion cerrada; no publica fecha de desembolso/admision'),
    ('CNMV-OIR-32583', 'record_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'TENDER: record_date no aplica a aceptacion de OPA'),
    ('CNMV-OIR-32583', 'payment_date'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'solicitud de autorizacion; calendario pendiente del folleto'),
    ('CNMV-OIR-32583', 'amount_or_ratio'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'terminos de la oferta remitidos al folleto; solo aparece aval de 114.771.143,76 EUR garantizando la contraprestacion'),
    ('CNMV-OIR-32583', 'currency'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'no declarado como campo de la oferta en este aviso'),
    ('CNMV-OIR-33825', 'ex_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'MERGER de filiales integrales: sin fechas de canje para accionistas'),
    ('CNMV-OIR-33825', 'record_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'sin canje para accionistas: no aplica'),
    ('CNMV-OIR-33825', 'payment_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'sin canje para accionistas: no aplica'),
    ('CNMV-OIR-33825', 'amount_or_ratio'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'absorcion de filiales integrales; no hay tipo de canje para accionistas de Bankinter'),
    ('CNMV-OIR-33825', 'currency'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'sin importes de canje: no aplica'),
    ('CNMV-OIR-35482', 'event_type'): ('AMBIGUOUS', 'AMBIGUOUS', 'UNDETERMINED', 'pagina oficial derechos de voto/capital: categoria CNMV inscripcion de reduccion, el artefacto no declara el evento como lexema'),
    ('CNMV-OIR-35482', 'ex_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'REGISTRATION: no aplica'),
    ('CNMV-OIR-35482', 'record_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'REGISTRATION: no aplica'),
    ('CNMV-OIR-35482', 'payment_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'REGISTRATION: no aplica'),
    ('CNMV-OIR-35482', 'amount_or_ratio'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'la pagina publica capital social/acciones como estado'),
    ('CNMV-OIR-35482', 'currency'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'no declarado como campo del evento'),
    ('CNMV-OIR-37214', 'amount_or_ratio'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: "dividendo a cuenta por un importe total de 342 millones de euros"; ancla "importe total de" no cubierta por el helper; ademas gross_per_share observado=0,01 es el nominal de la accion, no el dividendo (aun por determinar)'),
    ('CNMV-OIR-37214', 'currency'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc declara euros; importe total no extraido'),
    ('CNMV-OIR-37252', 'event_type'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: "oferta publica voluntaria de adquisicion de acciones ... sobre la totalidad de las acciones de AEDAS"; variante con adjetivo intercalado no detectada'),
    ('CNMV-OIR-37252', 'record_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'TENDER: record_date no aplica'),
    ('CNMV-OIR-37252', 'payment_date'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'aprobacion de accionistas del oferente; calendario de liquidacion no fijado en este aviso'),
    ('CNMV-OIR-37252', 'amount_or_ratio'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'terminos de la OPA no publicados en este aviso'),
    ('CNMV-OIR-37252', 'currency'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'no declarado en este aviso'),
    ('CNMV-OIR-37547', 'ex_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'EARLY_REDEMPTION de bonos: sin ex-date'),
    ('CNMV-OIR-37547', 'record_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'amortizacion total: sin record date separada'),
    ('CNMV-OIR-37547', 'payment_date'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: "amortizacion anticipada total de los Bonos existentes el 25 de noviembre de 2025"; no extraido'),
    ('CNMV-OIR-37547', 'amount_or_ratio'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: coste de ruptura 30.716.404 EUR y principal 30.187.500 EUR; formato simbolo EUR no extraido'),
    ('CNMV-OIR-37547', 'currency'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc declara EUR; no emitido'),
    ('CNMV-OIR-40729', 'ex_date'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: "cotizaran ex-dividendo a partir del 18 de mayo de 2026 (Fecha Ex-Dividendo en Europa)"; parser observo 2026-05-15 ("se preve anunciarlo el 15 de mayo")'),
    ('CNMV-OIR-40729', 'amount_or_ratio'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc: "dividendo por un importe total de 400 millones de euros"; ancla "importe total de" no cubierta; gross_per_share observado=0,01 es nominal, no dividendo'),
    ('CNMV-OIR-40729', 'currency'): ('MISSING', 'PUBLISHED', 'APPLICABLE', 'doc declara euros; importe total no extraido'),
    ('CNMV-OIR-41850', 'event_type'): ('AMBIGUOUS', 'AMBIGUOUS', 'UNDETERMINED', 'pagina oficial derechos de voto/capital: categoria CNMV capital tras aumento+reduccion del dividendo flexible; el artefacto no declara el evento como lexema'),
    ('CNMV-OIR-41850', 'ex_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'REGISTRATION: no aplica'),
    ('CNMV-OIR-41850', 'record_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'REGISTRATION: no aplica'),
    ('CNMV-OIR-41850', 'payment_date'): ('NOT_APPLICABLE', 'N/A', 'NOT_APPLICABLE', 'REGISTRATION: no aplica'),
    ('CNMV-OIR-41850', 'amount_or_ratio'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'la pagina publica capital social/acciones como estado'),
    ('CNMV-OIR-41850', 'currency'): ('UNKNOWN', 'NOT_PUBLISHED', 'APPLICABLE', 'no declarado como campo del evento'),
}

WRONG_POPULATED = {('CNMV-IP-2594', 'amount_or_ratio'), ('CNMV-IP-2594', 'currency'), ('CNMV-OIR-36680', 'event_type'), ('CNMV-OIR-38190', 'amount_or_ratio'), ('CNMV-OIR-38190', 'currency'), ('CNMV-OIR-41467', 'amount_or_ratio'), ('CNMV-OIR-41467', 'currency'), ('CNMV-OIR-37214', 'amount_or_ratio'), ('CNMV-OIR-37214', 'currency'), ('CNMV-OIR-40729', 'ex_date'), ('CNMV-OIR-40729', 'amount_or_ratio'), ('CNMV-OIR-40729', 'currency')}
OBSERVED = {('CNMV-IP-2594', 'amount_or_ratio'): 'amount.max_total=755000000 (programa de recompra, no dividendo)', ('CNMV-OIR-36680', 'event_type'): 'CASH_DIVIDEND', ('CNMV-OIR-38190', 'amount_or_ratio'): 'amount.gross_per_share=53', ('CNMV-OIR-41467', 'amount_or_ratio'): 'amount.gross_per_share=47', ('CNMV-OIR-37214', 'amount_or_ratio'): 'amount.gross_per_share=0.01 (nominal accion)', ('CNMV-OIR-40729', 'ex_date'): '2026-05-15', ('CNMV-OIR-40729', 'amount_or_ratio'): 'amount.gross_per_share=0.01 (nominal accion)'}
FAMILY_FIX = {'CNMV-OIR-36680': 'MERGER', 'POEX-DOC-4662': 'CASH_DIVIDEND', 'CNMV-OIR-37252': 'TENDER', 'BMEG-OtherPayments-ES0105389003-2025-05-22': 'CAPITAL_REDUCTION', 'BMEG-OtherPayments-ES0105273009-2026-01-02': 'OTHER_PAYMENT'}
NOT_CA = {'CNMV-OIR-42668'}
EVT = {'BMEG-CapitalIncreases-ES0105606190-2025-03-27': 'CAPITAL_INCREASE', 'BMEG-Dividends-ES0105448007-2026-07-08': 'CASH_DIVIDEND', 'BMEG-OtherPayments-ES0105273009-2026-01-02': 'OTHER_PAYMENT', 'BMEG-OtherPayments-ES0105389003-2025-05-22': 'OTHER_PAYMENT', 'CNMV-IP-2594': 'CASH_DIVIDEND', 'CNMV-OIR-35466': 'MERGER_OR_EXCHANGE', 'CNMV-OIR-35946': 'CAPITAL_INCREASE', 'CNMV-OIR-36141': 'CASH_DIVIDEND', 'CNMV-OIR-36507': 'UNKNOWN', 'CNMV-OIR-36680': 'CASH_DIVIDEND', 'CNMV-OIR-38190': 'CASH_DIVIDEND', 'CNMV-OIR-41467': 'CASH_DIVIDEND', 'CNMV-OIR-41942': 'EARLY_REDEMPTION', 'POEX-DOC-18666': 'CAPITAL_REDUCTION', 'POEX-DOC-4662': 'UNKNOWN', 'CNMV-IP-2670': 'CAPITAL_INCREASE', 'CNMV-OIR-32583': 'TAKEOVER_BID', 'CNMV-OIR-33825': 'MERGER_OR_EXCHANGE', 'CNMV-OIR-35482': 'UNKNOWN', 'CNMV-OIR-37214': 'CASH_DIVIDEND', 'CNMV-OIR-37252': 'UNKNOWN', 'CNMV-OIR-37547': 'EARLY_REDEMPTION', 'CNMV-OIR-40729': 'CASH_DIVIDEND', 'CNMV-OIR-41850': 'UNKNOWN', 'CNMV-OIR-42668': 'UNKNOWN'}


def row(fid, verdict, et, fam, f, app, cls, ps, loc, pop, obs=None):
    pipe = {'populated': pop}
    if obs:
        pipe['observed_value'] = obs
    return {'frame_item_id': fid, 'seed_verdict': verdict, 'event_type_observed': et, 'family': fam, 'field': f, 'applicability': app, 'classification': cls, 'pipeline': pipe, 'source_review': {'published_status': ps, 'evidence_locator': loc, 'reviewed_at': TS, 'reviewer': REV, 'source_document_id': fid}, 'status': 'PROPOSED'}


def build(setname):
    res = json.load(open('g1/results/' + setname + '-results.json', encoding='utf-8'))
    verdicts = {json.loads(l)['frame_item_id']: json.loads(l) for l in open('g1/adjudication/' + setname + '-seed-verdicts.jsonl', encoding='utf-8')}
    rows = []
    for e in res['results']:
        fid = e['frame_item_id']
        fields = e['facts']['populated_fields']
        et = EVT[fid]
        fam = FAMILY_FIX.get(fid) or FAMILY.get(et)
        mrow = matrix['matrix'].get(fam)
        verdict = verdicts[fid]['seed_verdict']
        for f in matrix['fields']:
            pop = populated(fields, f)
            key = (fid, f)
            if fid in NOT_CA:
                rows.append(row(fid, 'NOT_CA', et, fam, f, 'NOT_APPLICABLE', 'NOT_APPLICABLE', 'N/A', 'seed_verdict=NOT_CA: no hay evento sobre el titulo', pop))
                continue
            if pop and key not in WRONG_POPULATED:
                continue
            if key in A:
                cls, ps, app, loc = A[key]
                rows.append(row(fid, verdict, et, fam, f, app, cls, ps, loc, pop, OBSERVED.get(key)))
            elif mrow and mrow[f] == 'NOT_APPLICABLE':
                continue
            else:
                print('UNMAPPED', key)
    return rows


from collections import Counter
for s in ('holdout', 'adversarial'):
    rows = build(s)
    with open('g1/adjudication/' + s + '-missingness-review.jsonl', 'w', encoding='utf-8', newline='\n') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n')
    print(s, len(rows), Counter(r['classification'] for r in rows))
