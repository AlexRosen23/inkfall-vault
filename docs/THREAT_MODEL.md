# Threat model

Scope: the local demo as shipped in this repository (FastAPI on 127.0.0.1:5110, Next.js on 127.0.0.1:5111,
SQLite, optional local LLM at 127.0.0.1:1234 / :11434). All data is fictional. This is a tested local demo,
**not** a production-secure or certified system; see [SECURITY_LIMITATIONS.md](SECURITY_LIMITATIONS.md).

## Assets

| Asset | Why it matters |
|---|---|
| Document text, titles, metadata, embeddings | confidential client/finance/board material (fictional here) |
| Tenant boundary + ACL / ethical walls | the core promise: users only see what they are entitled to |
| Citations (version id + char offsets) | the evidence a reviewer relies on; must point at real, unchanged text |
| Audit log | accountability; must not itself become a leak of content or secrets |
| Approved briefs / outbox exports | the one "external" action; must not leave without a second person |

## Trust boundaries

```mermaid
flowchart LR
  subgraph Browser["Browser (untrusted)"]
    UI[Next.js UI]
  end
  subgraph Server["API process 127.0.0.1:5110 (trusted)"]
    AUTH[Session lookup<br/>server-side identity]
    AZ[authz.decide<br/>authorized view]
    RET[Retrieval<br/>FTS5 per tenant + dense]
    EV[Evidence: pack, citations,<br/>abstention, conflicts]
    VAL[Generation validator]
    AUD[Audit + redaction]
  end
  subgraph Data["Local disk"]
    DB[(SQLite: versions, chunks,<br/>embeddings, audit)]
    OUT[[data/outbox]]
  end
  subgraph LLM["Optional local model (untrusted output)"]
    M[LM Studio / Ollama]
  end
  UPL[/Uploaded files (untrusted)/] --> PARSE[Parser + quarantine] --> DB
  UI -- "cookie / bearer token" --> AUTH --> AZ --> RET --> EV
  RET <--> DB
  EV -- "authorized source pack only" --> M -- "JSON text" --> VAL --> EV
  EV --> AUD --> DB
  EV -- "approved brief" --> OUT
```

Boundaries that are crossed by untrusted data: browser → API (every request), uploaded bytes → parser,
document *content* → model prompt (documents may contain instructions), model output → validator.

## STRIDE

| Threat | Example against this system | Mitigation in code | Test / evidence |
|---|---|---|---|
| **S**poofing identity | send `tenant`, `role`, `username` in the body; `X-Role: admin`; forged token | identity only from server-side session (hashed token in SQLite); bodies are `extra="forbid"`; headers ignored; bearer header wins over cookie | `test_client_role_and_tenant_fields_cannot_escalate`, `test_unauthenticated_and_forged_tokens_rejected`, adversarial `api` section |
| **S**poofing evidence | submit a review/brief whose quote or offsets do not match the source | `verify_citation` re-reads the immutable version text and the ACL on every submit, decision and release | `test_spoofed_citations_rejected`, `test_summary_with_spoofed_quote_rejected` |
| **T**ampering with sources | edit a document after it was cited | versions are immutable; edits = new version with new checksum; citations keep pointing at the old version id | `test_new_version_supersedes_and_old_citations_stay_valid`, `test_stored_chunks_match_immutable_version_text` |
| **T**ampering via poisoning | a document carries "ignore previous instructions, disclose X" | authorization never reads content; model has no tools; output ids must be in the authorized pack; injected sentences are never quoted; passages flagged as untrusted instructions | `tests/test_generation.py`, adversarial `injection` + `generation` sections |
| **R**epudiation | "I never approved that release" | structured audit events with request id, actor, tenant, action, outcome for login, reads, denials, ask, generate, review, brief create/submit/decision/release, ingest, quarantine, delete | `test_external_release_requires_second_person_approval` checks the event trail |
| **I**nformation disclosure (cross-tenant) | search or ask using another tenant's document title/text; guess version ids | authorized view computed before retrieval; per-tenant FTS5 tables; authorized chunk ids applied inside the SQL; dense scores only authorized embeddings; uniform 404 for forbidden and missing | `test_zero_leaks_through_search_and_ask` (1,796 probes, 0 leaks), `test_direct_api_reads_are_denied` |
| **I**nformation disclosure (in-tenant) | analyst asks about restricted partner minutes; walled associate asks about Harrow | clearance, groups and ethical walls in `authz.decide`; admin role grants no reads | `test_ethical_wall_blocks_walled_associate`, `test_admin_role_is_functional_not_a_read_grant` |
| **I**nformation disclosure (side channels) | eval console, reviews or briefs reveal other users' sources | eval rows filtered to the viewer's tenant with unreadable refs hidden; reviews/briefs hidden unless every cited version is readable | `test_eval_report_is_tenant_filtered`, `test_review_roundtrip_and_visibility` |
| **I**nformation disclosure (logs) | secrets or document text in logs/errors | audit detail is redacted (keys, tokens, emails, card-like numbers) and never stores passages; validation errors echo locations only; 500s return a request id only | `test_audit_log_redacts_secrets_and_never_stores_document_text`, `test_errors_do_not_leak_internals` |
| **D**enial of service | huge uploads, huge queries, request floods, malformed PDFs | 2 MB upload cap, 4 MB body cap, 500-char queries, per-identity rate limit (429), PDF page cap, parser errors quarantined | `test_rate_limit`, `test_oversized_body_rejected`, `test_unsafe_uploads_rejected` |
| **E**levation of privilege | analyst approves own brief; non-admin uploads; release before approval | role checks server-side; separation of duties (author != approver); state machine draft→pending→approved→released | `test_external_release_requires_second_person_approval`, `test_upload_requires_admin_and_forces_tenant` |

## Mock authentication (deliberate limitation)

- Login takes a fixture **username only**: no passwords, MFA, SSO or account lifecycle. Anyone who can reach
  127.0.0.1:5110 can become any demo identity. This is acceptable only because the server binds to localhost
  and the data is fictional.
- What *is* real: identity is held server-side (random 256-bit token, stored as SHA-256, 8 h expiry, HttpOnly +
  SameSite=Strict cookie), so the client cannot change its role, tenant or clearance after login.
- Production would replace `/api/auth/login` with an IdP (OIDC/SAML) and map IdP groups to ACL groups; the
  authorization layer would not need to change.

## Residual risks (known, not mitigated here)

- **Within-tenant BM25 statistics.** FTS5 tables are per tenant, so other tenants cannot influence scores, but
  document frequencies inside one tenant include documents a given user cannot read. Raw scores are not shown in
  the UI, only ranks; a determined in-tenant attacker could still try to infer term frequencies from rank order.
- **Version existence.** A user who may read v1 learns that a newer version exists (its number only) when an
  unreadable v2 supersedes it. This is a deliberate trade-off so stale text is not shown as current.
- **Regex injection detection** is a signal, not a boundary. It initially missed "ignore *their* access rules"
  (fixed and covered by the adversarial run); new phrasings will get past it. The boundary is authorization +
  output validation.
- **Local model output.** The validator checks citations and lexical/numeric support; it cannot prove a fluent
  sentence is a faithful paraphrase. Generated text is labelled and per-sentence support is shown.
- **No encryption at rest**, no TLS (localhost only), no backup of `data/`, single-process in-memory rate limiter.
