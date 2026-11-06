"""Select by pre-execution order quantity, never response quality or labels."""
import json, random
from pathlib import Path
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parents[2]
p=ROOT/'analysis/state'
manifest_path=p/'sample_manifest.json'
m=json.loads(manifest_path.read_text())
if any(x.get('batch')=='quantity' for x in m['samples']):
    raise SystemExit('Quantity batch already exists; refusing to overwrite.')
traces=json.loads((p/'review_app/live_traces.json').read_text())['traces']
scenarios={x['id']:x for x in map(json.loads,(ROOT/'scenarios/support_scenarios.jsonl').read_text().splitlines())}
used={x['trace_id'] for x in m['samples']}
pools={1:[],2:[]}
for t in traces:
    if t['id'] in used: continue
    orders=scenarios.get(t['scenario_id'],{}).get('grounding',{}).get('orders',[])
    quantities={o.get('quantity') for o in orders}
    if len(quantities)==1 and next(iter(quantities)) in pools:
        pools[next(iter(quantities))].append(t)
rng=random.Random(20261105)
selected=[]
for quantity in [2,1]:
    for t in rng.sample(sorted(pools[quantity],key=lambda t:t['id']),15):
        selected.append(dict(trace_id=t['id'],session_id=t['session_id'],scenario_id=t['scenario_id'],role=t['role'],batch='quantity',method='stratified_random',dimension='order_quantity',dimension_value=quantity,review_order=len(selected)+1))
assert len({x['trace_id'] for x in selected})==30
assert not used.intersection(x['trace_id'] for x in selected)
m['samples'].extend(selected)
m['quantity_batch']={'seed':20261105,'created_at':datetime.now(timezone.utc).isoformat(),'dimension':'order_quantity','source':'Pre-execution grounding.orders in scenarios/support_scenarios.jsonl','meaning':'One product per order; quantity 1 versus quantity 2. Not distinct product line items.','eligible_pool_sizes':{str(k):len(v) for k,v in pools.items()},'selection':'15 random traces per quantity; no outcome or annotation filtering; excludes previously selected trace IDs.'}
manifest_path.write_text(json.dumps(m,indent=2)+'\n')
print('Selected 30 distinct additional traces: 15 quantity-two and 15 quantity-one.')
print('First:',selected[0]['scenario_id'])
