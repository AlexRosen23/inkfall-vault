# Contributing

## Branches and merges

- `main` is the reviewed line. Work on `feat/…`, `fix/…`, `chore/…` or `docs/…` branches, push, and open a PR
  with `gh pr create`. Merges into `main` need the owner's approval.
- The `pre-push` hook refuses direct pushes to `main` (`ALLOW_MAIN_PUSH=1` only for deliberate exceptions).
- `pre-commit` and `pre-push` run gitleaks. Never bypass them with `--no-verify`. The only allowlist entry
  covers corpus `doc_key:` identifiers (checked by hand; see `.gitleaks.toml`).

## Setup

```bash
make setup        # uv sync --extra dense, downloads all-MiniLM-L6-v2 (~90 MB), npm ci in web/
make seed         # validates the dataset and builds data/inkfall.db (+ embeddings)
make demo         # API on 127.0.0.1:5110 + web on 127.0.0.1:5111
```

Without network after setup everything works; without the dense extra (`make setup-offline`) the app runs
BM25 + extractive answers and reports dense/hybrid as unavailable.

## Checks

| Command | What it runs |
|---|---|
| `make test` | dataset validator + full pytest suite |
| `make security-test` | authz/isolation/security/generation suites + adversarial eval (`eval/reports/adversarial.json`) |
| `make eval` | gold set through BM25/dense/hybrid(/rerank) → `eval/reports/latest.json` + rendered docs |
| `make lint` | ruff + TypeScript typecheck + ESLint |
| `make smoke` | builds the static UI, serves it on one port over a throwaway DB copy, and drives real Chromium through login, the conflicting-clause question, a citation highlight, the ethical wall and the eval lab (installs Playwright 1.64.0 + Chromium on demand) |
| `make licenses`, `make audit-deps` | license inventory gate; pip-audit + npm audit |
| `make ci` | everything `.github/workflows/ci.yml` does |

CI: `.github/workflows/ci.yml` is defined but **GitHub Actions is disabled** on this private repo (owner
policy). Run `make ci` locally before opening a PR.

## Changing data

- Corpus documents are immutable once seeded: change = new version file (`.v2.md`) with a later
  `effective_date`. Run `uv run python scripts/validate_dataset.py`.
- Gold questions: answer spans must appear verbatim in a relevant, readable, in-force version. Tune heuristics on
  the `dev` split only; never on `test`.
- After changing retrieval/evidence code, commit first, then `make eval` so the report's provenance is clean.

## Environment variables (names only; nothing secret is required)

`INKFALL_DB`, `INKFALL_DATA_DIR`, `INKFALL_CORPUS_DIR`, `INKFALL_API_PORT`, `INKFALL_WEB_PORT`,
`INKFALL_EMBED_MODEL`, `INKFALL_RERANK_MODEL`, `INKFALL_LMSTUDIO_URL`, `INKFALL_OLLAMA_URL`, `INKFALL_LLM_MODEL`,
`INKFALL_LLM_MAX_TOKENS`, `INKFALL_AUDIT_RETENTION_DAYS`, `INKFALL_RATE_LIMIT_PER_MINUTE`, `INKFALL_API` (web proxy target).

## Never commit

Secrets, `.env*` (except `.env.example`), `data/` (SQLite DB, outbox), embedding caches, real documents.

## Releases and rollback

Annotated tags (`git tag -a v0.x.y`), rollback with `git revert` through a PR. No deployment exists; deploying
or making the repo public needs the owner's explicit approval.
