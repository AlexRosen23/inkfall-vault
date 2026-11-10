"""Retrieval over the authorized view only: BM25 (FTS5), dense (local embeddings), hybrid (RRF), rerank.

The candidate universe for every method is the chunk-id set derived from `access.authorized_versions`.
Lexical search applies it inside the SQL statement; dense search only loads those embeddings.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import embed
from .access import VersionView
from .db import Chunk, fts_table

STOPWORDS = set("""
a an and are as at be been but by can could did do does doing for from had has have how i if in into is it its
me my of on or our shall should so than that the their them then there these they this those to under up was we
were what when where which while who whom why will with would you your about any all also per may must not no
""".split())
QUESTION_FILLER = set("""
tell show find give list explain describe say says said state states stated according document documents doc
please much many long often whether exactly currently current currently version versions clause clauses section
need needs want wants don get gets put keep give take make happen back now today ago anymore still
january february march april may june july august september october november december
""".split())
YEAR = re.compile(r"^(?:19|20)\d\d$")
TOKEN = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*%?")
RRF_K = 60


@dataclass
class Hit:
    chunk_id: int
    version_id: int
    score: float
    rank: int
    method: str
    components: dict[str, int] = field(default_factory=dict)  # method -> rank (1-based)


@dataclass
class SearchResult:
    hits: list[Hit]
    method: str
    latency_ms: float
    candidates: int
    notes: list[str] = field(default_factory=list)


def normalize_query(q: str, max_chars: int = 500) -> str:
    q = unicodedata.normalize("NFKC", q)
    q = re.sub(r"[\x00-\x1f\x7f]", " ", q)
    return re.sub(r"\s+", " ", q).strip()[:max_chars]


def tokens(s: str) -> list[str]:
    return TOKEN.findall(s.lower())


# Small, generic contracts/policy vocabulary map used for query expansion (lexical search, coverage and
# sentence scoring). Plain-language phrasings map to the terms documents actually use.
SYNONYMS: dict[str, list[str]] = {
    "roll": ["renew", "renewal"], "rollover": ["renew", "renewal"], "end": ["terminate", "termination", "expire"],
    "cancel": ["terminate", "termination"], "leave": ["terminate", "termination"], "quit": ["terminate"],
    "charge": ["price", "fee", "fees"], "bill": ["fee", "fees", "invoice"], "cost": ["price", "fee"],
    "owe": ["fee", "payable", "liable"], "late": ["overdue", "due"], "pay": ["payment", "payable"],
    "uptime": ["availability", "available"], "availability": ["uptime"], "outage": ["unavailable", "incident"],
    "begin": ["start", "started", "commenced"], "start": ["began", "commenced"], "cap": ["limit", "liability"],
    "keep": ["retain", "retention"], "store": ["retain", "retention"], "delete": ["destroy", "disposal"],
    "fine": ["penalty"], "boss": ["manager"], "deadline": ["within", "due"], "wfh": ["remote"],
}


def expanded_terms(s: str) -> list[str]:
    terms = content_terms(s)
    out = list(terms)
    for t in terms:
        for syn in SYNONYMS.get(t, []):
            if syn not in out:
                out.append(syn)
    return out


def content_terms(s: str) -> list[str]:
    seen: list[str] = []
    for t in tokens(s):
        if t in STOPWORDS or t in QUESTION_FILLER or len(t) < 2 or YEAR.match(t):
            continue
        if t not in seen:
            seen.append(t)
    return seen


def stem(t: str) -> str:
    """Tiny suffix stripper for term-coverage checks (FTS5 uses Porter for ranking). A final silent "e" is dropped
    after stripping so that invoice/invoices/invoiced, quote/quotes and dispute/disputed share one stem."""
    base = t
    for suf in ("ations", "ation", "ings", "ing", "ies", "ied", "es", "ed", "s", "ly"):
        short_plural = suf == "s" and len(t) == 4 and not t.endswith(("ss", "us", "is"))  # fees, days, caps
        if (len(t) > len(suf) + 3 or short_plural) and t.endswith(suf):
            base = t[: -len(suf)] + ("y" if suf in ("ies", "ied") else "")
            if suf in ("ed", "ing", "ings") and len(base) > 3 and base[-1] == base[-2] and base[-1] not in "aeiouls":
                base = base[:-1]  # committed -> commit, stopped -> stop
            break
    if len(base) > 4 and base.endswith("e") and not base.endswith(("ee", "ie")):
        base = base[:-1]
    return base


def fts_query(q: str) -> str | None:
    terms = expanded_terms(q)
    if not terms:
        return None
    # Each term quoted -> no FTS operator injection from user text.
    return " OR ".join('"' + t.replace('"', "") + '"' for t in terms[:32])


def chunk_ids_for(session: Session, views: list[VersionView]) -> dict[int, int]:
    """Authorized chunk id -> version id."""
    vids = [v.version.id for v in views]
    if not vids:
        return {}
    rows = session.execute(select(Chunk.id, Chunk.version_id).where(Chunk.version_id.in_(vids))).all()
    return {cid: vid for cid, vid in rows}


def lexical(session: Session, tenant_id: str, query: str, allowed: dict[int, int], k: int = 50) -> list[Hit]:
    fq = fts_query(query)
    if not fq or not allowed:
        return []
    table = fts_table(tenant_id)
    # Table name comes from fts_table() (validated fixture tenant id); all values are bound parameters.
    sql = text(
        f"SELECT chunk_id, bm25({table}, 0.0, 2.0, 3.0, 1.0) AS s FROM {table} "  # noqa: S608
        f"WHERE {table} MATCH :q AND chunk_id IN (SELECT value FROM json_each(:ids)) ORDER BY s LIMIT :k"
    )
    rows = session.execute(sql, {"q": fq, "ids": json.dumps(list(allowed)), "k": k}).all()
    hits = []
    for i, (cid, s) in enumerate(rows, 1):
        cid = int(cid)
        if cid not in allowed:  # belt and braces: never trust the index alone
            continue
        hits.append(Hit(cid, allowed[cid], -float(s), i, "bm25", {"bm25": i}))
    return hits


def ensure_embeddings(session: Session, chunk_ids: list[int]) -> int:
    missing = session.scalars(select(Chunk).where(Chunk.id.in_(chunk_ids), Chunk.embedding.is_(None))).all()
    if not missing:
        return 0
    texts = [f"{c.version.title}. {c.heading}. {c.text}" for c in missing]
    vecs = embed.encode(texts)
    for c, v in zip(missing, vecs, strict=True):
        c.embedding = embed.to_blob(v)
        c.embed_model = embed.EMBED_MODEL_ID
    session.flush()
    return len(missing)


def dense(session: Session, query: str, allowed: dict[int, int], k: int = 50) -> list[Hit]:
    if not allowed:
        return []
    ids = list(allowed)
    rows = session.execute(select(Chunk.id, Chunk.embedding).where(Chunk.id.in_(ids), Chunk.embedding.is_not(None))).all()
    if not rows:
        return []
    mat = np.stack([embed.from_blob(b) for _, b in rows])
    qv = embed.encode([query])[0]
    sims = mat @ qv
    order = np.argsort(-sims)[:k]
    return [Hit(int(rows[i][0]), allowed[int(rows[i][0])], float(sims[i]), r, "dense", {"dense": r})
            for r, i in enumerate(order, 1)]


def rrf(lists: dict[str, list[Hit]], k: int = 50) -> list[Hit]:
    scores: dict[int, float] = {}
    comps: dict[int, dict[str, int]] = {}
    vid: dict[int, int] = {}
    for name, hits in lists.items():
        for h in hits:
            scores[h.chunk_id] = scores.get(h.chunk_id, 0.0) + 1.0 / (RRF_K + h.rank)
            comps.setdefault(h.chunk_id, {})[name] = h.rank
            vid[h.chunk_id] = h.version_id
    order = sorted(scores, key=lambda c: (-scores[c], c))[:k]
    return [Hit(c, vid[c], scores[c], i, "hybrid", comps[c]) for i, c in enumerate(order, 1)]


def rerank(session: Session, query: str, hits: list[Hit], top: int = 20) -> list[Hit]:
    head = hits[:top]
    if not head:
        return hits
    chunks = {c.id: c for c in session.scalars(select(Chunk).where(Chunk.id.in_([h.chunk_id for h in head])))}
    model = embed.get_reranker()
    scores = model.predict([(query, chunks[h.chunk_id].text) for h in head], show_progress_bar=False)
    order = sorted(range(len(head)), key=lambda i: -float(scores[i]))
    out = []
    for r, i in enumerate(order, 1):
        h = head[i]
        out.append(Hit(h.chunk_id, h.version_id, float(scores[i]), r, "rerank", {**h.components, "rerank": r}))
    return out + [Hit(h.chunk_id, h.version_id, h.score, len(out) + j + 1, h.method, h.components)
                  for j, h in enumerate(hits[top:])]


def search(session: Session, tenant_id: str, query: str, views: list[VersionView], method: str = "hybrid",
           k: int = 50) -> SearchResult:
    t0 = time.perf_counter()
    query = normalize_query(query)
    allowed = chunk_ids_for(session, views)
    notes: list[str] = []
    if method not in {"bm25", "dense", "hybrid", "rerank"}:
        raise ValueError("unknown retrieval method")
    dense_ok = method != "bm25" and embed.available()
    if method != "bm25" and not dense_ok:
        notes.append("dense retrieval unavailable (embedding model not downloaded); fell back to BM25")
    if dense_ok:
        ensure_embeddings(session, list(allowed))
    if method == "bm25" or not dense_ok:
        hits = lexical(session, tenant_id, query, allowed, k)
        used = "bm25"
    elif method == "dense":
        hits = dense(session, query, allowed, k)
        used = "dense"
    else:
        hits = rrf({"bm25": lexical(session, tenant_id, query, allowed, k), "dense": dense(session, query, allowed, k)}, k)
        used = "hybrid"
        if method == "rerank":
            if embed.reranker_available():
                hits = rerank(session, query, hits)
                used = "rerank"
            else:
                notes.append("reranker not downloaded (opt-in); returned hybrid order")
    return SearchResult(hits, used, (time.perf_counter() - t0) * 1000, len(allowed), notes)


def doc_ranking(hits: list[Hit]) -> list[int]:
    """Version ids in first-hit order (for document-level metrics)."""
    seen: list[int] = []
    for h in hits:
        if h.version_id not in seen:
            seen.append(h.version_id)
    return seen
