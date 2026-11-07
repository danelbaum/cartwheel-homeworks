"""Append the final 15 uniform HW4 checks without replacing earlier work."""
import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from analysis.helpers._state import write_json

STATE = Path(__file__).resolve().parents[1] / 'state'
SEED = 20261106


def main():
    path = STATE / 'sample_manifest.json'
    manifest = json.loads(path.read_text())
    if any(s['batch'] in {'final', 'final_uniform'} for s in manifest['samples']):
        raise SystemExit('Final batch already exists; preserving it.')
    snapshot = json.loads((STATE / 'review_app/live_traces.json').read_text())
    notes = json.loads((STATE / 'annotations.json').read_text())['annotations']
    selected = {s['trace_id'] for s in manifest['samples']}
    annotated = {n['trace_id'] for n in notes if not n.get('deleted')}
    excluded = selected | annotated
    pool = sorted((t for t in snapshot['traces'] if t['id'] not in excluded), key=lambda t: t['id'])
    assert len({t['id'] for t in pool}) == len(pool) >= 15
    chosen = random.Random(SEED).sample(pool, 15)
    records = [{
        'trace_id': t['id'], 'session_id': t['session_id'],
        'scenario_id': t['scenario_id'], 'role': t['role'],
        'batch': 'final_uniform', 'method': 'uniform', 'review_order': i,
    } for i,t in enumerate(chosen,1)]
    assert len({r['trace_id'] for r in records}) == 15
    assert not ({r['trace_id'] for r in records} & excluded)
    now = datetime.now(timezone.utc).isoformat()
    taxonomy = (STATE / 'patterns.json').read_bytes()
    audit = {
        'created_at': now, 'seed': SEED,
        'method': 'Simple random sample without replacement from sorted eligible trace IDs.',
        'exclusions': 'All previously selected trace IDs and all active annotated trace IDs.',
        'excluded_trace_ids': sorted(excluded),
        'eligible_trace_ids': [t['id'] for t in pool],
        'selected_trace_ids': [r['trace_id'] for r in records],
        'outcome_filters': 'None. AI labels, response quality, and predicted failures were not used.',
        'prior_ai_assessment': 'Cohort was previously AI-assessed; this is a fresh human review sample, not an AI-unseen holdout.',
        'taxonomy_sha256': hashlib.sha256(taxonomy).hexdigest(),
        'taxonomy_at_selection': json.loads(taxonomy),
    }
    write_json(STATE / 'review_app/final_sampling_audit.json', audit)
    manifest['samples'].extend(records)
    manifest['final_uniform_batch'] = {k:v for k,v in audit.items() if k not in {'taxonomy_at_selection','excluded_trace_ids','eligible_trace_ids'}}
    for b in manifest.get('remaining_batches',[]):
        if b['batch']=='final_uniform': b.update(status='selected; human review pending',selected_at=now)
    write_json(path,manifest)
    print(json.dumps({'selected':len(records),'pool':len(pool),'first':records[0]},indent=2))

if __name__ == '__main__':
    main()
