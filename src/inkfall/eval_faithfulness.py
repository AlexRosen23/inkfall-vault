"""Answer-faithfulness evaluation: generated answers, a binary LLM judge, and calibration against reference labels.

Method (Hamel Husain, "Using LLM-as-a-Judge", hamel.dev/blog/posts/llm-judge/): binary PASS/FAIL with a written
critique; reference labels split into judge-dev / judge-test; the judge prompt is tuned on judge-dev only and frozen
before it is run on judge-test; report the judge's true-positive rate (PASS recall) and true-negative rate (FAIL
recall) separately.

Criterion judged: **every claim in the answer is supported by the spans it cites.** It is not "the answer is correct"
or "the answer is complete"; those are reported separately with the deterministic gold-span metric.

Steps (each writes a saved file; nothing is hand-edited):

  python -m inkfall.eval_faithfulness generate   -> eval/reports/faithfulness_answers.json
  python -m inkfall.eval_faithfulness judge --split dev --prompt v1   -> eval/reports/faithfulness_judge_dev_v1.json
  python -m inkfall.eval_faithfulness judge --split test --prompt v2  -> eval/reports/faithfulness_judge_test_v2.json
  python -m inkfall.eval_faithfulness report --prompt v2  -> eval/reports/faithfulness.json (+ owner-review CSV)

Reference labels live in eval/faithfulness/labels.jsonl. They were written by an AI (Claude Code), NOT by a human
domain expert; every row says so, and agreement is reported as agreement with AI-drafted reference labels.
Limitation: the generator and the judge are the SAME local model (gpt-oss:20b) with different prompts, so they may
share blind spots (self-preference). See docs/RAG_EVALUATION.md.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import random
import re
import statistics
import subprocess
import time
from pathlib import Path

from .config import EVAL_DIR, ROOT, db_path
from .db import make_engine, session_factory
from .evidence import Passage
from .generate import support_level
from .gold import load_gold
from .identities import load_directory
from .providers import OpenAICompatible, get_provider, parse_json_block
from .service import run_query, verify_citation

REPORTS = EVAL_DIR / "reports"
FDIR = EVAL_DIR / "faithfulness"
ANSWERS = REPORTS / "faithfulness_answers.json"
LABELS = FDIR / "labels.jsonl"
LABELER = "claude-code (AI), pending owner review"

# Fabricated claims for synthetic negatives (none of these facts exists in the fictional corpus; checked by the
# reference labeler item by item). Picked deterministically per item.
FABRICATED = [
    "This obligation also binds every affiliate of both parties.",
    "Any change to it requires approval by both boards of directors.",
    "The provision was added after a regulator's audit finding.",
    "Breach of this term allows immediate termination without notice.",
    "The same term applies to all of the counterparty's other contracts.",
]
NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,  # noqa: S607
                              text=True, check=False).stdout.strip()
    except OSError:
        return ""


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


# ------------------------------------------------------------------------------------------------ generate

def _item_from_result(q, res: dict) -> dict | None:
    if res["mode"] != "generative" or not res["answer"]:
        return None
    srcs = {p["pid"]: p for p in res["sources"]}
    sents = []
    for a in res["answer"]:
        cited = []
        for c in a["citations"]:
            p = srcs[c["pid"]]
            cited.append({"pid": c["pid"], "ref": c["ref"], "version_id": c["version_id"],
                          "passage_start": p["char_start"], "passage_end": p["char_end"], "passage_text": p["text"],
                          "anchor_start": c["char_start"], "anchor_end": c["char_end"], "anchor_quote": c["quote"]})
        sents.append({"text": a["text"], "support": a["support"], "notes": a["notes"], "cited": cited})
    return {"item_id": q.id, "qid": q.id, "split": q.split, "category": q.category, "kind": "natural",
            "user": q.user, "as_of": q.as_of, "question": q.question, "status": res["status"],
            "sentences": sents, "gold_answer_spans": q.answer_spans,
            "gold_span_in_answer": any(sp in " ".join(s["text"] for s in sents) for sp in q.answer_spans),
            "generation": {k: res["generation"].get(k) for k in ("model", "provider", "latency_ms", "usage_reported")}}


def _perturb_number(item: dict, rng: random.Random) -> dict | None:
    for i, s in enumerate(item["sentences"]):
        m = NUM.search(s["text"])
        if not m or not s["cited"]:
            continue
        old = m.group(0)
        digits = old.replace(",", "")
        try:
            val = float(digits)
        except ValueError:
            continue
        new_val = val * rng.choice([2, 3]) + rng.choice([1, 5]) if val < 1000 else val * 1.5
        new = f"{new_val:g}" if "." in old else f"{int(new_val):,}" if "," in old else str(int(new_val))
        out = json.loads(json.dumps(item))
        out["sentences"][i]["text"] = s["text"][:m.start()] + new + s["text"][m.end():]
        out["item_id"], out["kind"] = item["item_id"] + "~num", "synthetic-number"
        out["perturbation"] = f"sentence {i + 1}: {old} -> {new}"
        return out
    return None


def _perturb_claim(item: dict, rng: random.Random) -> dict:
    out = json.loads(json.dumps(item))
    last = out["sentences"][-1]
    claim = rng.choice(FABRICATED)
    out["sentences"].append({"text": claim, "support": None, "notes": [], "cited": last["cited"]})
    out["item_id"], out["kind"] = item["item_id"] + "~claim", "synthetic-claim"
    out["perturbation"] = f"appended fabricated sentence citing the same passages: {claim!r}"
    return out


def _rescore(item: dict) -> None:
    """Deterministic span-support (generate.support_level) for every sentence, incl. perturbed ones."""
    for s in item["sentences"]:
        cited = [Passage(c["pid"], 0, c["version_id"], c["ref"], "", "", "", c["passage_start"], c["passage_end"],
                         c["passage_text"], 0, {}, "", True, None, None, "", "") for c in s["cited"]]
        if not cited:
            s["support"], s["notes"] = "unsupported", ["no citation"]
            continue
        s["support"], s["notes"] = support_level(s["text"], cited)


def generate(backend: str, synthetic_every: int = 3) -> dict:
    prov = get_provider(backend)
    if prov is None:
        raise SystemExit(f"no local backend '{backend}' detected; nothing run")
    directory = load_directory()
    S = session_factory(make_engine(db_path()))
    items, skipped, t0 = [], [], time.perf_counter()
    import inkfall.service as service
    orig = service.get_provider
    service.get_provider = lambda preferred=None: prov
    try:
        for q in load_gold():
            if q.split not in ("dev", "test"):
                continue
            with S() as s:
                res = run_query(s, directory.users[q.user], directory, q.question, dt.date.fromisoformat(q.as_of),
                                "hybrid", generate_mode=backend)
                # re-verify every citation against stored text + the asker's ACL (the existing validator)
                bad = 0
                for a in res["answer"]:
                    for c in a["citations"]:
                        ok, _ = verify_citation(s, directory.users[q.user], directory, c["version_id"],
                                                c["char_start"], c["char_end"], c["quote"])
                        bad += int(not ok)
                s.rollback()
            it = _item_from_result(q, res)
            if it is None:
                g = res["generation"]
                skipped.append({"qid": q.id, "split": q.split, "reason": "abstained before generation" if res["abstained"]
                                else f"generation {g.get('status')}: {g.get('rejected_reason')}"})
                print(q.id, "skipped", skipped[-1]["reason"], flush=True)
                continue
            it["citations_failing_reverification"] = bad
            items.append(it)
            print(q.id, q.split, res["status"], it["generation"]["latency_ms"], "ms",
                  [s["support"] for s in it["sentences"]], flush=True)
    finally:
        service.get_provider = orig
    # deterministic synthetic negatives on every Nth natural item (seeded), alternating number / claim perturbation
    rng = random.Random(20261109)
    synth = []
    for n, it in enumerate(items):
        if n % synthetic_every:
            continue
        p = _perturb_number(it, rng) if (n // synthetic_every) % 2 == 0 else None
        synth.append(p or _perturb_claim(it, rng))
    for it in synth:
        _rescore(it)
    out = {"generated_at": _now(),
           "provenance": {"git_commit": _commit(), "command": f"python -m inkfall.eval_faithfulness generate --backend {backend}",
                          "generator": {"provider": prov.name, "model": getattr(prov, "model", "?")},
                          "retrieval": "hybrid", "wall_seconds": round(time.perf_counter() - t0, 1),
                          "synthetic_note": "synthetic-* items are deterministic perturbations of natural answers "
                                            "(seed 20261109) added so the judge's true-negative rate can be measured; "
                                            "they are reported separately from natural answers."},
           "items": items + synth, "skipped": skipped}
    ANSWERS.write_text(json.dumps(out, indent=1) + "\n")
    print(f"natural answers: {len(items)}, synthetic: {len(synth)}, skipped: {len(skipped)}")
    return out


# ------------------------------------------------------------------------------------------------ judge

def judge_prompt(version: str) -> str:
    return (FDIR / f"judge_prompt_{version}.txt").read_text(encoding="utf-8")


def render_for_judge(item: dict) -> str:
    """What the judge sees: the question, each answer sentence, and the exact text of every span it cites."""
    parts = [f"Question: {item['question']}", "", "Answer sentences and the spans each one cites:"]
    for i, s in enumerate(item["sentences"], 1):
        parts.append(f"\n[S{i}] {s['text']}")
        if not s["cited"]:
            parts.append("  (cites nothing)")
        seen = set()
        for c in s["cited"]:
            if c["pid"] in seen:
                continue
            seen.add(c["pid"])
            parts.append(f'  <span id="{c["pid"]}" source="{c["ref"]}">\n{c["passage_text"].strip()}\n  </span>')
    return "\n".join(parts)


def run_judge(item: dict, prompt: str, judge: OpenAICompatible) -> dict:
    raw, meta = judge.complete(prompt, render_for_judge(item), max_tokens=4096)
    try:
        d = parse_json_block(raw)
        verdict = str(d.get("verdict", "")).strip().upper()
        critique = str(d.get("critique", ""))[:1200]
    except (ValueError, TypeError):
        verdict, critique = "", ""
    if verdict not in ("PASS", "FAIL"):
        # Unparseable judge output counts as FAIL (fail closed) and is reported.
        return {"verdict": "FAIL", "critique": "unparseable judge output", "parse_error": True,
                "latency_ms": round(meta.get("latency_ms", 0.0), 1), "raw": raw[:1500]}
    return {"verdict": verdict, "critique": critique, "parse_error": False,
            "latency_ms": round(meta.get("latency_ms", 0.0), 1),
            "tokens": (meta.get("usage") or {}).get("total_tokens", 0)}


def judge(split: str, version: str, backend: str) -> dict:
    data = json.loads(ANSWERS.read_text())
    info = next((p for p in __import__("inkfall.providers", fromlist=["detect"]).detect()
                 if p.name == backend and p.available), None)
    if info is None:
        raise SystemExit(f"no local backend '{backend}' detected; nothing run")
    model = data["provenance"]["generator"]["model"]
    j = OpenAICompatible(info.name, info.base_url, model)
    prompt = judge_prompt(version)
    rows, t0 = [], time.perf_counter()
    for it in data["items"]:
        if it["split"] != split:
            continue
        r = run_judge(it, prompt, j)
        rows.append({"item_id": it["item_id"], "kind": it["kind"], **r})
        print(it["item_id"], r["verdict"], r["latency_ms"], "ms", flush=True)
    out = {"generated_at": _now(),
           "provenance": {"git_commit": _commit(), "command": f"python -m inkfall.eval_faithfulness judge --split {split} "
                                                              f"--prompt {version} --backend {backend}",
                          "judge": {"provider": backend, "model": model, "prompt_version": version,
                                    "prompt_file": f"eval/faithfulness/judge_prompt_{version}.txt"},
                          "answers_file": "eval/reports/faithfulness_answers.json",
                          "answers_generated_at": data["generated_at"],
                          "wall_seconds": round(time.perf_counter() - t0, 1),
                          "limitation": "judge and generator are the same model (different prompts)"},
           "rows": rows}
    (REPORTS / f"faithfulness_judge_{split}_{version}.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


# ------------------------------------------------------------------------------------------------ report

def load_labels() -> dict[str, dict]:
    out = {}
    for line in LABELS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["item_id"]] = r
    return out


def confusion(pairs: list[tuple[str, str]]) -> dict:
    """pairs = (reference, predicted). Positive class = PASS (faithful)."""
    tp = sum(r == "PASS" and p == "PASS" for r, p in pairs)
    fn = sum(r == "PASS" and p == "FAIL" for r, p in pairs)
    tn = sum(r == "FAIL" and p == "FAIL" for r, p in pairs)
    fp = sum(r == "FAIL" and p == "PASS" for r, p in pairs)
    return {"n": len(pairs), "ref_pass": tp + fn, "ref_fail": tn + fp, "tp": tp, "fn": fn, "tn": tn, "fp": fp,
            "tpr": round(tp / (tp + fn), 3) if tp + fn else None,
            "tnr": round(tn / (tn + fp), 3) if tn + fp else None,
            "agreement": round((tp + tn) / len(pairs), 3) if pairs else None}


def deterministic_verdict(item: dict) -> str:
    """Code grader: PASS only when every sentence is 'supported' by the lexical+numeric span check."""
    return "PASS" if all(s["support"] == "supported" for s in item["sentences"]) else "FAIL"


def corrected_pass_rate(observed: float, tpr: float | None, tnr: float | None) -> float | None:
    """Rogan-Gladen correction of the judge's raw PASS rate using its measured TPR/TNR (clipped to [0, 1])."""
    if tpr is None or tnr is None or tpr + tnr - 1 <= 0:
        return None
    return round(min(1.0, max(0.0, (observed + tnr - 1) / (tpr + tnr - 1))), 3)


def report(version: str, dev_versions: list[str]) -> dict:
    data = json.loads(ANSWERS.read_text())
    items = {it["item_id"]: it for it in data["items"]}
    labels = load_labels()
    jt = json.loads((REPORTS / f"faithfulness_judge_test_{version}.json").read_text())
    jd = {v: json.loads((REPORTS / f"faithfulness_judge_dev_{v}.json").read_text()) for v in dev_versions}

    def block(judge_rows: list[dict], split: str) -> dict:
        jr = {r["item_id"]: r for r in judge_rows}
        out = {}
        for subset, keep in [("all", lambda it: True), ("natural", lambda it: it["kind"] == "natural"),
                             ("synthetic", lambda it: it["kind"] != "natural")]:
            ids = [i for i, it in items.items() if it["split"] == split and keep(it) and i in labels and i in jr]
            out[subset] = {"judge": confusion([(labels[i]["label"], jr[i]["verdict"]) for i in ids]),
                           "deterministic": confusion([(labels[i]["label"], deterministic_verdict(items[i])) for i in ids])}
        return out

    test_block = block(jt["rows"], "test")
    nat_test = [i for i, it in items.items() if it["split"] == "test" and it["kind"] == "natural"]
    jr_test = {r["item_id"]: r for r in jt["rows"]}
    judge_pass_rate = (sum(jr_test[i]["verdict"] == "PASS" for i in nat_test if i in jr_test) / len(nat_test)
                       if nat_test else 0.0)
    ref_pass_rate = (sum(labels[i]["label"] == "PASS" for i in nat_test if i in labels) / len(nat_test)
                     if nat_test else 0.0)
    nat = [it for it in items.values() if it["kind"] == "natural"]
    sents = [s for it in nat for s in it["sentences"]]
    det = {
        "natural_answers": len(nat),
        "sentences": len(sents),
        "sentence_support": {k: sum(s["support"] == k for s in sents) for k in ("supported", "partial", "unsupported")},
        "answers_all_sentences_supported": sum(deterministic_verdict(it) == "PASS" for it in nat),
        "answers_with_gold_span": sum(it["gold_span_in_answer"] for it in nat),
        "citations_reverified_ok": sum(len(s["cited"]) for s in sents) - sum(it.get("citations_failing_reverification", 0)
                                                                               for it in nat),
        "citations_total": sum(len(s["cited"]) for s in sents),
        "skipped_questions": len(data["skipped"]),
    }
    gen_lat = [it["generation"]["latency_ms"] for it in nat if it["generation"].get("latency_ms")]
    judge_lat = [r["latency_ms"] for r in jt["rows"] if r.get("latency_ms")]
    out = {
        "generated_at": _now(),
        "provenance": {"git_commit": _commit(), "command": f"python -m inkfall.eval_faithfulness report --prompt {version}",
                       "answers_file": "eval/reports/faithfulness_answers.json",
                       "answers_generated_at": data["generated_at"], "generator": data["provenance"]["generator"],
                       "judge_test_file": f"eval/reports/faithfulness_judge_test_{version}.json",
                       "judge_prompt": f"eval/faithfulness/judge_prompt_{version}.txt",
                       "labels_file": "eval/faithfulness/labels.jsonl", "labeler": LABELER,
                       "same_model_limitation": "The judge and the generator are the same local model "
                                                f"({data['provenance']['generator']['model']}) with different prompts."},
        "criterion": "every claim in the answer is supported by the spans it cites (binary PASS/FAIL)",
        "positive_class": "PASS",
        "dev_iterations": {v: block(jd[v]["rows"], "dev") for v in dev_versions},
        "test": test_block,
        "test_pass_rates_natural": {"reference_labels": round(ref_pass_rate, 3), "judge_raw": round(judge_pass_rate, 3),
                                    "judge_corrected": corrected_pass_rate(judge_pass_rate, test_block["all"]["judge"]["tpr"],
                                                                           test_block["all"]["judge"]["tnr"])},
        "deterministic_metrics_natural": det,
        "judge_parse_errors_test": sum(r.get("parse_error", False) for r in jt["rows"]),
        "latency_ms": {"generation_p50": round(statistics.median(gen_lat), 1) if gen_lat else None,
                       "generation_max": round(max(gen_lat), 1) if gen_lat else None,
                       "judge_p50": round(statistics.median(judge_lat), 1) if judge_lat else None},
        "label_counts": {"total": len(labels), "pass": sum(r["label"] == "PASS" for r in labels.values()),
                         "fail": sum(r["label"] == "FAIL" for r in labels.values())},
    }
    (REPORTS / "faithfulness.json").write_text(json.dumps(out, indent=1) + "\n")
    write_owner_review(items, labels, jr_test | {r["item_id"]: r for v in dev_versions[-1:] for r in jd[v]["rows"]})
    return out


def write_owner_review(items: dict, labels: dict, judge_rows: dict, n: int = 30) -> Path:
    """A fixed, seeded sample for the owner to confirm or correct the AI-drafted labels."""
    rng = random.Random(7)
    ids = sorted(i for i in labels if i in items)
    fails = [i for i in ids if labels[i]["label"] == "FAIL"]
    passes = [i for i in ids if labels[i]["label"] == "PASS"]
    pick = rng.sample(fails, min(len(fails), n // 2))
    pick += rng.sample(passes, min(len(passes), n - len(pick)))
    path = FDIR / "owner_review.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["item_id", "split", "kind", "question", "answer_and_cited_spans", "ai_label", "ai_critique",
                    "judge_verdict", "judge_critique", "owner_label (PASS/FAIL)", "owner_note"])
        for i in sorted(pick):
            it, lab, jr = items[i], labels[i], judge_rows.get(i, {})
            w.writerow([i, it["split"], it["kind"], it["question"], render_for_judge(it), lab["label"], lab["critique"],
                        jr.get("verdict", ""), jr.get("critique", ""), "", ""])
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--backend", default="ollama")
    jg = sub.add_parser("judge")
    jg.add_argument("--split", choices=["dev", "test"], required=True)
    jg.add_argument("--prompt", required=True)
    jg.add_argument("--backend", default="ollama")
    r = sub.add_parser("report")
    r.add_argument("--prompt", required=True, help="frozen prompt version used on judge-test")
    r.add_argument("--dev-versions", default="", help="comma list of prompt versions tried on judge-dev")
    a = ap.parse_args()
    if a.cmd == "generate":
        generate(a.backend)
    elif a.cmd == "judge":
        out = judge(a.split, a.prompt, a.backend)
        if LABELS.exists():
            labels = load_labels()
            pairs = [(labels[r["item_id"]]["label"], r["verdict"]) for r in out["rows"] if r["item_id"] in labels]
            print(json.dumps(confusion(pairs)))
    else:
        rep = report(a.prompt, [v for v in a.dev_versions.split(",") if v] or [a.prompt])
        print(json.dumps(rep["test"]["all"]["judge"]), json.dumps(rep["deterministic_metrics_natural"]))


if __name__ == "__main__":
    main()
