"""Retrieval regression floor on the dev split (BM25 always; hybrid when the embedding model is present)."""

import datetime as dt

import pytest

from inkfall.db import make_engine, session_factory
from inkfall.gold import load_gold
from inkfall.service import run_query

from .conftest import DENSE


@pytest.mark.parametrize("method", ["bm25", "hybrid"])
def test_dev_split_mrr_floor(base_db, directory, method):
    if method == "hybrid" and not DENSE:
        pytest.skip("embedding model not downloaded")
    qs = [q for q in load_gold() if q.split == "dev" and q.relevant]
    S = session_factory(make_engine(base_db))
    rr = []
    with S() as s:
        for q in qs:
            res = run_query(s, directory.users[q.user], directory, q.question, dt.date.fromisoformat(q.as_of), method)
            ranked = res["ranked_refs"]
            rr.append(next((1 / (i + 1) for i, r in enumerate(ranked[:10]) if r in set(q.relevant)), 0.0))
        s.rollback()
    mrr = sum(rr) / len(rr)
    assert mrr >= 0.9, f"{method} dev MRR@10 regressed to {mrr:.3f}"
