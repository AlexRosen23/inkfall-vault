"""Tenant isolation and authorization: the zero-leak fixture.

For every identity, every version it may NOT read is attacked through every read path:
direct reads (metadata, raw text, compare), listings, and targeted search/ask queries built from
the forbidden document's own title and text (BM25 and hybrid, which includes the dense path).
A leak is any forbidden canary (doc key, title or a distinctive text fragment) appearing anywhere
in any response. The fixture is deterministic; the expected leak count is exactly zero.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from sqlalchemy import select

from inkfall.access import acl_of, authorized_versions
from inkfall.authz import decide
from inkfall.db import DocumentVersion, make_engine, session_factory
from inkfall.search import chunk_ids_for, search

from .conftest import DENSE

AS_OF = "2026-11-01"


def all_strings(obj) -> str:
    out: list[str] = []

    def walk(o):
        if isinstance(o, str):
            out.append(o)
        elif isinstance(o, dict):
            for k, v in o.items():
                out.append(str(k))
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif o is not None:
            out.append(str(o))

    walk(obj)
    return "\n".join(out)


@pytest.fixture(scope="module")
def matrix(base_db, directory):
    """username -> (readable versions, forbidden versions) from the deterministic policy."""
    S = session_factory(make_engine(base_db))
    with S() as s:
        versions = list(s.scalars(select(DocumentVersion)))
        data = {}
        for name, user in directory.users.items():
            readable, forbidden = [], []
            for v in versions:
                (readable if decide(user, acl_of(v, v.document), directory).allowed else forbidden).append(
                    {"id": v.id, "ref": f"{v.document.doc_key}@{v.version}", "doc_key": v.document.doc_key,
                     "title": v.title, "text": v.text, "chunks": [c.text for c in v.chunks]})
            data[name] = (readable, forbidden)
    return data


def canaries(forbidden: list[dict], readable: list[dict]) -> dict[str, list[str]]:
    """Strings that would only appear in a response if forbidden content leaked."""
    allowed_text = "\n".join(r["text"] + "\n" + r["title"] + "\n" + r["ref"] for r in readable)
    out = {}
    for f in forbidden:
        c = [f["doc_key"]]
        if f["title"] not in allowed_text:
            c.append(f["title"])
        for chunk in f["chunks"]:
            frag = " ".join(chunk.split())[:60]
            if len(frag) >= 30 and frag not in allowed_text:
                c.append(frag)
        out[f["ref"]] = [x for x in c if x not in allowed_text]
    return out


def attack_queries(f: dict) -> list[str]:
    longest = max(f["chunks"], key=len) if f["chunks"] else f["title"]
    return [f["title"], " ".join(longest.split()[:14])]


def test_every_identity_has_forbidden_material(matrix):
    for name, (readable, forbidden) in matrix.items():
        assert readable, name
        assert len(forbidden) >= 25, name  # at least the two other tenants' documents


def test_direct_api_reads_are_denied(client, tokens, matrix):
    denied = 0
    for name, (readable, forbidden) in matrix.items():
        h = tokens[name]
        for f in forbidden:
            for path in (f"/api/documents/{f['id']}", f"/api/documents/{f['id']}/raw"):
                r = client.get(path, headers=h)
                assert r.status_code == 404, (name, f["ref"], path)
                assert f["doc_key"] not in r.text and f["title"] not in r.text
                denied += 1
            if readable:
                r = client.get(f"/api/compare/{readable[0]['id']}/{f['id']}", headers=h)
                assert r.status_code == 404
        # nonexistent ids look exactly like forbidden ones (no existence oracle)
        r = client.get("/api/documents/999999", headers=h)
        assert r.status_code == 404 and r.json()["error"] == "not_found"
    assert denied > 500


def test_listings_contain_only_authorized(client, tokens, matrix):
    for name, (readable, forbidden) in matrix.items():
        r = client.get("/api/documents?include_history=true", headers=tokens[name])
        assert r.status_code == 200
        refs = {d["ref"] for d in r.json()}
        assert refs <= {x["ref"] for x in readable}
        assert not refs & {x["ref"] for x in forbidden}


def test_zero_leaks_through_search_and_ask(client, tokens, matrix):
    leaks: list[tuple] = []
    probes = 0
    methods = ["bm25", "hybrid"] if DENSE else ["bm25"]
    for name, (readable, forbidden) in matrix.items():
        cans = canaries(forbidden, readable)
        for f in forbidden:
            for q in attack_queries(f):
                for m in methods:
                    r = client.post("/api/ask", headers=tokens[name],
                                    json={"question": q[:480], "as_of": AS_OF, "method": m, "include_history": True})
                    assert r.status_code == 200, r.text
                    blob = all_strings(r.json())
                    probes += 1
                    for ref, cs in cans.items():
                        for c in cs:
                            if c in q:
                                continue  # the attacker supplied this text; echoing their query is not a leak
                            if c in blob:
                                leaks.append((name, m, f["ref"], ref, c[:40]))
    report = {"probes": probes, "leaks": len(leaks), "examples": leaks[:5], "methods": methods}
    print("ISOLATION", json.dumps(report))
    assert probes > 1000
    assert leaks == [], report


def test_retrieval_candidates_are_authorized_chunks_only(base_db, directory):
    S = session_factory(make_engine(base_db))
    with S() as s:
        for user in directory.users.values():
            views = authorized_versions(s, user, directory, dt.date(2026, 11, 1), include_history=True)
            allowed = chunk_ids_for(s, views)
            for method in (["bm25", "dense", "hybrid"] if DENSE else ["bm25"]):
                res = search(s, user.tenant, "termination notice liability cap board minutes settlement", views, method)
                assert {h.chunk_id for h in res.hits} <= set(allowed)
                assert {h.version_id for h in res.hits} <= {v.version.id for v in views}


def test_no_endpoint_returns_embeddings(client, tokens):
    h = tokens["omar.haddad"]
    r = client.post("/api/ask", headers=h, json={"question": "credit facility covenants", "as_of": AS_OF})
    assert "embedding" not in r.text
    docs = client.get("/api/documents", headers=h).json()
    r = client.get(f"/api/documents/{docs[0]['version_id']}", headers=h)
    assert "embedding" not in r.text


def test_ethical_wall_blocks_walled_associate(client, tokens):
    h = tokens["theo.brandt"]
    r = client.post("/api/ask", headers=h, json={"question": "Harrow settlement authority and litigation hold",
                                                  "as_of": AS_OF, "include_history": True})
    body = r.json()
    assert body["abstained"]
    assert not any(ref.startswith("LF-HARROW") for ref in body["ranked_refs"])
    r2 = client.post("/api/ask", headers=tokens["marcus.oyelaran"],
                     json={"question": "Harrow settlement authority", "as_of": AS_OF})
    assert any(ref.startswith("LF-HARROW") for ref in r2.json()["ranked_refs"])


def test_positive_control_detector_sees_authorized_content(client, tokens, matrix):
    """The leak detector must fire when content IS legitimately returned, or a broken detector could pass."""
    readable, _ = matrix["marcus.oyelaran"]
    harrow = next(r for r in readable if r["doc_key"] == "LF-HARROW-SETTLEMENT")
    cans = canaries([harrow], [])
    r = client.post("/api/ask", headers=tokens["marcus.oyelaran"],
                    json={"question": attack_queries(harrow)[1], "as_of": AS_OF})
    blob = all_strings(r.json())
    assert any(c in blob for c in cans[harrow["ref"]] if c not in attack_queries(harrow)[1])
