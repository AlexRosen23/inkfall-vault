# The Inkfall Vault - every target is a real command. Ports: API 5110, web 5111.
SHELL := /bin/bash
UV ?= uv
API_PORT ?= 5110
WEB_PORT ?= 5111

.PHONY: help setup setup-offline seed api web demo test security-test eval eval-generative eval-docs lint audit-deps licenses ci rerank-model clean

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-16s %s\n", $$1, $$2}'

setup: ## Install Python + web deps and download the ~90 MB embedding model (one-time, needs network)
	$(UV) sync --extra dense
	$(UV) run python -c "from inkfall import embed; embed.get_model(allow_download=True); print('embedding model ready:', embed.EMBED_MODEL_ID)"
	cd web && npm ci

setup-offline: ## Install without the dense extra (BM25 + extractive only)
	$(UV) sync
	cd web && npm ci

seed: ## Rebuild data/inkfall.db from the fictional corpus (+ embeddings when available)
	$(UV) run python scripts/validate_dataset.py
	$(UV) run python -m inkfall.seed

api: ## Run the API on 127.0.0.1:$(API_PORT)
	$(UV) run uvicorn inkfall.api:create_app --factory --host 127.0.0.1 --port $(API_PORT)

web: ## Run the web app on 127.0.0.1:$(WEB_PORT) (proxies /api to the API)
	cd web && INKFALL_API=http://127.0.0.1:$(API_PORT) npx next dev --hostname 127.0.0.1 --port $(WEB_PORT)

demo: ## Seed if needed, then run API + web together (Ctrl-C stops both)
	@test -f data/inkfall.db || $(MAKE) seed
	@trap 'kill 0' EXIT; $(MAKE) api & sleep 2; $(MAKE) web

test: ## Full test suite (unit, isolation, security, generation guardrails, API contract)
	$(UV) run python scripts/validate_dataset.py
	$(UV) run pytest

security-test: ## Isolation + security + generation-guardrail suites, then the adversarial eval
	$(UV) run pytest tests/test_authz.py tests/test_isolation.py tests/test_api_security.py tests/test_generation.py -s
	$(UV) run python -m inkfall.adversarial

eval: ## Run the gold set through BM25/dense/hybrid(/rerank) and write eval/reports/latest.json
	@test -f data/inkfall.db || $(MAKE) seed
	$(UV) run python -m inkfall.evaluate
	$(UV) run python scripts/render_eval_docs.py

eval-docs: ## Re-render docs/RETRIEVAL_EVAL.md + docs/RAG_EVALUATION.md from the saved report
	$(UV) run python scripts/render_eval_docs.py

eval-generative: ## Opt-in: 6 dev questions through a local LM Studio/Ollama model (slow; ~1-2 min each)
	$(UV) run python -m inkfall.eval_generative
	$(UV) run python scripts/render_eval_docs.py

rerank-model: ## Opt-in: download the ~90 MB cross-encoder for the rerank experiment
	$(UV) run python -c "from inkfall import embed; embed.get_reranker(allow_download=True); print('reranker ready')"

lint: ## Ruff (Python) + TypeScript typecheck + ESLint
	$(UV) run ruff check src tests scripts
	cd web && npx tsc --noEmit && npm run lint

audit-deps: ## Known-vulnerability scan of Python and npm dependencies
	$(UV) run pip-audit --skip-editable
	cd web && npm audit --omit=dev --audit-level=high

licenses: ## Dependency license inventory (fails on GPL/AGPL in runtime deps)
	$(UV) run python scripts/check_licenses.py

ci: ## What .github/workflows/ci.yml runs (Actions are disabled on the repo; run this locally)
	$(MAKE) lint
	$(UV) run python scripts/validate_dataset.py
	$(UV) run pytest
	$(UV) run python -m inkfall.adversarial
	cd web && npm run build
	$(MAKE) licenses

clean: ## Remove generated local data (database, outbox) - corpus and reports are kept
	rm -rf data .pytest_cache .ruff_cache web/.next
