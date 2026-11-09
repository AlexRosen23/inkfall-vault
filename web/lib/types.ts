// Response shapes mirrored from src/inkfall/api.py and src/inkfall/service.py.

export interface Identity {
  username: string;
  display_name: string;
  title: string;
  tenant: string;
  tenant_name: string;
  roles: string[];
}

export interface Me extends Identity {
  groups: string[];
  clearance: string;
  collections: string[];
  /** Tenant ACL group names; only populated for admins (upload form hint). */
  tenant_groups?: string[];
}

export interface GenerationBackend {
  name: string;
  base_url: string;
  available: boolean;
  models: string[];
  chosen_model: string | null;
  detail: string;
}

export interface SystemInfo {
  embedding: { model_id: string; license?: string; status: string; [k: string]: unknown };
  reranker: { model_id: string; downloaded: boolean; note: string };
  generation_backends: GenerationBackend[];
  dataset_version: string | null;
  documents: number | null;
}

export interface Citation {
  pid: string;
  version_id: number;
  ref: string;
  char_start: number;
  char_end: number;
  quote: string;
}

export type Support = "verbatim" | "supported" | "partial" | "unsupported";

export interface AnswerSentence {
  text: string;
  citations: Citation[];
  support: Support | string;
  notes: string[];
}

export interface Conflict {
  kind: string;
  a: Citation;
  b: Citation;
  a_values: string[];
  b_values: string[];
  explanation: string;
}

export interface Passage {
  pid: string;
  chunk_id: number;
  version_id: number;
  ref: string;
  doc_key: string;
  title: string;
  heading: string;
  char_start: number;
  char_end: number;
  text: string;
  rank: number;
  method_ranks: Record<string, number>;
  effective_date: string;
  in_force: boolean;
  superseded_by: number | null;
  amends_key: string | null;
  doc_type: string;
  classification: string;
  injection_flags: string[];
}

export interface GraphNode {
  id: string;
  kind: "question" | "clause" | "document" | "entity";
  label: string;
  title?: string;
  doc_type?: string;
  effective_date?: string;
  in_force?: boolean;
  version_id?: number;
  pid?: string;
  cited?: boolean;
  injection?: boolean;
}

export interface GraphEdge {
  from: string;
  to: string;
  kind: "retrieved" | "part_of" | "party" | "amends" | "supersedes" | "contradicts";
  rank?: number;
  label?: string;
}

export type AnswerStatus = "supported" | "contradictory" | "insufficient_evidence" | "partially_unsupported";

export interface AskResult {
  question: string;
  as_of: string;
  scope: {
    tenant: string;
    collection: string | null;
    include_history: boolean;
    authorized_versions: number;
    authorized_chunks: number;
  };
  status: AnswerStatus;
  mode: "extractive" | "generative";
  mode_label: string;
  answer: AnswerSentence[];
  abstained: boolean;
  abstain_reason: string | null;
  trust: {
    evidence_coverage: number;
    matched_terms: string[];
    missing_terms: string[];
    gaps: string[];
    conflicts: Conflict[];
    amendment_overrides: string[];
    freshness: string[];
    untrusted_instructions_in_sources: { pid: string; ref: string; matches: string[] }[];
    untrusted_instructions_in_question: string[];
    note: string;
  };
  retrieval: {
    method: string;
    notes: string[];
    latency_ms: number;
    hits: { chunk_id: number; version_id: number; rank: number; components: Record<string, number> }[];
  };
  sources: Passage[];
  graph: { nodes: GraphNode[]; edges: GraphEdge[] };
  generation: {
    requested: boolean;
    status?: string;
    rejected_reason?: string | null;
    model?: string | null;
    provider?: string | null;
    latency_ms?: number;
    prompt_tokens_est?: number;
    completion_tokens_est?: number;
    usage_reported?: unknown;
    model_abstained?: boolean;
    cost_note?: string;
  };
  latency_ms: number;
  ranked_refs: string[];
  request_id: string;
}

export interface DocumentListItem {
  version_id: number;
  ref: string;
  doc_key: string;
  version: number;
  title: string;
  collection: string;
  doc_type: string;
  classification: string;
  effective_date: string;
  in_force: boolean;
  superseded_by: number | null;
  amends: string | null;
  tags: string[];
}

export interface DocumentPayload {
  version_id: number;
  ref: string;
  doc_key: string;
  version: number;
  title: string;
  collection: string;
  doc_type: string;
  matter: string | null;
  effective_date: string;
  classification: string;
  parties: string[] | null;
  tags: string[] | null;
  amends: string | null;
  text: string;
  chunks: { chunk_id: number; heading: string; char_start: number; char_end: number }[];
  lineage: {
    checksum_sha256: string;
    ingested_at: string;
    ingested_by: string;
    source_filename: string;
    source_mime: string;
    extraction_method: string;
    byte_size: number;
    retention: string;
    in_force_today: boolean;
    superseded_by_version: number | null;
  };
  access: { decision: string; reasons: string[]; acl_groups: string[]; ethical_wall_applies: boolean };
  versions: { version_id: number; version: number; effective_date: string }[];
}

export interface Clause {
  heading: string;
  text: string;
  char_start: number;
  char_end: number;
}

export interface ComparePair {
  left: Clause | null;
  right: Clause | null;
  word_changes: { op: string; a: string; b: string }[] | null;
  value_changes: Record<string, { from: string[]; to: string[] }>;
}

export type CompareOp = { op: "equal"; count: number } | { op: "replace" | "delete" | "insert"; pairs: ComparePair[] };

export interface CompareResult {
  a: { ref: string; version_id: number; effective_date: string };
  b: { ref: string; version_id: number; effective_date: string };
  ops: CompareOp[];
  method: string;
}

export interface BriefItem {
  text: string;
  version_id: number;
  char_start: number;
  char_end: number;
  quote: string;
  ref?: string;
}

export type SummaryStatus = "draft" | "pending" | "approved" | "rejected" | "released";

export interface Summary {
  id: number;
  title: string;
  question: string;
  author: string;
  status: SummaryStatus | string;
  recipient: string;
  approver: string | null;
  decision_note: string | null;
  items: BriefItem[];
  created_at: string;
  decided_at: string | null;
  released_at: string | null;
  export_path: string | null;
}

export interface Review {
  id: number;
  ts: string;
  username: string;
  question: string;
  answer_mode: string;
  sentence: string;
  version_id: number;
  char_start: number;
  char_end: number;
  verdict: string;
  reason: string;
}

export interface ReviewsResponse {
  reviews: Review[];
  counts: Record<string, number>;
  note: string;
}

export interface AuditRow {
  id: number;
  ts: string;
  request_id: string;
  username: string | null;
  action: string;
  outcome: string;
  detail: Record<string, unknown>;
}

export interface QuarantineRow {
  id: number;
  ts: string;
  filename: string;
  sha256: string;
  byte_size: number;
  reason: string;
  uploaded_by: string;
}

export interface AdminDocumentRow {
  doc_key: string;
  version: number;
  status: string;
  deleted: boolean;
  readable_by_you: boolean;
  title: string | null;
}

// ---------------------------------------------------------------- evaluation report

export interface MethodMetrics {
  questions?: number;
  answerable?: number;
  should_abstain?: number;
  recall_at_5?: number | null;
  precision_at_5?: number | null;
  hit_at_5?: number | null;
  mrr_at_10?: number | null;
  ndcg_at_10?: number | null;
  citations?: number;
  citation_validity?: number | null;
  answered_answerable?: number;
  answer_support_rate?: number | null;
  unsupported_answer_rate?: number | null;
  evidence_in_pack_rate?: number | null;
  abstention?: {
    precision: number | null;
    recall: number | null;
    f1: number | null;
    false_abstain_on_answerable: number;
    missed_abstain: number;
  };
  conflicts?: { expected: number; flagged: number; false_alarms_on_other_answerable: number; other_answerable: number };
  leaks?: number;
  injection_sentences_quoted?: number;
  errors?: number;
  latency_ms?: { p50: number | null; p95: number | null; max: number | null };
  throughput_qps_sequential?: number | null;
}

export interface QuestionMethodResult {
  latency_ms: number;
  error: string | null;
  status: string;
  retrieval_method_used: string;
  top_refs: string[];
  recall_at_5: number | null;
  precision_at_5: number | null;
  hit_at_5: number | null;
  mrr_at_10: number | null;
  ndcg_at_10: number | null;
  citations: number;
  citations_valid: number;
  cited_refs: string[];
  abstained: boolean;
  answer_supported: boolean | null;
  evidence_in_pack: boolean | null;
  conflict_flagged: boolean;
  leaks: string[];
  injection_quoted: boolean;
}

export interface EvalQuestion {
  id: string;
  user: string;
  question: string;
  category: string;
  split: string;
  as_of: string;
  relevant: string[];
  answer_spans: string[];
  expect_abstain: boolean;
  expect_conflict: boolean;
  forbidden: string[];
  methods: Record<string, QuestionMethodResult>;
  baseline_title_only?: { top_refs: string[]; recall_at_5: number | null; mrr_at_10: number | null };
}

export interface EvalReport {
  generated_at: string;
  provenance: {
    git_commit?: string;
    uncommitted_changes_in_src_or_data?: boolean;
    dataset_version?: string;
    documents?: number;
    gold_questions?: number;
    split_filter?: string;
    embedding_model?: string;
    reranker?: string | null;
    command?: string;
    machine?: Record<string, string | number>;
    wall_seconds?: number;
    answer_mode?: string;
    [k: string]: unknown;
  };
  methods_run: string[];
  methods_skipped: Record<string, string>;
  summary: Record<string, Record<string, MethodMetrics>>;
  by_category: Record<string, Record<string, MethodMetrics>>;
  questions: EvalQuestion[];
  visibility: string;
}
