"""OpenTelemetry spans for retrieval and generation, following the GenAI semantic conventions.

The GenAI conventions (github.com/open-telemetry/semantic-conventions-genai) are at status **Development**
(checked 2026-11-09): attribute names may still change. Spans used here:

* `retrieval` (kind INTERNAL): gen_ai.operation.name=retrieval, gen_ai.retrieval.top_k, plus inkfall.* counts.
* `chat {model}` (kind CLIENT): gen_ai.operation.name=chat, gen_ai.provider.name, gen_ai.request.model,
  gen_ai.response.model, gen_ai.request.max_tokens, gen_ai.usage.input_tokens / output_tokens when the provider
  reports them, error.type on failure, server.address / server.port, plus inkfall.validation.* results.

Off by default. INKFALL_OTEL=console prints spans to stdout; INKFALL_OTEL=otlp exports to
OTEL_EXPORTER_OTLP_ENDPOINT (needs the `otlp` extra: `uv sync --extra otlp`).

Privacy: this is a permission-aware system, so spans never carry the question text, document text, prompts,
model output or document ids (the conventions mark query text, retrieved documents and message content as opt-in;
we do not opt in). Only counts, method names, model names, token counts, latencies and validation outcomes.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from urllib.parse import urlparse

from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

_TRACER_NAME = "inkfall"
_configured = False


def configure(mode: str | None = None, exporter=None) -> str:
    """Install a tracer provider. `exporter` (an SDK SpanExporter) is for tests. Returns the active mode."""
    global _configured
    mode = (mode if mode is not None else os.environ.get("INKFALL_OTEL", "")).strip().lower()
    if exporter is None and mode not in ("console", "otlp"):
        return "off"
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": "inkfall-vault"}))
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        mode = "test"
    elif mode == "console":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(out=sys.stdout)))
    else:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        except ImportError:
            print("INKFALL_OTEL=otlp but the exporter is not installed (uv sync --extra otlp); tracing off",
                  file=sys.stderr)
            return "off"
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    if not _configured:
        trace.set_tracer_provider(provider)
        _configured = True
    return mode


def tracer(provider=None):
    return (provider or trace.get_tracer_provider()).get_tracer(_TRACER_NAME)


_tracer_provider_override = None


def _t():
    return tracer(_tracer_provider_override)


def set_test_provider(provider) -> None:
    """Route spans to a specific TracerProvider (tests); None restores the global one."""
    global _tracer_provider_override
    _tracer_provider_override = provider


@contextmanager
def retrieval_span(method: str, top_k: int, authorized_versions: int):
    with _t().start_as_current_span("retrieval", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("gen_ai.operation.name", "retrieval")
        span.set_attribute("gen_ai.retrieval.top_k", top_k)
        span.set_attribute("inkfall.retrieval.method", method)
        span.set_attribute("inkfall.authorized_versions", authorized_versions)
        yield span


PROVIDER_NAMES = {"claude": "anthropic", "ollama": "ollama", "lmstudio": "lmstudio"}


@contextmanager
def chat_span(provider_name: str, model: str, max_tokens: int, base_url: str | None):
    with _t().start_as_current_span(f"chat {model}", kind=SpanKind.CLIENT) as span:
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.provider.name", PROVIDER_NAMES.get(provider_name, provider_name))
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("gen_ai.request.max_tokens", max_tokens)
        if base_url:
            u = urlparse(base_url)
            if u.hostname:
                span.set_attribute("server.address", u.hostname)
                span.set_attribute("server.port", u.port or (443 if u.scheme == "https" else 80))
        yield span


def record_generation(span, g) -> None:
    """Attach the outcome of a GenerationResult to a chat span (no content, only counts/outcomes)."""
    usage = g.usage_reported or {}
    inp = usage.get("input_tokens", usage.get("prompt_tokens"))
    out = usage.get("output_tokens", usage.get("completion_tokens"))
    if inp is not None:
        span.set_attribute("gen_ai.usage.input_tokens", int(inp))
    if out is not None:
        span.set_attribute("gen_ai.usage.output_tokens", int(out))
    if g.model:
        span.set_attribute("gen_ai.response.model", g.model)
    span.set_attribute("inkfall.validation.status", "ok" if g.ok else "rejected")
    span.set_attribute("inkfall.validation.sentences", len(g.sentences))
    span.set_attribute("inkfall.validation.unsupported",
                       sum(1 for s in g.sentences if s.support == "unsupported"))
    span.set_attribute("inkfall.model_abstained", bool(g.abstained))
    if not g.ok:
        # The reason text can echo model output (e.g. an invented doc ref), so only a category is recorded.
        kind = "provider_error" if (g.rejected_reason or "").startswith("provider error") else "output_rejected"
        span.set_attribute("error.type", kind)
        span.set_status(Status(StatusCode.ERROR, kind))
