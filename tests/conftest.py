"""Shared fixtures. A fresh seeded SQLite database is built once per test session in a temp dir;
tests that mutate data copy it first."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="inkfall-test-"))
os.environ["INKFALL_DATA_DIR"] = str(_TMP / "data")
os.environ["INKFALL_DB"] = str(_TMP / "base.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from inkfall import embed  # noqa: E402
from inkfall.api import create_app  # noqa: E402
from inkfall.corpus import load_seed_corpus  # noqa: E402
from inkfall.identities import load_directory  # noqa: E402
from inkfall.seed import seed  # noqa: E402

DENSE = embed.available()


@pytest.fixture(scope="session")
def directory():
    return load_directory()


@pytest.fixture(scope="session")
def corpus(directory):
    return load_seed_corpus(directory)


@pytest.fixture(scope="session")
def base_db() -> Path:
    path = _TMP / "base.db"
    seed(path, with_embeddings=DENSE, quiet=True)
    return path


@pytest.fixture()
def fresh_db(base_db, tmp_path) -> Path:
    """A private copy of the seeded database, made with SQLite's online backup API. A plain file copy would open and
    close base.db behind SQLite's back: on POSIX, closing any descriptor to a file drops every fcntl lock the
    process holds on it, including those of the shared app's open WAL connections. On the macOS CI runner, later
    connections then failed with "disk I/O error". A file copy would also miss pages still in the -wal file."""
    dst = tmp_path / "work.db"
    src, out = sqlite3.connect(base_db), sqlite3.connect(dst)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    return dst


@pytest.fixture(scope="session")
def shared_app(base_db):
    """Read-only app over the base DB (do not mutate documents through it)."""
    return create_app(base_db, rate_limit=100000)


@pytest.fixture(scope="session")
def client(shared_app):
    with TestClient(shared_app) as c:
        yield c


@pytest.fixture()
def fresh_client(fresh_db):
    with TestClient(create_app(fresh_db, rate_limit=100000)) as c:
        yield c


def login(client: TestClient, username: str) -> dict:
    r = client.post("/api/auth/login", json={"username": username})
    assert r.status_code == 200, r.text
    client.cookies.clear()  # tests authenticate explicitly with the bearer token
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def tokens(client, directory):
    return {u: login(client, u) for u in directory.users}
