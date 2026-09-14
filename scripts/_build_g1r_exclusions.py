# -*- coding: utf-8 -*-
"""Genera g1r/manifests/excluded-g1-frame-items.json.

Congela el conjunto exacto de frame_item_id usados por G1
(DEV + HOLDOUT + ADVERSARIAL + NO_MATCH) que el sampling G1-R
elimina del frame antes de cualquier hash.
"""
import json, hashlib, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from ca_es.canonical import canonical_bytes  # noqa: E402

dh = json.loads((REPO / 'g1/manifests/dev-holdout.json').read_text(encoding='utf-8'))
reg = json.loads((REPO / 'g1/manifests/adversarial-registry.json').read_text(encoding='utf-8'))
nm = [json.loads(l)['frame_item_id']
      for l in (REPO / 'g1/adjudication/no-match-audit.jsonl').read_text(encoding='utf-8').splitlines()
      if l.strip()]

groups = {
    'dev': sorted(dh['development']),
    'holdout': sorted(dh['holdout']),
    'adversarial': sorted(e['frame_item_id'] for e in reg['entries']),
    'no_match': sorted(nm),
}
all_ids = sorted(i for g in groups.values() for i in g)
assert len(all_ids) == len(set(all_ids)) == 150, (len(all_ids), len(set(all_ids)))

doc = {
    'manifest_version': 'CA_ES_G1R_EXCLUDED_G1_ITEMS_V1',
    'frozen_at': '2026-09-14',
    'purpose': 'conjunto exacto de frame_item_id usados por G1; se eliminan del frame antes de cualquier hash en el sampling G1-R',
    'parent_frame': 'g1/manifests/sampling-frame.json',
    'parent_frame_sha256': 'edc785ebbe007ad5eec000edc06abaff15b2c674698c27e726cc41253dc94188',
    'groups': {k: {'count': len(v), 'frame_item_ids': v} for k, v in groups.items()},
    'total_excluded': len(all_ids),
}
doc['excluded_ids_sha256'] = hashlib.sha256(canonical_bytes(all_ids)).hexdigest()
(REPO / 'g1r/manifests/excluded-g1-frame-items.json').write_text(
    json.dumps(doc, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
print('total:', len(all_ids), {k: len(v) for k, v in groups.items()})
print('sha:', doc['excluded_ids_sha256'])
