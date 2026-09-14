# -*- coding: utf-8 -*-
"""Extrae texto de los 25 documentos DEV para adjudicacion (g1r/adjudication/dev-text/)."""
import json, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from ca_es.sources.parsers.pdf_text import extract_text, normalize_text
from ca_es.sources.parsers.html_text import html_to_text, decode as decode_html

OUT = REPO / 'g1r/adjudication/dev-text'
OUT.mkdir(parents=True, exist_ok=True)
for mp in sorted((REPO / 'g1r/manifests/dev').glob('*.json')):
    doc = json.loads(mp.read_text(encoding='utf-8'))['documents'][0]
    raw = REPO / doc['raw_relpath']
    mt = doc['media_type']
    if mt == 'application/pdf':
        text = normalize_text(extract_text(raw.read_bytes()))
    elif mt == 'application/json':
        text = raw.read_text(encoding='utf-8')
    else:
        text = html_to_text(decode_html(raw.read_bytes()))
    (OUT / (mp.stem + '.txt')).write_text(text, encoding='utf-8')
    print(mp.stem, mt, len(text))
