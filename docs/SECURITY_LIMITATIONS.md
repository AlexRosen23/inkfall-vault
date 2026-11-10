# Security limitations (candid)

The Inkfall Vault is a **local, single-user-machine demo over fictional data**. Its tests show specific
properties hold on this code and dataset. They do not make it production-secure, compliant with any framework
(SOC 2, ISO 27001, HIPAA, etc.), or suitable for real client documents. Nothing here is legal advice.

## What is actually demonstrated

- Deterministic server-side authorization on every read path (list, read, raw export, search, ask, compare,
  citations, reviews, briefs, eval console). Tested by a 12-identity sweep (see `make security-test`).
- Zero leaks in that sweep. That is evidence for *this* fixture, not proof for all inputs.
- Immutable, checksummed versions and exact-offset citations; spoofed citations are rejected.
- Model output never decides access, never sees unauthorized passages, has no tools, and is validated.

## What is not done (and would be needed for real use)

| Area | Gap |
|---|---|
| Authentication | Fixture usernames, no passwords/MFA/SSO; see THREAT_MODEL "Mock authentication". |
| Transport | HTTP on localhost only; no TLS, no reverse proxy, no CSRF token (relies on SameSite=Strict + JSON bodies). |
| Storage | SQLite file unencrypted at rest; no key management; no backups; `data/` is git-ignored. |
| Multi-instance | Rate limiter and sessions are per process; no shared store, no horizontal scaling. |
| Retention | Audit events purge after 30 days (configurable). Documents have retention *labels* only; no automated disposal, no legal-hold workflow. |
| Parsing | Text/Markdown/PDF text layer only; no OCR, no Office formats; PDF parsing uses `pypdf` in-process (no sandbox). |
| Malware | No antivirus scanning of uploads. Uploads are never executed or written to disk outside SQLite. |
| Side channels | In-tenant BM25 statistics include unreadable documents; superseded-version existence is disclosed. |
| Injection | Regex flagging is heuristic and bypassable; safety rests on authorization + output validation. |
| Generation faithfulness | Lexical/numeric support checks catch invented numbers and missing citations, not subtle misreadings; the LLM judge that complements them is calibrated only against AI-drafted labels and shares the generator's model. Stripping echoed passage markers can leave awkward prose ("According to, ..."). |
| Remote model | The optional Claude provider sends the authorized source pack to the Anthropic API (third party). Opt-in per question, needs a key, never auto-selected. Tests use offline fixtures; the only live use is one owner-run 6-question check (`eval/reports/generative_claude.json`). |
| MCP | The stdio MCP server trusts whoever starts it and binds one identity per process; no client authentication. |
| Tracing | OpenTelemetry spans are off by default and carry no content, but an OTLP endpoint receives model names, counts and latencies; point it only at a collector you control. |
| Monitoring | No alerting, SIEM export, or anomaly detection on the audit log. |
| Supply chain | Dependencies pinned; `make audit-deps` runs pip-audit/npm audit on demand; no SBOM signing, no CI (Actions disabled by policy). |
| Evaluation | 45 documents and 112 questions written for this project; small and self-authored, so metrics are optimistic about real-world corpora. |

## Found and fixed in the 2026-11-09 audit

A review of the paths *around* retrieval (reports, audit log, records management) found three ways to learn about
documents without opening them. The 12-identity sweep didn't cover them, because it probes search and reads only.
All three are fixed, with regression tests in `tests/test_report_visibility.py` and three new cases in the
sweep's `api` section:

- **The evaluation report showed walled content.** Per-question rows were filtered by tenant only. A walled
  associate (theo.brandt) could read the gold questions and answers for the Harrow matter, including the
  settlement authority. Rows about documents you can't read now keep their metrics but hide their question and
  answer text, and unreadable refs are hidden wherever they appear.
- **The audit view showed other users' questions and refs.** An admin or reviewer saw every question asked in the
  tenant and the refs it hit, including restricted ones. Other users' question text is now hidden, and so are refs
  and version ids the viewer can't read. Who acted, when, and with what outcome stay visible.
- **An admin could replace or delete a document it couldn't read.** Adding a version to an existing doc key, or
  deleting it, now needs read access to every active version (else 403, logged as denied).

## Reporting

This is a portfolio project, not a maintained product. Do not load real or sensitive documents into it.
