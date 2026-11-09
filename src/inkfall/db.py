"""SQLite storage (SQLAlchemy 2). Lexical search uses one FTS5 table per tenant.

Per-tenant FTS tables keep BM25 statistics (document frequencies) tenant-scoped, so one
tenant's vocabulary cannot shift another tenant's scores. Within a tenant, the authorized
chunk-id set is applied inside the same SQL statement as the MATCH (see search.py).
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .config import db_path

TENANT_ID = re.compile(r"^[a-z][a-z0-9]{1,30}$")


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSON, list: JSON}


class TenantRow(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(200))


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("tenant_id", "doc_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    doc_key: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    collection: Mapped[str] = mapped_column(String(64))
    doc_type: Mapped[str] = mapped_column(String(32))
    matter: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    versions: Mapped[list[DocumentVersion]] = relationship(back_populates="document", order_by="DocumentVersion.version")


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    effective_date: Mapped[dt.date] = mapped_column(Date)
    classification: Mapped[str] = mapped_column(String(32))
    acl_groups: Mapped[list] = mapped_column(JSON)
    ethical_wall: Mapped[list] = mapped_column(JSON, default=list)
    amends_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retention: Mapped[str] = mapped_column(String(120))
    parties: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    text: Mapped[str] = mapped_column(Text)  # immutable source text; citations index into it
    checksum: Mapped[str] = mapped_column(String(64))
    source_filename: Mapped[str] = mapped_column(String(300))
    source_mime: Mapped[str] = mapped_column(String(80))
    extraction_method: Mapped[str] = mapped_column(String(80))
    byte_size: Mapped[int] = mapped_column(Integer)
    ingested_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    ingested_by: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | deleted
    document: Mapped[Document] = relationship(back_populates="versions")
    chunks: Mapped[list[Chunk]] = relationship(back_populates="version", order_by="Chunk.ordinal")


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(String(300), default="")
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    embed_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    version: Mapped[DocumentVersion] = relationship(back_populates="chunks")


class SessionRow(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
    request_id: Mapped[str] = mapped_column(String(40))
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tenant_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(40))
    outcome: Mapped[str] = mapped_column(String(24))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class QuarantineRow(Base):
    __tablename__ = "quarantine"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    uploaded_by: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(300))


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    username: Mapped[str] = mapped_column(String(64))
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    request_id: Mapped[str] = mapped_column(String(40))
    question: Mapped[str] = mapped_column(String(600))
    answer_mode: Mapped[str] = mapped_column(String(16))
    sentence: Mapped[str] = mapped_column(Text)
    version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"))
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    verdict: Mapped[str] = mapped_column(String(24))  # correct | incorrect | partial
    reason: Mapped[str] = mapped_column(String(600), default="")


def fts_table(tenant_id: str) -> str:
    """Name of the tenant's FTS5 table. Tenant ids come from the fixture, never from the client."""
    if not TENANT_ID.match(tenant_id):
        raise ValueError("invalid tenant id")
    return f"chunks_fts_{tenant_id}"


def make_engine(path: Path | None = None) -> Engine:
    path = path or db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", future=True)

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    return engine


def create_schema(engine: Engine, tenant_ids: list[str]) -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for t in tenant_ids:
            conn.execute(text(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {fts_table(t)} USING fts5("
                "chunk_id UNINDEXED, title, heading, body, tokenize='porter unicode61')"
            ))


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


class Summary(Base):
    """A citation-backed brief assembled by an analyst. External release needs a second person's approval."""

    __tablename__ = "summaries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    author: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    question: Mapped[str] = mapped_column(String(600), default="")
    items: Mapped[list] = mapped_column(JSON, default=list)  # [{text, version_id, char_start, char_end, ref}]
    status: Mapped[str] = mapped_column(String(24), default="draft")  # draft|pending|approved|rejected|released
    recipient: Mapped[str] = mapped_column(String(200), default="")
    approver: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision_note: Mapped[str] = mapped_column(String(600), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    released_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    export_path: Mapped[str | None] = mapped_column(String(400), nullable=True)
