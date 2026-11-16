# Contradiction rule: what changed and what it measured

The rule lives in `evidence.find_conflicts`. It is deterministic, and no model is involved. This page records the
2026-11-09 revision: why it was made, what changed, and the numbers before and after on the **same frozen gold set**
(112 questions; no question, span or label was edited).

## Why

On the held-out test split, hybrid retrieval found **2 of 5** expected conflicts and raised **6 false alarms**
across 39 other answerable questions. The README listed this as the weakest result.

## Read this first: this is not a new held-out estimate

All five test-split conflict questions had already been reported, and the three misses were inspected one by one to
find their causes. Every change below fixes a gap in the *method* (a value type it could not read, a date format it
could not parse, a stemmer bug, an amendment it misread). None is a threshold tuned until the number moved. Still,
the test split is no longer independent for this rule. So read "after" as "the known failures are fixed". It is not
"contradiction detection generalizes". `resume_evidence/metrics.json` keeps the claim marked *do not claim*.

The dev split (4 conflict questions, where the original thresholds were tuned) is reported alongside as a regression
check.

## What changed

| Gap found | Example | Change |
|---|---|---|
| Counts were not a value type | CV-023 "How many depots lost live tracking…": incident note says 14, vendor RCA says 9 | A "how many X" question compares counts of X ("14 depots" vs "9 depots"). Time units stay durations. |
| Day-month-year dates were not parsed | All 119 dates in the documents' text are written "14 December 2026"; the parser read only "December 14, 2026" and ISO | Day-month-year is parsed. Before, date conflicts were impossible, and date questions got no value bonus when an answer sentence was picked. |
| Firm-wide policies never matched a named client | LF-022 "How long does Calderwood have to dispute one of our invoices?": the billing policy (30 days) applies to every engagement but never names Calderwood | A tenant-wide policy qualifies when the question is about the organization's own dealings ("our", "we", "us"), and must then share two concepts. A billing policy is *not* applied to a contract between two clients (LF-009). |
| A restating amendment hid the base value | PM-023: the amendment says the $25,000 quote threshold "continues to apply"; the rule treated the contract as overridden and the note said "the money differs" | An amendment that restates a value changes nothing, so the base value is compared with other documents. Override notes give the values ("14 days becomes 21 days from 2026-06-01"). |
| The stemmer split singular and plural | "invoices" → `invoic`, "invoice" → `invoice`; same for quote/quotes, dispute/disputes, fee/fees | After suffix stripping, a silent final "e" is dropped, and four-letter plurals are stemmed. This also feeds coverage and answer selection (see below). |
| Comparisons were flagged as contradictions | CV-011 "How does our treasury minimum cash rule compare with the… covenant?", PM-011 "…how is it different from…" | Comparison questions raise no conflict: differing values are the answer. |
| Questions about one named document were compared with others | LF-010 "…in the renewed engagement letter…", CV-020 "…for the Orion agreement?" | A question scoped to one document ("in/under/for the … letter/agreement/policy…", singular) raises no cross-document conflict. "Per the contract documents" (plural) is not scoped. |
| The subject's name counted as a shared topic | LF-012: a hold notice and a settlement memo both mention Harrow, with different dates about different things | The shared concept must be a topic, not the named subject or a unit word ("months", "amount"). |
| The same disagreement was listed twice | PM-023: contract and amendment both state $25,000 against the procurement policy | Identical value pairs are shown once. |

## Before and after (`make eval`, same 112 questions)

Before: `main` at `10aee90` (report from commit `2180604`). After: this branch.

Conflicts found / expected, and false alarms on other answerable questions:

| Split | Method | Before | After |
|---|---|---|---|
| test | BM25 | 2/5, 6 false alarms | 4/5, 3 false alarms |
| test | dense | 2/5, 4 | 4/5, 2 |
| test | **hybrid** (default) | **2/5, 6** | **5/5, 2** |
| test | hybrid + rerank | 3/5, 6 | 5/5, 4 |
| dev | BM25 | 4/4, 1 | 4/4, 1 |
| dev | dense | 3/4, 2 | 3/4, **3** |
| dev | hybrid | 4/4, 2 | 4/4, 2 |
| dev | hybrid + rerank | 4/4, 3 | 4/4, 3 |
| all | hybrid | 6/9, 8 | 9/9, 4 |

Side effects, mostly from the date parser and the stemmer, on the test split:

| Metric | Method | Before | After |
|---|---|---|---|
| Answer support rate | BM25 | 0.854 | 0.878 |
| Answer support rate | dense | 0.854 | 0.878 |
| Answer support rate | hybrid | 0.878 | 0.878 |
| MRR@10, nDCG@10, citation validity, leaks | all | unchanged | unchanged |

The abstention numbers in the report also include the separate XT-017 fix (PR #11).

## What is still wrong

- ~~One new false alarm: dev PM-001 under dense retrieval~~ (and PM-017, the same shape): fixed on 2026-11-16, see
  below.
- Remaining test false alarms (hybrid): CV-015 compares a service-credit percentage with an uptime percentage
  (both mention availability). LF-008 compares the indemnity limit with other money in the partners' minutes.
- The rule is lexical. It can't tell that two percentages measure different things, and a real corpus with more
  phrasing variety would lower its recall. A held-out estimate needs new conflict questions written without
  looking at this rule.

## 2026-11-16: a counterparty's duty is not the organization's own rule

**Cause (dev split).** PM-001 ("Above what purchase value do **we** now have to run a formal sealed bid…") and
PM-017 ("…at what purchase value did **we** need three written quotes?") ask about the Authority's own procurement
rule. The rule compared that policy with the Harrowgate maintenance contract and its amendment. The contract sentences
state *Harrowgate's* duty ("Harrowgate shall obtain three written quotes", "applies to Harrowgate's own purchases").
The questions name no subject, so the "same subject" check (condition 3) let every document through.

**Change (rule condition 5).** In a question about the organization's own conduct ("we", "our", "us"), a value
sentence whose actor is another party, written as "X shall/must/will" or "X's own", is not compared unless the
question names that party. Parties come from the document's own definitions ('Harrowgate Pumpworks Ltd.
("Harrowgate")'). Document nouns ("Agreement", "Contract", …) are excluded. A party whose full name contains the
tenant's name ("Pellmoor Water Authority (the "Authority")") is the organization itself. Questions that are not
first-person, or that name the counterparty, are compared as before; tests cover both.

**How it was measured.** The change was designed on the dev split only. The test split was then run once, as the
held-out check. Same frozen 112 questions; nothing in the gold set was edited.

| Split | Method | Before | After |
|---|---|---|---|
| dev | BM25 | 4/4, 1 false alarm | 4/4, **0** |
| dev | dense | 3/4, 3 | 3/4, **1** |
| dev | **hybrid** (default) | 4/4, 2 | 4/4, **0** |
| dev | hybrid + rerank | 4/4, 3 | 4/4, **1** |
| test | every method | unchanged (hybrid 5/5, 2) | unchanged |
| all | hybrid | 9/9, 4 | 9/9, **2** |

No other metric changed on either split (`eval/reports/latest.json`). The two remaining test false alarms (CV-015,
LF-008) have different causes, listed above, and are not addressed by this change. The test split says nothing new
about this rule's precision, because none of its false alarms had this shape.
