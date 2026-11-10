# AI Engineer readiness: what this repo shows, measured

This page maps the repository to what late-2026 AI Engineer / forward-deployed engineer postings ask for, lists
what the `feat/ai-engineer-readiness` branch added with the measured numbers (each from a saved run file), and
says plainly what is still missing.

## What postings ask for (sample of 9, checked 2026-11-09)

Postings sampled: Endeavor FDE ×2 (Chicago), Kirkland AI Engineer II (Chicago), iManage Sr AI Engineer (closed),
OpenAI Applied AI Engineer Enterprise + Enterprise HLS, Anthropic Staff GTM AI Engineer, Writer AI Engineer,
Databricks Sr FDE FinServ. Sources:
[Endeavor (Ashby API)](https://api.ashbyhq.com/posting-api/job-board/endeavorai) ·
[Kirkland (Dice mirror)](https://www.dice.com/job-detail/6e8edb07-ec39-4fc1-886f-990b692abc49) ·
[iManage](https://www.purpose.jobs/discover/companies/imanage-2-30d3782f-8d61-4fd1-aa6b-9695834634e0/jobs/84445120-senior-ai-engineer) ·
[OpenAI](https://jobs.ashbyhq.com/openai/6fc25168-bc4c-47a0-8601-583dfaf7fcbd) ·
[Anthropic](https://job-boards.greenhouse.io/anthropic/jobs/5390966008) ·
[Writer](https://jobs.ashbyhq.com/WRITER/93fbe5ce-2ce9-41ea-a998-a433c0f7f085) ·
[Databricks](https://databricks.com/company/careers/open-positions/job?gh_jid=8592938002).
Practice references: [Anthropic, demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents),
[Hamel Husain, LLM judges](https://hamel.dev/blog/posts/llm-judge/),
[OWASP LLM Top 10 2025](https://genai.owasp.org/llm-top-10/),
[Claude Citations](https://platform.claude.com/docs/en/build-with-claude/citations),
[MCP specification](https://modelcontextprotocol.io/specification/latest),
[OTel GenAI conventions](https://github.com/open-telemetry/semantic-conventions-genai).

| Requirement (postings asking, of 9) | Evidence in this repo | Strength |
|---|---|---|
| Python LLM applications (9/9) | FastAPI service; three generation providers behind one validator (`generate.py`, `providers.py`, `claude_citations.py`) | Good (local demo, not deployed) |
| Security, privacy, governance, human oversight (5/9) | Authorization before retrieval, 0-leak sweeps (extractive and with a real model), OWASP LLM mapping, second-person approval for releases, audit log | Strong for a demo |
| Agents / tool design (6/9) | MCP server with three read-only, permission-aware tools and launch-bound identity | Partial: tools, not an agent loop |
| Evals with graders calibrated against humans (4/9) | Deterministic retrieval/answer metrics on 112 gold questions; binary LLM judge with TPR/TNR on a held-out label split | Partial: labels are AI-drafted, pending owner review |
| RAG / retrieval (4/9) | BM25 / dense / RRF hybrid / rerank ablation with dev/test split and a no-RAG baseline | Strong |
| Observability / tracing (4/9) | OpenTelemetry GenAI spans (retrieval, chat), off by default, no content in spans | Basic |
| Cost / latency (3/9) | Latency p50/p95 per method; per-answer token usage; Claude list-price estimate per answer | Basic |
| MCP (1/9) | `src/inkfall/mcp_server.py`, docs/MCP_SERVER.md | Done |
| Cloud, containers, CI/CD (5/9) | `make ci` locally and on GitHub Actions (Linux runner, every push and PR) | Partial: CI only, no deployment (see below) |

## Added on this branch (numbers from saved files)

<!-- readiness:start -->

_Rendered by `scripts/render_eval_docs.py` from the saved reports named in each row._

| Added | What was measured | Result | File |
|---|---|---|---|
| Claude provider (Anthropic Citations API, custom-content documents) | request shape, block-index → char-offset mapping, re-verification, rejection of out-of-pack / out-of-range / tampered citations and refusals | offline: 13 tests against fixtures built from the documented response schema; one live run in the next row | `tests/test_claude_citations.py` |
| Live Claude check (claude-opus-5-5, 2026-11-09) | the 6 dev questions from `make eval-generative` | 6/6 outputs accepted; 18 sentences: 12 supported, 1 partial, 5 unsupported (5 of them uncited connecting sentences such as "The documents conflict on this point."); gold span in 5/6; **finding:** PM-007 abstained because passages were sent without their document title (fixed; not yet re-run live); p50 3083.3 ms; 14363 tokens reported | `eval/reports/generative_claude.json` |
| Adversarial sweep with a real model, run 1 | same sweep as the extractive run, gpt-oss:20b answering | **0 leaks**, 194 generated answers, 0/187 prompts with forbidden content; **finding:** one generated answer repeated a vendor notice's instruction to AI tools (fixed: such sentences are now withheld). Run 1 started at commit 97756f8; its `git_commit` field is the HEAD when it finished (later runs record both) | `eval/reports/adversarial_generative_run1.json` |
| Adversarial sweep with a real model, run 2 (after the fix) | 1796 probes + 898 direct reads, 12 identities | **0 leaks**; 194 generated answers; 0/187 prompts and 0 raw outputs with forbidden content; injection 20/21, generation 5/5, api 10/10 | `eval/reports/adversarial_generative.json` |
| Faithfulness LLM judge (binary, critique first), calibrated | judge-test, n=52 (37 PASS / 15 FAIL reference labels; all FAILs synthetic) | LLM judge TPR **0.946**, TNR **0.933**; deterministic span check TPR 0.730, TNR 1.000 — against **AI-drafted labels pending owner review**; judge = generator model | `eval/reports/faithfulness.json` |
| Deterministic metrics on the same answers | 63 natural answers, 73 sentences | 47 answers fully 'supported'; gold span present in 53; citations re-verified 92/92; generation p50 5037.8 ms, judge p50 28239.8 ms | `eval/reports/faithfulness.json` |
| MCP server (official SDK, stdio) | every identity × every unreadable version (449 pairs) through `fetch_document`, `cite` and a `search` built from the forbidden text; identity-argument escalation; a real stdio subprocess | forbidden == missing (`not_found`) for every pair; 0 forbidden canaries in search results (test assertions) | `tests/test_mcp_server.py` |
| OWASP Top 10 for LLM Apps 2025 mapping | LLM01-LLM10 → code + tests + residual risk | table | `docs/OWASP_LLM_TOP10.md` |
| OpenTelemetry GenAI spans (Development-status conventions) | span names/attributes; no content in spans | 3 tests | `tests/test_telemetry.py` |
| npm audit (2026-11-09) | `npm audit` and `npm audit --omit=dev` | 8 moderate findings, all in dev-only lint tooling (minimatch via typescript-eslint / eslint-config-next); `npm audit fix` changes nothing and the only offered fix is a major downgrade, so none was applied; production dependencies: 0. `pip-audit` (incl. the new anthropic, mcp and opentelemetry pins): no known vulnerabilities | `web/package-lock.json` (unchanged) |

<!-- readiness:end -->

Full tables: [RAG_EVALUATION.md](RAG_EVALUATION.md) (faithfulness and real-model adversarial sections).
Machine for every run: Apple M5 Pro, 48 GB, macOS 27.0.1; local model via Ollama on the same Mac, shared with other
workloads during the runs (latencies are not a benchmark).

## Still missing (honest)

- **Human labels.** Reference labels for the faithfulness judge were written by an AI (a Claude Code subagent),
  blind to the judge. They are pending owner review (`eval/faithfulness/owner_review.csv`, 30 items). Until a
  person confirms them, the TPR/TNR numbers are agreement with AI-drafted labels, not with a human expert.
- **Independent judge.** The judge and the generator are the same local model (gpt-oss:20b) with different
  prompts. A judge from a different model family would reduce self-preference risk.
- **Few natural failures.** Natural answers from the local model were almost all faithful, so the judge's
  true-negative rate rests mostly on synthetic negatives (changed numbers, appended fabricated sentences). Real
  subtle misreadings are under-represented.
- **Claude provider: one small live run.** Six questions through `make eval-claude-live` on 2026-11-09
  (`eval/reports/generative_claude.json`). It found one real defect: passages were sent without their document
  title, so a question naming the project only the title mentions was abstained on (fixed, not yet re-run live).
  Uncited connecting sentences ("The documents conflict on this point.") count as unsupported. Six questions are
  not a benchmark; the offline fixture tests remain the main coverage.
- **No deployment, no cloud.** Everything runs on one Mac. No container image, no IaC; a deployment is an owner
  decision. CI does run: GitHub Actions on `ubuntu-24.04` (enabled 2026-11-09) runs the `make ci` checks on every
  pull request and push to `main`.
- **Small, self-authored data.** 45 fictional documents and 112 questions written for this project; numbers are
  optimistic relative to a real corpus.
- **No agent loop.** The MCP server provides tools for someone else's agent; there is no multi-step agent with
  planning, memory or tool-choice evaluation here.
- **Tracing is minimal.** Spans exist and are tested, but there is no collector, dashboard, or sampling policy.
