"""Claude Citations provider, tested offline.

No API key is used. The responses come from fixtures built from the documented response schema
(tests/fixtures/claude_citations/*.json, each labelled as such). A fake client records the exact request the code
builds and returns the fixture, so these tests check (1) the request shape, (2) that returned block indices map
back onto stored character offsets, and (3) that every malformed or hostile citation is rejected.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path

import pytest

from inkfall import claude_citations as cc
from inkfall import service
from inkfall.db import make_engine, session_factory

FIX = Path(__file__).parent / "fixtures" / "claude_citations"
AS_OF = dt.date(2026, 11, 1)


def load(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text())


def resolve(response: dict, request: dict) -> dict:
    """Fill `_find` citations from the documents in the request the code actually built."""
    docs = [b for b in request["messages"][0]["content"] if b["type"] == "document"]
    out = copy.deepcopy(response)
    for blk in out["content"]:
        for c in blk.get("citations") or []:
            find = c.pop("_find", None)
            if find is None:
                continue
            for d_i, d in enumerate(docs):
                texts = [b["text"] for b in d["source"]["content"]]
                hit = next((i for i, t in enumerate(texts) if find in t), None)
                if hit is not None:
                    fill = {"document_index": d_i, "document_title": d["title"], "start_block_index": hit,
                            "end_block_index": hit + 1, "cited_text": texts[hit]}
                    for k, v in fill.items():
                        if c.get(k) is None:
                            c[k] = v
                    break
            else:
                raise AssertionError(f"fixture text not in any authorized document: {find!r}")
    return out


class FakeResponse:
    def __init__(self, d):
        self.d = d

    def to_dict(self):
        return self.d


class FakeClient:
    """Stands in for anthropic.Anthropic(); records requests, answers with a fixture."""

    def __init__(self, fixture: dict):
        self.fixture, self.requests = fixture, []
        self.messages = self
        self.beta = type("Beta", (), {"messages": self})()

    def create(self, **req):
        self.requests.append(req)
        return FakeResponse(resolve(self.fixture["response"], req))


@pytest.fixture()
def ask(base_db, directory, monkeypatch):
    S = session_factory(make_engine(base_db))

    def _ask(name: str, user: str | None = None, question: str | None = None):
        fx = load(name)
        client = FakeClient(fx)
        monkeypatch.setattr(service, "get_claude", lambda: cc.ClaudeCitations(client=client))
        with S() as s:
            res = service.run_query(s, directory.users[user or fx["user"]], directory, question or fx["question"],
                                    AS_OF, "hybrid", generate_mode="claude")
            s.rollback()
        return res, client

    return _ask


def test_fixtures_are_labelled_as_schema_built_not_recorded():
    for f in FIX.glob("*.json"):
        assert "NOT a recorded live API response" in json.loads(f.read_text())["_fixture"], f.name


def test_request_uses_custom_content_documents_with_exact_stored_spans(ask, base_db, directory):
    res, client = ask("grounded")
    req = client.requests[0]
    assert req["model"] == "claude-opus-5-5"
    assert "format" not in req.get("output_config", {}), "citations cannot be combined with structured outputs"
    docs = [b for b in req["messages"][0]["content"] if b["type"] == "document"]
    assert len(docs) == len(res["sources"]) > 0
    texts = {p["pid"]: p for p in res["sources"]}
    for d, src in zip(docs, res["sources"], strict=True):
        assert d["source"]["type"] == "content" and d["citations"] == {"enabled": True}
        assert d["title"].startswith(src["pid"])
        assert src["title"] in d["title"], "the document title names the subject a mid-document passage may not"
        for blk in d["source"]["content"]:
            assert blk["type"] == "text" and blk["text"].strip() == blk["text"] and blk["text"]
            assert blk["text"] in texts[src["pid"]]["text"]  # every block is a slice of the authorized passage
    assert req["messages"][0]["content"][-1] == {"type": "text", "text": f"Question: {res['question']}"}


def test_citations_map_back_to_stored_offsets_and_reverify(ask, client, tokens):
    res, _ = ask("grounded")
    assert res["mode"] == "generative" and res["generation"]["status"] == "ok", res["generation"]
    assert res["generation"]["provider"] == "claude" and "Anthropic API" in res["generation"]["cost_note"]
    assert len(res["answer"]) == 2
    for s in res["answer"]:
        assert s["support"] == "supported", s
        for c in s["citations"]:
            # independent check through the public API: offsets + quote are valid for this user
            r = client.post("/api/verify-citation", headers=tokens["dana.whitcombe"], json={
                "text": s["text"], "version_id": c["version_id"], "char_start": c["char_start"],
                "char_end": c["char_end"], "quote": c["quote"]}).json()
            assert r["valid"], r
    assert "99.9%" in res["answer"][0]["citations"][0]["quote"]
    assert "five percent (5%)" in res["answer"][1]["citations"][0]["quote"]


def test_invented_number_and_uncited_claim_are_labelled_unsupported(ask):
    res, _ = ask("uncited_and_invented")
    assert res["mode"] == "generative" and res["status"] == "partially_unsupported"
    first, second = res["answer"]
    assert first["support"] == "unsupported" and any("97.3" in n for n in first["notes"])
    assert second["support"] == "unsupported" and second["notes"] == ["no citation"]


@pytest.mark.parametrize("name,reason", [
    ("tampered_cited_text", "cited_text does not match"),
    ("bad_document_index", "not in the authorized pack"),
    ("bad_block_range", "outside document"),
    ("refusal", "model refused"),
])
def test_hostile_or_broken_outputs_are_rejected(ask, name, reason):
    res, _ = ask(name)
    assert res["mode"] == "extractive" and res["generation"]["status"] == "rejected"
    assert reason in res["generation"]["rejected_reason"]
    assert all("2.75" not in a["text"] for a in res["answer"])


def test_model_abstention_keeps_extractive_evidence(ask):
    res, _ = ask("abstain")
    assert res["generation"]["status"] == "ok" and res["generation"]["model_abstained"] is True
    assert res["mode"] == "extractive"


def test_forbidden_documents_never_reach_the_request(ask):
    """theo.brandt is walled off the Harrow matter; nothing from it may be sent to the API."""
    res, client = ask("abstain", user="theo.brandt",
                      question="Summarize the Pemberton judgment and the Harrow settlement authority.")
    blob = json.dumps(client.requests)
    assert "LF-HARROW" not in blob and "Harrow settlement" not in blob.replace("Question: Summarize the Pemberton "
                                                                            "judgment and the Harrow settlement", "")


def test_unavailable_without_api_key(base_db, directory, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    info = cc.info()
    assert info.available is False and info.detail == "ANTHROPIC_API_KEY not set"
    S = session_factory(make_engine(base_db))
    with S() as s:
        res = service.run_query(s, directory.users["dana.whitcombe"], directory,
                                "What availability does the Orion SLA commit to?", AS_OF, "hybrid", generate_mode="claude")
    assert res["mode"] == "extractive" and "ANTHROPIC_API_KEY not set" in res["generation"]["status"]


def test_never_selected_automatically(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-placeholder-not-a-key")
    from inkfall import providers
    assert all(p.name != "claude" for p in providers.detect())


def test_api_accepts_claude_mode_and_degrades(client, tokens, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/api/ask", headers=tokens["dana.whitcombe"],
                    json={"question": "What availability does the Orion SLA commit to?", "as_of": "2026-11-01",
                          "generate": "claude"})
    assert r.status_code == 200 and r.json()["mode"] == "extractive"
    backends = client.get("/api/system", headers=tokens["dana.whitcombe"]).json()["generation_backends"]
    claude = next(b for b in backends if b["name"] == "claude")
    assert claude["available"] is False
