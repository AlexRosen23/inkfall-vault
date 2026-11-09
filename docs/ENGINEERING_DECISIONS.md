# Engineering decisions and trade-offs

| # | Decision | Alternatives considered | Why | Cost / risk accepted |
|---|---|---|---|---|
| 1 | **Authorization as a pure function** (`authz.decide`) applied to build an authorized view *before* retrieval | Filter results after retrieval; vector-store metadata filters; ask the model to respect permissions | Pre-filtering means unauthorized text never enters scoring, snippets, prompts or logs; a pure function is exhaustively testable (540 decisions in the matrix) | Each query loads the tenant's version rows (fine at this scale; would need caching/indexing at 100k+ docs) |
| 2 | **One FTS5 table per tenant** | Single FTS table + WHERE filter | Keeps BM25 document-frequency statistics tenant-scoped, so tenants cannot influence each other's ranking | More tables to manage; in-tenant statistics still include unreadable docs (documented residual risk) |
| 3 | **Authorized chunk ids applied inside the SQL** (`chunk_id IN json_each(:ids)`) plus a second check in Python | Trust the index | Defence in depth: a future indexing bug cannot surface an unauthorized chunk | Negligible |
| 4 | **Uniform 404** for forbidden and missing | 403 for forbidden | Prevents probing which ids exist in other tenants | Slightly less helpful errors for legitimate users |
| 5 | **Immutable versions + exact char offsets** | Store chunks only; re-chunk on edit | Citations stay verifiable forever; "edit" = new version with new checksum | Storage grows with versions |
| 6 | **Extractive answers by default** (verbatim sentences) | Always generate | Works offline, zero cost, every word is source text; generation is opt-in and labelled | Extractive answers read like evidence lists, not prose |
| 7 | **Validate model output instead of trusting it**: JSON only, ids must be in the pack (else reject all), per-sentence lexical + numeric support, anchor to stored spans | LLM-as-judge; trust citations | Deterministic and testable with a scripted malicious model; catches invented ids and numbers | Cannot detect subtle paraphrase errors; strict numeric check can flag harmless restatements |
| 8 | **Deterministic grading** (gold spans, exact refs) | LLM judge, human-only rubric | Reproducible and free; no model grading itself | Gold spans can miss correct answers phrased differently; human labels collected separately |
| 9 | **Rule-based contradiction detection** (same subject, shared concept, unit-aware value mismatch, amendment-aware) | Ask a model "do these conflict?" | The spec forbids calling something a contradiction because a model said so; the rule is inspectable | Held-out recall is poor (see RAG_EVALUATION.md); honest result, not hidden |
| 10 | **Dev/test split**; thresholds tuned on dev only | Tune on everything | Keeps the test numbers honest | Test results are worse than dev for conflicts |
| 11 | **MiniLM-L6 embeddings on CPU** (~90 MB, Apache-2.0) | Larger BGE/E5, LM Studio nomic embeddings | Fast, small, reproducible offline, permissive license | Lower ceiling than larger models; dense alone ranks below hybrid here |
| 12 | **Reranker opt-in, measured as an ablation** | Rerank by default | Measured on 2026-11-09 (`make rerank-model && make eval`): `ms-marco-MiniLM-L6-v2` over the top 20 hybrid hits did not beat hybrid on the held-out split (MRR@10 0.955 vs 0.966, abstention F1 0.846 vs 0.923) and cost ~10x latency (p50 ~196 ms vs ~20 ms). A web-search cross-encoder is not tuned for clause-level legal text | Kept as an option, off by default; the negative result is published, not hidden |
| 13 | **SQLite** | PostgreSQL + pgvector | Zero-ops local demo; FTS5 built in | No concurrency at scale; Postgres would need a tsvector/pgvector backend behind `search.py` (not implemented) |
| 14 | **Fixture login, server-side sessions** | Client-side role switcher; real IdP | Honest demo boundary: the client can never choose its role | No real authentication (documented) |
| 15 | **Approval = second person + citation re-verification + local outbox** | Auto-send; single-person release | Shows a human-in-the-loop gate before any external action without sending anything anywhere | The "external" action is simulated |
| 16 | **CI defined but Actions disabled**; `make ci` runs the same steps locally | Enable Actions | Owner policy for private repos | Checks depend on running `make ci` |

## Performance and cost

- Retrieval + evidence on CPU: see p50/p95 in docs/RETRIEVAL_EVAL.md (BM25 single-digit ms; hybrid adds the
  query embedding). Seeding 45 docs / 646 chunks with embeddings takes ~20 s.
- Local generation with a 35B MoE model in LM Studio takes ~1-2 minutes per question on this Mac because the
  model spends most of its token budget on hidden reasoning that the server does not let the client disable.
  Billed cost is $0; token counts shown in the UI are estimates (chars/4) next to the server-reported usage.
