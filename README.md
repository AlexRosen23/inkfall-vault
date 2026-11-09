# The Inkfall Vault

A permission-aware **evidence workbench** for fictional legal, finance and policy documents. An analyst asks a
consequential question; the server finds only the documents that analyst may read, answers with exact,
clickable source spans (or abstains), shows contradictions side by side instead of flattening them, and keeps an
audit trail. A brief only leaves the team after a second person approves it.

> **Synthetic demo.** All organizations, people and documents are fictional. Not legal advice. Not affiliated with
> any real firm or vendor. A tested local demo, not a production-secure or certified system; see
> [docs/SECURITY_LIMITATIONS.md](docs/SECURITY_LIMITATIONS.md).

## What it demonstrates

- **Authorization before retrieval.** A deterministic policy (tenant, clearance, ACL groups, ethical walls) builds
  each user's authorized view *before* BM25, embeddings, snippets, prompts or logs see any content. Forbidden and
  missing objects look identical (404).
- **Hybrid retrieval, measured.** SQLite FTS5/BM25 (one index per tenant), local `all-MiniLM-L6-v2` embeddings,
  reciprocal-rank fusion; an opt-in cross-encoder rerank experiment. Compared on 112 gold questions with a
  dev/test split and a no-RAG title-only baseline.
- **Exact citations.** Immutable, checksummed versions; every cited sentence maps to stored character offsets and
  is re-verified whenever it comes back to the server.
- **Trust, not fake confidence.** Evidence coverage, retrieval diagnostics, freshness, amendment overrides,
  rule-based contradiction detection and flagged prompt-injection text, plus abstention when evidence is thin.
- **Optional local generation, validated.** LM Studio / Ollama are detected, never required. The model sees only
  authorized passages, has no tools, and its output is rejected or labelled when citations or numbers do not hold up.
- **Human in the loop.** Citation-backed briefs need a different reviewer's approval before the (local) release;
  correct / incorrect / partial labels on citations are stored for error analysis.

## Results

<!-- results:start -->

_From saved runs: `eval/reports/latest.json` (2026-11-09T05:03:56+00:00, commit `4adb7df`) and `adversarial.json` (2026-11-09T05:04:40+00:00). Held-out **test** split, 69 questions; CPU only (Apple M5 Pro)._

| | BM25 | Dense | Hybrid (RRF) | Title-only baseline |
|---|---|---|---|---|
| MRR@10 | 0.938 | 0.962 | 0.966 | 0.818 |
| nDCG@10 | 0.950 | 0.973 | 0.971 | n/a |
| Citation validity | 100.0% | 100.0% | 100.0% | n/a |
| Answer support (gold span in cited text) | 85.4% | 85.4% | 87.8% | n/a |
| Abstention F1 | 0.857 | 0.923 | 0.923 | n/a |
| Conflicts found / expected (false alarms) | 2/5 (6) | 2/5 (4) | 2/5 (6) | n/a |
| Leaks | 0 | 0 | 0 | n/a |
| Latency p50 / p95 (ms) | 3.2 / 4.7 | 11.7 / 15.9 | 11.9 / 15.5 | n/a |

Adversarial run: **0 leaks** across 12 identities, 1796 targeted search probes and 898 direct reads; injection 20/21, generation 5/5, api 10/10; documented quality miss: XT-017.

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
[Engineering decisions](docs/ENGINEERING_DECISIONS.md) · [Customer problem](docs/CUSTOMER_PROBLEM.md) ·
[Case study (synthetic)](docs/CUSTOMER_CASE_STUDY.md) · [Demo walkthrough](docs/DEMO_WALKTHROUGH.md) ·
[Recruiter pitch](docs/RECRUITER_PITCH.md) · [Interview defense](docs/INTERVIEW_DEFENSE.md) ·
[Contributing](CONTRIBUTING.md)

## Layout

```
src/inkfall/   authz, access, ingest, search, evidence, generate/providers, service, api, audit, evaluate, adversarial
web/           Next.js evidence-chamber UI (proxies /api to :5110)
corpus/        45 fictional documents + identities.yaml
eval/          gold questions, dataset manifest, saved reports
tests/         isolation, security, generation guardrails, ingestion, retrieval, API contract
docs/          design, security and evaluation docs
```

License: MIT.
