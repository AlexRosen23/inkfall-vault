"""FastAPI app. Identity comes only from the server-side session; request bodies cannot carry
tenant/role/user fields (extra="forbid"), and headers like X-Role are ignored.

Every data path calls access.authorized_versions / get_authorized_version first. Forbidden and
missing objects return the same 404 so the API is not an existence oracle.
"""

from __future__ import annotations

import base64
import binascii
import collections
import datetime as dt
import hashlib
import json
import logging
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit, embed, providers
from .access import authorized_versions, get_authorized_version
from .config import (
    DATA_DIR,
    EVAL_DIR,
    MAX_QUERY_CHARS,
    MAX_UPLOAD_BYTES,
    RATE_LIMIT_PER_MINUTE,
    SESSION_TTL_SECONDS,
)
from .db import (
    Document,
    QuarantineRow,
    Review,
    SessionRow,
    Summary,
    create_schema,
    make_engine,
    session_factory,
    utcnow,
)
from .identities import Directory, User, directory
from .ingest import IngestError, VersionInput, delete_document, quarantine, sniff_and_extract, store_version
from .redact import redact
from .search import ensure_embeddings
from .service import compare_versions, document_payload, new_request_id, run_query, verify_citation

log = logging.getLogger("inkfall")
COOKIE = "inkfall_session"
MAX_BODY = MAX_UPLOAD_BYTES * 2


@contextmanager
def tx(s: Session):
    """Commit on success, roll back on any exception (works with SQLAlchemy autobegin)."""
    try:
        yield
        s.commit()
    except BaseException:
        s.rollback()
        raise


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginIn(Strict):
    username: str = Field(max_length=64)


class AskIn(Strict):
    question: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    as_of: dt.date | None = None
    method: Literal["bm25", "dense", "hybrid", "rerank"] = "hybrid"
    collection: str | None = Field(default=None, max_length=64)
    include_history: bool = False
    generate: Literal["extractive", "generative", "lmstudio", "ollama"] = "extractive"


class ReviewIn(Strict):
    request_id: str = Field(max_length=40)
    question: str = Field(max_length=MAX_QUERY_CHARS)
    answer_mode: Literal["extractive", "generative"]
    sentence: str = Field(max_length=2000)
    version_id: int
    char_start: int
    char_end: int
    quote: str = Field(max_length=4000)
    verdict: Literal["correct", "incorrect", "partial"]
    reason: str = Field(default="", max_length=600)


class SummaryItem(Strict):
    text: str = Field(max_length=2000)
    version_id: int
    char_start: int
    char_end: int
    quote: str = Field(max_length=4000)


class SummaryIn(Strict):
    title: str = Field(min_length=1, max_length=200)
    question: str = Field(default="", max_length=MAX_QUERY_CHARS)
    recipient: str = Field(default="", max_length=200)
    items: list[SummaryItem] = Field(min_length=1, max_length=20)


class DecisionIn(Strict):
    decision: Literal["approve", "reject"]
    note: str = Field(default="", max_length=600)


class IngestIn(Strict):
    filename: str = Field(max_length=300)
    content_base64: str
    doc_key: str = Field(max_length=64)
    title: str = Field(max_length=300)
    collection: str = Field(max_length=64)
    doc_type: str = Field(default="memo", max_length=32)
    classification: Literal["public", "internal", "confidential", "restricted"] = "confidential"
    acl_groups: list[str] = Field(min_length=1, max_length=8)
    effective_date: dt.date
    retention: str = Field(default="7y", max_length=120)


# ------------------------------------------------------------------------------------------------ app state

class State:
    def __init__(self, db_file: Path | None = None):
        self.engine = make_engine(db_file)
        self.directory: Directory = directory()
        create_schema(self.engine, sorted(self.directory.tenants))
        self.Session = session_factory(self.engine)
        self.rate: dict[str, collections.deque] = collections.defaultdict(collections.deque)
        self.lock = threading.Lock()


def create_app(db_file: Path | None = None, rate_limit: int = RATE_LIMIT_PER_MINUTE) -> FastAPI:
    st = State(db_file)

    @asynccontextmanager
    async def lifespan(_app):
        with st.Session.begin() as s:
            audit.purge_expired(s)
        yield
        st.engine.dispose()

    app = FastAPI(title="The Inkfall Vault API", version="0.1.0", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.inkfall = st

    @app.middleware("http")
    async def guard(request: Request, call_next):
        rid = new_request_id()
        request.state.rid = rid
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > MAX_BODY:
            return JSONResponse({"error": "payload_too_large", "request_id": rid}, status_code=413)
        try:
            resp = await call_next(request)
        except Exception as exc:  # noqa: BLE001 - never leak internals
            log.error("request %s failed: %s", rid, type(exc).__name__)
            resp = JSONResponse({"error": "internal_error", "request_id": rid}, status_code=500)
        resp.headers["X-Request-ID"] = rid
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return resp

    @app.exception_handler(HTTPException)
    async def http_exc(request: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail, "request_id": getattr(request.state, "rid", "")},
                            status_code=exc.status_code, headers=getattr(exc, "headers", None))

    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def validation_exc(request: Request, exc: RequestValidationError):
        # Echo field locations and error types only - never the submitted values.
        errs = [{"loc": list(e.get("loc", [])), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse({"error": "invalid_request", "details": errs, "request_id": request.state.rid},
                            status_code=422)

    # -------------------------------------------------------------------------------- dependencies

    def db():
        with st.Session() as s:
            yield s

    def current_user(request: Request) -> User:
        # An explicit Authorization header wins over the browser cookie.
        auth = request.headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else request.cookies.get(COOKIE)
        if not token or len(token) > 200:
            raise HTTPException(401, "not_authenticated")
        with st.Session() as lookup:
            row = lookup.get(SessionRow, hashlib.sha256(token.encode()).hexdigest())
        if row is None or row.expires_at < utcnow():
            raise HTTPException(401, "not_authenticated")
        user = st.directory.users.get(row.username)
        if user is None:
            raise HTTPException(401, "not_authenticated")
        key = f"u:{user.username}"
        now = time.monotonic()
        with st.lock:
            q = st.rate[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= rate_limit:
                with st.Session.begin() as s2:
                    audit.log(s2, request.state.rid, "rate_limited", "denied", user.username, user.tenant)
                raise HTTPException(429, "rate_limited", headers={"Retry-After": "60"})
            q.append(now)
        request.state.user = user
        return user

    def require_role(user: User, *roles: str) -> None:
        if not any(user.has_role(r) for r in roles):
            raise HTTPException(403, "forbidden")

    def rid(request: Request) -> str:
        return request.state.rid

    # -------------------------------------------------------------------------------- auth

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/identities")
    def identities():
        """Demo login screen: the fixed, fictional fixture identities (no credentials exist)."""
        d = st.directory
        return [{"username": u.username, "display_name": u.display_name, "title": u.title,
                 "tenant": u.tenant, "tenant_name": d.tenants[u.tenant].name, "roles": list(u.roles)}
                for u in d.users.values()]

    @app.post("/api/auth/login")
    def login(body: LoginIn, request: Request, response: Response, s: Session = Depends(db)):
        user = st.directory.users.get(body.username)
        if user is None:
            with tx(s):
                audit.log(s, rid(request), "login_denied", "denied", None, None, attempted=body.username)
            raise HTTPException(401, "unknown_identity")
        token = secrets.token_urlsafe(32)
        with tx(s):
            s.add(SessionRow(token_hash=hashlib.sha256(token.encode()).hexdigest(), username=user.username,
                             expires_at=utcnow() + dt.timedelta(seconds=SESSION_TTL_SECONDS)))
            audit.log(s, rid(request), "login", "ok", user.username, user.tenant)
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=SESSION_TTL_SECONDS, path="/")
        return {"user": _me(user), "token": token, "auth": "DEMO fixture login: no password, local use only"}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, user: User = Depends(current_user), s: Session = Depends(db)):
        auth = request.headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else (request.cookies.get(COOKIE) or "")
        with tx(s):
            row = s.get(SessionRow, hashlib.sha256(token.encode()).hexdigest())
            if row:
                s.delete(row)
            audit.log(s, rid(request), "logout", "ok", user.username, user.tenant)
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    def _me(user: User) -> dict:
        t = st.directory.tenants[user.tenant]
        return {"username": user.username, "display_name": user.display_name, "title": user.title,
                "tenant": user.tenant, "tenant_name": t.name, "roles": list(user.roles), "groups": list(user.groups),
                "clearance": user.clearance, "collections": list(t.collections),
                # ACL group names of the caller's own tenant, for the admin upload form (labels only, no content)
                "tenant_groups": list(t.groups) if user.has_role("admin") else []}

    @app.get("/api/auth/me")
    def me(user: User = Depends(current_user)):
        return _me(user)

    # -------------------------------------------------------------------------------- documents

    @app.get("/api/documents")
    def list_documents(request: Request, collection: str | None = None, include_history: bool = True,
                       as_of: dt.date | None = None, user: User = Depends(current_user), s: Session = Depends(db)):
        views = authorized_versions(s, user, st.directory, as_of, include_history, collection)
        out = [{"version_id": v.version.id, "ref": v.ref, "doc_key": v.document.doc_key, "version": v.version.version,
                "title": v.version.title, "collection": v.document.collection, "doc_type": v.document.doc_type,
                "classification": v.version.classification, "effective_date": v.version.effective_date.isoformat(),
                "in_force": v.in_force, "superseded_by": v.superseded_by, "amends": v.version.amends_key,
                "tags": v.version.tags}
               for v in sorted(views, key=lambda x: (x.document.doc_key, x.version.version))]
        _audit(s, request, "list_documents", "ok", user, count=len(out), collection=collection)
        return out

    def _audit(s: Session, request: Request, action: str, outcome: str, user: User | None, **detail):
        with st.Session.begin() as s2:
            audit.log(s2, rid(request), action, outcome, user.username if user else None,
                      user.tenant if user else None, **detail)

    def _view_or_404(s: Session, request: Request, user: User, version_id: int):
        view = get_authorized_version(s, user, st.directory, version_id)
        if view is None:
            _audit(s, request, "read_denied", "denied", user, version_id=version_id)
            raise HTTPException(404, "not_found")
        return view

    @app.get("/api/documents/{version_id}")
    def read_document(version_id: int, request: Request, user: User = Depends(current_user), s: Session = Depends(db)):
        view = _view_or_404(s, request, user, version_id)
        history = [v for v in authorized_versions(s, user, st.directory, None, True)
                   if v.document.id == view.document.id]
        _audit(s, request, "read_document", "ok", user, ref=view.ref)
        return document_payload(view, sorted(history, key=lambda v: v.version.version))

    @app.get("/api/documents/{version_id}/raw")
    def raw_document(version_id: int, request: Request, user: User = Depends(current_user), s: Session = Depends(db)):
        view = _view_or_404(s, request, user, version_id)
        _audit(s, request, "export_raw", "ok", user, ref=view.ref)
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", view.ref)
        return PlainTextResponse(view.version.text, headers={
            "Content-Disposition": f'attachment; filename="{safe}.txt"'})

    @app.get("/api/compare/{a_id}/{b_id}")
    def compare(a_id: int, b_id: int, request: Request, user: User = Depends(current_user), s: Session = Depends(db)):
        a = _view_or_404(s, request, user, a_id)
        b = _view_or_404(s, request, user, b_id)
        if a.document.id != b.document.id:
            raise HTTPException(400, "versions_of_different_documents")
        if a.version.version > b.version.version:
            a, b = b, a
        _audit(s, request, "compare", "ok", user, a=a.ref, b=b.ref)
        return compare_versions(a, b)

    # -------------------------------------------------------------------------------- ask / search

    @app.post("/api/ask")
    def ask(body: AskIn, request: Request, user: User = Depends(current_user), s: Session = Depends(db)):
        if body.collection and body.collection not in st.directory.tenants[user.tenant].collections:
            raise HTTPException(404, "not_found")
        with tx(s):
            result = run_query(s, user, st.directory, body.question, body.as_of or dt.date.today(), body.method,
                               body.collection, body.include_history, body.generate)
        result["request_id"] = rid(request)
        _audit(s, request, "ask", result["status"], user, query=body.question, method=result["retrieval"]["method"],
               mode=result["mode"], refs=result["ranked_refs"][:5], abstained=result["abstained"],
               cited=sorted({c["ref"] for a in result["answer"] for c in a["citations"]}))
        if body.generate != "extractive":
            g = result["generation"]
            _audit(s, request, "generate", g.get("status", "skipped"), user, model=g.get("model"),
                   provider=g.get("provider"), rejected_reason=g.get("rejected_reason"))
        result.pop("ranked_version_ids", None)
        return result

    @app.post("/api/verify-citation")
    def verify(body: SummaryItem, user: User = Depends(current_user), s: Session = Depends(db)):
        ok, why = verify_citation(s, user, st.directory, body.version_id, body.char_start, body.char_end, body.quote)
        return {"valid": ok, "reason": why}

    # -------------------------------------------------------------------------------- reviews

    @app.post("/api/reviews")
    def create_review(body: ReviewIn, request: Request, user: User = Depends(current_user), s: Session = Depends(db)):
        ok, why = verify_citation(s, user, st.directory, body.version_id, body.char_start, body.char_end, body.quote)
        if not ok:
            raise HTTPException(404 if why == "version not found" else 400, "invalid_citation")
        with tx(s):
            r = Review(username=user.username, tenant_id=user.tenant, request_id=body.request_id,
                       question=body.question, answer_mode=body.answer_mode, sentence=body.sentence,
                       version_id=body.version_id, char_start=body.char_start, char_end=body.char_end,
                       verdict=body.verdict, reason=body.reason)
            s.add(r)
            s.flush()
            audit.log(s, rid(request), "review", body.verdict, user.username, user.tenant, review_id=r.id)
        return {"id": r.id}

    @app.get("/api/reviews")
    def list_reviews(user: User = Depends(current_user), s: Session = Depends(db)):
        q = select(Review).where(Review.tenant_id == user.tenant).order_by(Review.id.desc()).limit(200)
        if not user.has_role("reviewer"):
            q = q.where(Review.username == user.username)
        out = []
        for r in s.scalars(q):
            if get_authorized_version(s, user, st.directory, r.version_id) is None:
                continue  # reviews about versions this viewer cannot read are hidden
            out.append({"id": r.id, "ts": r.ts.isoformat() + "Z", "username": r.username, "question": r.question,
                        "answer_mode": r.answer_mode, "sentence": r.sentence, "version_id": r.version_id,
                        "char_start": r.char_start, "char_end": r.char_end, "verdict": r.verdict, "reason": r.reason})
        counts = collections.Counter(r["verdict"] for r in out)
        return {"reviews": out, "counts": dict(counts),
                "note": "Labels from local demo users; not externally audited annotations."}

    # -------------------------------------------------------------------------------- summaries + approval

    def _summary_or_404(s: Session, user: User, sid: int) -> Summary:
        sm = s.get(Summary, sid)
        if sm is None or sm.tenant_id != user.tenant:
            raise HTTPException(404, "not_found")
        for it in sm.items:
            if get_authorized_version(s, user, st.directory, it["version_id"]) is None:
                raise HTTPException(404, "not_found")  # can't see the brief unless you can read every source
        return sm

    def _summary_out(sm: Summary) -> dict:
        return {"id": sm.id, "title": sm.title, "question": sm.question, "author": sm.author, "status": sm.status,
                "recipient": sm.recipient, "approver": sm.approver, "decision_note": sm.decision_note,
                "items": sm.items, "created_at": sm.created_at.isoformat() + "Z",
                "decided_at": sm.decided_at.isoformat() + "Z" if sm.decided_at else None,
                "released_at": sm.released_at.isoformat() + "Z" if sm.released_at else None,
                "export_path": sm.export_path}

    @app.post("/api/summaries")
    def create_summary(body: SummaryIn, request: Request, user: User = Depends(current_user), s: Session = Depends(db)):
        items = []
        for it in body.items:
            ok, why = verify_citation(s, user, st.directory, it.version_id, it.char_start, it.char_end, it.quote)
            if not ok:
                raise HTTPException(400, f"invalid_citation: {why}")
            view = get_authorized_version(s, user, st.directory, it.version_id)
            items.append({**it.model_dump(), "ref": view.ref})
        with tx(s):
            sm = Summary(tenant_id=user.tenant, author=user.username, title=body.title, question=body.question,
                         items=items, recipient=body.recipient)
            s.add(sm)
            s.flush()
            audit.log(s, rid(request), "summary_create", "ok", user.username, user.tenant, summary_id=sm.id,
                      refs=sorted({i["ref"] for i in items}))
        return _summary_out(sm)

    @app.get("/api/summaries")
    def list_summaries(user: User = Depends(current_user), s: Session = Depends(db)):
        out = []
        for sm in s.scalars(select(Summary).where(Summary.tenant_id == user.tenant).order_by(Summary.id.desc())):
            try:
                out.append(_summary_out(_summary_or_404(s, user, sm.id)))
            except HTTPException:
                continue
        return out

    @app.post("/api/summaries/{sid}/submit")
    def submit_summary(sid: int, request: Request, user: User = Depends(current_user), s: Session = Depends(db)):
        with tx(s):
            sm = _summary_or_404(s, user, sid)
            if sm.author != user.username or sm.status not in {"draft", "rejected"}:
                raise HTTPException(409, "invalid_state")
            sm.status = "pending"
            audit.log(s, rid(request), "approval_request", "pending", user.username, user.tenant, summary_id=sid)
        return _summary_out(sm)

    @app.post("/api/summaries/{sid}/decision")
    def decide_summary(sid: int, body: DecisionIn, request: Request, user: User = Depends(current_user),
                       s: Session = Depends(db)):
        require_role(user, "reviewer")
        with tx(s):
            sm = _summary_or_404(s, user, sid)
            if sm.status != "pending":
                raise HTTPException(409, "invalid_state")
            if sm.author == user.username:
                raise HTTPException(403, "separation_of_duties: authors cannot approve their own brief")
            for it in sm.items:  # citations re-verified at decision time against immutable text
                ok, why = verify_citation(s, user, st.directory, it["version_id"], it["char_start"], it["char_end"],
                                          it["quote"])
                if not ok:
                    raise HTTPException(409, f"citation_no_longer_valid: {why}")
            sm.status = "approved" if body.decision == "approve" else "rejected"
            sm.approver, sm.decision_note, sm.decided_at = user.username, body.note, utcnow()
            audit.log(s, rid(request), "approval_decision", sm.status, user.username, user.tenant, summary_id=sid)
        return _summary_out(sm)

    @app.post("/api/summaries/{sid}/release")
    def release_summary(sid: int, request: Request, user: User = Depends(current_user), s: Session = Depends(db)):
        """The one 'external action'. It writes a packet to a local outbox folder; nothing leaves the machine."""
        sm = _summary_or_404(s, user, sid)
        if user.username not in {sm.author, sm.approver}:
            raise HTTPException(403, "forbidden")
        if sm.status != "approved":
            _audit(s, request, "export_release", "denied", user, summary_id=sid, reason="not approved")
            raise HTTPException(409, "approval_required")
        with tx(s):
            out_dir = DATA_DIR / "outbox" / user.tenant
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"brief-{sm.id}.md"
            lines = [f"# {sm.title}", "", f"Prepared by {sm.author}; approved by {sm.approver}.",
                     "Decision support from fictional demo data - not legal advice.", ""]
            for i, it in enumerate(sm.items, 1):
                lines += [f"{i}. {it['text']}", f"   Source: {it['ref']} chars {it['char_start']}-{it['char_end']}", ""]
            path.write_text("\n".join(lines), encoding="utf-8")
            sm.status, sm.released_at, sm.export_path = "released", utcnow(), str(path.relative_to(DATA_DIR))
            audit.log(s, rid(request), "export_release", "ok", user.username, user.tenant, summary_id=sid)
        return _summary_out(sm)

    # -------------------------------------------------------------------------------- admin

    def _safe_filename(name: str) -> str:
        name = name.replace("\\", "/").split("/")[-1]
        name = re.sub(r"[\x00-\x1f\x7f]", "", name)
        name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .")
        return (name or "upload")[:120]

    @app.post("/api/admin/ingest")
    def ingest(body: IngestIn, request: Request, user: User = Depends(current_user), s: Session = Depends(db)):
        require_role(user, "admin")
        tenant = st.directory.tenants[user.tenant]  # tenant forced from the session, never the body
        fname = _safe_filename(body.filename)
        try:
            data = base64.b64decode(body.content_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(400, "content is not valid base64") from None
        if body.collection not in tenant.collections or set(body.acl_groups) - set(tenant.groups):
            raise HTTPException(400, "collection or acl_groups not in your tenant")
        if not re.match(r"^[A-Z]{2}-[A-Z0-9-]{2,40}$", body.doc_key):
            raise HTTPException(400, "doc_key must look like CV-NEW-DOC")
        try:
            text, mime, method = sniff_and_extract(fname, data)
        except IngestError as exc:
            with tx(s):
                q = quarantine(s, user.tenant, user.username, fname, data, str(exc))
                audit.log(s, rid(request), "quarantine", "quarantined", user.username, user.tenant,
                          filename=fname, reason=str(exc), quarantine_id=q.id)
            return JSONResponse({"status": "quarantined", "reason": str(exc), "quarantine_id": q.id}, status_code=422)
        with tx(s):
            v = store_version(s, VersionInput(
                tenant_id=user.tenant, doc_key=body.doc_key, version=None, title=body.title,
                collection=body.collection, doc_type=body.doc_type, classification=body.classification,
                acl_groups=body.acl_groups, ethical_wall=[], matter=None, effective_date=body.effective_date,
                amends_key=None, retention=body.retention, parties=[], tags=["uploaded"], text=text,
                source_filename=fname, source_mime=mime, extraction_method=method, byte_size=len(data),
                ingested_by=user.username))
            if embed.available():
                ensure_embeddings(s, [c.id for c in v.chunks])
            audit.log(s, rid(request), "ingest", "ok", user.username, user.tenant, doc_key=body.doc_key,
                      version=v.version, checksum=v.checksum)
        return {"status": "indexed", "version_id": v.id, "version": v.version, "checksum": v.checksum,
                "chunks": len(v.chunks), "filename": fname}

    @app.delete("/api/admin/documents/{doc_key}")
    def delete_doc(doc_key: str, request: Request, user: User = Depends(current_user), s: Session = Depends(db)):
        require_role(user, "admin")
        with tx(s):
            n = delete_document(s, user.tenant, doc_key)
            audit.log(s, rid(request), "delete", "ok" if n else "not_found", user.username, user.tenant,
                      doc_key=doc_key, versions=n)
        if not n:
            raise HTTPException(404, "not_found")
        return {"deleted_versions": n}

    @app.get("/api/admin/quarantine")
    def list_quarantine(user: User = Depends(current_user), s: Session = Depends(db)):
        require_role(user, "admin")
        rows = s.scalars(select(QuarantineRow).where(QuarantineRow.tenant_id == user.tenant).order_by(QuarantineRow.id.desc()))
        return [{"id": r.id, "ts": r.ts.isoformat() + "Z", "filename": r.filename, "sha256": r.sha256,
                 "byte_size": r.byte_size, "reason": r.reason, "uploaded_by": r.uploaded_by} for r in rows]

    @app.get("/api/admin/audit")
    def audit_view(request: Request, user: User = Depends(current_user), s: Session = Depends(db)):
        require_role(user, "admin", "reviewer")
        rows = audit.recent(s, user.tenant)
        _audit(s, request, "audit_view", "ok", user, count=len(rows))
        return [{"id": r.id, "ts": r.ts.isoformat() + "Z", "request_id": r.request_id, "username": r.username,
                 "action": r.action, "outcome": r.outcome, "detail": r.detail} for r in rows]

    @app.get("/api/admin/documents")
    def admin_documents(user: User = Depends(current_user), s: Session = Depends(db)):
        """Records-management view: keys and versions only (no titles/text) for documents the admin
        cannot read. Content access still follows the ACL."""
        require_role(user, "admin")
        readable = {v.version.id for v in authorized_versions(s, user, st.directory, None, True)}
        out = []
        for d in s.scalars(select(Document).where(Document.tenant_id == user.tenant)):
            for v in d.versions:
                out.append({"doc_key": d.doc_key, "version": v.version, "status": v.status,
                            "deleted": d.deleted_at is not None, "readable_by_you": v.id in readable,
                            "title": v.title if v.id in readable else None})
        return out

    # -------------------------------------------------------------------------------- system + eval

    @app.get("/api/system")
    def system(user: User = Depends(current_user)):
        man = _read_json(EVAL_DIR / "dataset_manifest.json") or {}
        return {"embedding": embed.status(),
                "reranker": {"model_id": embed.RERANK_MODEL_ID, "downloaded": embed.reranker_available(),
                             "note": "opt-in experiment (make rerank-model)"},
                "generation_backends": [p.__dict__ for p in providers.detect()],
                "dataset_version": man.get("dataset_version"), "documents": man.get("documents")}

    @app.get("/api/eval/report")
    def eval_report(user: User = Depends(current_user), s: Session = Depends(db)):
        rep = _read_json(EVAL_DIR / "reports" / "latest.json")
        if rep is None:
            raise HTTPException(404, "no_report: run make eval")
        readable = {v.ref for v in authorized_versions(s, user, st.directory, None, True)}
        tenant_prefix = {"lanternfield": "LF", "corvane": "CV", "pellmoor": "PM"}[user.tenant]

        def scrub(refs):
            shown = [r for r in refs if r in readable]
            hidden = len(refs) - len(shown)
            return shown + ([f"[{hidden} reference(s) outside your access hidden]"] if hidden else [])

        rows = []
        for row in rep.get("questions", []):
            asker = st.directory.users.get(row.get("user", ""))
            if asker is None or asker.tenant != user.tenant:
                continue
            r = dict(row)
            for key in ("relevant", "forbidden"):
                r[key] = scrub(r.get(key, []))
            for m in r.get("methods", {}).values():
                m["top_refs"] = scrub(m.get("top_refs", []))
                m["cited_refs"] = scrub(m.get("cited_refs", []))
            rows.append(r)
        return {**{k: v for k, v in rep.items() if k != "questions"}, "questions": rows,
                "visibility": f"Aggregate metrics cover all tenants; per-question rows are limited to "
                              f"{tenant_prefix}/XT questions asked by {user.tenant} identities, with "
                              f"references you cannot read hidden."}

    @app.get("/api/eval/adversarial")
    def adversarial_report(user: User = Depends(current_user)):
        rep = _read_json(EVAL_DIR / "reports" / "adversarial.json")
        if rep is None:
            raise HTTPException(404, "no_report: run make security-test")
        cases = []
        for cs in rep.get("cases", []):
            asker = st.directory.users.get(cs.get("user") or "")
            if asker is not None and asker.tenant != user.tenant:
                continue  # other tenants' probe details (questions, refs) stay private
            cases.append(cs)
        iso = dict(rep.get("isolation", {}))
        iso["leak_examples"] = [e for e in iso.get("leak_examples", [])
                                if st.directory.users.get(e.get("user", "")) and
                                st.directory.users[e["user"]].tenant == user.tenant]
        return {**{k: v for k, v in rep.items() if k not in ("cases", "isolation")}, "isolation": iso,
                "cases": cases, "visibility": "Counts cover all tenants; case details limited to your tenant."}

    return app


def _read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def redact_for_log(s: str) -> str:
    return redact(s)

