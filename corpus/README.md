# Seed corpus

Every document here is **fictional**: the organizations, people, places, jurisdictions, amounts and events
were invented for this demo. None of it is legal, financial or policy advice, and none of it refers to a real
company or matter. Prompt-injection text inside some documents is deliberate test material.

Layout: `corpus/<tenant>/<file>.md`, one file per document *version*. `identities.yaml` defines the three
tenants, their collections, ACL groups and the twelve demo identities.

## Front matter

```yaml
---
doc_key: CV-MSA-ORION            # tenant prefix (LF/CV/PM) + key; stable across versions
version: 1                       # 1..n; a higher version supersedes the lower one from its effective_date
title: Master Services Agreement — Orion Telematics Ltd.
tenant: corvane                  # must match the folder
collection: vendor-contracts     # one of the tenant's collections
doc_type: contract               # contract amendment sla schedule policy incident_note memo minutes engagement_letter notice report
classification: confidential     # public < internal < confidential < restricted
acl_groups: [cv-procurement, cv-finance]   # reader needs >= 1 of these AND clearance >= classification
ethical_wall: []                 # usernames screened from this document even if their groups match
matter: null                     # matter id for walled matters (e.g. harrow)
effective_date: 2024-02-01
amends: null                     # for amendments: the doc_key of the agreement it amends
retention: 7y after termination
parties: [Corvane Freight Holdings, Orion Telematics Ltd.]
tags: []                         # e.g. [injection-fixture, distractor, contradiction]
---
```

Body: Markdown. `#` title line, then `## N. Heading` sections with numbered clauses (`4.2 ...`) as separate
paragraphs (blank line between paragraphs). Citations point at exact character offsets in the body, so the
body is treated as immutable once seeded: edit = new version file.

Validate with `uv run python scripts/validate_dataset.py` (also run by `make test`).
