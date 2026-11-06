from unittest.mock import Mock
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from observability import workshop


@pytest.mark.parametrize('endpoint', ['https://example.com/v1/', 'http://user:secret@localhost/v1/', 'http://localhost/v1/?key=secret'])
def test_rejects_nonlocal_or_credentialed_endpoint(endpoint):
    with pytest.raises(ValueError):
        workshop.setup_workshop(1, endpoint=endpoint)


def test_mirror_preserves_provider_and_existing_destination(monkeypatch):
    provider = TracerProvider()
    existing = InMemorySpanExporter()
    mirror = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(existing))
    monkeypatch.setattr(workshop.trace, 'get_tracer_provider', lambda: provider)
    replace = Mock(side_effect=AssertionError('must not replace existing provider'))
    monkeypatch.setattr(workshop.trace, 'set_tracer_provider', replace)
    instrument = Mock()
    monkeypatch.setattr('observability.instrument.instrument_genai', instrument)
    factory = Mock(return_value=mirror)
    monkeypatch.setattr(workshop, 'WorkshopSpanExporter', factory)
    client = workshop.setup_workshop(1)
    workshop.setup_workshop(1)  # no duplicate exporter
    with provider.get_tracer('test').start_as_current_span('get_policy') as span:
        span.set_attribute('gen_ai.tool.call.arguments', '{"id":"returns"}')
        span.set_attribute('gen_ai.tool.call.result', '{"days":30}')
    assert client.flush()
    assert len(existing.get_finished_spans()) == len(mirror.get_finished_spans()) == 1
    assert existing.get_finished_spans()[0].context == mirror.get_finished_spans()[0].context
    assert mirror.get_finished_spans()[0].attributes['gen_ai.tool.call.result'] == '{"days":30}'
    factory.assert_called_once()
    assert factory.call_args.kwargs['endpoint'] == 'http://127.0.0.1:5899/v1/traces'
    assert factory.call_args.kwargs['session'].trust_env is False
    replace.assert_not_called()
    provider.shutdown()


def test_mirror_failure_does_not_stop_existing_destination(monkeypatch):
    class FailedExporter(SpanExporter):
        def export(self, spans):
            return SpanExportResult.FAILURE
    provider = TracerProvider()
    existing = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(existing))
    monkeypatch.setattr(workshop.trace, 'get_tracer_provider', lambda: provider)
    monkeypatch.setattr('observability.instrument.instrument_genai', lambda p: None)
    monkeypatch.setattr(workshop, 'WorkshopSpanExporter', lambda **kw: FailedExporter())
    client = workshop.setup_workshop(1)
    with provider.get_tracer('test').start_as_current_span('tool'):
        pass
    client.flush()
    assert len(existing.get_finished_spans()) == 1
    provider.shutdown()


def test_tool_compatibility_does_not_mutate_langfuse_span():
    from opentelemetry.sdk.trace import ReadableSpan
    original = ReadableSpan(name='get_policy', attributes={
        'traceloop.span.kind': 'tool', 'gen_ai.tool.name': 'get_policy',
        'gen_ai.tool.call.arguments': '{"policy_id":"cw-returns"}',
        'gen_ai.tool.call.result': '{"ok":true}',
    }, start_time=100, end_time=200)
    mirrored = workshop.workshop_span(original)
    assert mirrored.attributes['traceloop.entity.input'] == original.attributes['gen_ai.tool.call.arguments']
    assert mirrored.attributes['traceloop.entity.output'] == original.attributes['gen_ai.tool.call.result']
    assert 'traceloop.entity.output' not in original.attributes
    assert mirrored.start_time == 100 and mirrored.end_time == 200
