"""Load and validate the fictional seed corpus (corpus/<tenant>/*.md with YAML front matter)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import CORPUS_DIR
from .identities import Directory

DOC_TYPES = {
    "contract", "amendment", "sla", "schedule", "policy", "incident_note", "memo",
    "minutes", "engagement_letter", "notice", "report",
}
FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
DOC_KEY = re.compile(r"^[A-Z]{2}-[A-Z0-9-]{2,40}$")


class CorpusError(ValueError):
    pass


@dataclass
class SeedDoc:
    path: Path
    doc_key: str
    version: int
    title: str
    tenant: str
    collection: str
    doc_type: str
    classification: str
    acl_groups: list[str]
    ethical_wall: list[str]
    matter: str | None
    effective_date: dt.date
    amends: str | None
    retention: str
    parties: list[str]
    body: str
    tags: list[str] = field(default_factory=list)

    @property
    def ref(self) -> str:
        return f"{self.doc_key}@{self.version}"

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.body.encode("utf-8")).hexdigest()


def parse_front_matter(text: str) -> tuple[dict, str]:
    m = FRONT_MATTER.match(text)
    if not m:
        raise CorpusError("missing YAML front matter")
    meta = yaml.safe_load(m.group(1)) or {}
    if not isinstance(meta, dict):
        raise CorpusError("front matter is not a mapping")
    return meta, text[m.end():].lstrip("\n")


def _as_date(value) -> dt.date:
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def parse_seed_file(path: Path, directory: Directory) -> SeedDoc:
    meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
    required = ["doc_key", "version", "title", "tenant", "collection", "doc_type", "classification",
                "acl_groups", "effective_date", "retention"]
    missing = [k for k in required if k not in meta]
    if missing:
        raise CorpusError(f"{path.name}: missing fields {missing}")
    tenant = directory.tenants.get(meta["tenant"])
    if tenant is None:
        raise CorpusError(f"{path.name}: unknown tenant {meta['tenant']}")
    if path.parent.name != tenant.id:
        raise CorpusError(f"{path.name}: lives in {path.parent.name}/ but tenant is {tenant.id}")
    if not DOC_KEY.match(str(meta["doc_key"])):
        raise CorpusError(f"{path.name}: doc_key {meta['doc_key']!r} must look like CV-MSA-ORION")
    if meta["collection"] not in tenant.collections:
        raise CorpusError(f"{path.name}: collection {meta['collection']} not in tenant {tenant.id}")
    if meta["doc_type"] not in DOC_TYPES:
        raise CorpusError(f"{path.name}: doc_type {meta['doc_type']} not in {sorted(DOC_TYPES)}")
    directory.level(meta["classification"])
    groups = list(meta["acl_groups"] or [])
    if not groups or set(groups) - set(tenant.groups):
        raise CorpusError(f"{path.name}: acl_groups {groups} must be non-empty and from {tenant.groups}")
    wall = list(meta.get("ethical_wall") or [])
    for name in wall:
        u = directory.users.get(name)
        if u is None or u.tenant != tenant.id:
            raise CorpusError(f"{path.name}: ethical_wall user {name} unknown in tenant")
    if len(body.strip()) < 400:
        raise CorpusError(f"{path.name}: body too short ({len(body.strip())} chars)")
    return SeedDoc(
        path=path,
        doc_key=str(meta["doc_key"]),
        version=int(meta["version"]),
        title=str(meta["title"]),
        tenant=tenant.id,
        collection=str(meta["collection"]),
        doc_type=str(meta["doc_type"]),
        classification=str(meta["classification"]),
        acl_groups=groups,
        ethical_wall=wall,
        matter=meta.get("matter"),
        effective_date=_as_date(meta["effective_date"]),
        amends=meta.get("amends"),
        retention=str(meta["retention"]),
        parties=list(meta.get("parties") or []),
        tags=list(meta.get("tags") or []),
        body=body,
    )


def load_seed_corpus(directory: Directory, root: Path | None = None,
                     tenants: list[str] | None = None) -> list[SeedDoc]:
    root = root or CORPUS_DIR
    docs: list[SeedDoc] = []
    for tenant_id in sorted(tenants or directory.tenants):
        for path in sorted((root / tenant_id).glob("*.md")):
            docs.append(parse_seed_file(path, directory))
    seen: dict[str, Path] = {}
    keys = {d.doc_key: d for d in docs}
    for d in docs:
        if d.ref in seen:
            raise CorpusError(f"duplicate {d.ref} in {d.path.name} and {seen[d.ref].name}")
        seen[d.ref] = d.path
        if d.amends and d.amends not in keys:
            raise CorpusError(f"{d.path.name}: amends unknown doc_key {d.amends}")
        if d.amends and keys[d.amends].tenant != d.tenant:
            raise CorpusError(f"{d.path.name}: amends a document of another tenant")
    by_key: dict[str, list[SeedDoc]] = {}
    for d in docs:
        by_key.setdefault(d.doc_key, []).append(d)
    for key, versions in by_key.items():
        nums = sorted(v.version for v in versions)
        if nums != list(range(1, len(nums) + 1)):
            raise CorpusError(f"{key}: versions must be 1..n, got {nums}")
        ordered = sorted(versions, key=lambda v: v.version)
        for a, b in zip(ordered, ordered[1:], strict=False):
            if b.effective_date <= a.effective_date:
                raise CorpusError(f"{key}: v{b.version} must take effect after v{a.version}")
            if b.tenant != a.tenant:
                raise CorpusError(f"{key}: versions span tenants")
    return docs


def manifest(docs: list[SeedDoc]) -> dict:
    """Dataset manifest with per-file hashes and a dataset version hash for repeatability."""
    entries = [
        {
            "ref": d.ref, "tenant": d.tenant, "file": f"{d.tenant}/{d.path.name}", "doc_type": d.doc_type,
            "classification": d.classification, "effective_date": d.effective_date.isoformat(),
            "sha256": hashlib.sha256(d.path.read_bytes()).hexdigest(),
        }
        for d in docs
    ]
    digest = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
    return {"dataset": "inkfall-seed", "dataset_version": digest[:16], "documents": len(entries),
            "entries": entries}
