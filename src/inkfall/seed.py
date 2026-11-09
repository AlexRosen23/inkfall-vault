"""`make seed`: rebuild the local SQLite database from the fictional corpus (idempotent, destructive
only to data/inkfall.db, which is generated and git-ignored)."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from sqlalchemy import select

from . import embed
from .config import EVAL_DIR, db_path
from .corpus import load_seed_corpus, manifest
from .db import Chunk, TenantRow, create_schema, make_engine, session_factory
from .identities import load_directory
from .ingest import seed_input, store_version
from .search import ensure_embeddings


def seed(path: Path | None = None, with_embeddings: bool = True, quiet: bool = False) -> dict:
    path = path or db_path()
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(path) + suffix)
        if p.exists():
            p.unlink()
    directory = load_directory()
    docs = load_seed_corpus(directory)
    engine = make_engine(path)
    create_schema(engine, sorted(directory.tenants))
    Session = session_factory(engine)
    t0 = time.perf_counter()
    with Session.begin() as s:
        for t in directory.tenants.values():
            s.add(TenantRow(id=t.id, name=t.name, kind=t.kind))
        s.flush()
        for d in sorted(docs, key=lambda d: (d.tenant, d.doc_key, d.version)):
            store_version(s, seed_input(d))
    embedded = 0
    embed_note = "skipped"
    if with_embeddings:
        if embed.available():
            with Session.begin() as s:
                ids = list(s.scalars(select(Chunk.id)))
                embedded = ensure_embeddings(s, ids)
            embed_note = f"{embedded} chunks embedded with {embed.EMBED_MODEL_ID}"
        else:
            embed_note = "embedding model not available; dense retrieval disabled until `make setup`"
    with Session() as s:
        n_chunks = len(list(s.scalars(select(Chunk.id))))
    man = manifest(docs)
    (EVAL_DIR / "dataset_manifest.json").write_text(json.dumps(man, indent=2) + "\n")
    info = {"db": str(path), "documents": len(docs), "chunks": n_chunks, "embeddings": embed_note,
            "dataset_version": man["dataset_version"], "seconds": round(time.perf_counter() - t0, 2)}
    if not quiet:
        print(json.dumps(info, indent=2))
    engine.dispose()
    return info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-embeddings", action="store_true")
    args = ap.parse_args()
    seed(with_embeddings=not args.no_embeddings)


if __name__ == "__main__":
    main()
