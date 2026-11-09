"""Validate the seed corpus and gold questions. Exit 1 on any problem.

Usage: uv run python scripts/validate_dataset.py [--tenant corvane]
"""

from __future__ import annotations

import argparse
import collections
import sys

from inkfall.corpus import CorpusError, load_seed_corpus
from inkfall.gold import load_gold, validate_gold
from inkfall.identities import load_directory


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", help="only report questions for this tenant prefix (LF, CV, PM, XT)")
    args = ap.parse_args()
    directory = load_directory()
    try:
        prefix = {"LF": "lanternfield", "CV": "corvane", "PM": "pellmoor"}
        only = [prefix[args.tenant.upper()]] if args.tenant and args.tenant.upper() in prefix else None
        docs = load_seed_corpus(directory, tenants=only)
    except CorpusError as exc:
        print(f"CORPUS ERROR: {exc}")
        return 1
    questions = load_gold()
    if args.tenant:
        questions = [q for q in questions if q.id.startswith(args.tenant.upper())]
    problems = validate_gold(questions, docs, directory)
    by_tenant = collections.Counter(d.tenant for d in docs)
    cats = collections.Counter(q.category for q in questions)
    print(f"documents: {len(docs)} {dict(by_tenant)}")
    print(f"questions: {len(questions)} {dict(sorted(cats.items()))}")
    print(f"abstain: {sum(q.expect_abstain for q in questions)}  conflict: {sum(q.expect_conflict for q in questions)}"
          f"  splits: {dict(collections.Counter(q.split for q in questions))}")
    for p in problems:
        print("PROBLEM:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
