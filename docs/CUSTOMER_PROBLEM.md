# Customer problem (synthetic scenario)

> All organizations, people and documents are fictional. This describes the problem the demo is built
> around; it is not a real customer engagement and no adoption or savings are claimed.

## Personas

| Persona | Tenant | Job to be done |
|---|---|---|
| **Ava Lindqvist**, commercial analyst | Lanternfield Partners LLP (law firm) | Answer a partner's question about a client supply agreement: which notice period and liability cap apply *today*, after a restatement and an amendment, and whether any internal memo disagrees. |
| **Dana Whitcombe**, procurement analyst | Corvane Freight Holdings | Before a vendor review, confirm Orion's committed uptime and the September outage duration, which two Orion-supplied documents and Corvane's own incident note state differently. |
| **Rhea Castellanos**, policy analyst | Pellmoor Water Authority | Confirm the current records-retention period and procurement quote threshold after policy revisions, without seeing restricted board material. |
| **Marcus Oyelaran** / reviewers | each tenant | Approve a citation-backed brief before it leaves the team. |

## Pain today (in the scenario)

- The answer is spread across a base agreement, a restated version, an amendment and a memo; keyword search
  returns all of them with no notion of which version is in force on a given date.
- Internal documents contradict each other (memo says 60 days, restated MSA says 90). Generic chat tools tend
  to flatten that into one confident answer.
- Matter-level ethical walls and board-level restrictions mean "just index everything" is unacceptable: a
  walled associate must not get a single snippet, title or citation from the walled matter.
- Anything sent outside the team needs a second person to sign off, and a trail of who saw what.

## Requirements

1. Answers only from documents the user is entitled to, enforced in server code before retrieval.
2. Every claim cites an exact span of an exact, immutable version; one click shows it highlighted.
3. Version-aware: "as of" date, superseded versions labelled, amendments shown as overrides.
4. Contradictions shown side by side, never silently resolved; abstain when evidence is insufficient.
5. Works offline with no model (extractive); a local model is optional and its output is validated.
6. Human approval before the one external action (releasing a brief); full audit trail.

## Success criteria and how they are measured

| Criterion | Measure | Where |
|---|---|---|
| No unauthorized exposure | leak count across all identities and attack probes = 0 | `make security-test` → `eval/reports/adversarial.json` |
| Right document found | MRR@10 / nDCG@10 on held-out gold questions vs a title-only baseline | `make eval` → docs/RETRIEVAL_EVAL.md |
| Trustworthy citations | citation validity = 100%; answer-support and unsupported-answer rates reported | docs/RAG_EVALUATION.md |
| Knows when to stop | abstention precision/recall/F1 on unanswerable + permission probes | docs/RAG_EVALUATION.md |
| Conflicts surfaced | conflicts found / expected and false alarms | docs/RAG_EVALUATION.md (currently weak on test; see limitations) |
| Fast enough | p50/p95 latency on CPU | eval report |
| Time-to-task | **not measured**: would need a timed study with real users. A protocol is in CUSTOMER_CASE_STUDY.md. | n/a |

## Constraints

Local CPU only; no paid APIs; fictional data only; no deployment; mock authentication on localhost.
