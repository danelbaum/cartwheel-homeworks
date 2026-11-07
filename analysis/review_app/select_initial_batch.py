"""Reproducible HW4 batch: 15 uniform traces + 15 centroid representatives."""
import hashlib
import json
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from analysis.helpers._state import write_json
from analysis.helpers.selection import _standardize, _kmeans

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / 'analysis/state'
SEED = 20261027


def main():
    destination = STATE / 'sample_manifest.json'
    if destination.exists():
        raise SystemExit('A sample manifest already exists; refusing to replace it.')
    source = STATE / 'review_app/live_traces.json'
    snapshot = json.loads(source.read_text())
    traces = sorted(snapshot['traces'], key=lambda t:t['id'])
    assert len(traces) == len({t['id'] for t in traces})
    roles = sorted({t.get('role') or 'unknown' for t in traces})
    names = sorted({tool['name'] for t in traces for tool in t['tools']})
    sessions = Counter(t['session_id'] for t in traces)
    features = ['session_turn_count','tool_call_count','distinct_tools','request_length'] + ['role:'+r for r in roles] + ['tool:'+n for n in names]
    raw = []
    for t in traces:
        tools = {tool['name'] for tool in t['tools']}
        request = next((b['text'] for b in t['blocks'] if b['role']=='user'),'')
        raw.append([sessions[t['session_id']],len(t['tools']),len(tools),len(request)] + [int(t.get('role')==r) for r in roles] + [int(n in tools) for n in names])
    vectors = _standardize(raw)
    clusters = _kmeans(vectors, k=8, seed=SEED, iters=100)
    groups = {c:[i for i,a in enumerate(clusters) if a==c] for c in sorted(set(clusters))}
    centers = {c:[sum(vectors[i][d] for i in group)/len(group) for d in range(len(features))] for c,group in groups.items()}
    distances = [sum((a-b)**2 for a,b in zip(vectors[i],centers[clusters[i]])) for i in range(len(traces))]
    uniform = random.Random(SEED).sample(range(len(traces)),15)
    selected = set(uniform)
    candidates = {c:sorted((i for i in group if i not in selected),key=lambda i:(distances[i],traces[i]['id'])) for c,group in groups.items()}
    reps = []
    while len(reps)<15:
        before=len(reps)
        for c in sorted(candidates):
            if candidates[c] and len(reps)<15:
                i=candidates[c].pop(0);reps.append(i);selected.add(i)
        if before==len(reps):raise ValueError('Insufficient distinct representatives')
    records=[]
    for i in uniform+reps:
        t=traces[i]
        records.append({'trace_id':t['id'],'session_id':t['session_id'],'scenario_id':t['scenario_id'],'role':t['role'],'batch':'initial','method':'uniform' if i in uniform else 'cluster_representative','review_order':len(records)+1,'cluster':clusters[i],'squared_distance_to_centroid':distances[i]})
    assert len(records)==len({r['trace_id'] for r in records})==30
    audit={'seed':SEED,'features':features,'feature_vectors':raw,'standardized_vectors':vectors,'trace_ids':[t['id'] for t in traces],'assignments':clusters,'centroids':centers,'cluster_sizes':{c:len(g) for c,g in groups.items()}}
    write_json(STATE/'review_app/initial_sampling_audit.json',audit)
    manifest={'version':1,'created_at':datetime.now(timezone.utc).isoformat(),'seed':SEED,'source':'live Langfuse cohort snapshot','source_fetched_at':snapshot['fetched_at'],'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'population_trace_ids':[t['id'] for t in traces],'population_size':len(traces),'selection_unit':'distinct trace ID; other session turns are displayed for context only','methodology':{'uniform':'Simple random sample without replacement from all cohort trace IDs, sorted by ID before seeding.','representatives':'Eight clusters fitted to standardized structural features, role and tool identity. Round-robin nearest-to-centroid traces, excluding all uniform picks.','features':features,'outcome_filters':'None. No failure predictions, annotations, scores, or response quality used.','review_order':'Uniform draw order followed by representatives; no outcome-based reordering.'},'samples':records,'remaining_batches':[{'batch':'product_dimension','count':30,'status':'not selected; dimension must be chosen before inspecting outcomes'},{'batch':'depth_search','count':25,'status':'not selected'},{'batch':'final_uniform','count':15,'status':'not selected; reserve until taxonomy draft'}]}
    write_json(destination,manifest)
    print(json.dumps({'count':len(records),'methods':dict(Counter(r['method'] for r in records)),'roles':dict(Counter(r['role'] for r in records)),'clusters':len(groups),'multi_turn_targets':sum(sessions[traces[i]['session_id']]>1 for i in uniform+reps),'first':records[0]},indent=2))

if __name__=='__main__':main()
