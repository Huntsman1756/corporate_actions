# -*- coding: utf-8 -*-
"""Adjudicacion HOLDOUT G1-R (propuesta, pendiente de firma humana).

Genera:
  g1r/adjudication/holdout-seed-review.jsonl        verdicts por seed
  g1r/adjudication/holdout-missingness-review.jsonl ground truth por campo critico
  g1r/adjudication/holdout-instrument-review.jsonl  resolucion de instrumento
  g1r/manifests/holdout-adjudication-sha256.json    SHA256 de los 3 artefactos
  g1r/results/holdout-verdict-proposal.json         metricas del veredicto

Los valores esperados proceden de la lectura del documento oficial
(g1r/adjudication/holdout-text/<id>.txt); nunca del parser. Los dos
documentos sin capa de texto (CNMV-OIR-34719, POEX-DOC-15339) quedan
REQUIRES_HUMAN_REVIEW: el parser abstuvo y no emitio facts, pero la
missingness no es adjudicable sin inspeccion visual del PDF.
"""
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))

TS = '2026-09-14'
REV = 'devin-agent'
TXT = 'g1r/adjudication/holdout-text'
FIELDS = ['event_type', 'ex_date', 'record_date', 'payment_date',
          'amount_or_ratio', 'currency']
FIN = lambda v, c='EUR': {'currency': c, 'normalized': v}  # noqa: E731

FACTS = json.loads(
    (REPO / 'g1r/adjudication/_holdout_facts.json').read_text(encoding='utf-8'))
RUN = json.loads(
    (REPO / 'g1r/results/holdout-run-1-a6a0674-results.json')
    .read_text(encoding='utf-8'))
RES = {x['frame_item_id']: x for x in RUN['results']}


def emitted(fid, field):
    f = FACTS.get(fid, {})
    if field == 'amount_or_ratio':
        return {k: v for k, v in f.items()
                if k.startswith(('amount.', 'ratio.'))}
    if field == 'currency':
        out = {}
        if 'instrument.currency' in f:
            out['instrument.currency'] = f['instrument.currency']
        for k, v in f.items():
            if (k.startswith(('amount.', 'ratio.'))
                    and isinstance(v, dict) and v.get('__financial__')):
                out[k + '.currency'] = v['currency']
        return out
    key = {'event_type': 'event_type', 'ex_date': 'date.ex_date',
           'record_date': 'date.record_date',
           'payment_date': 'date.payment_date'}[field]
    return {key: f[key]} if key in f else {}


# verdict por seed: (verdict, family, nota affected, quote)
SEEDS = {
    'BMEG-Delistings-ES0105077004-2026-04-01': (
        'ACTUAL_CA', 'DELISTING',
        'affected = ES0105077004 (fila BMEG)',
        'official_category=Delistings; admissionDate=20260401; '
        'nominal=2133576.0; turnover=3043901.76'),
    'BMEG-Dividends-ES0131703003-2025-09-18': (
        'ACTUAL_CA', 'CASH_DIVIDEND',
        'affected = ES0131703003 (fila BMEG)',
        'A CUENTA ORDINARIO gross 0.1275767 net 0.10333713 EUR; '
        'exDate 20250918; payment 20250922'),
    'CNMV-IP-2683': (
        'ACTUAL_CA', 'TAKEOVER_BID',
        'affected = acciones de Biotest AG (name-only en doc; el evento '
        'NO es sobre las acciones del emisor Grifols)',
        'filial de Grifols anuncia decision de oferta publica de compra '
        'para exclusion de cotizacion sobre Biotest AG: EUR 43,00 '
        'ordinaria / EUR 30,00 preferente'),
    'CNMV-OIR-33177': (
        'NOT_CA', None,
        'n/a',
        'Telefonica comunica el cierre de la sociedad conjunta de fibra '
        'con Vodafone; no hay evento sobre el titulo'),
    'CNMV-OIR-34106': (
        'NOT_CA', None,
        'n/a',
        'Ezentis emite 220 obligaciones convertibles (instrumento de '
        'deuda); no hay evento sobre la accion cotizada'),
    'CNMV-OIR-34625': (
        'ACTUAL_CA', 'TAKEOVER_BID',
        'affected = acciones de ProSiebenSat.1 (ISIN DE000PSM7770 '
        'explicito en doc)',
        'comienza el plazo de aceptacion de la oferta publica de '
        'adquisicion voluntaria de MFE sobre ProSieben (documento de '
        'oferta aprobado por BaFin)'),
    'CNMV-OIR-34719': (
        'REQUIRES_HUMAN_REVIEW', None,
        'PDF escaneado sin capa de texto (/Font:0, /Image:2): el parser '
        'abstuvo y no emitio facts; la missingness requiere inspeccion '
        'visual humana',
        None),
    'CNMV-OIR-35131': (
        'NOT_CA', None,
        'n/a',
        'Squirrel Media formaliza la adquisicion de NF Media y MATPRO '
        '(M&A sobre participaciones de terceros); no hay evento sobre '
        'el titulo cotizado'),
    'CNMV-OIR-41312': (
        'ACTUAL_CA', 'CASH_DIVIDEND',
        'affected = Acciona Energia (name-only)',
        'JGA 4/6/2026 aprueba dividendo ejercicio 2025 pagadero '
        '18/6/2026; LTT 15/6, ExDate 16/6, Record 17/6; bruto '
        '0,03001963 EUR/accion (0,03 ajustado por autocartera)'),
    'CNMV-OIR-41650': (
        'ACTUAL_CA', 'CASH_DIVIDEND',
        'affected = Acciona (name-only)',
        'JGA 25/6/2026 aprueba dividendo ejercicio 2025 pagadero '
        '9/7/2026; LTT 6/7, ExDate 7/7, Record 8/7; bruto '
        '5,74867096 EUR/accion (5,65 ajustado por autocartera)'),
    'POEX-DOC-15339': (
        'REQUIRES_HUMAN_REVIEW', None,
        'PDF escaneado sin capa de texto (/Font:0, /Image:8): el parser '
        'abstuvo y no emitio facts; la missingness requiere inspeccion '
        'visual humana',
        None),
    'POEX-DOC-39649': (
        'ACTUAL_CA', 'CAPITAL_INCREASE',
        'affected = acciones cotizables NEXTLOG ES0105969002 '
        '(explicito: "ISIN acciones cotizables"); ES0605969908 es el '
        'ISIN de los derechos y ES0105969028 el temporal de nuevas',
        'AMPLIACION DE CAPITAL CON DERECHOS DE SUSCRIPCION: '
        '2 derechos -> 1 accion nueva; precio suscripcion 4 EUR por '
        'accion nueva (1 nominal + 3 prima); periodo 14-27 jul 2026'),
    'POEX-DOC-4162': (
        'ACTUAL_CA', 'CASH_DIVIDEND',
        'affected = AOFI SHENI SOCIMI (name-only)',
        'dividendo a cuenta 2024: bruto total 850.000,00; bruto/accion '
        '1,69898061; neto/accion 1,37617429; Ex 25/4, Record 24/4, '
        'Pago 25/4/2025'),
    'POEX-DOC-4318': (
        'ACTUAL_CA', 'CAPITAL_REDUCTION',
        'affected = AC RESIDENCIAL SOCIMI (name-only)',
        'reduccion de capital 1.194.912,96 EUR devolviendo aportaciones '
        '(-0,04 EUR nominal/accion); LTT 6/5, Ex 7/5, Record 6/5, '
        'Pago 7/5/2025; neto 0,0396 EUR/accion'),
    'POEX-DOC-4319': (
        'ACTUAL_CA', 'CAPITAL_REDUCTION',
        'affected = AC RESIDENCIAL SOCIMI (name-only)',
        'segundo punto JGA: misma reduccion 1.194.912,96 EUR '
        '(-0,04 EUR/accion); LTT 6/5, Ex 7/5, Record 6/5, Pago '
        '7/5/2025; neto 0,0396 EUR/accion'),
}

# expected por (seed, field): None => NOT_APPLICABLE / UNKNOWN
E = {
    'BMEG-Delistings-ES0105077004-2026-04-01': {
        'event_type': ('APPLICABLE', 'CORRECT', {'event_type': 'DELISTING'}),
        'ex_date': ('NOT_APPLICABLE', 'NOT_APPLICABLE', None),
        'record_date': ('NOT_APPLICABLE', 'NOT_APPLICABLE', None),
        'payment_date': ('NOT_APPLICABLE', 'NOT_APPLICABLE', None),
        'amount_or_ratio': ('APPLICABLE', 'CORRECT', {
            'amount.nominal': FIN('2133576.0', None),
            'amount.turnover': FIN('3043901.76', None)}),
        'currency': ('APPLICABLE', 'UNKNOWN', None),
    },
    'BMEG-Dividends-ES0131703003-2025-09-18': {
        'event_type': ('APPLICABLE', 'CORRECT',
                       {'event_type': 'CASH_DIVIDEND'}),
        'ex_date': ('APPLICABLE', 'CORRECT',
                    {'date.ex_date': '2025-09-18'}),
        'record_date': ('APPLICABLE', 'UNKNOWN', None),
        'payment_date': ('APPLICABLE', 'CORRECT',
                         {'date.payment_date': '2025-09-22'}),
        'amount_or_ratio': ('APPLICABLE', 'CORRECT', {
            'amount.gross_per_share': FIN('0.1275767'),
            'amount.net_per_share': FIN('0.10333713')}),
        'currency': ('APPLICABLE', 'CORRECT',
                     {'instrument.currency': 'EUR'}),
    },
    'CNMV-IP-2683': {
        'event_type': ('APPLICABLE', 'CORRECT',
                       {'event_type': 'TAKEOVER_BID'}),
        'ex_date': ('NOT_APPLICABLE', 'NOT_APPLICABLE', None),
        'record_date': ('NOT_APPLICABLE', 'NOT_APPLICABLE', None),
        'payment_date': ('APPLICABLE', 'UNKNOWN', None),
        'amount_or_ratio': ('APPLICABLE', 'MISSING', {
            'amount.gross_per_share': FIN('43.00')}),
        'currency': ('APPLICABLE', 'MISSING',
                     {'instrument.currency': 'EUR'}),
    },
    'CNMV-OIR-34625': {
        'event_type': ('APPLICABLE', 'CORRECT',
                       {'event_type': 'TAKEOVER_BID'}),
        'ex_date': ('NOT_APPLICABLE', 'NOT_APPLICABLE', None),
        'record_date': ('NOT_APPLICABLE', 'NOT_APPLICABLE', None),
        'payment_date': ('APPLICABLE', 'UNKNOWN', None),
        'amount_or_ratio': ('APPLICABLE', 'UNKNOWN', None),
        'currency': ('APPLICABLE', 'UNKNOWN', None),
    },
    'CNMV-OIR-41312': {
        'event_type': ('APPLICABLE', 'MISSING',
                       {'event_type': 'CASH_DIVIDEND'}),
        'ex_date': ('APPLICABLE', 'CORRECT',
                    {'date.ex_date': '2026-06-16'}),
        'record_date': ('APPLICABLE', 'CORRECT',
                        {'date.record_date': '2026-06-17'}),
        'payment_date': ('APPLICABLE', 'CORRECT',
                         {'date.payment_date': '2026-06-18'}),
        'amount_or_ratio': ('APPLICABLE', 'MISSING', {
            'amount.gross_per_share': FIN('0.03001963')}),
        'currency': ('APPLICABLE', 'MISSING',
                     {'instrument.currency': 'EUR'}),
    },
    'CNMV-OIR-41650': {
        'event_type': ('APPLICABLE', 'MISSING',
                       {'event_type': 'CASH_DIVIDEND'}),
        'ex_date': ('APPLICABLE', 'CORRECT',
                    {'date.ex_date': '2026-07-07'}),
        'record_date': ('APPLICABLE', 'CORRECT',
                        {'date.record_date': '2026-07-08'}),
        'payment_date': ('APPLICABLE', 'CORRECT',
                         {'date.payment_date': '2026-07-09'}),
        'amount_or_ratio': ('APPLICABLE', 'MISSING', {
            'amount.gross_per_share': FIN('5.74867096')}),
        'currency': ('APPLICABLE', 'MISSING',
                     {'instrument.currency': 'EUR'}),
    },
    'POEX-DOC-39649': {
        'event_type': ('APPLICABLE', 'MISSING',
                       {'event_type': 'CAPITAL_INCREASE'}),
        'ex_date': ('NOT_APPLICABLE', 'NOT_APPLICABLE', None),
        'record_date': ('NOT_APPLICABLE', 'NOT_APPLICABLE', None),
        'payment_date': ('NOT_APPLICABLE', 'NOT_APPLICABLE', None),
        'amount_or_ratio': ('APPLICABLE', 'MISSING', {
            'amount.gross_per_share': FIN('4'),
            'ratio.terms': '2 derechos -> 1 accion nueva'}),
        'currency': ('APPLICABLE', 'CORRECT',
                     {'instrument.currency': 'EUR'}),
    },
    'POEX-DOC-4162': {
        'event_type': ('APPLICABLE', 'CORRECT',
                       {'event_type': 'CASH_DIVIDEND'}),
        'ex_date': ('APPLICABLE', 'CORRECT',
                    {'date.ex_date': '2025-04-25'}),
        'record_date': ('APPLICABLE', 'CORRECT',
                        {'date.record_date': '2025-04-24'}),
        'payment_date': ('APPLICABLE', 'CORRECT',
                         {'date.payment_date': '2025-04-25'}),
        'amount_or_ratio': ('APPLICABLE', 'MISSING', {
            'amount.gross_per_share': FIN('1.69898061'),
            'amount.net_per_share': FIN('1.37617429'),
            'amount.gross_total': FIN('850000.00')}),
        'currency': ('APPLICABLE', 'CORRECT',
                     {'instrument.currency': 'EUR'}),
    },
    'POEX-DOC-4318': {
        'event_type': ('APPLICABLE', 'CORRECT',
                       {'event_type': 'CAPITAL_REDUCTION'}),
        'ex_date': ('APPLICABLE', 'CORRECT',
                    {'date.ex_date': '2025-05-07'}),
        'record_date': ('APPLICABLE', 'CORRECT',
                        {'date.record_date': '2025-05-06'}),
        'payment_date': ('APPLICABLE', 'CORRECT',
                         {'date.payment_date': '2025-05-07'}),
        'amount_or_ratio': ('APPLICABLE', 'MISSING', {
            'amount.gross_per_share': FIN('0.04'),
            'amount.net_per_share': FIN('0.0396'),
            'amount.reduction_total': FIN('1194912.96')}),
        'currency': ('APPLICABLE', 'CORRECT',
                     {'instrument.currency': 'EUR'}),
    },
    'POEX-DOC-4319': {
        'event_type': ('APPLICABLE', 'CORRECT',
                       {'event_type': 'CAPITAL_REDUCTION'}),
        'ex_date': ('APPLICABLE', 'CORRECT',
                    {'date.ex_date': '2025-05-07'}),
        'record_date': ('APPLICABLE', 'CORRECT',
                        {'date.record_date': '2025-05-06'}),
        'payment_date': ('APPLICABLE', 'CORRECT',
                         {'date.payment_date': '2025-05-07'}),
        'amount_or_ratio': ('APPLICABLE', 'MISSING', {
            'amount.gross_per_share': FIN('0.04'),
            'amount.net_per_share': FIN('0.0396'),
            'amount.reduction_total': FIN('1194912.96')}),
        'currency': ('APPLICABLE', 'CORRECT',
                     {'instrument.currency': 'EUR'}),
    },
}

FIELD_NOTES = {
    ('CNMV-IP-2683', 'amount_or_ratio'): (
        'oferta sobre Biotest: EUR 43,00 por ordinaria + EUR 30,00 por '
        'preferente publicados; ninguno emitido'),
    ('CNMV-OIR-41312', 'event_type'): (
        '"abono de un dividendo" / "reparto del dividendo" no casan con '
        'los anclas de familia (sin "de X euros" ni "a cuenta"): '
        'completeness, no falso positivo'),
    ('CNMV-OIR-41650', 'event_type'): (
        'mismo patron que 41312: anclas de familia no disparan; '
        'completeness'),
    ('CNMV-OIR-41312', 'amount_or_ratio'): (
        'bruto 0,03 -> 0,03001963 EUR/accion (ajuste autocartera) '
        'publicado; no emitido'),
    ('CNMV-OIR-41650', 'amount_or_ratio'): (
        'bruto 5,65 -> 5,74867096 EUR/accion (ajuste autocartera) '
        'publicado; no emitido'),
    ('POEX-DOC-39649', 'amount_or_ratio'): (
        'FLAG REVISOR: emitido amount.gross_per_share=4 EUR '
        '("4 EUR POR ACCION NUEVA" = precio de suscripcion). Valor '
        'verbatim correcto; el slot gross_per_share se sostiene como '
        'contraprestacion bruta por accion (precedente IP-3011: precio '
        'OPA -> gross_per_share), pero issue_price_per_share es el slot '
        'canonico mas preciso -> decidir si es WRONG_ATTRIBUTION. '
        'Ademas ratio.terms 2:1 publicado y no emitido -> MISSING'),
    ('POEX-DOC-4162', 'amount_or_ratio'): (
        'neto/accion 1,37617429 publicado y no emitido -> MISSING '
        '(bruto y total si emitidos)'),
    ('POEX-DOC-4318', 'amount_or_ratio'): (
        'neto 0,0396 y reduccion_total 1.194.912,96 publicados y no '
        'emitidos -> MISSING (bruto si emitido)'),
    ('POEX-DOC-4319', 'amount_or_ratio'): (
        'igual que 4318'),
}

INSTRUMENT = {
    'BMEG-Delistings-ES0105077004-2026-04-01': (
        'RESOLVED_BASELINE', 'ES0105077004',
        'SOURCE_CARRIED_INSTRUMENT_BINDING: fila BMEG estructurada '
        'porta ISIN'),
    'BMEG-Dividends-ES0131703003-2025-09-18': (
        'RESOLVED_BASELINE', 'ES0131703003',
        'SOURCE_CARRIED_INSTRUMENT_BINDING: fila BMEG estructurada '
        'porta ISIN'),
    'CNMV-IP-2683': (
        'HUMAN_RELATION_REQUIRED', None,
        'affected = Biotest AG (name-only en doc, sin ISIN); el evento '
        'es sobre acciones de Biotest, no del emisor Grifols'),
    'CNMV-OIR-33177': ('NOT_APPLICABLE', None, 'seed NOT_CA'),
    'CNMV-OIR-34106': ('NOT_APPLICABLE', None, 'seed NOT_CA'),
    'CNMV-OIR-34625': (
        'RESOLVABLE_AUTOMATICALLY', None,
        'EXPLICIT_SOURCE_ASSERTION: "ProSiebenSat.1 Media SE (ISIN: '
        'DE000PSM7770)" explicito en el documento; no extraido por el '
        'parser'),
    'CNMV-OIR-34719': (
        'REQUIRES_HUMAN_REVIEW', None,
        'PDF escaneado sin capa de texto'),
    'CNMV-OIR-35131': ('NOT_APPLICABLE', None, 'seed NOT_CA'),
    'CNMV-OIR-41312': (
        'HUMAN_RELATION_REQUIRED', None,
        'Acciona Energia name-only; sin identificador oficial en doc'),
    'CNMV-OIR-41650': (
        'HUMAN_RELATION_REQUIRED', None,
        'Acciona name-only; sin identificador oficial en doc'),
    'POEX-DOC-15339': (
        'REQUIRES_HUMAN_REVIEW', None,
        'PDF escaneado sin capa de texto'),
    'POEX-DOC-39649': (
        'RESOLVABLE_AUTOMATICALLY', None,
        'el doc etiqueta "ISIN acciones cotizables ES0105969002"; el '
        'parser emitio los 3 ISIN del documento como Conflict '
        'registrado (comportamiento seguro, sin merge silencioso); '
        'affected = ES0105969002 determinable por la etiqueta'),
    'POEX-DOC-4162': (
        'HUMAN_RELATION_REQUIRED', None,
        'AOFI SHENI SOCIMI name-only; sin ISIN en doc'),
    'POEX-DOC-4318': (
        'HUMAN_RELATION_REQUIRED', None,
        'AC RESIDENCIAL SOCIMI name-only; sin ISIN en doc'),
    'POEX-DOC-4319': (
        'HUMAN_RELATION_REQUIRED', None,
        'AC RESIDENCIAL SOCIMI name-only; sin ISIN en doc'),
}


def main():
    adj = REPO / 'g1r' / 'adjudication'
    seed_rows, miss_rows, inst_rows = [], [], []
    for fid, (verdict, family, note, quote) in SEEDS.items():
        seed_rows.append({
            'frame_item_id': fid,
            'seed_verdict': verdict,
            'family': family,
            'affected_instrument_note': note,
            'evidence': {'quote': quote, 'title': None},
            'evidence_locator': f'{TXT}/{fid}.txt',
            'implementation_mechanism': None,
            'lifecycle_stage': None,
            'proposed_at': TS,
            'proposed_by': REV,
            'status': 'PROPOSED',
        })
        for field in FIELDS:
            if verdict == 'NOT_CA':
                app, cls, exp = 'NOT_APPLICABLE', 'NOT_APPLICABLE', None
                pub = 'N/A'
            elif verdict == 'REQUIRES_HUMAN_REVIEW':
                app, cls, exp = 'REQUIRES_HUMAN_REVIEW', \
                    'REQUIRES_HUMAN_REVIEW', None
                pub = 'NOT_REVIEWABLE_NO_TEXT_LAYER'
            else:
                app, cls, exp = E[fid][field]
                pub = ('PUBLISHED' if exp else
                       ('UNKNOWN' if cls == 'UNKNOWN' else 'N/A'))
            miss_rows.append({
                'frame_item_id': fid,
                'field': field,
                'family': family,
                'applicability': app,
                'classification': cls,
                'expected_claims': exp,
                'p0_error': None,
                'pipeline': {
                    'emitted_claims': emitted(fid, field),
                    'populated': bool(emitted(fid, field)),
                },
                'seed_verdict': verdict,
                'source_review': {
                    'evidence_locator': FIELD_NOTES.get(
                        (fid, field), f'{TXT}/{fid}.txt'),
                    'published_status': pub,
                    'reviewed_at': TS,
                    'reviewer': REV,
                    'source_document_id': fid,
                },
                'status': 'PROPOSED',
            })
        rclass, bound, inote = INSTRUMENT[fid]
        inst_rows.append({
            'frame_item_id': fid,
            'resolution_class': rclass,
            'baseline_resolved': RES[fid]['instrument_resolved'],
            'bound_isin': bound,
            'expected_affected': note,
            'adr013_note': inote,
            'evidence_locator': f'{TXT}/{fid}.txt',
            'reviewed_at': TS,
            'reviewer': REV,
            'status': 'PROPOSED',
        })

    def dump(name, rows):
        p = adj / name
        p.write_text(''.join(json.dumps(r, ensure_ascii=False,
                                        sort_keys=True) + '\n'
                             for r in rows), encoding='utf-8')
        return p

    paths = [dump('holdout-seed-review.jsonl', seed_rows),
             dump('holdout-missingness-review.jsonl', miss_rows),
             dump('holdout-instrument-review.jsonl', inst_rows)]
    manifest = {
        'manifest_version': 'CA_ES_G1R_HOLDOUT_ADJUDICATION_V1',
        'frozen_at': TS,
        'status': 'PROPOSED_PENDING_HUMAN_SIGN',
        'files': {
            str(p.relative_to(REPO)).replace('\\', '/'):
                hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths
        },
    }
    (REPO / 'g1r/manifests/holdout-adjudication-sha256.json').write_text(
        json.dumps(manifest, indent=1) + '\n', encoding='utf-8')

    # metricas del veredicto (propuesta)
    pub = sum(1 for r in miss_rows
              if r['source_review']['published_status'] == 'PUBLISHED')
    missing = sum(1 for r in miss_rows if r['classification'] == 'MISSING')
    pending = sum(1 for r in miss_rows
                  if r['classification'] == 'REQUIRES_HUMAN_REVIEW')
    p0_emitted = sum(
        len([k for k in FACTS.get(fid, {})
             if k.startswith(('event_type', 'date.', 'amount.', 'ratio.'))])
        for fid in FACTS)
    verdict = {
        'proposal_version': 'CA_ES_G1R_HOLDOUT_VERDICT_PROPOSAL_V1',
        'status': 'PROPOSED_PENDING_HUMAN_SIGN',
        'parser_freeze': 'g1r-parser-freeze @ a6a0674',
        'runs': ['holdout-run-1-a6a0674', 'holdout-run-2-a6a0674'],
        'second_run_determinism': 1.0,
        'p0_on_reviewed_documents': {
            'false_financial_facts': 0,
            'wrong_attribution': 0,
            'wrong_event_type': 0,
            'date_misbinding': 0,
            'false_positive_event': 0,
            'review_flags_for_human': [
                'POEX-DOC-39649 amount.gross_per_share=4: slot '
                'gross_per_share vs issue_price_per_share (ver nota)',
                'POEX-DOC-39649 instrument.isin: 3 ISIN emitidos como '
                'Conflict registrado, no merge silencioso',
            ],
        },
        'p0_review_coverage': {
            'reviewable_documents': 13,
            'requires_human_review': [
                'CNMV-OIR-34719', 'POEX-DOC-15339'],
            'emitted_p0_facts_reviewed': p0_emitted,
            'coverage_on_reviewable': 1.0,
            'blind_spot': 'los 2 PDF escaneados no emiten facts; su '
                          'missingness queda pendiente de inspeccion '
                          'humana',
        },
        'parser_miss_rate_guard': {
            'published_field_rows': pub,
            'missing_field_rows': missing,
            'pending_human_rows': pending,
            'rule': 'missing * 60 <= published * 23',
            'lhs': missing * 60,
            'rhs': pub * 23,
            'pass': missing * 60 <= pub * 23,
            'caveat': 'excluye las 12 filas REQUIRES_HUMAN_REVIEW de los '
                      '2 PDF sin capa de texto',
        },
        'invariants': {
            'field_provenance_rate': 1.0,
            'silent_conflicts': 0,
            'unproven_auto_merges': 0,
            'human_authored_facts': 0,
            'second_run_determinism': 1.0,
        },
        'measured_not_binding': {
            'event_detected': '15/15',
            'instrument_resolved': '2/15',
            'critical_facts_extracted': '8/15',
            'funnel': RUN['funnel'],
        },
    }
    (REPO / 'g1r/results/holdout-verdict-proposal.json').write_text(
        json.dumps(verdict, indent=1, ensure_ascii=False) + '\n',
        encoding='utf-8')
    print(f'seeds={len(seed_rows)} miss_rows={len(miss_rows)} '
          f'inst={len(inst_rows)}')
    print(f'published={pub} missing={missing} pending={pending} '
          f'guard={missing * 60}<={pub * 23} -> '
          f'{missing * 60 <= pub * 23}')


if __name__ == '__main__':
    sys.exit(main())
