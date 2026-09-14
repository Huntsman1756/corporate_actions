# -*- coding: utf-8 -*-
"""Genera g1r/manifests/g1-regression-oracle.json (V2, claims ejecutables).

Re-ejecuta el parser congelado c431830 sobre los 25 manifests sellados
(mismos raw bytes, facts en memoria) y traduce la adjudicacion firmada
a expected_claims / forbidden_claims / allowed_outcomes verificables.
"""
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ca_es.canonical import canonical_bytes  # noqa: E402
from ca_es.pipeline import run_pipeline  # noqa: E402
from ca_es.reference.esma_firds import load_firds_listings  # noqa: E402

FIELD_NS = {
    'event_type': lambda f: {'event_type': f['event_type']} if 'event_type' in f else {},
    'ex_date': lambda f: {'date.ex_date': f['date.ex_date']} if 'date.ex_date' in f else {},
    'record_date': lambda f: {'date.record_date': f['date.record_date']} if 'date.record_date' in f else {},
    'payment_date': lambda f: {'date.payment_date': f['date.payment_date']} if 'date.payment_date' in f else {},
}

def fin(v):
    return {'normalized': v['normalized'], 'currency': v['currency']} if isinstance(v, dict) and v.get('__financial__') else v

def claims_for(field, f):
    if field == 'amount_or_ratio':
        return {k: fin(v) for k, v in f.items() if k.startswith(('amount.', 'ratio.'))}
    if field == 'currency':
        out = {}
        if 'instrument.currency' in f:
            out['instrument.currency'] = f['instrument.currency']
        for k, v in f.items():
            if k.startswith(('amount.', 'ratio.')) and isinstance(v, dict) and v.get('__financial__'):
                out[k + '.currency'] = v['currency']
        return out
    return FIELD_NS[field](f)

def sealed_facts():
    resolver = load_firds_listings(REPO / 'g0/corpus/reference/esma-firds-listings.json')
    out = {}
    for setname in ('holdout', 'adversarial'):
        for mpath in sorted((REPO / 'g1/manifests' / setname).glob('*.json')):
            rel = str(mpath.relative_to(REPO)).replace('\\', '/')
            run = run_pipeline(REPO, manifest_relpath=rel, resolver=resolver,
                               instrument_bindings_relpath='g0/corpus/reference/portfolio-instruments.json',
                               run_id='ORACLE-DUMP', executed_at='2026-09-14T00:00:00Z')
            out.setdefault(setname, {})[mpath.stem] = {
                f['field_path']: f['value'] for f in run['body']['facts']
                if f['value'] not in (None, 'UNKNOWN')}
    return out

CORRECT_FIELDS = []  # (set, frame_item_id, field) — derivado del V1 firmado

INCORRECT = [
    {'frame_item_id': 'CNMV-OIR-37214', 'set': 'adversarial', 'field': 'amount_or_ratio',
     'required': 'CORRECT_OR_ABSTAIN',
     'forbidden_claims': {'amount.gross_per_share': {'normalized': '0.01', 'currency': 'EUR'}},
     'allowed_outcomes': ['ABSENT', {'amount.gross_total': {'normalized': '342000000', 'currency': 'EUR'}}],
     'note': '0,01 era nominal de accion, no dividendo. Publicado: "importe total de 342 millones de euros".'},
    {'frame_item_id': 'CNMV-OIR-40729', 'set': 'adversarial', 'field': 'amount_or_ratio',
     'required': 'CORRECT_OR_ABSTAIN',
     'forbidden_claims': {'amount.gross_per_share': {'normalized': '0.01', 'currency': 'EUR'}},
     'allowed_outcomes': ['ABSENT', {'amount.gross_total': {'normalized': '400000000', 'currency': 'EUR'}}],
     'note': '0,01 era nominal de accion, no dividendo. Publicado: "importe total de 400 millones de euros".'},
    {'frame_item_id': 'CNMV-OIR-40729', 'set': 'adversarial', 'field': 'ex_date',
     'required': 'CORRECT_OR_ABSTAIN',
     'forbidden_claims': {'date.ex_date': '2026-05-15'},
     'allowed_outcomes': ['ABSENT', {'date.ex_date': '2026-05-18'}],
     'note': '15-may era fecha prevista de anuncio; ex-dividendo publicado = 18-may-2026.'},
    {'frame_item_id': 'CNMV-IP-2594', 'set': 'holdout', 'field': 'amount_or_ratio',
     'required': 'CORRECT_OR_ABSTAIN',
     'forbidden_claims': {'amount.max_total': {'normalized': '755000000', 'currency': 'EUR'}},
     'allowed_outcomes': ['ABSENT', {'amount.gross_per_share': {'normalized': '0.1244', 'currency': 'EUR'}}],
     'note': '755M pertenece al programa de recompra. Dividendo publicado: 12,44 centimos brutos/accion.'},
    {'frame_item_id': 'CNMV-OIR-36680', 'set': 'holdout', 'field': 'event_type',
     'required': 'CORRECT_OR_ABSTAIN',
     'forbidden_claims': {'event_type': 'CASH_DIVIDEND'},
     'allowed_outcomes': ['ABSENT', {'event_type': 'MERGER_OR_EXCHANGE'}],
     'note': 'Documento de fusion por absorcion JSS->Arima; CASH_DIVIDEND era lexema espurio.'},
    {'frame_item_id': 'CNMV-OIR-38190', 'set': 'holdout', 'field': 'amount_or_ratio',
     'required': 'CORRECT_OR_ABSTAIN',
     'forbidden_claims': {'amount.gross_per_share': {'normalized': '53', 'currency': 'EUR'}},
     'allowed_outcomes': ['ABSENT', {'amount.gross_per_share': {'normalized': '0.53', 'currency': 'EUR'}}],
     'note': 'DECIMAL_SPLIT_PDF: "0. 53 euros" se emitio como 53.'},
    {'frame_item_id': 'CNMV-OIR-41467', 'set': 'holdout', 'field': 'amount_or_ratio',
     'required': 'CORRECT_OR_ABSTAIN',
     'forbidden_claims': {'amount.gross_per_share': {'normalized': '47', 'currency': 'EUR'}},
     'allowed_outcomes': ['ABSENT', {'amount.gross_per_share': {'normalized': '0.47', 'currency': 'EUR'}}],
     'note': 'DECIMAL_SPLIT_PDF: "0, 47 euros" se emitio como 47.'},
]

def main():
    facts = sealed_facts()
    old = json.loads((REPO / 'g1r/manifests/g1-regression-oracle.json').read_text(encoding='utf-8'))
    correct, empty = [], []
    for e in old['known_correct_critical_fields']:
        cl = claims_for(e['field'], facts[e['set']][e['frame_item_id']])
        if not cl:
            empty.append((e['frame_item_id'], e['field']))
        correct.append({'frame_item_id': e['frame_item_id'], 'set': e['set'],
                        'field': e['field'], 'required': 'REMAIN_CORRECT', 'expected_claims': cl})
    incorrect = INCORRECT
    oracle = {
        'oracle_version': 'CA_ES_G1_REGRESSION_ORACLE_V2',
        'frozen_at': '2026-09-14',
        'source': 'adjudicacion firmada G1 sealed + re-ejecucion determinista del parser c431830 sobre manifests sellados',
        'claim_semantics': {
            'financial': 'igualdad semantica sobre {normalized, currency}; raw_lexeme/scale no comparan',
            'scalar': 'igualdad exacta de string (event_type, date.*, instrument.currency)'},
        'evaluation_rule': {
            'REMAIN_CORRECT': 'todos los expected_claims deben seguir emitidos y semanticamente iguales; se permiten claims adicionales, siempre sujetos a p0_review',
            'CORRECT_OR_ABSTAIN': 'ningun forbidden_claim puede emitirse; el claim-set emitido del campo debe ser vacio (ABSENT) o semanticamente igual a uno de allowed_outcomes'},
        'known_correct_critical_fields': correct,
        'known_p0_incorrect_fields': incorrect,
        'counts': {'correct': len(correct), 'p0_incorrect': len(incorrect)},
        'note': '49 = 37 HOLDOUT + 12 ADVERSARIAL campos criticos correctos; 7 campos poblados incorrectos conocidos.'}
    oracle['oracle_sha256'] = hashlib.sha256(canonical_bytes(oracle)).hexdigest()
    (REPO / 'g1r/manifests/g1-regression-oracle.json').write_text(
        json.dumps(oracle, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    print('correct:', len(correct), 'incorrect:', len(incorrect), 'empty:', empty)
    print('sha:', oracle['oracle_sha256'])

if __name__ == '__main__':
    main()
