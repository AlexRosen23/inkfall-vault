# The Inkfall Vault

A permission-aware **evidence workbench** for fictional legal, finance and policy documents. An analyst asks a
consequential question; the server finds only the documents that analyst may read, answers with exact,
clickable source spans (or abstains), shows contradictions side by side instead of flattening them, and keeps an
audit trail. A brief only leaves the team after a second person approves it.

> **Synthetic demo.** All organizations, people and documents are fictional. Not legal advice. Not affiliated with
> any real firm or vendor. A tested local demo, not a production-secure or certified system; see
> [docs/SECURITY_LIMITATIONS.md](docs/SECURITY_LIMITATIONS.md).

## For AI Engineer reviewers

A 60-second path through the repo. One command after `make setup && make seed` (no model, no API key; the MCP
isolation sweep makes it take a few minutes on CPU):

```bash
uv run pytest tests/test_claude_citations.py tests/test_mcp_server.py tests/test_generation.py -q
```

Then look at:

1. **Claude Citations API, mapped to stored offsets**: [`src/inkfall/claude_citations.py`](src/inkfall/claude_citations.py)
   (each authorized span is one custom-content block; citations are re-verified against stored text and the ACL).
2. **Permission-aware MCP server**: [`src/inkfall/mcp_server.py`](src/inkfall/mcp_server.py) and
   [docs/MCP_SERVER.md](docs/MCP_SERVER.md) (identity bound at launch; forbidden = missing).
3. **Evals with a calibrated judge**: [docs/RAG_EVALUATION.md](docs/RAG_EVALUATION.md) (faithfulness section),
   [`src/inkfall/eval_faithfulness.py`](src/inkfall/eval_faithfulness.py).
4. **Security mapping**: [docs/OWASP_LLM_TOP10.md](docs/OWASP_LLM_TOP10.md).

<!-- reviewers:start -->

Headline numbers (rendered from saved runs by `scripts/render_eval_docs.py`):

- Retrieval, held-out test split: hybrid MRR@10 **0.966**, citation validity **100.0%**, abstention F1 0.923 (`eval/reports/latest.json`).
- Permission isolation: **0 leaks** in 1796 search probes + 898 direct reads (`eval/reports/adversarial.json`).
- Same sweep with **gpt-oss:20b** writing the answers: **0 leaks**, 194 generated answers, 0 of 187 prompts contained forbidden content (`eval/reports/adversarial_generative.json`).
- Faithfulness LLM judge on judge-test: TPR **0.946**, TNR **0.933** (n=52; natural answers only: n=37, TPR 0.946) against **AI-drafted reference labels pending owner review**; judge = generator model (`eval/reports/faithfulness.json`).

<!-- reviewers:end -->

What this does and does not show, with gaps: [docs/AI_ENGINEER_READINESS.md](docs/AI_ENGINEER_READINESS.md).
Walkthrough video (40 s, recorded with Playwright): [docs/media/walkthrough.webm](docs/media/walkthrough.webm).

| Generated answer (gpt-oss:20b), each sentence checked | Citation verified against stored text | Faithfulness judge calibration |
|---|---|---|
| ![Generated answer with support label](docs/media/generated-answer.png) | ![Side-by-side citation verification](docs/media/citation-verified.png) | ![Judge TPR/TNR table](docs/media/faithfulness-console.png) |

## What it demonstrates

- **Authorization before retrieval.** A deterministic policy (tenant, clearance, ACL groups, ethical walls) builds
  each user's authorized view *before* BM25, embeddings, snippets, prompts or logs see any content. Forbidden and
  missing objects look identical (404).
- **Hybrid retrieval, measured.** SQLite FTS5/BM25 (one index per tenant), local `all-MiniLM-L6-v2` embeddings,
  reciprocal-rank fusion; a cross-encoder rerank ablation (measured: no gain on this corpus, ~10x latency). Compared on 112 gold questions with a
  dev/test split and a no-RAG title-only baseline.
- **Exact citations.** Immutable, checksummed versions; every cited sentence maps to stored character offsets and
  is re-verified whenever it comes back to the server.
- **Trust, not fake confidence.** Evidence coverage, retrieval diagnostics, freshness, amendment overrides,
  rule-based contradiction detection and flagged prompt-injection text, plus abstention when evidence is thin.
- **Optional local generation, validated.** LM Studio / Ollama are detected, never required. The model sees only
  authorized passages, has no tools, and its output is rejected or labelled when citations or numbers do not hold up.
- **Claude with native citations (opt-in).** The Anthropic Citations API with one custom-content block per
  authorized span; Claude's block-index citations map back to stored character offsets and are re-verified. Tested
  offline with fixtures built from the documented response schema; never auto-selected, needs `ANTHROPIC_API_KEY`.
- **MCP server.** Read-only `search` / `fetch_document` / `cite` tools over stdio with the identity bound at launch.
- **Measured faithfulness.** A binary LLM judge for "every claim is supported by its cited spans", calibrated
  (TPR/TNR) against reference labels on a held-out split, next to the deterministic span-support metrics.
- **Human in the loop.** Citation-backed briefs need a different reviewer's approval before the (local) release;
  correct / incorrect / partial labels on citations are stored for error analysis.

## Results

<!-- results:start -->

_From saved runs: `eval/reports/latest.json` (2026-11-09T05:52:59+00:00, commit `2180604`) and `adversarial.json` (2026-11-09T19:13:36+00:00). Held-out **test** split, 69 questions; CPU only (Apple M5 Pro)._

| | BM25 | Dense | Hybrid (RRF) | Hybrid + rerank | Title-only baseline |
|---|---|---|---|---|---|
| MRR@10 | 0.938 | 0.962 | 0.966 | 0.955 | 0.818 |
| nDCG@10 | 0.950 | 0.973 | 0.971 | 0.968 | n/a |
| Citation validity | 100.0% | 100.0% | 100.0% | 100.0% | n/a |
| Answer support (gold span in cited text) | 85.4% | 85.4% | 87.8% | 87.2% | n/a |
| Abstention F1 | 0.857 | 0.923 | 0.923 | 0.846 | n/a |
| Conflicts found / expected (false alarms) | 2/5 (6) | 2/5 (4) | 2/5 (6) | 3/5 (6) | n/a |
| Leaks | 0 | 0 | 0 | 0 | n/a |
| Latency p50 / p95 (ms) | 4.4 / 8.1 | 18.9 / 42.1 | 19.8 / 40.3 | 195.7 / 319.0 | n/a |

Adversarial run: **0 leaks** across 12 identities, 1796 targeted search probes and 898 direct reads; injection 20/21, generation 5/5, api 10/10; documented quality miss: XT-017.

Same sweep with a real local model (gpt-oss:20b via ollama) generating every non-abstained answer: **0 leaks**; 194 answers generated, 187 prompts checked for forbidden content (0 hits).

Answer faithfulness (gpt-oss:20b answers, binary LLM judge): judge-test TPR **0.946** / TNR **0.933** (n=52) against AI-drafted reference labels pending owner review; 47/63 natural answers pass the deterministic span check.

Recall@5 is 1.0 for every method because each identity can read only 3-15 versions; read MRR/nDCG. Contradiction detection is weak on held-out questions and is not claimed as a strength.

<!-- results:end -->

Full tables and failure examples: [docs/RETRIEVAL_EVAL.md](docs/RETRIEVAL_EVAL.md),
[docs/RAG_EVALUATION.md](docs/RAG_EVALUATION.md); claim-by-claim evidence: [resume_evidence/metrics.json](resume_evidence/metrics.json).

## Quickstart

Requirements: macOS or Linux, Python 3.12 via [uv](https://docs.astral.sh/uv/), Node 24. One-time setup needs
network (Python/npm packages and the ~90 MB embedding model); after that everything runs offline.

```bash
make setup
```

```bash
make seed
```

```bash
make serve
```

Open http://127.0.0.1:5110 and pick an identity. `make serve` (= `./run.sh`) serves the API, the read-only project
contract (`/health`, `/capabilities`, `/runs`) and the built UI from one process on **5110**; it seeds the database
and builds the UI first if they are missing. For development with hot reload, `make demo` runs the API on 5110 and
the Next.js dev server on **5111**. No LLM is needed; to try local generation, load a chat model in LM Studio (port 1234) or Ollama
(11434) and choose "Local model" in the scope panel.

| Command | Does |
|---|---|
| `make serve` | one-port app on 127.0.0.1:5110 (what the Constellation world opens) |
| `make test` | dataset validation + full test suite |
| `make security-test` | isolation/security/generation suites + adversarial eval → `eval/reports/adversarial.json` |
| `make eval` | gold set × BM25/dense/hybrid(/rerank) → `eval/reports/latest.json` + rendered docs |
| `make eval-generative` | opt-in: 6 dev questions through the local model (slow) |
| `make ci` | lint, typecheck, tests, adversarial eval, web build, license gate |
| `make mcp` | MCP server on stdio (`MCP_USER=dana.whitcombe` by default) |
| `make security-test-generative` | opt-in, slow: the adversarial sweep with `gpt-oss:20b` (Ollama) writing every answer |
| `make eval-faithfulness` | opt-in, slow: re-judge the saved answers with the frozen judge prompt → `eval/reports/faithfulness.json` |

CI is defined in `.github/workflows/ci.yml` but **GitHub Actions is disabled** on this private repository; run
`make ci` locally.

## Demo identities (fictional)

| Tenant | Identities |
|---|---|
| Lanternfield Partners LLP (law firm) | `ava.lindqvist` analyst · `marcus.oyelaran` partner/reviewer · `theo.brandt` associate (walled off the Harrow matter) · `lf.admin` |
| Corvane Freight Holdings | `dana.whitcombe` procurement/reviewer · `omar.haddad` treasury (restricted) · `june.park` ops · `cv.admin` |
| Pellmoor Water Authority | `rhea.castellanos` policy/reviewer · `sam.okafor` ops · `nadia.voss` board secretary (restricted) · `pm.admin` |

## Docs

[Architecture](docs/ARCHITECTURE.md) · [Threat model](docs/THREAT_MODEL.md) ·
[Authorization matrix](docs/AUTHORIZATION_MATRIX.md) · [Security limitations](docs/SECURITY_LIMITATIONS.md) ·
[API & auth contract](docs/API_AND_AUTH_CONTRACT.md) · [Retrieval eval](docs/RETRIEVAL_EVAL.md) ·
[RAG eval](docs/RAG_EVALUATION.md) · [Datasets & licenses](docs/DATASETS_AND_LICENSES.md) ·
[Engineering decisions](docs/ENGINEERING_DECISIONS.md) · [OWASP LLM Top 10 mapping](docs/OWASP_LLM_TOP10.md) ·
[MCP server](docs/MCP_SERVER.md) · [AI Engineer readiness](docs/AI_ENGINEER_READINESS.md) · [Customer problem](docs/CUSTOMER_PROBLEM.md) ·
[Case study (synthetic)](docs/CUSTOMER_CASE_STUDY.md) · [Demo walkthrough](docs/DEMO_WALKTHROUGH.md) ·
[Recruiter pitch](docs/RECRUITER_PITCH.md) · [Interview defense](docs/INTERVIEW_DEFENSE.md) ·
[Contributing](CONTRIBUTING.md)

## Layout

```
src/inkfall/   authz, access, ingest, search, evidence, generate/providers, claude_citations, service, api, audit,
               evaluate, adversarial, eval_faithfulness, mcp_server, telemetry
web/           Next.js evidence-chamber UI (proxies /api to :5110)
corpus/        45 fictional documents + identities.yaml
eval/          gold questions, dataset manifest, saved reports
tests/         isolation, security, generation guardrails, ingestion, retrieval, API contract
docs/          design, security and evaluation docs
```

License: MIT.
