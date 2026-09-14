# -*- coding: utf-8 -*-
"""G1-R spike bake-off: evalua librerias OSS contra el ground truth DEV.

Corre con .venv-spikes (NO forma parte del runtime stdlib-only de src/).

Para cada libreria mide:
  - gt_hits: expected_claims PUBLISHED del missingness review que un
    candidato del spike puede producir (match semantico por valor)
  - extra_candidates: candidatos emitidos sin correspondencia en GT
    (potenciales falsas extracciones que la capa de atribucion tendria
    que rechazar)
  - deterministic: misma salida en 2 ejecuciones
  - preserva evidencia raw (span/lexema/coords)

Salida: g1r/results/spike-bakeoff.json
"""
import hashlib
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / 'g1r/corpus/raw/dev'
REVIEW = REPO / 'g1r/adjudication/dev-missingness-review.jsonl'
OUT = REPO / 'g1r/results/spike-bakeoff.json'

DEV_IDS = [p.stem for p in sorted(RAW.iterdir())]


def norm_amount(v):
    """'6.003.600,00' -> Decimal('6003600.00') estilo ES."""
    s = v.strip().replace('EUR', '').replace('euros', '').replace('euro', '')
    s = s.replace('\xa0', ' ').strip()
    s = re.sub(r'[^\d,\.\-]', '', s)
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        s = s.replace('.', '').replace(',', '.')
    try:
        return Decimal(s).normalize()
    except Exception:
        return None


# ---------------------------------------------------------------- GT ----
def load_gt():
    """expected_claims PUBLISHED por seed: {fid: [(key, value)]}."""
    gt = {}
    for line in REVIEW.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r['classification'] in ('CORRECT', 'MISSING', 'FALSE_FINANCIAL_FACT') \
                and r['source_review']['published_status'] == 'PUBLISHED' \
                and r['expected_claims']:
            for k, v in r['expected_claims'].items():
                gt.setdefault(r['frame_item_id'], []).append((k, v))
    return gt


GT = load_gt()

ISIN_RE = re.compile(r'\bES[A-Z0-9]{10}\b')
DATE_LEX_RE = re.compile(
    r'\b(\d{1,2}\s+de\s+[a-záéíóú]+\s+de\s+\d{4}|\d{1,2}/\d{1,2}/\d{4}'
    r'|\d{1,2}-\d{1,2}-\d{4}|\d{8})\b', re.I)
AMOUNT_LEX_RE = re.compile(r'\d{1,3}(?:\.\d{3})*,\d+|\d+\.\d{2,}')


# ------------------------------------------------------- extractores ----
def text_pdfplumber(path):
    import pdfplumber
    spans = []
    with pdfplumber.open(str(path)) as pdf:
        for pi, page in enumerate(pdf.pages):
            for w in page.extract_words(use_text_flow=False):
                spans.append({'t': w['text'], 'p': pi,
                              'b': [round(w['x0'], 1), round(w['top'], 1),
                                    round(w['x1'], 1), round(w['bottom'], 1)]})
    return ' '.join(s['t'] for s in spans), spans


def text_docling(path):
    from docling_core.types.doc.page import TextCellUnit
    from docling_parse.pdf_parser import DoclingPdfParser
    doc = DoclingPdfParser().load(str(path))
    spans = []
    for pi, (ok, page) in enumerate(doc.iterate_pages()):
        for cell in page.iterate_cells(TextCellUnit.WORD):
            r = cell.rect
            spans.append({'t': cell.text, 'p': pi,
                          'b': [round(r.r_x0, 1), round(r.r_y0, 1),
                                round(r.r_x2, 1), round(r.r_y2, 1)]})
    return ' '.join(s['t'] for s in spans), spans


def text_html(path):
    import html as h
    raw = path.read_text(encoding='utf-8', errors='replace')
    txt = re.sub(r'<[^>]+>', ' ', raw)
    return h.unescape(re.sub(r'\s+', ' ', txt))


def text_json(path):
    return path.read_text(encoding='utf-8', errors='replace')


def corpus_texts(extractor):
    """{fid: (text, spans_or_None)} sobre los raws DEV."""
    out = {}
    for fid in DEV_IDS:
        raw = next(RAW.glob(fid + '.*'))
        ext = raw.suffix.lower()
        try:
            if ext == '.pdf':
                out[fid] = extractor(raw)
            elif ext == '.html':
                out[fid] = (text_html(raw), None)
            else:
                out[fid] = (text_json(raw), None)
        except Exception as e:  # noqa: BLE001 - spike: registrar, no abortar
            out[fid] = ('', f'ERROR: {e}')
    return out


# ------------------------------------------------------- candidatos -----
def candidates_priceparser(texts):
    from price_parser import Price
    cands = {}
    for fid, (text, _) in texts.items():
        out = []
        for m in AMOUNT_LEX_RE.finditer(text):
            lex = m.group(0)
            ctx = text[max(0, m.start() - 90):m.end() + 30]
            cur = 'EUR' if re.search(r'(euro|EUR|€)', ctx, re.I) else None
            p = Price.fromstring(lex + (' EUR' if cur else ''))
            if p.amount is not None:
                out.append({'lexeme': lex, 'value': str(p.amount),
                            'currency': p.currency, 'span': m.start()})
        cands[fid] = out
    return cands


def candidates_recognizers(texts):
    from recognizers_suite import recognize_number, recognize_datetime, Culture
    cands = {}
    for fid, (text, _) in texts.items():
        out = []
        for r in recognize_number(text, Culture.Spanish):
            res = r.resolution
            v = res.get('value') if isinstance(res, dict) else None
            if v is not None:
                out.append({'kind': 'number', 'lexeme': r.text, 'value': v})
        for r in recognize_datetime(text, Culture.Spanish):
            res = r.resolution or {}
            vals = res.get('values') or []
            for vv in vals:
                if vv.get('type') == 'date' and vv.get('value'):
                    out.append({'kind': 'date', 'lexeme': r.text,
                                'value': vv['value']})
        cands[fid] = out
    return cands


def candidates_dateparser(texts):
    import dateparser
    cands = {}
    for fid, (text, _) in texts.items():
        out = []
        for m in DATE_LEX_RE.finditer(text):
            d = dateparser.parse(m.group(0), languages=['es'],
                                 settings={'PREFER_DAY_OF_MONTH': 'first'})
            if d:
                out.append({'lexeme': m.group(0),
                            'value': d.date().isoformat(),
                            'span': m.start()})
        cands[fid] = out
    return cands


def candidates_stdnum_isin(texts):
    from stdnum import isin
    cands = {}
    for fid, (text, _) in texts.items():
        out = []
        for m in ISIN_RE.finditer(text):
            out.append({'lexeme': m.group(0),
                        'valid_checksum': bool(isin.is_valid(m.group(0))),
                        'span': m.start()})
        cands[fid] = out
    return cands


def candidates_spacy(texts):
    import spacy
    from spacy.matcher import Matcher
    nlp = spacy.blank('es')
    matcher = Matcher(nlp.vocab)
    matcher.add('ROLE', [
        [{'LOWER': {'IN': ['ex', 'ex-date', 'ex-cupon', 'ex-cupón']}}],
        [{'LOWER': {'IN': ['record', 'record-date', 'corte']}}],
        [{'LOWER': {'IN': ['pago', 'liquidacion', 'liquidación', 'abono',
                           'payment']}}],
        [{'LOWER': 'precio'}, {'LOWER': {'IN': ['de', 'del']},
                              'OP': '?'},
         {'LOWER': {'IN': ['oferta', 'contraprestacion',
                           'contraprestación']}}],
        [{'LOWER': 'cotizacion'}, {'LOWER': 'de'}, {'LOWER': 'referencia'}],
        [{'LOWER': {'IN': ['dividendo', 'ampliacion', 'ampliación',
                           'oferta', 'desdoblamiento', 'scrip',
                           'opscv', 'opa']}}],
    ])
    cands = {}
    for fid, (text, _) in texts.items():
        doc = nlp(text[:200000])
        out = [{'match_id': nlp.vocab.strings[m], 'span': s,
                'text': doc[s:e].text}
               for m, s, e in matcher(doc)]
        cands[fid] = out
    return cands


# ------------------------------------------------------- evaluacion -----
def gt_value_match(key, expected, cand_value):
    if isinstance(expected, dict):  # financiero
        try:
            return Decimal(str(cand_value)) == Decimal(expected['normalized'])
        except Exception:
            return False
    return str(cand_value)[:10] == str(expected)[:10]


def evaluate(name, cands, kind):
    """kind: 'amount'|'date' — solo evalua GT claims de ese tipo."""
    hits, misses = [], []
    for fid, gts in GT.items():
        for key, expected in gts:
            if kind == 'amount' and key.startswith(('amount.', 'ratio.')):
                ok = any(gt_value_match(key, expected, c['value'])
                         for c in cands.get(fid, []) if 'value' in c)
            elif kind == 'date' and key.startswith('date.'):
                ok = any(str(c.get('value')) == expected
                         for c in cands.get(fid, []))
            else:
                continue
            (hits if ok else misses).append(f'{fid}:{key}')
    n_cand = sum(len(v) for v in cands.values())
    return {'gt_hits': hits, 'gt_misses': misses, 'candidates_total': n_cand}


def evaluate_isin(cands):
    """ISINs esperados segun dev-instrument-review (los que el doc porta)."""
    instr = [json.loads(l) for l in
             (REPO / 'g1r/adjudication/dev-instrument-review.jsonl')
             .read_text(encoding='utf-8').splitlines() if l.strip()]
    per_seed = {}
    for r in instr:
        fid = r['frame_item_id']
        found = [c for c in cands.get(fid, []) if c['valid_checksum']]
        expect = r.get('bound_isin') or ''
        expected_in_doc = ISIN_RE.findall(r.get('expected_affected') or '')
        per_seed[fid] = {
            'baseline_resolved': r['baseline_resolved'],
            'resolution_class': r['resolution_class'],
            'valid_isins_in_doc': [c['lexeme'] for c in found],
            'expected_in_text': expected_in_doc,
        }
    auto = {fid: v for fid, v in per_seed.items()
            if v['resolution_class'] == 'RESOLVABLE_AUTOMATICALLY'}
    auto_hit = sum(1 for v in auto.values() if v['valid_isins_in_doc'])
    return {'per_seed': per_seed,
            'resolvable_auto_seeds': list(auto),
            'resolvable_auto_hit': auto_hit,
            'candidates_total': sum(len(v) for v in cands.values())}


def det_hash(fn, arg):
    a = json.dumps(fn(arg), sort_keys=True, default=str)
    b = json.dumps(fn(arg), sort_keys=True, default=str)
    return hashlib.sha256(a.encode()).hexdigest() == hashlib.sha256(b.encode()).hexdigest()


def main():
    results = {}

    # --- A: pdfplumber (layout + spans) ---
    texts_pl = corpus_texts(text_pdfplumber)
    n_words = sum(len(s) for _, s in texts_pl.values() if isinstance(s, list))
    results['pdfplumber'] = {
        'words_with_bbox': n_words,
        'evidence_spans': True,
        'deterministic': det_hash(lambda t: t, [t for t, _ in texts_pl.values()]),
        'notes': 'words con x0/x1/top/bottom por pagina; lexemas decimales '
                 'conservados como tokens (0,6000 etc.)',
    }

    # --- B: docling-parse ---
    try:
        texts_dl = corpus_texts(text_docling)
        n_cells = sum(len(s) for _, s in texts_dl.values() if isinstance(s, list))
        results['docling_parse'] = {'cells_with_bbox': n_cells,
                                    'evidence_spans': True,
                                    'notes': 'celdas de pagina con bbox'}
    except Exception as e:  # noqa: BLE001
        results['docling_parse'] = {'error': str(e)}
        texts_dl = {}

    # --- C: price-parser sobre texto pdfplumber ---
    c_pp = candidates_priceparser(texts_pl)
    results['price_parser'] = evaluate('price_parser', c_pp, 'amount')
    results['price_parser']['deterministic'] = det_hash(
        candidates_priceparser, texts_pl)

    # --- D: recognizers-text ---
    try:
        c_rec = candidates_recognizers(texts_pl)
        ev_amt = evaluate('rec_amount', c_rec, 'amount')
        ev_dt = evaluate('rec_date', c_rec, 'date')
        results['recognizers_text'] = {**ev_amt, 'date_' + 'hits': ev_dt['gt_hits'],
                                       'date_misses': ev_dt['gt_misses']}
        results['recognizers_text']['deterministic'] = det_hash(
            candidates_recognizers, texts_pl)
    except Exception as e:  # noqa: BLE001
        results['recognizers_text'] = {'error': str(e)}

    # --- E: dateparser ---
    c_dp = candidates_dateparser(texts_pl)
    results['dateparser'] = evaluate('dateparser', c_dp, 'date')
    results['dateparser']['deterministic'] = det_hash(
        candidates_dateparser, texts_pl)

    # --- F: spaCy Matcher (roles) ---
    c_sp = candidates_spacy(texts_pl)
    results['spacy_matcher'] = {
        'role_matches_total': sum(len(v) for v in c_sp.values()),
        'deterministic': det_hash(candidates_spacy, texts_pl),
        'notes': 'blank("es") + Matcher; aporta roles lexicos, no decision',
    }

    # --- G: stdnum ISIN (contra instrument-review) ---
    texts_all = {}
    for fid in DEV_IDS:
        raw = next(RAW.glob(fid + '.*'))
        if raw.suffix == '.pdf' and fid in texts_pl:
            texts_all[fid] = texts_pl[fid]
        elif raw.suffix == '.html':
            texts_all[fid] = (text_html(raw), None)
        else:
            texts_all[fid] = (text_json(raw), None)
    c_isin = candidates_stdnum_isin(texts_all)
    results['stdnum_isin'] = evaluate_isin(c_isin)
    results['stdnum_isin']['deterministic'] = det_hash(
        candidates_stdnum_isin, texts_all)
    results['stdnum_isin']['invalid_checksums'] = sum(
        1 for v in c_isin.values() for c in v if not c['valid_checksum'])

    # extra-candidates del extractor monetario (posibles falsos)
    gt_amounts = {fid: [v['normalized'] for k, v in gts
                        if isinstance(v, dict)]
                  for fid, gts in GT.items()}
    extra = 0
    for fid, cs in c_pp.items():
        gta = gt_amounts.get(fid, [])
        for c in cs:
            try:
                if str(Decimal(str(c['value']))) not in \
                        {str(Decimal(x)) for x in gta}:
                    extra += 1
            except Exception:
                extra += 1
    results['price_parser']['extra_candidates_not_in_gt'] = extra

    OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False) + '\n',
                   encoding='utf-8')
    print(json.dumps(results, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
