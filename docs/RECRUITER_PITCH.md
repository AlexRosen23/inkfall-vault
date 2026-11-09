# Recruiter pitch

**The Inkfall Vault** is a local, permission-aware evidence workbench for legal, finance and policy documents
(all fictional). It is the "secure enterprise RAG" piece of my portfolio: retrieval that never sees what the user
may not read, citations that resolve to exact stored text, abstention instead of guessing, and an evaluation
harness with published failure cases.

## Architecture in five lines

1. A deterministic policy (tenant, clearance, ACL groups, ethical walls) builds each user's authorized view
   **before** any retrieval; roles grant functions, never reads.
2. Hybrid retrieval over that view: SQLite FTS5/BM25 (one index per tenant) + local MiniLM embeddings, RRF fusion.
3. An evidence layer produces verbatim, offset-exact citations, evidence-coverage diagnostics, rule-based
   contradiction flags, amendment overrides and prompt-injection flags; it abstains when evidence is thin.
4. Optional local LLM (LM Studio / Ollama) sees only authorized passages, has no tools, and its JSON output is
   validated sentence by sentence; spoofed citations reject the whole answer.
5. Briefs leave the team only after a second person approves; everything is audited with redaction.

FastAPI · SQLAlchemy · SQLite FTS5 · sentence-transformers · Next.js 16 / React 19 / TypeScript · pytest.
Diagrams: [ARCHITECTURE.md](ARCHITECTURE.md). Security: [THREAT_MODEL.md](THREAT_MODEL.md),
[SECURITY_LIMITATIONS.md](SECURITY_LIMITATIONS.md).

## Resume bullet candidates

Each number below is copied from `resume_evidence/metrics.json`, which is generated from saved runs; re-check that
file before using a bullet. Status is **ready** only when every factual claim maps to code plus test output.

1. **Status: ready.** Built a permission-aware RAG evidence workbench (FastAPI, SQLite FTS5, local MiniLM
   embeddings, Next.js) that enforces tenant, clearance and ethical-wall rules before retrieval; an automated
   12-identity adversarial sweep (1,796 targeted search probes and 898 direct reads) found 0 leaks, and tests
   reject role tampering, spoofed citations and malicious-model outputs.
   - Evidence: `eval/reports/adversarial.json` (isolation), `tests/test_isolation.py`,
     `tests/test_api_security.py`, `tests/test_generation.py`; verify with `make security-test`.
2. **Status: ready.** Built a reproducible RAG evaluation harness over 112 self-written gold questions with a
   held-out split; hybrid BM25 + dense retrieval reached MRR@10 0.966 vs 0.818 for a title-only baseline,
   with 100% citation-span validity and 0.92 abstention F1 on held-out questions, and published failure cases
   (including weak contradiction detection) instead of a single accuracy score.
   - Evidence: `eval/reports/latest.json` → `summary.test`; verify with `make seed && make eval`.

Not claimable: time-to-task savings (not measured), production use or customers (none), contradiction detection
quality (fails on held-out questions), anything about real legal documents (all data is synthetic).
