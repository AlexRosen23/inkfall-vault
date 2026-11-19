"""The owner's decision on the one label the AI second review flagged (LF-010) is recorded in the owner-review format."""
import csv
import json
from pathlib import Path

FDIR = Path(__file__).resolve().parents[1] / "eval" / "faithfulness"
COLUMNS = ["item_id", "split", "kind", "question", "answer_and_cited_spans", "ai_label", "ai_critique",
           "judge_verdict", "judge_critique", "owner_label (PASS/FAIL)", "owner_note"]


def _rows(name):
    with (FDIR / name).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_flagged_decision_uses_the_owner_review_columns():
    with (FDIR / "owner_review_flagged.csv").open(newline="", encoding="utf-8") as f:
        assert next(csv.reader(f)) == COLUMNS
    with (FDIR / "owner_review.csv").open(newline="", encoding="utf-8") as f:
        assert next(csv.reader(f)) == COLUMNS


def test_flagged_rows_are_exactly_the_second_review_disagreements_and_decided():
    flagged = {r["item_id"] for r in _rows("ai_second_review.csv") if r["agrees"] != "yes"}
    rows = _rows("owner_review_flagged.csv")
    assert {r["item_id"] for r in rows} == flagged == {"LF-010"}
    assert not flagged & {r["item_id"] for r in _rows("owner_review.csv")}
    labels = {r["item_id"]: r for r in (json.loads(x) for x in (FDIR / "labels.jsonl").read_text().splitlines() if x.strip())}
    for r in rows:
        assert r["owner_label (PASS/FAIL)"] == "FAIL"
        assert r["ai_label"] == labels[r["item_id"]]["label"]
        assert "$680" in r["owner_note"] and "$650" in r["owner_note"]
