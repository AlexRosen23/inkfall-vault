"""The AI second review covers exactly the 54 labels outside the owner's 30-item sample, and says it is not human."""
import csv
import json
from pathlib import Path

FDIR = Path(__file__).resolve().parents[1] / "eval" / "faithfulness"
REVIEWER = "claude (independent AI re-check, 2026-11-16; not a human review)"
COLUMNS = ["item_id", "drafted_label", "second_review_label", "agrees", "reason", "reviewer"]


def _csv(name):
    with (FDIR / name).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _labels():
    return {r["item_id"]: r for r in (json.loads(line) for line in (FDIR / "labels.jsonl").read_text().splitlines()
                                      if line.strip())}


def test_second_review_covers_exactly_the_non_owner_items():
    labels = _labels()
    owner = {r["item_id"] for r in _csv("owner_review.csv")}
    rows = _csv("ai_second_review.csv")
    ids = [r["item_id"] for r in rows]
    assert len(ids) == len(set(ids)) == 54
    assert set(ids) == set(labels) - owner
    assert not set(ids) & owner


def test_second_review_rows_are_consistent_and_labelled_as_ai():
    labels = _labels()
    with (FDIR / "ai_second_review.csv").open(newline="", encoding="utf-8") as f:
        assert next(csv.reader(f)) == COLUMNS
    for r in _csv("ai_second_review.csv"):
        assert r["drafted_label"] == labels[r["item_id"]]["label"], r["item_id"]
        assert r["second_review_label"] in {"PASS", "FAIL"}
        assert r["agrees"] == ("yes" if r["second_review_label"] == r["drafted_label"] else "no")
        assert r["reason"].strip()
        assert r["reviewer"] == REVIEWER
        # The second review is an AI pass: it must never be recorded as an owner or human review.
        assert "confirmed by owner" not in labels[r["item_id"]]["labeler"]
