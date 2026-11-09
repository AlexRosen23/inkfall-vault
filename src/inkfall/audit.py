"""Structured audit events: request id, actor, tenant, action, outcome, redacted detail.

Detail never contains document text or snippets - only ids, refs, counts and redacted query text.
Retention is bounded (AUDIT_RETENTION_DAYS) and enforced by `purge_expired`.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import AUDIT_RETENTION_DAYS
from .db import AuditEvent, utcnow
from .redact import redact_obj

ACTIONS = {
    "login", "logout", "login_denied", "list_documents", "read_document", "read_denied", "export_raw", "search",
    "ask", "generate", "compare", "review", "ingest", "quarantine", "delete", "eval_run", "audit_view",
    "summary_create", "approval_request", "approval_decision", "export_release", "rate_limited", "auth_denied",
}


def log(session: Session, request_id: str, action: str, outcome: str, username: str | None = None,
        tenant_id: str | None = None, **detail) -> None:
    if action not in ACTIONS:
        raise ValueError(f"unknown audit action {action}")
    session.add(AuditEvent(request_id=request_id, username=username, tenant_id=tenant_id, action=action,
                           outcome=outcome, detail=redact_obj(detail)))


def purge_expired(session: Session, days: int = AUDIT_RETENTION_DAYS, now: dt.datetime | None = None) -> int:
    cutoff = (now or utcnow()) - dt.timedelta(days=days)
    res = session.execute(delete(AuditEvent).where(AuditEvent.ts < cutoff))
    return res.rowcount or 0


def recent(session: Session, tenant_id: str, limit: int = 200) -> list[AuditEvent]:
    return list(session.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant_id)
                                .order_by(AuditEvent.id.desc()).limit(limit)))
