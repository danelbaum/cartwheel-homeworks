"""Opt-in local OTLP mirror; Langfuse retains ownership of its provider."""
from urllib.parse import urlparse

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_processors = {}


def workshop_span(span):
    """Add Workshop's supported legacy tool aliases to a copy only.

    Workshop 0.1.24's traceloopToolAdapter reads traceloop.entity.* rather
    than the newer gen_ai.tool.call.* emitted by the course instrumentor.
    Identity, timing, results and hierarchy remain the original evidence.
    """
    attributes = dict(span.attributes or {})
    if attributes.get('traceloop.span.kind') != 'tool':
        return span
    for source, target in [('gen_ai.tool.call.arguments', 'traceloop.entity.input'),
                           ('gen_ai.tool.call.result', 'traceloop.entity.output'),
                           ('gen_ai.tool.name', 'traceloop.entity.name')]:
        if source in attributes:
            attributes.setdefault(target, attributes[source])
    return ReadableSpan(
        name=span.name, context=span.context, parent=span.parent,
        resource=span.resource, attributes=attributes, events=span.events,
        links=span.links, kind=span.kind, status=span.status,
        start_time=span.start_time, end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class WorkshopSpanExporter(OTLPSpanExporter):
    def export(self, spans):
        return super().export([workshop_span(span) for span in spans])



class WorkshopTracing:
    def __init__(self, provider):
        self.provider = provider

    def flush(self):
        # Flush both destinations before the CLI waits for another message.
        return self.provider.force_flush(timeout_millis=10000)


def setup_workshop(user_id: int, *, endpoint: str = 'http://127.0.0.1:5899/v1/'):
    """Attach the standard OTLP exporter to the existing provider, once.

    Workshop supports OTLP/HTTP protobuf at /v1/traces. No Raindrop cloud
    client, auto-instrumentation, or second provider is initialized. In
    Workshop-only mode, create the sole provider and use the same course
    Agents instrumentation. Tool content is enabled per CLI invocation.
    """
    parsed = urlparse(endpoint)
    if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost'}
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('Workshop endpoint must be local HTTP.')
    provider = trace.get_tracer_provider()
    if isinstance(provider, trace.ProxyTracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    if not isinstance(provider, TracerProvider):
        raise RuntimeError('Workshop requires an OpenTelemetry SDK provider; existing provider was not changed.')
    from observability.instrument import instrument_genai
    instrument_genai(provider)
    url = endpoint.rstrip('/') + '/traces'
    key = (provider, url)
    if key not in _processors:
        # Explicit empty headers/session prevent inherited cloud credentials
        # and proxy settings from being forwarded to this local destination.
        import requests
        from opentelemetry.exporter.otlp.proto.http import Compression
        session = requests.Session()
        session.trust_env = False
        exporter = WorkshopSpanExporter(endpoint=url, headers={"Content-Type": "application/x-protobuf"}, session=session,
                                    timeout=3, compression=Compression.NoCompression)
        processor = BatchSpanProcessor(exporter, schedule_delay_millis=500)
        provider.add_span_processor(processor)
        _processors[key] = processor
    return WorkshopTracing(provider)
