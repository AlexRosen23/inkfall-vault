"""Ingestion: untrusted bytes -> validated text -> immutable version -> chunks with exact offsets.

Invariant (tested): for every chunk, version.text[chunk.char_start:chunk.char_end] == chunk.text.
Edits never mutate a stored version; they create a new version. Deletion removes index rows.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from .config import MAX_UPLOAD_BYTES
from .corpus import SeedDoc
from .db import Chunk, Document, DocumentVersion, QuarantineRow, fts_table, utcnow

MAX_CHUNK_CHARS = 900
MIN_CHUNK_CHARS = 60
ALLOWED_EXT = {".md": "text/markdown", ".markdown": "text/markdown", ".txt": "text/plain", ".pdf": "application/pdf"}
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class IngestError(ValueError):
    """Raised for input that must be quarantined rather than indexed."""


@dataclass
class ChunkSpan:
    ordinal: int
    heading: str
    start: int
    end: int


# ---------------------------------------------------------------- parsing (untrusted input boundary)

def sniff_and_extract(filename: str, data: bytes) -> tuple[str, str, str]:
    """Return (text, mime, extraction_method). Raise IngestError for anything unsafe or unparseable."""
    if len(data) == 0:
        raise IngestError("empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise IngestError(f"file exceeds {MAX_UPLOAD_BYTES} bytes")
    name = filename.lower()
    ext = name[name.rfind("."):] if "." in name else ""
    if ext not in ALLOWED_EXT:
        raise IngestError(f"unsupported file type {ext or '(none)'}")
    mime = ALLOWED_EXT[ext]
    if ext == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise IngestError("declared PDF but missing %PDF- header")
        return _extract_pdf(data), mime, "pypdf text layer (no OCR)"
    if data.startswith(b"%PDF-") or data[:4] in (b"PK\x03\x04", b"\x7fELF") or data[:2] == b"MZ":
        raise IngestError("binary content in a text upload")
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IngestError("text is not valid UTF-8") from exc
    return normalize_text(decoded), mime, "utf-8 text"


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise IngestError("encrypted PDF")
        if len(reader.pages) > 200:
            raise IngestError("PDF has more than 200 pages")
        pages = [(p.extract_text() or "") for p in reader.pages]
    except IngestError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, OSError) as exc:
        raise IngestError(f"PDF could not be parsed ({type(exc).__name__})") from exc
    out = normalize_text("\n\n".join(pages))
    if len(out.strip()) < 40:
        raise IngestError("PDF has no extractable text layer (OCR is disabled by design)")
    return out


def normalize_text(raw: str) -> str:
    t = unicodedata.normalize("NFC", raw.replace("\r\n", "\n").replace("\r", "\n"))
    t = CONTROL.sub("", t)
    return t.strip("\n") + "\n"


# ---------------------------------------------------------------- chunking

PARA = re.compile(r"\n[ \t]*\n+")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def chunk_spans(body: str) -> list[ChunkSpan]:
    """Paragraph/clause chunks. Headings are context, not chunks. Offsets index into `body`."""
    spans: list[ChunkSpan] = []
    heading = ""
    pos = 0
    pieces: list[tuple[int, int]] = []
    for m in PARA.finditer(body):
        pieces.append((pos, m.start()))
        pos = m.end()
    pieces.append((pos, len(body)))
    pending: tuple[int, int] | None = None
    pending_heading = ""
    for start, end in pieces:
        seg = body[start:end]
        lead = len(seg) - len(seg.lstrip())
        start += lead
        end = start + len(body[start:end].rstrip())
        if end <= start:
            continue
        first_line = body[start:end].split("\n", 1)[0]
        hm = HEADING.match(first_line)
        if hm and "\n" not in body[start:end]:
            if pending:
                spans.extend(_split_long(body, pending, pending_heading))
                pending = None
            heading = hm.group(2).strip()
            continue
        if pending and (pending[1] - pending[0]) < MIN_CHUNK_CHARS and pending_heading == heading:
            pending = (pending[0], end)  # merge a tiny paragraph forward
            continue
        if pending:
            spans.extend(_split_long(body, pending, pending_heading))
        pending, pending_heading = (start, end), heading
    if pending:
        spans.extend(_split_long(body, pending, pending_heading))
    for i, s in enumerate(spans):
        s.ordinal = i
    return spans


SENT_END = re.compile(r"(?<=[.;:!?])\s+(?=[A-Z0-9(\"“])")


def _split_long(body: str, span: tuple[int, int], heading: str) -> list[ChunkSpan]:
    start, end = span
    if end - start <= MAX_CHUNK_CHARS:
        return [ChunkSpan(0, heading, start, end)]
    out: list[ChunkSpan] = []
    cur = start
    while end - cur > MAX_CHUNK_CHARS:
        window = body[cur:cur + MAX_CHUNK_CHARS]
        cut = None
        for m in SENT_END.finditer(window):
            if m.start() > MAX_CHUNK_CHARS // 3:
                cut = m.start()
        if cut is None:
            cut = window.rfind(" ")
            if cut <= 0:
                cut = MAX_CHUNK_CHARS
        out.append(ChunkSpan(0, heading, cur, cur + cut))
        cur = cur + cut
        while cur < end and body[cur].isspace():
            cur += 1
    if cur < end:
        out.append(ChunkSpan(0, heading, cur, end))
    return out


def sentence_spans(body: str, start: int, end: int) -> list[tuple[int, int]]:
    """Sentence-ish spans inside [start, end) with absolute offsets."""
    out: list[tuple[int, int]] = []
    cur = start
    seg = body[start:end]
    for m in SENT_END.finditer(seg):
        s_end = start + m.start()
        if s_end > cur:
            out.append((cur, s_end))
        cur = start + m.end()
    if cur < end:
        out.append((cur, end))
    return [(a, b) for a, b in out if body[a:b].strip()]


# ---------------------------------------------------------------- storing versions

@dataclass
class VersionInput:
    tenant_id: str
    doc_key: str
    version: int | None
    title: str
    collection: str
    doc_type: str
    classification: str
    acl_groups: list[str]
    ethical_wall: list[str]
    matter: str | None
    effective_date: dt.date
    amends_key: str | None
    retention: str
    parties: list[str]
    tags: list[str]
    text: str
    source_filename: str
    source_mime: str
    extraction_method: str
    byte_size: int
    ingested_by: str


def store_version(session: Session, vi: VersionInput) -> DocumentVersion:
    doc = session.scalar(select(Document).where(Document.tenant_id == vi.tenant_id, Document.doc_key == vi.doc_key))
    if doc is None:
        doc = Document(tenant_id=vi.tenant_id, doc_key=vi.doc_key, title=vi.title, collection=vi.collection,
                       doc_type=vi.doc_type, matter=vi.matter)
        session.add(doc)
        session.flush()
    elif doc.deleted_at is not None:
        doc.deleted_at = None  # re-ingesting a deleted key starts a fresh active history
    existing = [v.version for v in doc.versions]
    number = vi.version if vi.version is not None else (max(existing, default=0) + 1)
    if number in existing:
        raise IngestError(f"{vi.doc_key} version {number} already exists (versions are immutable)")
    doc.title = vi.title
    v = DocumentVersion(
        document_id=doc.id, tenant_id=vi.tenant_id, version=number, title=vi.title,
        effective_date=vi.effective_date, classification=vi.classification, acl_groups=list(vi.acl_groups),
        ethical_wall=list(vi.ethical_wall), amends_key=vi.amends_key, retention=vi.retention,
        parties=list(vi.parties), tags=list(vi.tags), text=vi.text,
        checksum=hashlib.sha256(vi.text.encode("utf-8")).hexdigest(), source_filename=vi.source_filename,
        source_mime=vi.source_mime, extraction_method=vi.extraction_method, byte_size=vi.byte_size,
        ingested_by=vi.ingested_by, ingested_at=utcnow(),
    )
    session.add(v)
    session.flush()
    for cs in chunk_spans(vi.text):
        c = Chunk(version_id=v.id, tenant_id=vi.tenant_id, ordinal=cs.ordinal, heading=cs.heading[:300],
                  char_start=cs.start, char_end=cs.end, text=vi.text[cs.start:cs.end])
        session.add(c)
        session.flush()
        session.execute(
            text(f"INSERT INTO {fts_table(vi.tenant_id)}(chunk_id, title, heading, body) VALUES (:id, :t, :h, :b)"),  # noqa: S608
            {"id": c.id, "t": vi.title, "h": cs.heading, "b": c.text},
        )
    return v


def seed_input(d: SeedDoc) -> VersionInput:
    return VersionInput(
        tenant_id=d.tenant, doc_key=d.doc_key, version=d.version, title=d.title, collection=d.collection,
        doc_type=d.doc_type, classification=d.classification, acl_groups=d.acl_groups,
        ethical_wall=d.ethical_wall, matter=d.matter, effective_date=d.effective_date, amends_key=d.amends,
        retention=d.retention, parties=d.parties, tags=d.tags, text=normalize_text(d.body),
        source_filename=f"corpus/{d.tenant}/{d.path.name}", source_mime="text/markdown",
        extraction_method="utf-8 text (seed corpus)", byte_size=len(d.body.encode("utf-8")), ingested_by="seed",
    )


def quarantine(session: Session, tenant_id: str, username: str, filename: str, data: bytes, reason: str) -> QuarantineRow:
    """Record a rejected upload. Stores only name, hash, size and reason - never the content."""
    row = QuarantineRow(tenant_id=tenant_id, uploaded_by=username, filename=filename[:300],
                        sha256=hashlib.sha256(data).hexdigest(), byte_size=len(data), reason=reason[:300])
    session.add(row)
    session.flush()
    return row


def delete_document(session: Session, tenant_id: str, doc_key: str) -> int:
    """Soft-delete a document: versions marked deleted, chunks + FTS rows + embeddings removed."""
    doc = session.scalar(select(Document).where(Document.tenant_id == tenant_id, Document.doc_key == doc_key,
                                                Document.deleted_at.is_(None)))
    if doc is None:
        return 0
    doc.deleted_at = utcnow()
    n = 0
    for v in doc.versions:
        v.status = "deleted"
        ids = [c.id for c in v.chunks]
        for cid in ids:
            session.execute(text(f"DELETE FROM {fts_table(tenant_id)} WHERE chunk_id = :id"), {"id": cid})  # noqa: S608
        session.execute(delete(Chunk).where(Chunk.version_id == v.id))
        n += 1
    session.flush()
    return n
