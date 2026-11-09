# API and auth contract

Base URL `http://127.0.0.1:5110` (the web app proxies `/api/*`). Machine-readable contract:
[`docs/openapi.json`](openapi.json) (checked against the live app by `tests/test_api_contract.py`;
regenerate with `make openapi`). Interactive docs at `/api/docs` while the API runs.

## Authentication (demo)

| Step | Contract |
|---|---|
| Login | `POST /api/auth/login {"username": "<fixture id>"}` → sets `inkfall_session` (HttpOnly, SameSite=Strict, 8 h) and returns `{user, token}` |
| Authenticate later requests | browser: the cookie; scripts/tests: `Authorization: Bearer <token>` (the header wins if both are present) |
| Identity | resolved server-side from the session: username → tenant, groups, clearance, roles (fixture `corpus/identities.yaml`) |
| Logout | `POST /api/auth/logout` deletes the session row |
| Not allowed | any `tenant`, `role`, `username`, `clearance` field in a body → **422** (`extra="forbid"`); `X-Role`/`X-Tenant` headers and query params are ignored |

There are no passwords: this is a local fixture login, documented as a limitation in THREAT_MODEL.md.

## Authorization semantics

- Every document-bearing response is computed from the caller's **authorized view** (see AUTHORIZATION_MATRIX.md).
- Forbidden and nonexistent objects both return **404 `{"error": "not_found"}`** (no existence oracle).
- Role-gated functions return **403** (`forbidden`, or `separation_of_duties: ...`).
- State conflicts return **409** (`approval_required`, `invalid_state`, `citation_no_longer_valid: ...`).

## Endpoints

| Method + path | Who | Purpose |
|---|---|---|
| `GET /api/health` | anyone | liveness |
| `GET /api/identities` | anyone | fixture identities for the login screen (no secrets exist) |
| `GET /api/auth/me` | user | identity, tenant, groups, clearance, roles, collections |
| `GET /api/documents?collection&include_history&as_of` | user | authorized versions (metadata only) |
| `GET /api/documents/{version_id}` | user | text, chunks with offsets, lineage, access reasons, authorized version list |
| `GET /api/documents/{version_id}/raw` | user | `text/plain` attachment, `nosniff` |
| `GET /api/compare/{a}/{b}` | user | clause diff + typed value changes between two authorized versions of one document |
| `POST /api/ask` | user | full evidence pipeline (see below) |
| `POST /api/verify-citation` | user | is `{version_id, char_start, char_end, quote}` real and readable by me? |
| `POST /api/reviews`, `GET /api/reviews` | user | correct / incorrect / partial labels on cited spans |
| `POST /api/summaries`, `GET /api/summaries` | user | citation-backed briefs (every item re-verified) |
| `POST /api/summaries/{id}/submit` | author | draft/rejected → pending |
| `POST /api/summaries/{id}/decision` | reviewer, not author | approve / reject |
| `POST /api/summaries/{id}/release` | author or approver | approved → released; writes `data/outbox/<tenant>/brief-<id>.md` only |
| `POST /api/admin/ingest` | admin | JSON upload (`content_base64`), tenant forced from session; bad files → 422 + quarantine |
| `DELETE /api/admin/documents/{doc_key}` | admin | soft delete versions, hard delete chunks/FTS/embeddings |
| `GET /api/admin/quarantine`, `/api/admin/documents` | admin | quarantine list (no content); registry (titles hidden when unreadable) |
| `GET /api/admin/audit` | admin, reviewer | tenant audit events (redacted) |
| `GET /api/system` | user | embedding/reranker status, detected generation backends, dataset version |
| `GET /api/eval/report`, `GET /api/eval/adversarial` | user | saved reports; per-question/case rows limited to own tenant |

## Read-only project contract (no session)

For dashboards such as the owner's Constellation, which reads it from 127.0.0.1 only. Built from the saved reports
in `eval/reports/`; it carries aggregate numbers and labels and **never** document text, titles, questions,
identities or tenant data (`tests/test_contract.py` checks every document key, title and opening line against it).

| Path | Returns |
|---|---|
| `GET /health` | `{status: ok \| degraded, project_id: "inkfall", mode, version, problems[], last_run}` |
| `GET /capabilities` | `{project_id, name, version, implemented[], not_implemented[], disabled_by_design[], active_mode, dataset: {synthetic: true, …}, endpoints}` |
| `GET /runs?limit=N` | `{project_id, total, runs[]}`, newest first; each run `{run_id, kind: eval \| adversarial \| generative, status: completed \| failed, mode: "recorded", started_at, ended_at, headline, provenance: {synthetic: true, git_commit, dataset_version, command}, artifacts}` |
| `GET /runs/{run_id}` | one run, or 404 |

A run is only ever a measurement this repository executed and saved (`make eval`, `make security-test`,
`make eval-generative`). `provenance.synthetic` is true because the corpus is fictional, not because the run was
simulated.

## Pages and framing

When `web/out` exists (`make web-export`, or `run.sh` builds it), the API also serves the static UI at `/`. Page
responses carry a CSP of `default-src 'self'` (inline scripts/styles allowed for Next.js) and
`frame-ancestors 'self' http://127.0.0.1:4520 http://127.0.0.1:4521 http://localhost:4520 http://localhost:4521`, so
only this machine's Constellation can embed it. API and contract responses keep `frame-ancestors 'none'` and
`X-Frame-Options: DENY`.

## `POST /api/ask`

Request: `{question (1-500 chars), as_of?, method: bm25|dense|hybrid|rerank, collection?, include_history, generate: extractive|generative|lmstudio|ollama}`.

Response (abridged): `status` (`supported` | `contradictory` | `insufficient_evidence` | `partially_unsupported`),
`mode` + `mode_label` (extractive vs generated is always explicit), `answer[]` (`text`, `citations[]` with
`version_id/char_start/char_end/quote/ref/pid`, `support`, `notes`), `abstained`, `abstain_reason`,
`trust` (`evidence_coverage`, matched/missing terms, gaps, `conflicts[]`, `amendment_overrides`, `freshness`,
`untrusted_instructions_in_sources/question`), `retrieval` (method, notes, latency, top hits with per-method ranks),
`sources[]` (the source pack), `graph` (nodes/edges from metadata and retrieval links), `generation` (status,
model, latency, token *estimates*, reported usage, rejection reason), `request_id`.

## Limits and headers

Body > 4 MB → 413; upload > 2 MB → quarantined; queries > 500 chars → 422; per-identity rate limit (default
120/min) → 429 with `Retry-After`. Every response carries `X-Request-ID`, `Cache-Control: no-store`,
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and a restrictive CSP.
Errors never echo submitted values or stack traces.
