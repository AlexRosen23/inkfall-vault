"""OpenTelemetry GenAI spans (development-status conventions): names, attributes, and no content in spans."""

from __future__ import annotations

import datetime as dt
import json

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from inkfall import service, telemetry
from inkfall.db import make_engine, session_factory
from inkfall.providers import Provider

QUESTION = "What availability does the Orion SLA commit to?"


class Fake(Provider):
    name, model, base_url = "ollama", "gpt-oss:20b", "http://127.0.0.1:11434/v1"

    def complete(self, system, user, max_tokens=700):
        import re
        pid = re.findall(r'<passage id="(P\d+)"', user)[0]
        return (json.dumps({"sentences": [{"text": "Orion commits to monthly availability of 99.9%.", "cites": [pid]}]}),
                {"model": self.model, "provider": self.name, "latency_ms": 5.0,
                 "usage": {"prompt_tokens": 700, "completion_tokens": 40, "total_tokens": 740}})


@pytest.fixture()
def spans(monkeypatch):
    exp = InMemorySpanExporter()
    tp = TracerProvider()
    tp.add_span_processor(SimpleSpanProcessor(exp))
    telemetry.set_test_provider(tp)
    yield exp
    telemetry.set_test_provider(None)


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("INKFALL_OTEL", raising=False)
    assert telemetry.configure() == "off"


def test_retrieval_and_chat_spans_follow_genai_conventions(spans, base_db, directory, monkeypatch):
    monkeypatch.setattr(service, "get_provider", lambda preferred=None: Fake())
    S = session_factory(make_engine(base_db))
    with S() as s:
        res = service.run_query(s, directory.users["dana.whitcombe"], directory, QUESTION, dt.date(2026, 11, 1),
                                "hybrid", generate_mode="generative")
    assert res["mode"] == "generative"
    got = {sp.name: sp for sp in spans.get_finished_spans()}
    r, c = got["retrieval"], got["chat gpt-oss:20b"]
    assert r.attributes["gen_ai.operation.name"] == "retrieval" and r.attributes["gen_ai.retrieval.top_k"] == 50
    assert r.attributes["inkfall.retrieval.hits"] > 0
    a = c.attributes
    assert a["gen_ai.operation.name"] == "chat" and a["gen_ai.provider.name"] == "ollama"
    assert a["gen_ai.request.model"] == "gpt-oss:20b" and a["gen_ai.usage.input_tokens"] == 700
    assert a["gen_ai.usage.output_tokens"] == 40 and a["server.address"] == "127.0.0.1" and a["server.port"] == 11434
    assert a["inkfall.validation.status"] == "ok"
    # privacy: no question text, document text, refs or model output in any span attribute
    blob = json.dumps([dict(sp.attributes) for sp in spans.get_finished_spans()])
    for forbidden in (QUESTION, "Orion", "99.9", "CV-SLA"):
        assert forbidden not in blob


def test_rejected_output_marks_error_without_echoing_model_text(spans, base_db, directory, monkeypatch):
    class Spoof(Fake):
        def complete(self, system, user, max_tokens=700):
            return json.dumps({"sentences": [{"text": "x", "cites": ["CV-CREDIT-FACILITY@1"]}]}), {"model": self.model}

    monkeypatch.setattr(service, "get_provider", lambda preferred=None: Spoof())
    S = session_factory(make_engine(base_db))
    with S() as s:
        service.run_query(s, directory.users["dana.whitcombe"], directory, QUESTION, dt.date(2026, 11, 1),
                          "hybrid", generate_mode="generative")
    c = next(sp for sp in spans.get_finished_spans() if sp.name.startswith("chat"))
    assert c.attributes["error.type"] == "output_rejected" and c.status.status_code.name == "ERROR"
    assert "CV-CREDIT" not in json.dumps(dict(c.attributes)) + (c.status.description or "")
