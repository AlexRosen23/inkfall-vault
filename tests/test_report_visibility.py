"""Side channels around the read path: saved evaluation reports, the audit view and records management.

Each of these is a way to learn about a document without opening it, so each must follow the same authorized view
as search and reads: a role (admin, reviewer) grants functions, never content, and an ethical wall holds here too.
"""

from __future__ import annotations

import base64
import json
import re

from inkfall.config import EVAL_DIR

from .conftest import login

AS_OF = "2026-11-01"
DOC_REF = re.compile(r"\b(?:LF|CV|PM)-[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*(?:@\d+)?\b")


def readable(c, h) -> tuple[set[str], set[str]]:
    docs = c.get("/api/documents?include_history=true", headers=h).json()
    return {d["ref"] for d in docs}, {d["doc_key"] for d in docs}


def strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, list):
        return [x for v in obj for x in strings(v)]
    if isinstance(obj, dict):
        return [x for v in obj.values() for x in strings(v)]
    return []


def unreadable_refs_in(text: str, refs: set[str], keys: set[str]) -> set[str]:
    return {m for m in DOC_REF.findall(text) if m not in refs and m not in keys}


def test_eval_report_never_shows_content_of_unreadable_documents(client, tokens, directory):
    """The failures explorer must not hand a walled associate the walled matter's gold answers or questions."""
    raw = json.loads((EVAL_DIR / "reports" / "latest.json").read_text())
    for username, h in tokens.items():
        r = client.get("/api/eval/report", headers=h)
        if r.status_code == 404:
            return
        refs, keys = readable(client, h)
        assert not unreadable_refs_in(r.text, refs, keys), username
        shown = {row["id"]: row for row in r.json()["questions"]}
        me = directory.users[username]
        for row in raw["questions"]:
            asker = directory.users[row["user"]]
            if asker.tenant != me.tenant or row["user"] == username:
                continue
            hidden_expected = (not set(row["relevant"]) <= refs) if row["relevant"] else \
                not {k.split("@")[0] for k in row["forbidden"]} <= keys
            if hidden_expected:
                out = shown[row["id"]]
                assert out["answer_spans"] == [] and out.get("content_hidden"), (username, row["id"])
                assert row["question"] not in strings(out), (username, row["id"])


def test_walled_associate_cannot_read_harrow_answers_from_the_eval_lab(client, tokens):
    body = client.get("/api/eval/report", headers=tokens["theo.brandt"]).text
    for secret in ("1,150,000", "620,000", "14 December 2026", "Harrow mediation", "Harrow litigation hold"):
        assert secret not in body, secret
    rows = client.get("/api/eval/report", headers=tokens["theo.brandt"]).json()["questions"]
    assert any(r.get("content_hidden") for r in rows)  # the rows are still counted, just without their text
    # The partner on the matter still sees the full rows.
    assert "1,150,000" in client.get("/api/eval/report", headers=tokens["marcus.oyelaran"]).text


def test_adversarial_reports_hide_unreadable_refs(client, tokens):
    for name in ("adversarial", "adversarial-generative"):
        for username, h in tokens.items():
            r = client.get(f"/api/eval/{name}", headers=h)
            if r.status_code == 404:
                continue
            refs, keys = readable(client, h)
            assert not unreadable_refs_in(r.text, refs, keys), (name, username)


def test_audit_view_hides_other_users_questions_and_unreadable_refs(fresh_client):
    c = fresh_client
    marcus, ava, admin = login(c, "marcus.oyelaran"), login(c, "ava.lindqvist"), login(c, "lf.admin")
    walled_q = "What settlement authority has the client given in the Harrow matter?"
    assert c.post("/api/ask", headers=marcus, json={"question": walled_q, "as_of": AS_OF}).status_code == 200
    assert c.post("/api/ask", headers=ava, json={"question": "Brightwater termination notice",
                                                  "as_of": AS_OF}).status_code == 200
    r = c.get("/api/admin/audit", headers=admin)
    assert r.status_code == 200
    refs, keys = readable(c, admin)
    assert walled_q not in r.text and "Brightwater termination notice" not in r.text
    assert not unreadable_refs_in(r.text, refs, keys)
    asks = [e for e in r.json() if e["action"] == "ask"]
    assert {e["username"] for e in asks} >= {"marcus.oyelaran", "ava.lindqvist"}  # who and when stay visible
    # The asker still sees their own question in full when they hold an audit role.
    own = c.get("/api/admin/audit", headers=marcus).json()
    assert any(e["detail"].get("query") == walled_q for e in own if e["username"] == "marcus.oyelaran")


def _unreadable_key(c, admin) -> str:
    return next(d["doc_key"] for d in c.get("/api/admin/documents", headers=admin).json()
                if not d["readable_by_you"] and not d["deleted"])


def test_admin_cannot_replace_or_delete_a_document_it_cannot_read(fresh_client):
    c = fresh_client
    admin = login(c, "lf.admin")
    key = _unreadable_key(c, admin)
    before = [d for d in c.get("/api/admin/documents", headers=admin).json() if d["doc_key"] == key]
    payload = {"filename": "x.md", "content_base64": base64.b64encode(b"# Replacement\n\nNew terms " * 10).decode(),
               "doc_key": key, "title": "Replacement", "collection": "commercial", "acl_groups": ["lf-all"],
               "effective_date": "2026-10-01", "classification": "internal"}
    r = c.post("/api/admin/ingest", headers=admin, json=payload)
    assert r.status_code == 403
    assert c.delete(f"/api/admin/documents/{key}", headers=admin).status_code == 403
    after = [d for d in c.get("/api/admin/documents", headers=admin).json() if d["doc_key"] == key]
    assert after == before  # no new version, nothing deleted
    events = [e for e in c.get("/api/admin/audit", headers=admin).json() if e["outcome"] == "denied"]
    assert {e["action"] for e in events} >= {"ingest", "delete"}
