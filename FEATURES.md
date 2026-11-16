# The Inkfall Vault: features

The Inkfall Vault is a local evidence workbench for legal, finance and policy documents. An analyst asks a question,
and the server searches only the documents that analyst may read. It answers with sentences quoted word for word,
each tied to the exact characters it came from. If the evidence is too thin it says so, and when two documents
disagree it shows both. Everything runs on one laptop, on CPU, with no model and no API key required. All three
organizations and all 45 documents are fictional.

**This is the source-of-truth features list.** Every PR that adds, changes, removes or switches off something a person
can see or use updates this file in the same PR (see "Keeping this file true").

- **Repo:** AlexRosen23/inkfall-vault (public) · **Folder:** `~/Desktop/Claude Projects/The Inkfall Vault`
- **Status:** Working local demo (not production-secure; mock login) · **Version:** 0.1.0 · **`main`:** `30da973` (2026-11-15)
- **Last updated:** 2026-11-15, written from the code, README, docs and tests.

**Status words** (a feature with no status word is live):
| Word | Means |
| --- | --- |
| *Live* | on `main` and working |
| *Off by default* | built, behind a flag, a setting or an opt-in choice |
| *Partial* | built, with a stated weakness |
| *Planned* | listed as a next step in the README, not built |

## At a glance
| | |
| --- | --- |
| Stack | Python 3.12 (uv), FastAPI, SQLAlchemy, SQLite FTS5, sentence-transformers `all-MiniLM-L6-v2` (CPU), Next.js 16 / React 19 / TypeScript, pytest |
| Opt-in extras | Anthropic SDK (Claude Citations), MCP Python SDK, OpenTelemetry, LM Studio / Ollama local models |
| Ports | API and one-port app 5110; Next.js dev server 5111 |
| Code size | 5,467 lines of Python in `src/inkfall/` (26 modules plus `__init__`), 2,555 lines of TypeScript/TSX in `web/` (5 pages, 9 components) |
| Data | 3 fictional organizations, 12 fictional identities, 45 documents (15 per organization), 646 chunks, 112 gold questions |
| Tests | 18 test files, 110 `def test_` functions counted from source; README records 126 collected tests passing on 2026-11-10 |
| API | 32 route handlers in `src/inkfall/api.py` (session API under `/api/*`, plus a read-only contract) |
| MCP tools | 3, all read-only: `search`, `fetch_document`, `cite` |
| Headline results (saved runs) | hybrid MRR@10 0.966 and citation validity 100% on the held-out split; 0 leaks in 1,796 search probes and 898 direct reads |
| PRs | 17 PRs: 16 merged, 1 closed as a duplicate (#5) |
| CI | GitHub Actions `ci.yml` on `ubuntu-24.04`, every PR and push to `main` |
| License | MIT |

## Contents
1. What it is and who it's for
2. How to run it
3. Architecture at a glance
4. Features
5. Integrations
6. Data and privacy
7. Tests and evidence
8. Known limits and gaps
9. Change log
- Keeping this file true

## 1. What it is and who it's for

- **For:** a reviewer, interviewer or engineer who wants to see a retrieval-augmented system whose main promise
  (nobody sees what they may not read) holds by construction, and is tested under attack.
- **The scenario:** a law firm, a freight group or a water authority with many documents. A correct answer must
  come only from material the asker may read, must be checkable against exact source text, and must know when to
  stop. The scenario is written out in `docs/CUSTOMER_PROBLEM.md`.
- **The one thing it does best:** it decides access in plain code before any search runs, so unauthorized text never
  reaches ranking, snippets, prompts or logs.
- **What it is not:** legal advice, a certified system, or a production product. Login is a mock. See section 8.

## 2. How to run it

**Requirements:** macOS or Linux, [uv](https://docs.astral.sh/uv/) (installs Python 3.12), Node 24 and npm. The
one-time setup needs network access (Python and npm packages, plus a ~90 MB embedding model from Hugging Face).
After that everything runs offline.

| Step | Command | What it does |
| --- | --- | --- |
| 1 | `make setup` | `uv sync --extra dense`, downloads the embedding model, `npm ci` in `web/` |
| 2 | `make seed` | validates the dataset, then builds `data/inkfall.db` (+ embeddings) from the fictional corpus |
| 3 | `make serve` | runs `./run.sh`: API, read-only contract and built UI on one port, 127.0.0.1:5110 |

- `make setup-offline` installs without the dense extra: BM25 retrieval and extractive answers only; dense and
  hybrid are reported as unavailable.
- `./run.sh` seeds the database and builds the static UI (`web/out`) if either is missing, and stops with a message
  if `.venv` or `web/node_modules` is missing.
- `make demo`: dev mode. API on 5110 plus the Next.js dev server with hot reload on 5111 (it proxies `/api`).
- `make api` and `make web` run each half alone. Other port: `INKFALL_API_PORT=5112 ./run.sh`.
- Health check: `curl -s http://127.0.0.1:5110/health` returns `{"status":"ok","project_id":"inkfall","mode":"extractive",...}`.
- **Launch configurations** (`.claude/launch.json`): `inkfall-api` (port 5110) and `inkfall-web` (port 5111).

**All `make` targets:**

| Target | What it does |
| --- | --- |
| `make test` | dataset validator + full pytest suite |
| `make security-test` | authorization, isolation, API security and generation suites, then the adversarial sweep (`eval/reports/adversarial.json`) |
| `make eval` | gold set through BM25 / dense / hybrid (/ rerank) to `eval/reports/latest.json`, then re-renders the eval docs |
| `make eval-docs` | re-render eval docs, resume metrics and the authorization matrix from saved reports |
| `make eval-generative` | *Off by default.* 6 dev questions through a local LM Studio / Ollama model (slow) |
| `make eval-claude-live` | *Off by default, paid.* the same 6 questions through Claude's Citations API; needs `ANTHROPIC_API_KEY` |
| `make security-test-generative` | *Off by default.* adversarial sweep with a local model (`gpt-oss:20b` via Ollama) writing every answer; 1–2 hours |
| `make eval-faithfulness` | *Off by default.* re-judge saved answers with the frozen judge prompt, rebuild `faithfulness.json` |
| `make rerank-model` | *Off by default.* download the ~90 MB cross-encoder for the rerank experiment |
| `make mcp` | MCP server on stdio; `MCP_USER=dana.whitcombe` by default |
| `make lint` | Ruff, TypeScript typecheck, ESLint |
| `make smoke` | build the static UI, serve it on one port, drive real Chromium through the main flows (installs Playwright 1.64.0 + Chromium on demand) |
| `make licenses`, `make audit-deps` | dependency license gate; pip-audit + npm audit |
| `make ci` | everything the CI workflow runs |
| `make openapi` | regenerate the OpenAPI snapshot `docs/openapi.json` |
| `make web-export` | rebuild the static UI served by `make serve` |
| `make clean` | delete generated local data (database, outbox, caches); corpus and reports stay |

**Environment variables (names only; nothing secret is required):** `INKFALL_DB`, `INKFALL_DATA_DIR`,
`INKFALL_CORPUS_DIR`, `INKFALL_API_PORT`, `INKFALL_WEB_PORT`, `INKFALL_EMBED_MODEL`, `INKFALL_RERANK_MODEL`,
`INKFALL_LMSTUDIO_URL`, `INKFALL_OLLAMA_URL`, `INKFALL_LLM_MODEL`, `INKFALL_LLM_MAX_TOKENS`,
`INKFALL_AUDIT_RETENTION_DAYS`, `INKFALL_RATE_LIMIT_PER_MINUTE`, `INKFALL_API` (web proxy target),
`INKFALL_MCP_USER` (MCP identity), `INKFALL_OTEL` (tracing mode). `ANTHROPIC_API_KEY` switches on the opt-in Claude
provider.

**Demo identities (all fictional):**

| Organization | Identities |
| --- | --- |
| Lanternfield Partners LLP (law firm) | `ava.lindqvist` analyst · `marcus.oyelaran` partner/reviewer · `theo.brandt` associate (walled off the Harrow matter) · `lf.admin` |
| Corvane Freight Holdings | `dana.whitcombe` procurement/reviewer · `omar.haddad` treasury (restricted) · `june.park` ops · `cv.admin` |
| Pellmoor Water Authority | `rhea.castellanos` policy/reviewer · `sam.okafor` ops · `nadia.voss` board secretary (restricted) · `pm.admin` |

**Two questions to try** (checked against the API on 2026-11-09, per the README):
- As `ava.lindqvist`: "How much notice does the Brightwater supply agreement require to terminate for
  convenience?" gives status `contradictory`: the restated agreement's "ninety (90) days" and an internal memo's
  "sixty (60) days" appear side by side with exact spans.
- As `theo.brandt`: "What settlement authority has the client given in the Harrow matter?" gives
  `insufficient_evidence`, because that associate is behind the matter's ethical wall.

## 3. Architecture at a glance

One Python process (FastAPI over SQLite) serves the API, the read-only contract and a static export of the Next.js
UI. The security boundary is one function, and everything after it treats its input as already filtered.

```
Browser (untrusted) --session cookie--> api.py  (session -> user, limits, audit)
MCP client --stdio--> mcp_server.py ----------\
                                               v
                 access.authorized_versions  (calls authz.decide per version)
                                               | authorized chunk ids only
                                               v
              search.py  (FTS5 per tenant + MiniLM + reciprocal-rank fusion)
                                               v
                 SQLite  (immutable versions, chunks, FTS5, embeddings, audit)
                                               v
              evidence.py  (source pack, verbatim answer, abstain, conflicts, injection flags)
                      .  optional: authorized passages only
                      v
              Model (opt-in: LM Studio / Ollama / Claude) -> generate.py validator -> back to evidence
                                               v
                 api.py -> response;  approved briefs -> data/outbox
```

| Path | What lives there |
| --- | --- |
| `src/inkfall/` | The service. Core: `authz` (policy), `access` (authorized view), `ingest`, `search`, `evidence`, `generate` + `providers`, `service`, `api`, `audit` + `redact`, `contract`, `evaluate`, `adversarial`, `eval_generative`, `seed`, `db`, `config`, `corpus`, `identities`, `embed`, `gold`. Opt-in: `claude_citations`, `mcp_server`, `eval_faithfulness`, `telemetry` |
| `web/` | Next.js 16 UI: `app/` (login, workbench, library, lab, admin), `components/` (9 files), `lib/` (API client, types) |
| `corpus/` | 45 fictional documents in three tenant folders, plus `identities.yaml` |
| `eval/` | `gold/` (4 files, 112 questions), `dataset_manifest.json`, `faithfulness/` (judge prompts v1 and v2, AI-drafted labels, owner-review CSV with the owner's 30 verdicts, AI second-review CSV for the other 54), `reports/` (saved runs) |
| `tests/` | 18 test files |
| `scripts/` | dataset validator, eval-doc renderer, authorization-matrix renderer, license gate, browser smoke test, walkthrough recorder |
| `docs/` | 17 design, security and evaluation write-ups, `openapi.json`, `media/` (3 screenshots, 1 video) |
| `resume_evidence/metrics.json` | each claim with its metric, source, verify command and status |

**One question, end to end:**
1. **Who is asking.** `POST /api/ask` arrives with an HttpOnly session cookie (or a bearer token). The server finds
   the user from a server-side session whose token is stored hashed. Request bodies reject extra fields, so a client
   cannot add `tenant` or `role`.
2. **What they may read.** `access.authorized_versions` loads only the caller's tenant and runs `authz.decide` on each
   document version, then keeps the version in force on the "as of" date. Future-dated versions are never returned early.
3. **Retrieval inside that view.** FTS5 `MATCH` runs in the tenant's own table with the authorized chunk ids applied
   inside the SQL. Cosine similarity runs over authorized embeddings only. The two rankings are fused with
   reciprocal-rank fusion (k = 60). Unauthorized ids are dropped again in Python as a second guard.
4. **Evidence, not prose.** `evidence.py` builds a source pack (top 6 chunks, at most 3 per version) and picks verbatim
   sentences by IDF-weighted overlap, each with exact offsets. It computes coverage and abstains below 0.5 or when a
   named subject is missing, runs the contradiction rule, and flags sentences that look like injected instructions.
5. **Optional generation.** Only if a model was requested and the system did not abstain (section 4.6).
6. **Audit and response.** The event is logged (request id, actor, tenant, action, outcome, redacted query, never
   passage text). The answer returns with citations, a trust panel, retrieval diagnostics and an evidence graph.

## 4. Features

### 4.1 Access control (the security boundary)
- **Deterministic authorization** `authz.decide`: one pure function decides each document version. Allowed only if:
  same organization (tenant), document classification within the person's clearance, at least one shared ACL group,
  not behind an ethical wall naming the person, and not deleted. Deny wins, and an unknown label fails closed. Every
  decision carries plain-language reasons. `src/inkfall/authz.py`
- **Authorized view before retrieval** `access.authorized_versions`: search, ask, compare, library, citations, reviews,
  briefs and the evaluation console all read through the same view. `src/inkfall/access.py`
- **Ethical walls:** a named person is screened from a matter even inside their own team. Walled content never shows
  up as a snippet, title or citation.
- **Roles grant functions, never reads:** an admin can upload, delete and view the audit log, but no admin role opens a
  document by itself. Reviewer is a separate role used for brief approval.
- **Forbidden looks the same as missing:** unreadable and non-existent documents both return 404, so probing learns nothing.
- **Generated authorization matrix:** all 540 user × version decisions are rendered to `docs/AUTHORIZATION_MATRIX.md`
  by `scripts/render_authz_matrix.py`.
- **Server-side sessions:** the token is stored hashed, the `Authorization` header wins over a leftover cookie, and
  sessions last 8 hours. `src/inkfall/api.py`
- **API hardening:** request bodies reject unknown fields; query limit 500 characters; upload limit 2 MB; request size
  limits; a rate limit (default 120 per minute per process); error bodies list field names and types only, not values.
  Document text is served as inert text. Pages carry a CSP that allows framing only by the local Constellation host
  (*Partial*: protections are per process; see section 8).
- **Mock login** *(Partial)*: you pick a fixture identity, with no password. Sessions are real; authentication is not.

### 4.2 Retrieval
- **BM25 search** over SQLite FTS5, one index per tenant, so one tenant's documents cannot shift another's ranking.
  `src/inkfall/search.py`
- **Dense search** with `all-MiniLM-L6-v2` embeddings on CPU (needs the ~90 MB model from `make setup`).
- **Hybrid search** fusing both with reciprocal-rank fusion (k = 60). It is the default method.
- **Cross-encoder rerank** *(Off by default)*: `cross-encoder/ms-marco-MiniLM-L6-v2` over hybrid. Measured as no gain
  on this corpus at about 10 times the latency; kept as a recorded negative result. Download with `make rerank-model`.
- **"As of" date and version history:** returns the version in force on a chosen date. An option includes historical
  (superseded) versions. Old citations stay valid when a newer version arrives.
- **Collection filter:** limit a question to one collection.
- **Question clean-up:** stop words and filler words are dropped before lexical search.
- **Graceful degradation:** without the model, BM25 and extractive answers still work, and dense/hybrid are reported unavailable.

### 4.3 Evidence, citations and abstention
- **Extractive answers** (default, no model): verbatim sentences with exact character offsets into an immutable,
  checksummed document version. `src/inkfall/evidence.py`
- **Citation verification:** `POST /api/verify-citation` re-checks offsets (and an optional quote) against stored text
  and the caller's permissions, every time. Spoofed citations are rejected. `service.verify_citation`
- **Abstention:** if evidence coverage is under 0.5 or a named subject is missing from all authorized evidence, the
  answer is `insufficient_evidence` with the reason (for example "Named subject(s) not present in any authorized
  evidence: Harrow"). Test-split abstention F1 is 0.943 (hybrid).
- **Contradiction detection** *(Partial)*: a testable rule flags conflicts: same subject, shared concept, different
  values in compatible units. Status `contradictory` shows both sides with their spans. Handles counts, day-month-year
  dates, firm policies and restating amendments; in "do we / our" questions it does not compare a counterparty's own
  duty ("Harrowgate shall…") with the organization's rule. Rule write-up: `docs/CONTRADICTION_RULE.md`.
- **Amendment overrides:** an amendment counts as an override only when it restates the same kind of quantity in the
  same unit, so a real memo-versus-agreement conflict is not hidden.
- **Prompt-injection flagging** *(Partial, regex heuristic)*: sentences in documents or questions that look like
  instructions to an AI are flagged, shown as "Untrusted instructions detected", and never quoted as an answer.
  Safety rests on authorization and output checks, not on this flag.
- **Refusing instruction-following questions:** a question that tells the vault to follow instructions inside a
  document is refused (PR #11, closing probe XT-017).
- **Version compare:** `GET /api/compare/{a_id}/{b_id}` gives a clause-by-clause diff with typed value changes.

### 4.4 Web app (Next.js, five pages)
- **Login page:** choose a demo identity (`GET /api/identities`).
- **Workbench** (`/`): a six-stage flow.
  - *Scope:* collection, "as of" date, retrieval method (hybrid, bm25, dense, rerank), answer mode (extractive, local
    model, Claude Citations when available), and a "include historical versions" box.
  - *Ask:* 500-character question box, Cmd/Ctrl+Enter to ask, a Cancel button for slow answers.
  - *Verify:* answer panel with citation chips and an "abstained" state; clicking a citation opens the source with the
    cited span highlighted.
  - *Compare:* side-by-side version and conflict view.
  - *Brief:* build a brief from verified citations.
  - *Approve:* submit, review and release (4.5).
- **Trust inspector:** evidence coverage meter, injection warnings, conflicts, amendment overrides, freshness, and
  retrieval diagnostics. `web/components/TrustInspector.tsx`
- **Evidence graph:** a diagram of the question, sources and citations. `web/components/EvidenceGraph.tsx`
- **Document inspector:** a modal with the answer sentence, citations, context, document text and clauses, an "Access &
  lineage" section (why this identity may read it, version chain), and review labels. `web/components/DocumentInspector.tsx`
- **Library** (`/library`): every version the identity may read, filterable by collection, type, status (in force or
  historical) and title or ref text.
- **Evaluation & Trust Console** (`/lab`): "How well does the vault find, cite and refuse?" Shows provenance of the
  saved run, per-method metrics, a dev/test split switch, per-question results, adversarial results and the
  faithfulness judge. Rows are filtered through the viewer's authorized view (PR #10).
- **Admin console** (`/admin`): upload a document, list tenant documents, delete, quarantine list, audit log. Visible
  only to admin roles; others see "Forbidden".
- **Accessibility touches:** skip-to-main target, labelled form fields, `aria-live` loading text, dialog roles.
- **Polish from the 2026-11-09 audit (PR #13):** no blocking load screen while models are detected, readable document
  headings, answer-key tags hidden.

### 4.5 Briefs, review and release
- **Briefs:** an analyst builds a brief from verified citations. `POST /api/summaries`, `GET /api/summaries`.
- **Second-person approval:** `POST /api/summaries/{id}/submit` then `/decision`. Only a reviewer may decide, the
  author cannot approve their own brief (`separation_of_duties`), and the reviewer must be able to read every cited
  source. All citations are re-verified at decision time and again at release.
- **Spoofed quotes rejected:** a brief with a quote that is not in the stored text is refused.
- **Release to a local outbox:** `POST /api/summaries/{id}/release` writes `data/outbox/<tenant>/brief-<id>.md`. The
  "external" action is simulated; nothing leaves the machine. Release needs status `approved`.
- **Review labels:** `POST /api/reviews`, `GET /api/reviews` store correct / incorrect / partial labels on citations.

### 4.6 Optional models
- **Local generation** *(Off by default)*: LM Studio (port 1234) or Ollama (port 11434) are detected, never required.
  The model gets only authorized passages as data, no tools. It must return JSON sentences citing passage ids.
  `src/inkfall/generate.py`, `src/inkfall/providers.py`
- **Per-sentence validator:** an id outside the pack rejects the whole output; each sentence is graded supported,
  partial or unsupported on word and number overlap; sentences that repeat an injected instruction are withheld;
  accepted sentences are anchored back to stored spans.
- **Claude Citations provider** *(Off by default, Partial)*: with `ANTHROPIC_API_KEY` set, "Claude citations API"
  appears as an answer mode. Each authorized span is sent as one custom-content block, Claude's block citations are
  mapped back to (version, start, end), and each is re-verified before display. It sends authorized passages to
  Anthropic, so it is never auto-selected. `src/inkfall/claude_citations.py`
- **Faithfulness judge** *(Off by default)*: an LLM judge grades whether each generated answer is supported, calibrated
  against reference labels. Frozen prompts v1 and v2 in `eval/faithfulness/`. `src/inkfall/eval_faithfulness.py`

### 4.7 MCP server *(Off by default; run with `make mcp`)*
A second front door over stdio, for MCP clients such as Claude Code or Claude Desktop. `src/inkfall/mcp_server.py`,
`docs/MCP_SERVER.md`.
- **`search`**: query (up to 500 characters), optional `as_of`, `method` (bm25, dense, hybrid). Returns extractive
  sentences with exact citations, authorized passages with injection flags, conflicts and abstention.
- **`fetch_document`**: full text and metadata of one version the identity may read.
- **`cite`**: whether a citation is valid for this identity, and the exact stored quote.
- **Identity bound at launch** (`INKFALL_MCP_USER` or `--user`). No tool takes a user, tenant or role argument.
- **No existence oracle:** a forbidden version returns the same `not_found` as a missing one.
- **Untrusted-content marking:** results carry `untrusted_content: true` and per-passage `injection_flags`.
- **Read-only annotations** on all three tools; each call writes an audit event (`via: mcp`).

### 4.8 Audit, redaction and tracing
- **Structured audit log:** request id, actor, tenant, action, outcome, and a redacted query. Never passage text.
  Retention is 30 days by default (`INKFALL_AUDIT_RETENTION_DAYS`). The admin audit view shows only events the admin
  may see. `src/inkfall/audit.py`, `src/inkfall/redact.py`
- **OpenTelemetry GenAI spans** *(Off by default)*: `INKFALL_OTEL=console` prints spans; `INKFALL_OTEL=otlp` exports
  them (needs `uv sync --extra otlp`). Spans never carry question, document, prompt or output text.
  `src/inkfall/telemetry.py`

### 4.9 Uploads and administration
- **Document upload** `POST /api/admin/ingest`: text, Markdown and PDF text layer, up to 2 MB. New content for an
  existing document becomes a new immutable version. File names are sanitized.
- **Quarantine:** corrupt or malicious uploads are held and listed at `GET /api/admin/quarantine`.
- **Delete** `DELETE /api/admin/documents/{doc_key}`: admin only, and only for documents the admin can read (PR #10).
- **Admin document and audit lists:** `GET /api/admin/documents`, `GET /api/admin/audit`.

### 4.10 Evaluation and evidence tooling
- **Gold set:** 112 questions in four files (Lanternfield 30, Corvane 30, Pellmoor 30, cross-tenant 22) with a dev/test
  split. Heuristics are tuned on dev only. `eval/gold/`
- **Dataset validator** `scripts/validate_dataset.py`: checks every answer span appears verbatim in a relevant, readable,
  in-force version, and every relevant document against the access policy.
- **Evaluation harness** `inkfall.evaluate`: MRR@10, nDCG@10, citation validity, answer support, abstention F1,
  conflicts found and false alarms, leaks, and latency, for BM25, dense, hybrid and rerank, plus a title-only baseline.
- **Adversarial sweep** `inkfall.adversarial`: 12 identities, targeted search probes and direct reads, injection cases,
  generation attacks with a scripted malicious model, and 13 API-section checks (side channels from PR #10 included).
- **Real-model adversarial sweep** *(Off by default)*: `make security-test-generative` with `gpt-oss:20b`.
- **Rendered docs:** `scripts/render_eval_docs.py` writes the eval docs, `resume_evidence/metrics.json` and the README
  results block from saved reports, never from typed numbers.
- **Provenance:** every report records its command, commit and machine.
- **Browser smoke test** `make smoke`: real Chromium drives login, the conflicting-clause question, a citation
  highlight, the ethical wall and the eval lab, and checks the lab's API response for walled content.
- **Walkthrough:** a 40-second video, `docs/media/walkthrough.webm`, recorded with Playwright (`scripts/record_walkthrough.py`).
- **License gate** `scripts/check_licenses.py`: fails on GPL or AGPL in runtime dependencies.

### 4.11 Read-only project contract
Served without a session, built only from saved reports, with aggregates and labels but never document text or titles.
`src/inkfall/contract.py`
- `GET /health`: status (`ok` or `degraded`), project id `inkfall`, mode, version, problems, last run.
- `GET /capabilities`: what is implemented and what is not.
- `GET /runs`, `GET /runs/{run_id}`: saved measurements, each marked synthetic.
- `GET /api/system`: dataset version, document count, model and backend detection.
- `GET /api/eval/report`, `/api/eval/adversarial`, `/api/eval/adversarial-generative`, `/api/eval/faithfulness`:
  saved reports, filtered to what the viewer may see.

### 4.12 Not built
- **PostgreSQL backend** *(Planned)*: SQLite only; a tsvector plus pgvector backend is a next step.
- **OCR and Office formats:** not built; only the PDF text layer is parsed.
- **Real authentication** (OIDC, TLS) *(Planned)*.
- **Time-to-task savings:** not measured; a protocol is in `docs/CUSTOMER_CASE_STUDY.md`.

## 5. Integrations
- **Hugging Face model hub:** the one-time download of `all-MiniLM-L6-v2` (and the optional rerank model).
- **LM Studio and Ollama** (local, optional): OpenAI-compatible endpoints on 127.0.0.1.
- **Anthropic Citations API** (optional, paid, sends authorized passages): `make eval-claude-live`, and the UI answer mode.
- **MCP clients:** Claude Code (`claude mcp add inkfall-vault ...`, see `docs/MCP_SERVER.md`) and Claude Desktop.
- **OpenTelemetry** (optional): console or OTLP export.
- **The owner's Constellation app:** the README says it has a world, "The Evidence Chamber", that launches `./run.sh`
  and reads `/runs` and `/capabilities`. That app is a separate private repository.
- **GitHub Actions:** `.github/workflows/ci.yml` (see section 7).

## 6. Data and privacy
- **All data is fictional.** Three invented organizations, 12 invented people, 45 invented documents.
  `docs/DATASETS_AND_LICENSES.md` lists dataset and model licenses.
- **Where it lives:** `data/inkfall.db` (SQLite), `data/outbox/` (released briefs), embedding caches. `data/` is not
  committed and `make clean` deletes it.
- **What leaves the machine by default:** nothing. The one-time setup downloads packages and a model. Claude is used
  only if the user sets `ANTHROPIC_API_KEY` and chooses it, and then authorized passages and document titles go to Anthropic.
- **Secrets:** none are required. Gitleaks runs in pre-commit and pre-push hooks, with one narrow allowlist for the
  fictional `doc_key:` ids. `.env*` files and `data/` must never be committed.
- **Audit and tracing:** redacted queries only; no passage text in audit events or spans.
- **Not encrypted at rest.** See `docs/SECURITY_LIMITATIONS.md`.

## 7. Tests and evidence
Counted from source on 2026-11-15, not run. The README records 126 tests collected and passing on 2026-11-10 (after PRs #10–#14).

| File | `def test_` count | Covers |
| --- | --- | --- |
| `tests/test_api_security.py` | 25 | forged tokens, role/tenant fields, oversize bodies, rate limit, error bodies |
| `tests/test_generation.py` | 12 | guardrails, scripted malicious model |
| `tests/test_claude_citations.py` | 10 | Claude Citations mapping (fixtures built from the documented schema) |
| `tests/test_isolation.py` | 8 | zero leaks through search and ask |
| `tests/test_evidence_rules.py` | 8 | abstention, conflicts, amendment rule |
| `tests/test_authz.py` | 7 | authorization decisions, admin grants no reads |
| `tests/test_mcp_server.py` | 6 | MCP identity, forbidden equals missing, a stdio subprocess |
| `tests/test_ingest.py` | 5 | uploads, versions, quarantine |
| `tests/test_api_contract.py` | 5 | OpenAPI snapshot and API shape |
| `tests/test_report_visibility.py` | 5 | eval report side-channel fixes |
| `tests/test_contract.py` | 4 | read-only contract |
| `tests/test_telemetry.py` | 3 | spans carry no text |
| `tests/test_eval_claude_live.py` | 2 | live-run bookkeeping |
| `tests/test_dataset.py` | 2 | dataset integrity |
| `tests/test_retrieval.py` | 1 | dev-split MRR floor |
| **Total** | **103** | (parametrized cases account for the README's higher collected count) |

Commands: `make test` (validator + pytest), `make security-test`, `make lint`, `make smoke`, `make ci`.

**Recorded results** (saved reports in `eval/reports/`, quoted from the README, which cites 2026-11-09 to 2026-11-10 runs):
- Retrieval, held-out test split, 69 questions: BM25 MRR@10 0.938; dense 0.962; hybrid 0.966; hybrid + rerank 0.955;
  title-only baseline 0.814. Citation validity 100% for every method. Hybrid abstention F1 0.943.
  Hybrid latency p50 about 10.7 ms, rerank p50 about 89.8 ms.
- Contradictions on the test split, hybrid: 5 of 5 found, 2 false alarms. Not a held-out estimate (the rule was revised
  after inspecting its misses; before: 2 of 5 with 6 false alarms). Marked "do not claim" in `resume_evidence/metrics.json`.
- Adversarial sweep (`adversarial.json`): 0 leaks across 12 identities, 1,796 search probes and 898 direct reads;
  injection 21/21, generation 5/5, API 13/13.
- Real-model sweep (`adversarial_generative.json`, `gpt-oss:20b`, 2026-11-09): 0 leaks, 194 answers, 0 of 187 prompts
  with forbidden content. The first run caught the model echoing an injected instruction; fixed, run 2 passed.
- Faithfulness judge (judge-test, n=52): TPR 0.946, TNR 0.933 against AI-drafted labels: 30 owner-reviewed (30/30 agreed, 2026-11-16); 54 AI-drafted and independently re-checked by a second AI pass (53 agree, 1 flagged for owner decision: LF-010); not human-reviewed.
- Local generation sample (6 questions): 6 of 6 accepted; of 13 sentences, 10 supported, 2 partial, 1 unsupported.
- Live Claude sample (2026-11-09, 6 dev questions): 6 of 6 accepted; of 18 sentences, 12 supported, 1 partial, 5
  unsupported (all uncited connecting sentences). PM-007 wrongly abstained; the title fix has not been re-run live.
- MCP: 449 identity × unreadable-version pairs fetch and cite as missing; 0 forbidden canaries in 449 searches.
- CI: first run on Linux installed in 81 s; later runs are on the Actions tab.

## 8. Known limits and gaps
- Contradiction detection has no clean held-out number. Remaining false alarms (CV-015, LF-008 on test) are listed in `docs/CONTRADICTION_RULE.md`; the dev ones (PM-001, PM-017) were fixed on 2026-11-16.
- Abstention misses 2 of the 9 plain "unanswerable" gold questions across both splits (CV-024, LF-024; dev). A rule tried on 2026-11-16 fixed them on dev but refused 2 answerable held-out questions, so it was not shipped (`docs/ENGINEERING_DECISIONS.md` #17).
- Login is mock: no password, MFA or SSO; HTTP on localhost only.
- SQLite only; no PostgreSQL backend. No OCR or Office formats.
- Data is small and self-written (45 documents, 112 questions), so metrics are optimistic. Recall@5 is 1.0 for every method.
- Injection flagging and faithfulness checks are heuristic: they catch invented ids and numbers, not subtle misreadings.
- Faithfulness judge: labels AI-drafted; owner confirmed a 30-label sample on 2026-11-16 (30/30 agreed); the other
  54 of 84 were re-checked only by a second AI pass (53 agree, 1 flagged), not by a human; judge is the same model as the generator; all 15 FAIL labels in the test split are
  synthetic.
- Claude provider has one small live run; uncited connecting sentences count as unsupported.
- The MCP server trusts whoever starts it (one identity per process, no client authentication).
- In-tenant BM25 statistics still include documents the user cannot read (a documented residual risk).
- Storage is unencrypted at rest; rate limiting and sessions are per process.
- The adversarial sweep covers search, reads and the API checks added in PR #10; any new endpoint returning saved data
  needs a sweep case.
- No Dependabot configuration.

**Next steps listed in the README (*Planned*):** new conflict questions for a real held-out number; extend the sweep to
every endpoint returning saved data; owner decision on LF-010 (flagged by the AI second review) and a human review of the other 53 labels outside the reviewed 30; re-run the live Claude check; real
authentication and TLS; a Postgres backend.

## 9. Change log
| Date | PR | Change |
| --- | --- | --- |
| 2026-11-16 | — | Faithfulness labels: AI second review of the 54 labels outside the owner's 30 (53 agree, LF-010 flagged for owner decision; not a human review, no label or metric changed) |
| 2026-11-16 | #20 | Faithfulness labels: owner reviewed the 30-label sample (30/30 agreed) |
| 2026-11-16 | #19 | Contradiction rule: a counterparty's duty is not our own rule (dev false alarms 2 → 0, hybrid; test unchanged); abstention rule tried and not shipped |
| 2026-11-11 | #17 | Refresh the Claude generative report (owner re-run of 2026-11-09 21:58 UTC) |
| 2026-11-10 | #16 | Fix the LICENSE text; stop tests leaking temp databases |
| 2026-11-10 | #15 | README describes the merged audit fixes |
| 2026-11-10 | #14 | `make smoke`: real-browser test of the one-port build, run in CI |
| 2026-11-10 | #13 | Demo polish: no blocking load screen, readable document headings, answer-key tags hidden |
| 2026-11-10 | #12 | Contradiction rule: held-out 2/5 to 5/5, false alarms 6 to 2 on the same frozen questions |
| 2026-11-10 | #11 | Refuse questions that ask to act on document instructions (XT-017) |
| 2026-11-10 | #10 | Close three side channels: eval report, audit view, admin replace/delete |
| 2026-11-10 | #6 | README write-up; CI moved to Linux with CPU-only torch; Actions enabled |
| 2026-11-09 | #9 | Record the first live Claude run; send document titles to Claude; fix token total |
| 2026-11-09 | #8 | `make eval-claude-live`; seed the database before the adversarial step in CI |
| 2026-11-09 | #7 | Add MIT LICENSE |
| 2026-11-09 | #5 | Closed: duplicate fix for the one-port login loop (fixed in #4) |
| 2026-11-09 | #4 | AI Engineer readiness: Claude Citations, real-model sweep, faithfulness judge, MCP server, OWASP LLM mapping, OTel spans |
| 2026-11-09 | #3 | Rerank ablation: measured, no gain |
| 2026-11-09 | #2 | Read-only contract and one-port serving |
| 2026-11-09 | #1 | First build: data, access and retrieval, evidence and guarded generation, UI, evaluation docs (phases 1–5) |

## Keeping this file true
- **Same PR, same change:** a PR that adds, changes, removes or switches off anything a person can see or use updates
  this file in that PR.
- **Status moves with reality:** change the status word when a feature moves (for example *Partial* to live).
- **Only what is true:** list nothing that is not in code, tests or docs; write "unverified" instead of guessing; keep
  numbers tied to a saved report and its date.
- **Repo gates:** the README's rendered results blocks come from `scripts/render_eval_docs.py`; re-render them rather
  than typing numbers. Run `make ci` before opening a PR. Never bypass the gitleaks hooks.
