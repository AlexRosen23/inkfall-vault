"""Fixture identities, tenants and the classification ladder (corpus/identities.yaml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .config import CORPUS_DIR


@dataclass(frozen=True)
class Tenant:
    id: str
    name: str
    kind: str
    collections: tuple[str, ...]
    groups: tuple[str, ...]


@dataclass(frozen=True)
class User:
    username: str
    display_name: str
    tenant: str
    title: str
    roles: tuple[str, ...]
    groups: tuple[str, ...]
    clearance: str

    def has_role(self, role: str) -> bool:
        return role in self.roles


@dataclass(frozen=True)
class Directory:
    levels: tuple[str, ...]
    tenants: dict[str, Tenant] = field(default_factory=dict)
    users: dict[str, User] = field(default_factory=dict)

    def level(self, name: str) -> int:
        try:
            return self.levels.index(name)
        except ValueError as exc:  # unknown labels fail closed
            raise ValueError(f"unknown classification {name!r}") from exc


def load_directory(path: Path | None = None) -> Directory:
    path = path or (CORPUS_DIR / "identities.yaml")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    tenants = {
        t["id"]: Tenant(t["id"], t["name"], t["kind"], tuple(t["collections"]), tuple(t["groups"]))
        for t in raw["tenants"]
    }
    users: dict[str, User] = {}
    levels = tuple(raw["classification_levels"])
    for u in raw["users"]:
        user = User(
            username=u["username"],
            display_name=u["display_name"],
            tenant=u["tenant"],
            title=u.get("title", ""),
            roles=tuple(u.get("roles", [])),
            groups=tuple(u.get("groups", [])),
            clearance=u["clearance"],
        )
        if user.tenant not in tenants:
            raise ValueError(f"user {user.username} has unknown tenant {user.tenant}")
        bad = set(user.groups) - set(tenants[user.tenant].groups)
        if bad:
            raise ValueError(f"user {user.username} has groups outside its tenant: {sorted(bad)}")
        if user.clearance not in levels:
            raise ValueError(f"user {user.username} has unknown clearance {user.clearance}")
        users[user.username] = user
    return Directory(levels=levels, tenants=tenants, users=users)


@lru_cache(maxsize=1)
def directory() -> Directory:
    return load_directory()
