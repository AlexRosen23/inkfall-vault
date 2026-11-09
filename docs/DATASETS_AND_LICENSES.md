# Datasets and licenses

## Seed corpus (fictional, created for this project)

- 45 Markdown documents across three invented organizations (`corpus/<tenant>/*.md`): Lanternfield Partners
  LLP (law firm), Corvane Freight Holdings (logistics/finance), Pellmoor Water Authority (public utility).
- Written for this repository on 2026-11-08 by the builder (Claude Code sessions) from a brief that required
  versions, amendments, contradictions, distractors, future-dated versions, and prompt-injection fixtures.
- **Synthetic.** No real companies, people, matters, statutes or jurisdictions; any resemblance is accidental.
  Not legal, financial or policy advice. No affiliation with any real firm or vendor.
- Repeatability: `eval/dataset_manifest.json` lists every file with its SHA-256 and a dataset version hash
  (recomputed by `make seed`).
- License: same as the repository (MIT).

## Gold evaluation set

- `eval/gold/*.jsonl`: 112 questions (90 per-tenant + 22 cross-tenant/injection probes), each with asking
  identity, as-of date, relevant version refs, verbatim answer spans, abstain/conflict expectations,
  forbidden documents and a dev/test split. Validated by `scripts/validate_dataset.py` (spans must occur
  verbatim; relevant docs must be readable and in force; forbidden docs must be unreadable).
- Self-authored alongside the corpus, so it is easier than real-world queries. It is not an external benchmark.

## Models

| Model | Use | License | Size | Default |
|---|---|---|---|---|
| `sentence-transformers/all-MiniLM-L6-v2` | dense retrieval (384-d) | Apache-2.0 | ~90 MB | yes (`make setup` downloads it) |
| `cross-encoder/ms-marco-MiniLM-L6-v2` | rerank ablation (measured 2026-11-09: no gain here) | Apache-2.0 | ~90 MB | no (`make rerank-model`) |
| Any local OpenAI-compatible chat model (tested: `qwen3.6-35b-a3b-mlx` in LM Studio) | optional generative summaries | the model's own license | user-provided | no |

## Software

Runtime dependencies are pinned in `pyproject.toml`/`uv.lock` and `web/package-lock.json`.
`make licenses` writes the full inventory to `eval/reports/licenses.json` and fails on GPL/AGPL/SSPL runtime
dependencies. The current inventory includes weak-copyleft packages (LGPL-3.0, MPL-2.0) that are used
unmodified as libraries; review before any redistribution.
