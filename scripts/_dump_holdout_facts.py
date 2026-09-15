# -*- coding: utf-8 -*-
import json, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from ca_es.pipeline import run_pipeline
from ca_es.reference.esma_firds import load_firds_listings

resolver = load_firds_listings(REPO / 'g0/corpus/reference/esma-firds-listings.json')
out = {}
for mp in sorted((REPO / 'g1r/manifests/holdout').glob('*.json')):
    rel = str(mp.relative_to(REPO)).replace(chr(92), '/')
    run = run_pipeline(REPO, manifest_relpath=rel, resolver=resolver,
                       instrument_bindings_relpath='g0/corpus/reference/portfolio-instruments.json',
                       run_id='ADJ-HOLDOUT', executed_at='2026-09-14T00:00:00Z')
    out[mp.stem] = {
        f['field_path']: f['value'] for f in run['body']['facts']
        if f['value'] not in (None, 'UNKNOWN')}
Path('g1r/adjudication/_holdout_facts.json').write_text(
    json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True), encoding='utf-8')
print('seeds:', len(out))
