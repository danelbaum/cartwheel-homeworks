"""Cartwheel HW4 review: python -m analysis.review_app.server --port 8021."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
import uuid
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv
from analysis.helpers._state import read_json, write_json, append_jsonl, read_jsonl, write_jsonl
from analysis.helpers.normalization import normalize_trace, _text

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STATE = Path(os.environ.get('CARTWHEEL_ANALYSIS_STATE', ROOT / 'analysis/state'))
LOCK = threading.RLock()
TOKEN = secrets.token_urlsafe(32)
TRACES = {}
STATUS = {'phase': 'loading', 'loaded': 0, 'total': 0, 'error': None}
CLIENT = None
SPEC = ''
SPEC_HASH = ''


def now():
    return datetime.now(timezone.utc).isoformat()


def rows(name, key):
    value = read_json(STATE / name, [])
    return value.get(key, []) if isinstance(value, dict) else value


def save_rows(name, key, value):
    old = read_json(STATE / name, [])
    if isinstance(old, dict):
        old[key] = value
        write_json(STATE / name, old)
    else:
        write_json(STATE / name, value)


def attributes(raw):
    return normalize_trace(raw)['metadata']


def build_trace(raw):
    n = normalize_trace(raw)
    blocks = []
    def add(key, role, value, **extra):
        text = _text(value)
        if text.strip():
            blocks.append({'key': key, 'role': role, 'text': text, **extra})
    add('user', 'user', raw.get('input'))
    observations = sorted(raw.get('observations', []), key=lambda o: o.get('startTime') or '')
    tools = []
    systems = []
    for o in observations:
        if o.get('type') == 'GENERATION':
            messages = o.get('input') or {}
            if isinstance(messages, dict):
                for m in messages.get('messages', []):
                    if m.get('role') == 'system':
                        text = _text([m])
                        if text not in systems:
                            systems.append(text)
            for i, m in enumerate(o.get('output') or []):
                if not isinstance(m, dict):
                    continue
                for j, part in enumerate(m.get('parts', [])):
                    if part.get('type') == 'text' and part.get('content'):
                        add(f'{o["id"]}:{i}:{j}', 'assistant', part['content'], timestamp=o.get('endTime'))
        elif o.get('type') == 'TOOL':
            tool = {'id': o['id'], 'name': o['name'], 'input': o.get('input'), 'output': o.get('output'), 'timestamp': o.get('startTime'), 'end_time': o.get('endTime'), 'level': o.get('level'), 'status_message': o.get('statusMessage')}
            tools.append(tool)
            add(f'{o["id"]}:call', 'tool', o.get('input'), name=o['name'], tool_id=o['id'], timestamp=o.get('startTime'))
            add(f'{o["id"]}:result', 'tool_result', o.get('output'), name=o['name'], tool_id=o['id'], timestamp=o.get('endTime'))
    final = _text(raw.get('output'))
    if final.strip() and not any(b['role'] == 'assistant' and b['text'] == final for b in blocks):
        add('output', 'assistant', final)
    meta = n['metadata']
    store = meta.get('cartwheel.store_id')
    if store is None:
        for system in systems:
            match = re.search(r'^- Store id: (\d+)', system, re.M)
            if match:
                store = match[1]
                break
    return {'id': n['trace_id'], 'session_id': n['meta'].get('session_id') or n['trace_id'], 'scenario_id': n['meta'].get('scenario_id'), 'timestamp': n['timestamp'], 'role': n['meta'].get('role'), 'user_id': meta.get('cartwheel.user_id'), 'user_name': meta.get('cartwheel.user_name'), 'store_id': store, 'prompt_version': n['meta'].get('prompt_version'), 'blocks': blocks, 'tools': tools, 'system_prompts': systems, 'url': os.environ.get('LANGFUSE_HOST', '').rstrip('/') + raw.get('htmlPath', ''), 'raw': raw}


def caller_context(trace):
    """Supplement only identity-matched callers with saved pre-execution facts."""
    result = {'name': trace.get('user_name'), 'role': trace.get('role'),
              'user_id': trace.get('user_id'), 'store_id': trace.get('store_id'),
              'store_name': None, 'supplemented': False}
    source = ROOT / 'scenarios/support_scenarios.jsonl'
    if not source.exists():
        return result
    for line in source.read_text().splitlines():
        row = json.loads(line)
        if row.get('id') != trace.get('scenario_id'):
            continue
        grounding = row.get('grounding', {})
        user = grounding.get('authenticated_user', {})
        if trace.get('user_id') is None or str(user.get('id')) != str(trace['user_id']):
            return result
        if trace.get('role') and user.get('role') != trace['role']:
            return result
        if trace.get('store_id') is not None and str(user.get('store_id')) != str(trace['store_id']):
            return result
        for key, source_key in [('name', 'name'), ('role', 'role'), ('store_id', 'store_id')]:
            if result[key] is None and user.get(source_key) is not None:
                result[key] = user[source_key]
                result['supplemented'] = True
        if result['store_id'] is not None:
            store = next((v for v in grounding.get('stores', [])
                          if str(v.get('id')) == str(result['store_id'])), None)
            if store and store.get('name'):
                result['store_name'] = store['name']
                result['supplemented'] = True
        return result
    return result


def load_live():
    global TRACES
    try:
        # Scope to the student's completed HW3 cohort, not demonstration/pilot traces.
        export = read_json(ROOT / 'traces/support_traces.json', {})
        cohort = {t.get('cartwheel_scenario_id') or attributes(t).get('cartwheel.scenario_id') for t in export.get('traces', [])}
        if not cohort:
            raise ValueError('The HW3 export does not identify a scenario cohort.')
        summaries = []
        page = 1
        while True:
            response = CLIENT.api.trace.list(page=page, limit=100, name='cartwheel.session_message')
            batch = response.data or []
            for t in batch:
                raw = json.loads(t.json(by_alias=True))
                # Summaries can have no input/output, so read metadata directly.
                md = raw.get('metadata') or {}
                attr = md.get('attributes') or {}
                if isinstance(attr, str):
                    attr = json.loads(attr)
                if (md.get('cartwheel.scenario_id') or attr.get('cartwheel.scenario_id')) in cohort:
                    summaries.append(t.id)
            if len(batch) < 100:
                break
            page += 1
        ids = sorted(set(summaries))
        STATUS.update(total=len(ids), loaded=0)
        if not ids:
            raise ValueError('No live Langfuse traces matched the HW3 cohort.')
        loaded = {}
        def fetch(tid):
            return build_trace(json.loads(CLIENT.api.trace.get(tid).json(by_alias=True)))
        with ThreadPoolExecutor(max_workers=6) as pool:
            for job in as_completed([pool.submit(fetch, tid) for tid in ids]):
                trace = job.result()
                loaded[trace['id']] = trace
                STATUS['loaded'] = len(loaded)
        write_json(STATE / 'review_app/live_traces.json', {'fetched_at': now(), 'traces': list(loaded.values())})
        with LOCK:
            TRACES = loaded
            STATUS.update(phase='live', error=None, refreshed_at=now())
    except Exception as exc:
        STATUS.update(phase='error', error=f'Live trace refresh failed ({type(exc).__name__}). Check Langfuse and retry. Existing local notes are preserved.')


def sync_record(record, kind):
    """Stable score IDs make retries and edits idempotent; local history retains revisions."""
    from langfuse.api.resources.score.types.create_score_request import CreateScoreRequest
    score_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'cartwheel-review:{kind}:{record["id"]}'))
    if kind == 'label':
        name, value, dtype = record['mode'], record['label'], 'NUMERIC'
    else:
        name, value, dtype = 'hw4_review_note', ('withdrawn' if record.get('deleted') else record.get('kind', 'observation')), 'CATEGORICAL'
    payload = {k: v for k, v in record.items() if k not in ('sync', 'sync_error')}
    CLIENT.api.score.create(request=CreateScoreRequest(id=score_id, traceId=record['trace_id'], name=name, value=value, dataType=dtype, comment=json.dumps(payload, ensure_ascii=False), metadata={'review_app': 'hw4', 'record_id': record['id'], 'revision': record['revision']}))
    return score_id


def annotations():
    return rows('annotations.json', 'annotations')


def label_records():
    return read_json(STATE / 'review_app/labels.json', [])


def commit_record(record, kind):
    """Durable local-first write plus retriable canonical write; never fake success."""
    filename, key = ('annotations.json', 'annotations') if kind == 'note' else ('review_app/labels.json', 'labels')
    current = rows(filename, key)
    current = [r for r in current if r.get('id') != record['id']] + [record]
    save_rows(filename, key, current)
    history = read_jsonl(STATE / 'review_app/history.jsonl')
    if not any(e['kind'] == kind and e['record']['id'] == record['id'] and e['record']['revision'] == record['revision'] for e in history):
        append_jsonl(STATE / 'review_app/history.jsonl', {'kind': kind, 'record': dict(record)})
    try:
        record['score_id'] = sync_record(record, kind)
        record['sync'] = 'synced'
    except Exception:
        record['sync'] = 'pending'
    save_rows(filename, key, current)
    if kind == 'label':
        label_path = STATE / f'labels/{record["mode"]}.jsonl'
        history = read_jsonl(label_path)
        history = [r for r in history if not (r.get('id') == record['id'] and r.get('revision') == record['revision'])]
        write_jsonl(label_path, history + [record])
    return record


def save_note(body):
    tid = body.get('trace_id')
    if tid not in TRACES:
        raise ValueError('Unknown trace.')
    note_id = body.get('id') or str(uuid.uuid4())
    old = next((r for r in annotations() if r.get('id') == note_id), None)
    if old and (old.get('trace_id') != tid or body.get('revision') != old.get('revision')):
        raise ValueError('This note changed in another window. Reload before editing.')
    kind = body.get('kind', 'observation')
    if kind not in ('observation', 'no_failure_observed'):
        raise ValueError('Invalid annotation kind.')
    note = str(body.get('note', '')).strip()
    if not note or len(note) > 8000:
        raise ValueError('Enter an observation of at most 8,000 characters.')
    block_key = body.get('block_key')
    quote = body.get('quote', '')
    start, end = body.get('start'), body.get('end')
    if kind == 'observation':
        block = next((b for b in TRACES[tid]['blocks'] if b['key'] == block_key), None)
        # Browser offsets use UTF-16 code units, not Python code points.
        if not block or type(start) is not int or type(end) is not int or not 0 <= start < end:
            raise ValueError('Select a passage before saving an observation.')
        text = block['text'].encode('utf-16-le')
        if end * 2 > len(text) or text[start*2:end*2].decode('utf-16-le') != quote:
            raise ValueError('The selected quote no longer matches the recorded trace.')
    record = {'id': note_id, 'trace_id': tid, 'session_id': TRACES[tid]['session_id'], 'kind': kind, 'block_key': block_key, 'start': start, 'end': end, 'quote': quote, 'note': note, 'source': 'human', 'revision': (old or {}).get('revision', 0)+1, 'created_at': (old or {}).get('created_at', now()), 'updated_at': now(), 'deleted': bool(body.get('deleted')), 'spec_sha256': SPEC_HASH, 'sync': 'pending'}
    if body.get('suggestion_id'):
        record['suggestion_id'] = body['suggestion_id']
    return commit_record(record, 'note')


def get_modes():
    data = read_json(STATE / 'patterns.json', {'modes': []})
    modes = data.get('modes', []) if isinstance(data, dict) else data
    if isinstance(modes, dict):
        return [dict(v, name=k) for k, v in modes.items()]
    return modes


def save_label(body):
    tid, mode, label = body.get('trace_id'), body.get('mode'), body.get('label')
    final = {m.get('name') for m in get_modes() if m.get('status') == 'final'}
    if tid not in TRACES or mode not in final or not re.fullmatch(r'[a-z][a-z0-9_]{0,79}', mode or '') or type(label) is not int or label not in (0, 1):
        raise ValueError('Choose a valid final mode and a present/absent judgment.')
    note = str(body.get('note', '')).strip()
    if not note:
        raise ValueError('Record the evidence for this judgment.')
    lid = str(uuid.uuid5(uuid.NAMESPACE_URL, f'hw4:{tid}:{mode}'))
    old = next((r for r in label_records() if r['id'] == lid), None)
    if body.get('revision', 0) != (old or {}).get('revision', 0):
        raise ValueError('This judgment changed. Reload before editing.')
    record = {'id': lid, 'trace_id': tid, 'mode': mode, 'label': label, 'note': note, 'source': 'human', 'revision': (old or {}).get('revision', 0)+1, 'updated_at': now(), 'spec_sha256': SPEC_HASH, 'sync': 'pending'}
    return commit_record(record, 'label')


def payload():
    grouped = {}
    for t in TRACES.values():
        grouped.setdefault(t['session_id'], []).append(t)
    sessions = []
    for sid, group in grouped.items():
        group.sort(key=lambda t: (t['timestamp'] or '', t['id']))
        first = group[0]
        sessions.append({'id': sid, 'trace_ids': [t['id'] for t in group], 'scenario_id': first['scenario_id'], 'role': first['role'], 'timestamp': first['timestamp'], 'preview': next((b['text'] for b in first['blocks'] if b['role'] == 'user'), '')})
    sessions.sort(key=lambda s: s['timestamp'] or '', reverse=True)
    return {'status': dict(STATUS), 'sessions': sessions, 'annotations': annotations(), 'labels': label_records(), 'ai_assessments': read_json(STATE / 'review_app/ai_assessments.json', {}), 'modes': get_modes(), 'suggestions': rows('suggestions.json', 'suggestions'), 'manifest': read_json(STATE / 'sample_manifest.json', None), 'spec': SPEC, 'spec_hash': SPEC_HASH, 'csrf': TOKEN}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def send(self, value, status=200, content_type='application/json'):
        body = json.dumps(value, ensure_ascii=False).encode() if content_type == 'application/json' else value
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        if urlparse('http://' + self.headers.get('Host', '')).hostname not in ('127.0.0.1', 'localhost'):
            return self.send({'error': 'Local access only'}, 403)
        parsed = urlparse(self.path)
        if parsed.path == '/':
            return self.send((HERE/'index.html').read_bytes(), content_type='text/html; charset=utf-8')
        if parsed.path in ('/app.js', '/style.css'):
            return self.send((HERE/parsed.path[1:]).read_bytes(), content_type='text/javascript' if parsed.path.endswith('.js') else 'text/css')
        with LOCK:
            if parsed.path == '/api/state':
                return self.send(payload())
            if parsed.path == '/api/session':
                sid = parse_qs(parsed.query).get('id', [''])[0]
                group = sorted((t for t in TRACES.values() if t['session_id'] == sid), key=lambda t: (t['timestamp'] or '', t['id']))
                return self.send({'traces': [{**t, 'caller_context': caller_context(t)} for t in group]})
        self.send({'error': 'Not found'}, 404)
    def do_POST(self):
        if self.headers.get('X-Review-Token') != TOKEN or self.headers.get('Content-Type') != 'application/json':
            return self.send({'error': 'Reload the local review page before saving.'}, 403)
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length < 100000:
            return self.send({'error': 'Invalid request size'}, 400)
        try:
            body = json.loads(self.rfile.read(length))
            with LOCK:
                if self.path == '/api/note':
                    result = save_note(body)
                elif self.path == '/api/label':
                    result = save_label(body)
                elif self.path == '/api/retry':
                    for kind, records in [('note', annotations()), ('label', label_records())]:
                        for r in records:
                            if r.get('sync') == 'pending':
                                commit_record(r, kind)
                    result = {'ok': True}
                elif self.path == '/api/refresh':
                    if STATUS['phase'] != 'loading':
                        STATUS.update(phase='loading', loaded=0)
                        threading.Thread(target=load_live, daemon=True).start()
                    result = {'ok': True}
                elif self.path == '/api/suggestion':
                    values = rows('suggestions.json', 'suggestions')
                    s = next((s for s in values if s.get('id') == body.get('id')), None)
                    if not s or body.get('decision') not in ('accepted', 'rejected'):
                        raise ValueError('Unknown suggestion or decision.')
                    if body['decision'] == 'accepted':
                        note = dict(body.get('annotation') or {}, suggestion_id=s['id'])
                        save_note(note)
                    s.update(status=body['decision'], reviewed_at=now(), decision_note=body.get('reason', ''))
                    save_rows('suggestions.json', 'suggestions', values)
                    result = {'ok': True}
                else:
                    return self.send({'error': 'Not found'}, 404)
            self.send(result)
        except (ValueError, KeyError, TypeError, UnicodeError) as exc:
            self.send({'error': str(exc)}, 400)
        except Exception:
            self.send({'error': 'Operation failed. Your previously saved work is preserved.'}, 500)


def monitor_annotations():
    previous = None
    while True:
        with LOCK:
            current = annotations()
            snapshot = json.dumps(current, sort_keys=True)
            if previous is not None and snapshot != previous:
                active = [n for n in current if not n.get('deleted')]
                append_jsonl(STATE / 'review_app/annotation-events.jsonl', {
                    'at': now(), 'active_notes': len(active),
                    'traces_touched': len({n.get('trace_id') for n in active}),
                    'latest': max(current, key=lambda n: n.get('updated_at', ''), default=None),
                })
            previous = snapshot
        time.sleep(2)


def main():
    global CLIENT, SPEC, SPEC_HASH
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8021)
    args = parser.parse_args()
    load_dotenv(ROOT / '.env')
    from langfuse import Langfuse
    CLIENT = Langfuse(timeout=30)
    SPEC = (ROOT / 'SPEC.md').read_text()
    SPEC_HASH = hashlib.sha256(SPEC.encode()).hexdigest()
    snapshot = STATE / f'review_app/specs/{SPEC_HASH}.md'
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    if not snapshot.exists():
        snapshot.write_text(SPEC)
    threading.Thread(target=load_live, daemon=True).start()
    threading.Thread(target=monitor_annotations, daemon=True).start()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'Cartwheel review: http://127.0.0.1:{args.port}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
