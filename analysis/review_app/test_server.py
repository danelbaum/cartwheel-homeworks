import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from analysis.review_app import server as s


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(s, 'STATE', tmp_path)
    monkeypatch.setattr(s, 'SPEC_HASH', 'test-spec')
    raw = json.loads((s.ROOT / 'traces/support_traces.json').read_text())['traces'][0]
    trace = s.build_trace(raw)
    monkeypatch.setattr(s, 'TRACES', {trace['id']: trace})
    writes = []
    def create(*, request):
        writes.append(request)
    monkeypatch.setattr(s, 'CLIENT', SimpleNamespace(api=SimpleNamespace(score=SimpleNamespace(create=create))))
    return trace, writes


def note(trace):
    b = next(b for b in trace['blocks'] if b['role'] == 'assistant')
    return dict(trace_id=trace['id'], block_key=b['key'], start=0, end=10, quote=b['text'][:10], note='Human observation')


def test_actual_cohort_preserves_trace_ids_and_session_groups():
    raw = json.loads((s.ROOT / 'traces/support_traces.json').read_text())['traces']
    traces = [s.build_trace(r) for r in raw]
    assert len(traces) == len({t['id'] for t in traces}) == 259
    assert len({t['session_id'] for t in traces}) == 250
    for t in traces:
        assert t['blocks'][0]['role'] == 'user'
        assert any(b['role'] == 'assistant' for b in t['blocks'])
        for tool in t['tools']:
            assert any(b.get('tool_id') == tool['id'] for b in t['blocks'])


def test_anchored_note_and_categorical_sync(workspace):
    trace, writes = workspace
    record = s.save_note(note(trace))
    assert record['sync'] == 'synced'
    assert writes[0].trace_id == trace['id']
    assert writes[0].data_type == 'CATEGORICAL'
    assert writes[0].name == 'hw4_review_note'
    assert s.annotations()[0]['quote'] == record['quote']


def test_rejects_wrong_quote_and_unknown_trace(workspace):
    trace, writes = workspace
    with pytest.raises(ValueError):
        s.save_note(dict(note(trace), quote='wrong'))
    with pytest.raises(ValueError):
        s.save_note(dict(note(trace), trace_id='wrong'))
    assert not writes
    assert not s.annotations()


def test_preserves_other_records_and_revision_history(workspace):
    trace, writes = workspace
    s.write_json(s.STATE / 'annotations.json', {'annotations': [{'id': 'prior', 'note': 'Existing work'}], 'version': 'original'})
    first = s.save_note(note(trace))
    second = s.save_note(dict(first, note='Revised observation'))
    assert second['revision'] == 2
    assert s.read_json(s.STATE / 'annotations.json')['version'] == 'original'
    assert s.annotations()[0]['id'] == 'prior'
    assert len(s.read_jsonl(s.STATE / 'review_app/history.jsonl')) == 2
    with pytest.raises(ValueError):
        s.save_note(dict(first, note='Stale edit'))


def test_sync_failure_retains_local_note(workspace, monkeypatch):
    trace, _ = workspace
    def fail(*args):
        raise RuntimeError('offline')
    monkeypatch.setattr(s, 'sync_record', fail)
    result = s.save_note(note(trace))
    assert result['sync'] == 'pending'
    assert s.annotations()[0]['note'] == 'Human observation'


def test_delete_is_auditable_and_synced(workspace):
    trace, writes = workspace
    first = s.save_note(note(trace))
    second = s.save_note(dict(first, deleted=True))
    assert second['deleted']
    assert writes[-1].value == 'withdrawn'
    assert len(s.read_jsonl(s.STATE / 'review_app/history.jsonl')) == 2


def test_no_failure_is_not_a_binary_mode_label(workspace):
    trace, writes = workspace
    s.save_note(dict(trace_id=trace['id'], kind='no_failure_observed', note='no failure observed'))
    assert writes[0].value == 'no_failure_observed'
    assert not list((s.STATE / 'labels').glob('*'))


def test_utf16_quote_offsets(workspace):
    trace, _ = workspace
    trace['blocks'][0]['text'] = 'Hi 😀 there'
    result = s.save_note(dict(trace_id=trace['id'], block_key='user', start=3, end=5, quote='😀', note='Emoji selection'))
    assert result['quote'] == '😀'


def test_final_labels_only_and_binary_convention(workspace):
    trace, writes = workspace
    body = dict(trace_id=trace['id'], mode='example_mode', label=1, note='Reviewed evidence')
    with pytest.raises(ValueError):
        s.save_label(body)
    s.write_json(s.STATE / 'patterns.json', {'modes':[{'name':'example_mode','status':'final'}]})
    result = s.save_label(body)
    assert writes[-1].value == 1
    assert writes[-1].data_type == 'NUMERIC'
    assert (s.STATE / 'labels/example_mode.jsonl').exists()
    with pytest.raises(ValueError):
        s.save_label(body)
    changed = s.save_label(dict(body, revision=result['revision'], label=0))
    assert changed['label'] == 0


def test_retry_and_edits_use_one_canonical_score(workspace):
    trace, writes = workspace
    first = s.save_note(note(trace))
    second = s.save_note(dict(first, note='Updated'))
    assert writes[0].id == writes[1].id
    count = len(s.read_jsonl(s.STATE / 'review_app/history.jsonl'))
    s.commit_record(second, 'note')
    assert writes[-1].id == writes[0].id
    assert len(s.read_jsonl(s.STATE / 'review_app/history.jsonl')) == count


def test_label_retry_has_no_duplicate_local_revision(workspace):
    trace, _ = workspace
    s.write_json(s.STATE / 'patterns.json', {'modes':[{'name':'example_mode','status':'final'}]})
    record = s.save_label(dict(trace_id=trace['id'], mode='example_mode', label=0, note='Evidence'))
    s.commit_record(record, 'label')
    records = s.read_jsonl(s.STATE / 'labels/example_mode.jsonl')
    assert len(records) == 1
    assert records[0]['sync'] == 'synced'
