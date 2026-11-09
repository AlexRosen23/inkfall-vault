"""The authorized view: every read path starts here.

`authorized_versions` loads only the caller's tenant rows, runs the deterministic policy in
authz.py on each version, then applies the temporal filter. Nothing downstream (search, dense
scoring, snippets, graph, generation, export) ever receives a version id that is not in this set.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .authz import Decision, DocACL, decide
from .db import Document, DocumentVersion
from .identities import Directory, User


@dataclass
class VersionView:
    version: DocumentVersion
    document: Document
    decision: Decision
    in_force: bool
    superseded_by: int | None  # version number that superseded it (as of the date), if any
    newer_pending: int | None  # authorized future version number, if one exists

    @property
    def ref(self) -> str:
        return f"{self.document.doc_key}@{self.version.version}"


def acl_of(v: DocumentVersion, doc: Document) -> DocACL:
    return DocACL(
        tenant=v.tenant_id,
        classification=v.classification,
        acl_groups=tuple(v.acl_groups or ()),
        ethical_wall=tuple(v.ethical_wall or ()),
        deleted=(v.status != "active" or doc.deleted_at is not None),
    )


def authorized_versions(session: Session, user: User, directory: Directory, as_of: dt.date | None = None,
                        include_history: bool = False, collection: str | None = None) -> list[VersionView]:
    as_of = as_of or dt.date.today()
    docs = session.scalars(
        select(Document).where(Document.tenant_id == user.tenant).options(selectinload(Document.versions))
    ).all()
    out: list[VersionView] = []
    for doc in docs:
        if collection and doc.collection != collection:
            continue
        readable: list[tuple[DocumentVersion, Decision]] = []
        for v in doc.versions:
            d = decide(user, acl_of(v, doc), directory)
            if d.allowed:
                readable.append((v, d))
        # Version precedence is computed over ALL active versions so an unreadable newer version
        # still supersedes; we only disclose its number, never its content or metadata.
        active = [v for v in doc.versions if v.status == "active" and doc.deleted_at is None]
        effective = [v for v in active if v.effective_date <= as_of]
        current = max(effective, key=lambda v: v.version, default=None)
        for v, d in readable:
            in_force = current is not None and v.id == current.id
            later = [x for x in effective if x.version > v.version]
            superseded_by = min((x.version for x in later), default=None)
            pending = [x.version for x, _ in readable if x.effective_date > as_of and x.version > v.version]
            view = VersionView(v, doc, d, in_force, superseded_by, min(pending, default=None))
            if v.effective_date > as_of:
                continue  # not yet in force: never retrievable for this date
            if in_force or include_history:
                out.append(view)
    return out


def get_authorized_version(session: Session, user: User, directory: Directory, version_id: int) -> VersionView | None:
    """Fetch one version for display. Returns None for missing AND forbidden (no existence oracle)."""
    v = session.get(DocumentVersion, version_id)
    if v is None or v.tenant_id != user.tenant:
        return None
    doc = v.document
    d = decide(user, acl_of(v, doc), directory)
    if not d.allowed:
        return None
    active = [x for x in doc.versions if x.status == "active"]
    today = dt.date.today()
    effective = [x for x in active if x.effective_date <= today]
    current = max(effective, key=lambda x: x.version, default=None)
    later = [x.version for x in effective if x.version > v.version]
    return VersionView(v, doc, d, current is not None and current.id == v.id, min(later, default=None), None)
