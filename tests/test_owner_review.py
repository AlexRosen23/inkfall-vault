"""The owner-review CSV and the label provenance must agree (30 reviewed, 54 not)."""
import csv
import json
from pathlib import Path

FDIR = Path(__file__).resolve().parents[1] / "eval" / "faithfulness"


def _rows():
    with (FDIR / "owner_review.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _labels():
    return [json.loads(line) for line in (FDIR / "labels.jsonl").read_text().splitlines() if line.strip()]


def test_owner_review_rows_are_all_filled_and_recorded():
    rows = _rows()
    assert len(rows) == 30
    for r in rows:
        assert r["owner_label (PASS/FAIL)"] in {"PASS", "FAIL"}
    agree = sum(r["owner_label (PASS/FAIL)"] == r["ai_label"] for r in rows)
    assert agree == 30


def test_label_provenance_matches_owner_sample():
    reviewed = {r["item_id"] for r in _rows()}
    labels = _labels()
    assert len(labels) == 84
    for lab in labels:
        expected = "confirmed by owner" if lab["item_id"] in reviewed else "not owner-reviewed"
        assert expected in lab["labeler"], lab["item_id"]
        assert "pending" not in lab["labeler"]
