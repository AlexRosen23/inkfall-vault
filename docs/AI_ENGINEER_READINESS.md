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
| Cloud, containers, CI/CD (5/9) | `make ci` locally; CI workflow defined but GitHub Actions disabled by owner policy | Missing (see below) |

## Added on this branch (numbers from saved files)

RESULTS_PLACEHOLDER

## Still missing (honest)

- **Human labels.** Reference labels for the faithfulness judge were written by an AI (a Claude Code subagent),
  blind to the judge. They are pending owner review (`eval/faithfulness/owner_review.csv`, 30 items). Until a
  person confirms them, the TPR/TNR numbers are agreement with AI-drafted labels, not with a human expert.
- **Independent judge.** The judge and the generator are the same local model (gpt-oss:20b) with different
  prompts. A judge from a different model family would reduce self-preference risk.
- **Few natural failures.** Natural answers from the local model were almost all faithful, so the judge's
  true-negative rate rests mostly on synthetic negatives (changed numbers, appended fabricated sentences). Real
  subtle misreadings are under-represented.
- **Claude provider never called live.** No API key was available. The Citations integration is tested against
  fixtures built from the documented response schema; a live run (`ANTHROPIC_API_KEY=… generate=claude`) may surface
  differences (for example how blocks are cited across sentence boundaries, or the server-side fallback beta).
- **No deployment, no cloud, no CI.** Everything runs on one Mac. No container image, no IaC, GitHub Actions
  disabled by owner policy. A deployment and a CI run are owner decisions.
- **Small, self-authored data.** 45 fictional documents and 112 questions written for this project; numbers are
  optimistic relative to a real corpus.
- **No agent loop.** The MCP server provides tools for someone else's agent; there is no multi-step agent with
  planning, memory or tool-choice evaluation here.
- **Tracing is minimal.** Spans exist and are tested, but there is no collector, dashboard, or sampling policy.
