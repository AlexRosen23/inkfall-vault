"""`make eval-generative`: a small sample of dev questions through the optional local model.

Slow by nature (~1-2 min/question with a local 35B model), so it is a separate, opt-in run. Results go to
eval/reports/generative.json and are never used for headline claims.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import time

from .claude_citations import get_claude
from .config import EVAL_DIR, db_path
from .db import make_engine, session_factory
from .gold import load_gold
from .identities import load_directory
from .providers import get_provider
from .service import run_query

DEFAULT_IDS = ["LF-003", "LF-021", "CV-021", "CV-027", "PM-007", "PM-021"]


def _reported_total(usage: dict | None) -> int:
    """Total tokens a provider reported: OpenAI-style `total_tokens`, else Anthropic-style input + output."""
    u = usage or {}
    if "total_tokens" in u:
        return int(u["total_tokens"] or 0)
    return int(u.get("input_tokens") or 0) + int(u.get("output_tokens") or 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default=",".join(DEFAULT_IDS))
    ap.add_argument("--backend", default="auto")
    args = ap.parse_args()
    if args.backend == "claude":  # remote + paid: only on an explicit request, and only with ANTHROPIC_API_KEY set
        prov = get_claude()
        if prov is None:
            raise SystemExit("ANTHROPIC_API_KEY is not set; the Claude live check needs it (nothing run, nothing spent)")
    else:
        prov = get_provider(None if args.backend == "auto" else args.backend)
    if prov is None:
        raise SystemExit("no local generation backend detected (LM Studio :1234 / Ollama :11434); nothing run")
    directory = load_directory()
    qs = {q.id: q for q in load_gold()}
    S = session_factory(make_engine(db_path()))
    rows = []
    for qid in args.ids.split(","):
        q = qs[qid]
        t0 = time.perf_counter()
        with S() as s:
            res = run_query(s, directory.users[q.user], directory, q.question, dt.date.fromisoformat(q.as_of),
                            "hybrid", generate_mode=prov.name)
            s.rollback()
        g = res["generation"]
        sents = res["answer"] if res["mode"] == "generative" else []
        rows.append({"id": qid, "category": q.category, "question": q.question, "status": res["status"],
                     "mode": res["mode"], "generation_status": g.get("status"), "rejected_reason": g.get("rejected_reason"),
                     "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                     "prompt_tokens_est": g.get("prompt_tokens_est", 0), "completion_tokens_est": g.get("completion_tokens_est", 0),
                     "usage_reported": g.get("usage_reported", {}), "raw_output": g.get("raw_output", ""),
                     "sentences": [{"text": a["text"], "support": a["support"], "notes": a["notes"],
                                    "refs": [c["ref"] for c in a["citations"]]} for a in sents],
                     "gold_span_in_generated": any(sp in " ".join(a["text"] for a in sents) for sp in q.answer_spans)})
        print(qid, res["mode"], g.get("status"), rows[-1]["latency_ms"], "ms", [a["support"] for a in sents])
    lat = [r["latency_ms"] for r in rows]
    allsent = [s for r in rows for s in r["sentences"]]
    summary = {"questions": len(rows), "accepted": sum(r["generation_status"] == "ok" for r in rows),
               "rejected": sum(r["generation_status"] == "rejected" for r in rows), "sentences": len(allsent),
               "supported": sum(s["support"] == "supported" for s in allsent),
               "partial": sum(s["support"] == "partial" for s in allsent),
               "unsupported": sum(s["support"] == "unsupported" for s in allsent),
               "latency_ms": {"p50": round(statistics.median(lat), 1), "p95": round(max(lat), 1)},
               "prompt_tokens_est": sum(r["prompt_tokens_est"] for r in rows),
               "completion_tokens_est": sum(r["completion_tokens_est"] for r in rows),
               "usage_reported_total_tokens": sum(_reported_total(r["usage_reported"]) for r in rows)}
    out = {"generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
           "provenance": {"model": getattr(prov, "model", "?"), "provider": prov.name,
                          "command": "make eval-claude-live" if prov.name == "claude" else "make eval-generative",
                          "note": "p95 reported as the max of a small sample"},
           "summary": summary, "questions": rows}
    out_name = "generative_claude.json" if prov.name == "claude" else "generative.json"
    (EVAL_DIR / "reports" / out_name).write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
