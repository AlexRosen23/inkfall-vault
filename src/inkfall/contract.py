"""Read-only project contract for dashboards (GET /health, /capabilities, /runs, /runs/{id}).

Built only from the saved reports in eval/reports/ (evaluation, adversarial and generative runs) and from static
facts about this build. It carries aggregate numbers and labels, never document text, titles, questions or any
tenant's data, so it is served without a session. A run is a measurement this repository actually executed and saved;
nothing is synthesized here. The dataset itself is fictional, which `provenance.synthetic` says on every run.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from . import __version__, embed
from .config import EVAL_DIR, db_path

PROJECT_ID = "inkfall"
RUN_ID = re.compile(r"^[A-Za-z0-9._:-]{1,96}$")


def _read(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _stamp(iso: str) -> str:
    return re.sub(r"[^0-9]", "", iso)[:14]


def _minus(iso: str, seconds: float | None) -> str | None:
    try:
        t = dt.datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    return (t - dt.timedelta(seconds=float(seconds or 0))).isoformat(timespec="seconds")


def _f(x, digits=3):
    return f"{x:.{digits}f}" if isinstance(x, int | float) else "n/a"


def _eval_run(rep: dict) -> dict:
    pv = rep.get("provenance", {})
    test = rep.get("summary", {}).get("test", {})
    best = test.get("hybrid") or test.get("bm25") or {}
    method = "hybrid" if test.get("hybrid") else "bm25"
    cv = best.get("citation_validity")
    headline = (f"{method} MRR@10 {_f(best.get('mrr_at_10'))} · nDCG@10 {_f(best.get('ndcg_at_10'))} · citations "
                f"{'n/a' if cv is None else f'{cv * 100:.0f}%'} valid · abstain F1 {_f(best.get('abstention', {}).get('f1'))} · "
                f"{best.get('leaks', 'n/a')} leaks (test split, {best.get('questions', '?')} questions)")
    leaks = sum(m.get("leaks", 0) for sp in rep.get("summary", {}).values() for k, m in sp.items()
                if isinstance(m, dict) and k != "baseline_title_only")
    return {
        "project_id": PROJECT_ID, "run_id": f"eval-{_stamp(rep['generated_at'])}", "kind": "eval",
        "status": "completed" if leaks == 0 else "failed", "mode": "recorded",
        "started_at": _minus(rep["generated_at"], pv.get("wall_seconds")), "ended_at": rep["generated_at"],
        "headline": headline,
        "provenance": {"synthetic": True, "data": "fictional corpus", "git_commit": pv.get("git_commit"),
                       "dataset_version": pv.get("dataset_version"), "command": "make eval",
                       "methods": rep.get("methods_run", []), "skipped": rep.get("methods_skipped", {})},
        "artifacts": ["eval/reports/latest.json", "docs/RETRIEVAL_EVAL.md", "docs/RAG_EVALUATION.md"],
    }


def _history_run(h: dict) -> dict | None:
    head = h.get("headline") or {}
    m = head.get("hybrid") or head.get("bm25")
    if not m or "generated_at" not in h:
        return None
    return {
        "project_id": PROJECT_ID, "run_id": f"eval-{_stamp(h['generated_at'])}", "kind": "eval",
        "status": "completed" if not m.get("leaks") else "failed", "mode": "recorded",
        "started_at": None, "ended_at": h["generated_at"],
        "headline": f"{'hybrid' if head.get('hybrid') else 'bm25'} MRR@10 {_f(m.get('mrr_at_10'))} · "
                    f"{m.get('leaks', 'n/a')} leaks (all splits; summary line from history)",
        "provenance": {"synthetic": True, "data": "fictional corpus", "git_commit": h.get("commit"),
                       "dataset_version": h.get("dataset_version"), "command": "make eval"},
        "artifacts": ["eval/reports/history.jsonl"],
    }


def _adversarial_run(rep: dict) -> dict:
    iso = rep.get("isolation", {})
    sec = rep.get("sections", {})
    parts = [f"{iso.get('leaks', 'n/a')} leaks in {iso.get('search_probes', 0):,} probes + "
             f"{iso.get('direct_read_attempts', 0):,} direct reads"]
    parts += [f"{k} {v.get('passed')}/{v.get('total')}" for k, v in sec.items()]
    return {
        "project_id": PROJECT_ID, "run_id": f"adversarial-{_stamp(rep['generated_at'])}", "kind": "adversarial",
        "status": "completed" if rep.get("security_passed") else "failed", "mode": "recorded",
        "started_at": _minus(rep["generated_at"], rep.get("provenance", {}).get("wall_seconds")),
        "ended_at": rep["generated_at"], "headline": " · ".join(parts),
        "provenance": {"synthetic": True, "data": "fictional corpus; scripted malicious model, not a real LLM",
                       "git_commit": rep.get("provenance", {}).get("git_commit"),
                       "dataset_version": rep.get("provenance", {}).get("dataset_version"),
                       "command": "make security-test", "quality_misses": len(rep.get("quality_misses", []))},
        "artifacts": ["eval/reports/adversarial.json"],
    }


def _generative_run(rep: dict) -> dict:
    s = rep.get("summary", {})
    pv = rep.get("provenance", {})
    return {
        "project_id": PROJECT_ID, "run_id": f"generative-{_stamp(rep['generated_at'])}", "kind": "generative",
        "status": "completed", "mode": "recorded", "started_at": None, "ended_at": rep["generated_at"],
        "headline": (f"{s.get('accepted')}/{s.get('questions')} outputs accepted · {s.get('supported')} of "
                     f"{s.get('sentences')} sentences supported · p50 {round((s.get('latency_ms', {}).get('p50') or 0) / 1000)} s "
                     f"· local {pv.get('model')}"),
        "provenance": {"synthetic": True, "data": "fictional corpus; small sample, not a headline claim",
                       "model": pv.get("model"), "provider": pv.get("provider"), "command": "make eval-generative"},
        "artifacts": ["eval/reports/generative.json"],
    }


def runs(root: Path | None = None) -> list[dict]:
    root = root or (EVAL_DIR / "reports")
    out: dict[str, dict] = {}
    hist = root / "history.jsonl"
    if hist.exists():
        for line in hist.read_text().splitlines():
            try:
                r = _history_run(json.loads(line))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            if r:
                out[r["run_id"]] = r
    for name, fn in (("latest.json", _eval_run), ("adversarial.json", _adversarial_run), ("generative.json", _generative_run)):
        rep = _read(root / name)
        if isinstance(rep, dict) and rep.get("generated_at"):
            r = fn(rep)
            out[r["run_id"]] = r  # the full report wins over its one-line history entry
    return sorted(out.values(), key=lambda r: r["ended_at"] or "", reverse=True)


def runs_page(limit: int = 20) -> dict:
    rs = runs()
    return {"project_id": PROJECT_ID, "total": len(rs), "runs": rs[: max(1, min(limit, 50))]}


def run_by_id(run_id: str) -> dict | None:
    if not RUN_ID.match(run_id):
        return None
    return next((r for r in runs() if r["run_id"] == run_id), None)


def capabilities() -> dict:
    rerank = embed.reranker_available()
    dense = embed.available()
    man = _read(EVAL_DIR / "dataset_manifest.json") or {}
    implemented = [
        "server-side tenant, clearance, ACL-group and ethical-wall authorization before retrieval",
        "BM25 retrieval (SQLite FTS5, one index per tenant)",
        "extractive answers: verbatim sentences with exact character-offset citations",
        "abstention on thin evidence; rule-based contradiction flags; amendment overrides",
        "prompt-injection flagging in sources and questions",
        "version compare (clause diff with typed value changes)",
        "citation-backed briefs with second-person approval before a local-outbox release",
        "human review labels on citations",
        "structured, redacted audit log with retention",
        "upload parsing with quarantine (text, Markdown, PDF text layer)",
        "evaluation harness (112 gold questions, dev/test split) and adversarial sweep",
    ]
    if dense:
        implemented.insert(2, f"dense retrieval ({embed.EMBED_MODEL_ID}, CPU) and RRF hybrid")
    implemented.append("optional local generation through LM Studio or Ollama, validated per sentence")
    not_implemented = [
        "real authentication (fixture identities only, localhost)",
        "OCR and Office formats",
        "PostgreSQL backend",
        "time-to-task user study",
    ]
    if not dense:
        not_implemented.append("dense retrieval (embedding model not downloaded: make setup)")
    if not rerank:
        not_implemented.append("cross-encoder rerank (model not downloaded: make rerank-model)")
    else:
        implemented.insert(3, f"cross-encoder rerank experiment ({embed.RERANK_MODEL_ID})")
    return {
        "project_id": PROJECT_ID, "name": "The Inkfall Vault", "version": __version__,
        "description": "Permission-aware evidence workbench over fictional legal, finance and policy documents.",
        "implemented": implemented, "not_implemented": not_implemented,
        "disabled_by_design": [
            "letting a model or prompt decide access",
            "sending anything off this machine (briefs are released to a local outbox)",
            "paid or cloud model calls",
        ],
        "active_mode": "extractive",
        "dataset": {"synthetic": True, "documents": man.get("documents"), "dataset_version": man.get("dataset_version"),
                    "tenants": 3, "identities": 12},
        "endpoints": ["/health", "/capabilities", "/runs", "/runs/{run_id}", "/api/* (session required)"],
    }


def health() -> dict:
    problems = []
    if not db_path().exists():
        problems.append("database missing: run make seed")
    rs = runs()
    last = rs[0] if rs else None
    return {
        "status": "ok" if not problems else "degraded", "project_id": PROJECT_ID, "mode": "extractive",
        "version": __version__, "problems": problems,
        "last_run": {"run_id": last["run_id"], "kind": last["kind"], "status": last["status"]} if last else None,
    }
