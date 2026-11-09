# Customer case study (synthetic)

> **Disclaimer.** "Lanternfield Partners LLP", "Corvane Freight Holdings" and "Pellmoor Water Authority" are
> invented. There is no customer, no deployment and no adoption. This walks through what the system does on
> its fictional corpus, with results taken from the saved test runs. It is a portfolio case study, not a
> testimonial.

## Situation

Lanternfield's commercial team supports a client, Brightwater Dairy Cooperative, on a packaging supply
agreement with Ostrander Packaging. The agreement was restated in July 2025 (v2) and amended in February 2026;
an internal memo from March 2026 summarises the terms. A partner asks: *"What notice do we need to give to end the
Brightwater agreement for convenience, and is anything inconsistent?"* At the same time, the firm runs a walled
litigation matter (Harrow) that one associate must not see at all.

## Workflow in the product

1. **Scope.** Ava Lindqvist (commercial analyst, confidential clearance) signs in; the server derives her tenant,
   groups and clearance. She picks the `commercial` collection and today's date.
2. **Ask.** Hybrid retrieval runs only over the 11 versions she may read. The answer is extractive: verbatim
   sentences with exact citations.
3. **Verify.** Each citation opens the source version with the span highlighted, plus a lineage drawer
   (checksum, ingestion time, extraction method, retention label, why access was granted).
4. **Compare.** The version comparison shows the restated v2 changed the convenience-termination notice and the
   liability cap relative to v1 (clause diff with typed value changes).
5. **Resolve.** The trust inspector shows contradictions only when its rule fires (same subject, shared
   concept, disagreeing same-unit values) and amendment overrides separately. Where it does not fire, the
   analyst still sees both passages in the source pack; detection quality is reported honestly (below).
6. **Brief and approve.** Ava adds cited sentences to a brief and submits it. She cannot approve it herself
   (separation of duties); Marcus, a reviewer who can read every cited source, approves; the release writes a
   Markdown packet to a local outbox. Every step is in the audit log.
7. **Isolation check.** Switching to Theo Brandt (walled from Harrow) and asking about the Harrow settlement
   returns an abstention: no title, snippet, citation or graph node from the walled matter.

## Results (from saved runs, not estimates)

See `resume_evidence/metrics.json` for each claim with its source file, test id, verification command and status.
Highlights to quote only with that file open: tenant-isolation leak count, held-out MRR/nDCG vs the title-only
baseline, citation validity, abstention F1, and contradiction detection (currently **not** a claimable strength).

## What we would measure with real users (not done)

Time-to-task was **not** measured; it needs people. A fair protocol:

1. Recruit analysts; give each 6 tasks of the kind above (2 single-document, 2 version/amendment, 2 conflict).
2. Counterbalance two conditions: (A) the library view + keyword search only; (B) the full workbench.
3. Record time to a submitted brief, the brief's citation correctness (graded against gold spans) and any
   access violations (expected zero in both conditions because the server enforces ACLs).
4. Report medians with spread and per-task results; do not convert to dollar savings.
