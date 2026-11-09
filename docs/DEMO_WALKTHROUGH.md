# 90-second demo walkthrough

Shows an authorized query with verified citations, a denied query from a different identity, and a documented
failure case. All data is fictional. No model is needed (extractive mode).

## Before recording

```bash
make seed
```

```bash
make demo
```

Open http://127.0.0.1:5111, set the browser to about 1440x900, and start a screen recording (macOS:
Cmd-Shift-5 → "Record Selected Portion"). Don't record real browser tabs, bookmarks or accounts.

## Script

| Time | Do | Say |
|---|---|---|
| 0:00 | Login screen | "Three fictional organizations, twelve fixture identities. The server decides what each one may read; there is no role switcher in the client." |
| 0:08 | Pick **Ava Lindqvist** (Lanternfield, commercial analyst). Click the suggestion *"What notice is required to terminate the Brightwater supply agreement for convenience?"* → **Ask** | "Retrieval runs only over the 11 versions Ava may read: BM25 and local embeddings, fused." |
| 0:15 | Point at the **Contradictory evidence** badge and the **Extractive** label | "Every answer sentence is verbatim source text. The restated agreement says ninety days; an internal memo still says sixty. It shows both instead of picking one." |
| 0:25 | Click the **P2 · LF-MSA-BRIGHTWATER@2** chip | "Side-by-side verification: the exact character span in the stored version, re-checked against the source." |
| 0:32 | Open **Access & lineage**, then the **Compare** tab (v1 → v2) | "Why Ava may read it, the checksum and ingestion record, and what changed between versions: the notice period and the liability cap." |
| 0:42 | Close; **+ Add to brief** on the 90-day sentence, submit the brief | "Anything leaving the team needs a different reviewer. Ava cannot approve her own brief." |
| 0:50 | **Switch identity** → **Theo Brandt** (walled off the Harrow matter). Ask *"What is the Harrow settlement authority?"* | "Theo is in the litigation group, but an ethical wall screens him from Harrow." |
| 0:57 | Show **Insufficient evidence** (named subject not in authorized evidence), the graph with no Harrow node, then **Library**: no Harrow documents | "No title, snippet, citation or graph node. Direct API reads return the same 404 as a nonexistent id." |
| 1:05 | **Evaluation lab**: provenance block, test-split table, adversarial section | "Numbers come from saved runs with the commit and dataset hash: zero leaks across 1,796 targeted probes; held-out MRR and nDCG against a title-only baseline." |
| 1:15 | Failures explorer → filter *conflict false alarm* | "And the failures: contradiction detection is weak on held-out questions, and one injection probe (XT-017, visible to Corvane identities) gets an answer from authorized documents when it should abstain. Nothing leaks, but it's listed rather than hidden." |
| 1:25 | End on the footer | "Fictional data, decision support, not legal advice." |

## Optional extras (outside the 90 seconds)

- **Approve and release:** switch to **Marcus Oyelaran** → Approvals → Approve → as Ava, **Release** → the packet
  is written to `data/outbox/lanternfield/` and the audit log (Admin or reviewer) shows each step.
- **Local model:** with LM Studio running a chat model, choose "Local model" and ask the Orion uptime question.
  It takes about 1-2 minutes; each generated sentence shows supported / partial / unsupported.
- **Admin:** sign in as `cv.admin`: the registry lists restricted documents by key with titles hidden; an upload
  of `../../etc/passwd.pdf` is quarantined with its hash and reason, never its content.
