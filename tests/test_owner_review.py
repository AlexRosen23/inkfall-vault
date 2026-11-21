"""The owner-review CSV and the label provenance must agree (30 reviewed, 1 owner-decided flag, 53 not)."""
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


def _decided():
    with (FDIR / "owner_review_flagged.csv").open(newline="", encoding="utf-8") as f:
        return {r["item_id"] for r in csv.DictReader(f)}


def test_label_provenance_matches_owner_sample():
    reviewed, decided = {r["item_id"] for r in _rows()}, _decided()
    labels = _labels()
    assert len(labels) == 84
    for lab in labels:
        expected = ("confirmed by owner" if lab["item_id"] in reviewed
                    else "owner decision" if lab["item_id"] in decided else "not owner-reviewed")
        assert expected in lab["labeler"], lab["item_id"]
        assert "pending" not in lab["labeler"]


def test_report_keeps_the_owner_sample_when_labels_change(tmp_path, monkeypatch):
    """Re-running the report after a label change must not reshuffle the 30 items the owner already reviewed."""
    from inkfall import eval_faithfulness as ef

    src = (FDIR / "owner_review.csv").read_text(encoding="utf-8")
    (tmp_path / "owner_review.csv").write_text(src, encoding="utf-8")
    monkeypatch.setattr(ef, "FDIR", tmp_path)
    items = {it["item_id"]: it for it in json.loads(ef.ANSWERS.read_text())["items"]}
    labels = ef.load_labels()
    for lab in labels.values():  # flip every label: an unfrozen sample would come out different
        lab["label"] = "PASS" if lab["label"] == "FAIL" else "FAIL"
    ef.write_owner_review(items, labels, {})
    with (tmp_path / "owner_review.csv").open(newline="", encoding="utf-8") as f:
        after = {r["item_id"]: r["owner_label (PASS/FAIL)"] for r in csv.DictReader(f)}
    assert after == {r["item_id"]: r["owner_label (PASS/FAIL)"] for r in _rows()}
