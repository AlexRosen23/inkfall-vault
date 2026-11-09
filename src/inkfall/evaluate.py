"""`make eval`: run the gold set through every retrieval method and write a provenance-stamped report.

Grading is deterministic (see docs/RAG_EVALUATION.md):
- Retrieval: document-version level against gold `relevant` refs: recall@5, precision@5, hit@5, MRR@10, nDCG@10.
- Citation validity: each cited quote must equal stored text[start:end] of a version the asker may read.
- Answer support: a non-abstained answer is "supported" when at least one gold answer span appears
  verbatim inside its cited sentences; otherwise it counts toward the unsupported-answer rate.
- Abstention: positive class = "should abstain"; precision/recall/F1.
- Conflicts: detection rate on expect_conflict questions; false-alarm rate on other answerable ones.
- Leaks: any ref outside the asker's authorized set, or any gold `forbidden` doc key, anywhere in a
  response (ranked list, sources, citations, graph) counts as one leak.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import platform
import statistics
import subprocess
import time
from pathlib import Path

from sqlalchemy.orm import Session

from . import embed
from .access import authorized_versions
from .config import EVAL_DIR, ROOT, db_path
from .db import make_engine, session_factory
from .gold import GoldQuestion, load_gold
from .identities import Directory, load_directory
from .search import content_terms, stem, tokens
from .service import run_query

K = 5


def _ndcg(ranked: list[str], relevant: set[str], k: int = 10) -> float:
    dcg = sum(1 / math.log2(i + 2) for i, r in enumerate(ranked[:k]) if r in relevant)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return dcg / idcg if idcg else 0.0


def _mrr(ranked: list[str], relevant: set[str], k: int = 10) -> float:
    for i, r in enumerate(ranked[:k]):
        if r in relevant:
            return 1 / (i + 1)
    return 0.0


def title_baseline(session: Session, user, directory: Directory, q: GoldQuestion) -> list[str]:
    """No-RAG baseline: rank authorized documents by query-term overlap with their *titles* only,
    approximating a person browsing a document library by name."""
    views = authorized_versions(session, user, directory, dt.date.fromisoformat(q.as_of))
    qs = {stem(t) for t in content_terms(q.question)}
    scored = []
    for v in views:
        ts = {stem(t) for t in tokens(v.version.title + " " + v.document.doc_key.replace("-", " "))}
        scored.append((len(qs & ts), v.version.effective_date.toordinal(), v.ref))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [r for s, _, r in scored if s > 0]


def _all_refs(res: dict) -> set[str]:
    refs = set(res.get("ranked_refs", []))
    refs |= {s["ref"] for s in res.get("sources", [])}
    refs |= {c["ref"] for a in res.get("answer", []) for c in a["citations"]}
    refs |= {n["label"] for n in res.get("graph", {}).get("nodes", []) if n.get("kind") == "document"}
    return refs


def evaluate_question(session: Session, directory: Directory, q: GoldQuestion, method: str,
                      readable: dict[str, set[str]]) -> dict:
    user = directory.users[q.user]
    t0 = time.perf_counter()
    error = None
    try:
        res = run_query(session, user, directory, q.question, dt.date.fromisoformat(q.as_of), method)
    except Exception as exc:  # noqa: BLE001 - recorded as an error-rate datapoint
        error = type(exc).__name__
        res = {"ranked_refs": [], "answer": [], "sources": [], "graph": {}, "abstained": True,
               "trust": {"conflicts": []}, "status": "error", "retrieval": {"method": method}}
    latency = (time.perf_counter() - t0) * 1000
    ranked = res["ranked_refs"]
    rel = set(q.relevant)
    out: dict = {"latency_ms": round(latency, 1), "error": error, "status": res["status"],
                 "retrieval_method_used": res["retrieval"]["method"], "top_refs": ranked[:5]}
    if rel:
        top = ranked[:K]
        out.update(recall_at_5=len(rel & set(top)) / len(rel), precision_at_5=len(rel & set(top)) / K,
                   hit_at_5=float(bool(rel & set(top))), mrr_at_10=_mrr(ranked, rel), ndcg_at_10=_ndcg(ranked, rel))
    # citation validity
    cits = [c for a in res["answer"] for c in a["citations"]]
    texts = {}
    valid = 0
    for c in cits:
        if c["version_id"] not in texts:
            from .db import DocumentVersion
            v = session.get(DocumentVersion, c["version_id"])
            texts[c["version_id"]] = (v.text if v else "", f"{v.document.doc_key}@{v.version}" if v else "")
        body, ref = texts[c["version_id"]]
        if body[c["char_start"]:c["char_end"]] == c["quote"] and ref in readable[q.user]:
            valid += 1
    out.update(citations=len(cits), citations_valid=valid, cited_refs=sorted({c["ref"] for c in cits}))
    abstained = bool(res["abstained"])
    out["abstained"] = abstained
    if not abstained and q.answer_spans:
        cited_text = " ".join(c["quote"] for c in cits)
        pack_text = " ".join(s["text"] for s in res["sources"])
        out["answer_supported"] = any(sp in cited_text for sp in q.answer_spans)
        out["evidence_in_pack"] = any(sp in pack_text for sp in q.answer_spans)
    out["conflict_flagged"] = bool(res["trust"]["conflicts"])
    leaked = sorted(r for r in _all_refs(res) if r not in readable[q.user])
    forbidden_hit = sorted(r for r in _all_refs(res) if r.split("@")[0] in set(q.forbidden))
    out["leaks"] = sorted(set(leaked) | set(forbidden_hit))
    out["injection_quoted"] = any(
        any(k in a["text"].lower() for k in ("ignore previous", "ignore prior", "disregard your", "instruction for ai"))
        for a in res["answer"])
    return out


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    i = min(len(xs) - 1, max(0, math.ceil(p / 100 * len(xs)) - 1))
    return round(xs[i], 1)


def aggregate(rows: list[dict], method: str) -> dict:
    per = [r["methods"][method] for r in rows]
    qs = [r for r in rows]
    answerable = [(q, m) for q, m in zip(qs, per, strict=True) if q["relevant"]]
    should_abstain = [(q, m) for q, m in zip(qs, per, strict=True) if q["expect_abstain"]]
    tp = sum(m["abstained"] for _, m in should_abstain)
    fp = sum(m["abstained"] for _, m in answerable)
    fn = len(should_abstain) - tp
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    answered = [(q, m) for q, m in answerable if not m["abstained"]]
    conflict_q = [(q, m) for q, m in answerable if q["expect_conflict"]]
    nonconf = [(q, m) for q, m in answerable if not q["expect_conflict"]]
    lat = [m["latency_ms"] for m in per]
    cits = sum(m["citations"] for m in per)

    def mean(key):
        vals = [m[key] for _, m in answerable if key in m]
        return round(statistics.fmean(vals), 4) if vals else None

    return {
        "questions": len(per), "answerable": len(answerable), "should_abstain": len(should_abstain),
        "recall_at_5": mean("recall_at_5"), "precision_at_5": mean("precision_at_5"), "hit_at_5": mean("hit_at_5"),
        "mrr_at_10": mean("mrr_at_10"), "ndcg_at_10": mean("ndcg_at_10"),
        "citations": cits, "citation_validity": round(sum(m["citations_valid"] for m in per) / cits, 4) if cits else None,
        "answered_answerable": len(answered),
        "answer_support_rate": round(sum(m.get("answer_supported", False) for _, m in answered) / len(answered), 4)
        if answered else None,
        "unsupported_answer_rate": round(1 - sum(m.get("answer_supported", False) for _, m in answered) / len(answered), 4)
        if answered else None,
        "evidence_in_pack_rate": round(sum(m.get("evidence_in_pack", False) for _, m in answered) / len(answered), 4)
        if answered else None,
        "abstention": {"precision": round(prec, 4), "recall": round(rec, 4),
                       "f1": round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0,
                       "false_abstain_on_answerable": fp, "missed_abstain": fn},
        "conflicts": {"expected": len(conflict_q), "flagged": sum(m["conflict_flagged"] for _, m in conflict_q),
                      "false_alarms_on_other_answerable": sum(m["conflict_flagged"] for _, m in nonconf),
                      "other_answerable": len(nonconf)},
        "leaks": sum(len(m["leaks"]) for m in per),
        "injection_sentences_quoted": sum(m["injection_quoted"] for m in per),
        "errors": sum(1 for m in per if m["error"]),
        "latency_ms": {"p50": _pct(lat, 50), "p95": _pct(lat, 95), "max": round(max(lat), 1) if lat else 0.0},
        "throughput_qps_sequential": round(len(lat) / (sum(lat) / 1000), 2) if lat else 0.0,
    }


def machine() -> dict:
    def sh(*cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False).stdout.strip()
        except OSError:
            return ""
    mem = sh("sysctl", "-n", "hw.memsize")
    return {"platform": platform.platform(), "machine": platform.machine(),
            "cpu": sh("sysctl", "-n", "machdep.cpu.brand_string") or platform.processor(),
            "memory_gb": round(int(mem) / 2**30) if mem.isdigit() else None,
            "python": platform.python_version(), "device": "cpu"}


def run(methods: list[str], split: str | None = None, out: Path | None = None) -> dict:
    directory = load_directory()
    questions = [q for q in load_gold() if split in (None, "all") or q.split == split]
    S = session_factory(make_engine(db_path()))
    avail = {"bm25": True, "dense": embed.available(), "hybrid": embed.available(),
             "rerank": embed.available() and embed.reranker_available()}
    ran = [m for m in methods if avail.get(m)]
    skipped = {m: ("embedding model not downloaded" if m in ("dense", "hybrid") else
                   "cross-encoder not downloaded (opt-in: make rerank-model)") for m in methods if not avail.get(m)}
    rows: list[dict] = []
    t0 = time.perf_counter()
    with S() as s:
        # Readable = the ACL decision alone (any date): leaks are judged on authorization, not on time.
        from sqlalchemy import select as _select

        from .access import acl_of
        from .authz import decide
        from .db import DocumentVersion
        all_versions = list(s.scalars(_select(DocumentVersion)))
        readable = {u.username: {f"{v.document.doc_key}@{v.version}" for v in all_versions
                                 if decide(u, acl_of(v, v.document), directory).allowed}
                    for u in directory.users.values()}
        for q in questions:
            row = {"id": q.id, "user": q.user, "question": q.question, "category": q.category, "split": q.split,
                   "as_of": q.as_of, "relevant": q.relevant, "answer_spans": q.answer_spans,
                   "expect_abstain": q.expect_abstain, "expect_conflict": q.expect_conflict, "forbidden": q.forbidden,
                   "methods": {}}
            for m in ran:
                row["methods"][m] = evaluate_question(s, directory, q, m, readable)
            user = directory.users[q.user]
            base = title_baseline(s, user, directory, q)
            rel = set(q.relevant)
            row["baseline_title_only"] = {"top_refs": base[:5], **({"recall_at_5": len(rel & set(base[:5])) / len(rel),
                                                                    "mrr_at_10": _mrr(base, rel)} if rel else {})}
            rows.append(row)
        s.rollback()
    wall = time.perf_counter() - t0
    by_split = {}
    for sp in ("dev", "test", "all"):
        sub = [r for r in rows if sp == "all" or r["split"] == sp]
        if not sub:
            continue
        by_split[sp] = {m: aggregate(sub, m) for m in ran}
        ans = [r for r in sub if r["relevant"]]
        by_split[sp]["baseline_title_only"] = {
            "recall_at_5": round(statistics.fmean(r["baseline_title_only"]["recall_at_5"] for r in ans), 4) if ans else None,
            "mrr_at_10": round(statistics.fmean(r["baseline_title_only"]["mrr_at_10"] for r in ans), 4) if ans else None}
    cats = sorted({r["category"] for r in rows})
    by_category = {c: {m: aggregate([r for r in rows if r["category"] == c], m) for m in ran} for c in cats}
    manifest = json.loads((EVAL_DIR / "dataset_manifest.json").read_text())
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                                check=False).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "src", "corpus", "eval/gold"], cwd=ROOT,
                                    capture_output=True, text=True, check=False).stdout.strip())
    except OSError:
        commit, dirty = "", None
    report = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "provenance": {"git_commit": commit, "uncommitted_changes_in_src_or_data": dirty,
                       "dataset_version": manifest["dataset_version"], "documents": manifest["documents"],
                       "gold_questions": len(questions), "split_filter": split or "all",
                       "embedding_model": embed.EMBED_MODEL_ID if avail["dense"] else None,
                       "reranker": embed.RERANK_MODEL_ID if avail["rerank"] else None,
                       "command": "make eval", "machine": machine(), "wall_seconds": round(wall, 1),
                       "answer_mode": "extractive (no LLM)"},
        "methods_run": ran, "methods_skipped": skipped,
        "summary": by_split, "by_category": by_category, "questions": rows,
    }
    out = out or (EVAL_DIR / "reports" / "latest.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + "\n")
    hist = EVAL_DIR / "reports" / "history.jsonl"
    with hist.open("a") as f:
        allm = by_split.get("all", {})
        f.write(json.dumps({"generated_at": report["generated_at"], "commit": commit,
                            "dataset_version": manifest["dataset_version"],
                            "headline": {m: {k: allm[m].get(k) for k in ("recall_at_5", "mrr_at_10", "leaks")}
                                         for m in ran}}) + "\n")
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--methods", default="bm25,dense,hybrid,rerank")
    ap.add_argument("--split", default=None, choices=[None, "dev", "test", "all"])
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    rep = run(args.methods.split(","), args.split, args.out)
    for sp, ms in rep["summary"].items():
        for m, a in ms.items():
            if m == "baseline_title_only":
                print(f"{sp:5} {m:20} R@5={a['recall_at_5']} MRR={a['mrr_at_10']}")
                continue
            print(f"{sp:5} {m:20} R@5={a['recall_at_5']} P@5={a['precision_at_5']} MRR={a['mrr_at_10']} "
                  f"nDCG={a['ndcg_at_10']} cite_valid={a['citation_validity']} support={a['answer_support_rate']} "
                  f"abstainF1={a['abstention']['f1']} conflicts={a['conflicts']['flagged']}/{a['conflicts']['expected']}"
                  f"(fa {a['conflicts']['false_alarms_on_other_answerable']}) leaks={a['leaks']} "
                  f"p50={a['latency_ms']['p50']}ms p95={a['latency_ms']['p95']}ms err={a['errors']}")
    if rep["methods_skipped"]:
        print("skipped:", rep["methods_skipped"])


if __name__ == "__main__":
    main()
