"""Gold evaluation questions (eval/gold/*.jsonl): schema and integrity checks."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path

from .authz import DocACL, can_read
from .config import EVAL_DIR
from .corpus import SeedDoc
from .identities import Directory

CATEGORIES = {
    "single_hop", "multi_hop", "numeric", "temporal", "contradiction", "abstain", "permission", "injection",
}
DEFAULT_AS_OF = "2026-11-01"


@dataclass
class GoldQuestion:
    id: str
    user: str
    question: str
    category: str
    split: str
    as_of: str = DEFAULT_AS_OF
    relevant: list[str] = field(default_factory=list)
    answer_spans: list[str] = field(default_factory=list)
    expect_abstain: bool = False
    expect_conflict: bool = False
    forbidden: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def tenant(self) -> str:
        return self.id.split("-")[0]


def load_gold(root: Path | None = None) -> list[GoldQuestion]:
    root = root or (EVAL_DIR / "gold")
    out: list[GoldQuestion] = []
    for path in sorted(root.glob("*.jsonl")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                out.append(GoldQuestion(**raw))
            except (json.JSONDecodeError, TypeError) as exc:
                raise ValueError(f"{path.name}:{n}: {exc}") from exc
    return out


def in_force(doc: SeedDoc, all_versions: list[SeedDoc], as_of: dt.date) -> bool:
    if doc.effective_date > as_of:
        return False
    later = [v for v in all_versions if v.doc_key == doc.doc_key and v.version > doc.version
             and v.effective_date <= as_of]
    return not later


def validate_gold(questions: list[GoldQuestion], docs: list[SeedDoc], directory: Directory) -> list[str]:
    """Return a list of problems (empty = valid)."""
    problems: list[str] = []
    refs = {d.ref: d for d in docs}
    keys = {d.doc_key for d in docs}
    ids: set[str] = set()
    for q in questions:
        where = q.id
        if q.id in ids:
            problems.append(f"{where}: duplicate id")
        ids.add(q.id)
        user = directory.users.get(q.user)
        if user is None:
            problems.append(f"{where}: unknown user {q.user}")
            continue
        if q.category not in CATEGORIES:
            problems.append(f"{where}: bad category {q.category}")
        if q.split not in {"dev", "test"}:
            problems.append(f"{where}: split must be dev or test")
        if not q.question.strip():
            problems.append(f"{where}: empty question")
        try:
            as_of = dt.date.fromisoformat(q.as_of)
        except ValueError:
            problems.append(f"{where}: bad as_of {q.as_of}")
            continue
        if q.expect_abstain and (q.relevant or q.answer_spans):
            problems.append(f"{where}: abstain questions must have no relevant docs or answer spans")
        if not q.expect_abstain and not q.relevant:
            problems.append(f"{where}: answerable question needs relevant refs")
        if q.relevant and not q.answer_spans:
            problems.append(f"{where}: answerable question needs answer_spans")
        if q.expect_conflict and len(q.relevant) < 2:
            problems.append(f"{where}: conflict questions need >= 2 relevant refs")
        for ref in q.relevant:
            d = refs.get(ref)
            if d is None:
                problems.append(f"{where}: unknown relevant ref {ref}")
                continue
            acl = DocACL(d.tenant, d.classification, tuple(d.acl_groups), tuple(d.ethical_wall))
            if not can_read(user, acl, directory):
                problems.append(f"{where}: user {q.user} cannot read relevant {ref}")
            if not in_force(d, docs, as_of):
                problems.append(f"{where}: relevant {ref} is not in force on {q.as_of}")
        for span in q.answer_spans:
            if not any(span in refs[r].body for r in q.relevant if r in refs):
                problems.append(f"{where}: answer span {span!r} not found verbatim in relevant docs")
        for key in q.forbidden:
            if key not in keys:
                problems.append(f"{where}: unknown forbidden doc_key {key}")
                continue
            for d in (x for x in docs if x.doc_key == key):
                acl = DocACL(d.tenant, d.classification, tuple(d.acl_groups), tuple(d.ethical_wall))
                if can_read(user, acl, directory):
                    problems.append(f"{where}: forbidden {d.ref} is actually readable by {q.user}")
    return problems
