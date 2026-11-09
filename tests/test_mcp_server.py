"""MCP server: in-process client (official SDK) against the real tools and the seeded test database.

Proves: identity comes from server launch only; forbidden versions return exactly the same not_found as missing ones
for every identity; searches built from forbidden documents' own text return 0 forbidden content.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from mcp import Client
from sqlalchemy import select

from inkfall.access import acl_of
from inkfall.authz import decide
from inkfall.db import DocumentVersion, make_engine, session_factory
from inkfall.mcp_server import NOT_FOUND, build_server

IDENTITY_WORDS = {"user", "username", "tenant", "role", "roles", "clearance", "groups", "identity", "as_user"}


def run(coro):
    return asyncio.run(coro)


def text_of(result) -> str:
    return "\n".join(getattr(c, "text", "") for c in result.content)


@pytest.fixture(scope="module")
def versions(base_db, directory):
    S = session_factory(make_engine(base_db))
    with S() as s:
        out = []
        for v in s.scalars(select(DocumentVersion)):
            out.append({"id": v.id, "tenant": v.tenant_id, "key": v.document.doc_key, "title": v.title,
                        "chunks": [c.text for c in v.chunks],
                        "readers": {u for u in directory.users
                                    if decide(directory.users[u], acl_of(v, v.document), directory).allowed}})
    return out


def test_tools_take_no_identity_arguments(base_db, directory):
    async def go():
        async with Client(build_server("june.park", base_db, directory)) as c:
            return (await c.list_tools()).tools

    tools = run(go())
    assert {t.name for t in tools} == {"search", "fetch_document", "cite"}
    for t in tools:
        props = set((t.input_schema or {}).get("properties", {}))
        assert not props & IDENTITY_WORDS, (t.name, props)
        assert t.annotations and t.annotations.read_only_hint is True


def test_identity_arguments_cannot_escalate(base_db, directory, versions):
    """june.park (Corvane ops) tries to pass identity fields; the call fails or is ignored, never escalates."""
    secret = next(v for v in versions if v["key"] == "CV-CREDIT-FACILITY" and "june.park" not in v["readers"])

    async def go():
        async with Client(build_server("june.park", base_db, directory)) as c:
            a = await c.call_tool("fetch_document", {"version_id": secret["id"], "user": "omar.haddad",
                                                     "role": "admin"})
            b = await c.call_tool("search", {"query": secret["title"], "tenant": "corvane", "username": "omar.haddad"})
            return a, b

    a, b = run(go())
    assert a.is_error and secret["key"] not in text_of(a)
    assert b.is_error or secret["key"] not in text_of(b)


def test_forbidden_equals_missing_and_zero_forbidden_content(base_db, directory, versions):
    """For every identity: every unreadable version -> the same not_found as a nonexistent id, through both
    fetch_document and cite; and a search built from that version's own title/longest chunk leaks nothing."""
    missing_id = max(v["id"] for v in versions) + 1000
    stats = {"fetch": 0, "cite": 0, "search": 0, "leaks": 0}

    async def per_user(u: str):
        readable_text = "\n".join(t for v in versions if u in v["readers"] for t in [v["title"], *v["chunks"]])
        async with Client(build_server(u, base_db, directory)) as c:
            miss_f = await c.call_tool("fetch_document", {"version_id": missing_id})
            miss_c = await c.call_tool("cite", {"version_id": missing_id, "char_start": 0, "char_end": 10})
            assert miss_f.is_error and text_of(miss_f).endswith(NOT_FOUND)
            assert miss_c.is_error and text_of(miss_c).endswith(NOT_FOUND)
            for v in versions:
                if u in v["readers"]:
                    continue
                f = await c.call_tool("fetch_document", {"version_id": v["id"]})
                ct = await c.call_tool("cite", {"version_id": v["id"], "char_start": 0, "char_end": 10})
                stats["fetch"] += 1
                stats["cite"] += 1
                assert (f.is_error, text_of(f)) == (miss_f.is_error, text_of(miss_f)), (u, v["key"])
                assert (ct.is_error, text_of(ct)) == (miss_c.is_error, text_of(miss_c)), (u, v["key"])
                canaries = [v["key"]] + [" ".join(ch.split())[:60] for ch in v["chunks"] if len(ch) > 40]
                canaries = [x for x in canaries if x not in readable_text]
                longest = max(v["chunks"], key=len) if v["chunks"] else v["title"]
                q = " ".join(longest.split()[:14])[:480]
                s = await c.call_tool("search", {"query": q, "as_of": "2026-11-01"})
                stats["search"] += 1
                blob = text_of(s) + json.dumps(s.structured_content or {})
                hit = [x for x in canaries if x not in q and x in blob]
                if hit:
                    stats["leaks"] += 1
                    pytest.fail(f"{u} saw forbidden {v['key']}: {hit[0][:40]}")

    for u in directory.users:
        run(per_user(u))
    print("mcp isolation:", stats)
    assert stats["fetch"] > 400 and stats["leaks"] == 0


def test_authorized_read_and_cite_roundtrip(base_db, directory, versions):
    mine = next(v for v in versions if "dana.whitcombe" in v["readers"] and v["key"] == "CV-SLA-ORION")

    async def go():
        async with Client(build_server("dana.whitcombe", base_db, directory)) as c:
            doc = await c.call_tool("fetch_document", {"version_id": mine["id"]})
            body = doc.structured_content["text"]
            i = body.index("99.9%")
            good = await c.call_tool("cite", {"version_id": mine["id"], "char_start": i, "char_end": i + 5,
                                              "quote": "99.9%"})
            bad = await c.call_tool("cite", {"version_id": mine["id"], "char_start": i, "char_end": i + 5,
                                             "quote": "97.3%"})
            s = await c.call_tool("search", {"query": "What availability does the Orion SLA commit to?",
                                             "as_of": "2026-11-01"})
            return doc, good, bad, s

    doc, good, bad, s = run(go())
    assert not doc.is_error and doc.structured_content["untrusted_content"] is True
    assert good.structured_content["valid"] is True and good.structured_content["quote"] == "99.9%"
    assert bad.structured_content["valid"] is False
    sc = s.structured_content
    assert sc["answer"] and all(c["ref"].startswith("CV-") for a in sc["answer"] for c in a["citations"])


def test_unknown_identity_refuses_to_start(base_db, directory):
    with pytest.raises(SystemExit):
        build_server("mallory", base_db, directory)


def test_real_stdio_subprocess(base_db):
    """Launch `python -m inkfall.mcp_server` as a subprocess and talk MCP over its stdin/stdout."""
    import os
    import sys

    from mcp.client.stdio import StdioServerParameters

    params = StdioServerParameters(command=sys.executable, args=["-m", "inkfall.mcp_server"],
                                   env={**os.environ, "INKFALL_MCP_USER": "theo.brandt", "INKFALL_DB": str(base_db)})

    async def go():
        async with Client(params) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            s = await c.call_tool("search", {"query": "Harrow settlement authority", "as_of": "2026-11-01"})
            return names, s

    names, s = run(go())
    assert names == {"search", "fetch_document", "cite"}
    assert "LF-HARROW" not in text_of(s) + json.dumps(s.structured_content or {})  # theo is walled off Harrow
