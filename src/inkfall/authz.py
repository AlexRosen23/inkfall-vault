"""Deterministic authorization. The ONLY place that decides who may read a document version.

No model, prompt or client-supplied parameter takes part in this decision. Every read path
(list, search, snippets, raw text, embeddings, graph, citations, exports, generation) calls
`can_read` or `authorized_version_ids` before any document content is touched.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .identities import Directory, User


@dataclass(frozen=True)
class DocACL:
    """The access-relevant metadata of one document version."""

    tenant: str
    classification: str
    acl_groups: tuple[str, ...]
    ethical_wall: tuple[str, ...] = ()
    deleted: bool = False


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)


def decide(user: User, acl: DocACL, directory: Directory) -> Decision:
    """Explainable access decision. Deny wins; unknown labels fail closed."""
    reasons: list[str] = []
    if acl.deleted:
        return Decision(False, ("document deleted",))
    if user.tenant != acl.tenant:
        # Do not echo the other tenant's id into reasons that might be shown to the user.
        return Decision(False, ("different tenant",))
    reasons.append(f"tenant match ({user.tenant})")
    try:
        doc_level = directory.level(acl.classification)
        user_level = directory.level(user.clearance)
    except ValueError:
        return Decision(False, ("unknown classification label",))
    if doc_level > user_level:
        return Decision(False, (f"classification {acl.classification} exceeds clearance {user.clearance}",))
    reasons.append(f"clearance {user.clearance} >= {acl.classification}")
    shared = sorted(set(user.groups) & set(acl.acl_groups))
    if not shared:
        return Decision(False, ("no shared ACL group",))
    reasons.append("shared ACL group(s): " + ", ".join(shared))
    if user.username in acl.ethical_wall:
        return Decision(False, ("ethical wall: user is screened from this matter",))
    if acl.ethical_wall:
        reasons.append("not behind the matter's ethical wall")
    return Decision(True, tuple(reasons))


def can_read(user: User, acl: DocACL, directory: Directory) -> bool:
    return decide(user, acl, directory).allowed
