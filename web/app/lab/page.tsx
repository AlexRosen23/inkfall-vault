"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { KV, Section } from "@/components/Bits";
import { ApiError, api, errorText, humanize, num, pct, when } from "@/lib/api";
import type { EvalQuestion, EvalReport, MethodMetrics, QuestionMethodResult, ReviewsResponse } from "@/lib/types";

type Load<T> = { data?: T; error?: string; missing?: boolean };

function useLoad<T>(path: string): Load<T> {
  const [state, setState] = useState<Load<T>>({});
  useEffect(() => {
    let cancelled = false;
    api<T>(path)
      .then((data) => {
        if (!cancelled) setState({ data });
      })
      .catch((e: unknown) => {
        if (!cancelled) setState({ error: errorText(e), missing: e instanceof ApiError && e.status === 404 });
      });
    return () => {
      cancelled = true;
    };
  }, [path]);
  return state;
}

const METRIC_ROWS: { label: string; get: (m: MethodMetrics) => ReactNode; hint?: string }[] = [
  { label: "Questions", get: (m) => num(m.questions) },
  { label: "Answerable / should abstain", get: (m) => `${num(m.answerable)} / ${num(m.should_abstain)}` },
  { label: "Recall@5", get: (m) => num(m.recall_at_5), hint: "saturates on this small corpus" },
  { label: "Precision@5", get: (m) => num(m.precision_at_5) },
  { label: "MRR@10", get: (m) => num(m.mrr_at_10) },
  { label: "nDCG@10", get: (m) => num(m.ndcg_at_10) },
  { label: "Citation validity", get: (m) => pct(m.citation_validity) },
  { label: "Answer support rate", get: (m) => pct(m.answer_support_rate) },
  { label: "Unsupported-answer rate", get: (m) => pct(m.unsupported_answer_rate) },
  { label: "Abstention P / R / F1", get: (m) => (m.abstention ? `${num(m.abstention.precision, 2)} / ${num(m.abstention.recall, 2)} / ${num(m.abstention.f1, 2)}` : "—") },
  { label: "Conflicts flagged / expected", get: (m) => (m.conflicts ? `${m.conflicts.flagged} / ${m.conflicts.expected}` : "—") },
  { label: "Conflict false alarms", get: (m) => (m.conflicts ? `${m.conflicts.false_alarms_on_other_answerable} of ${m.conflicts.other_answerable}` : "—") },
  { label: "Leaks", get: (m) => <span className={m.leaks ? "error" : ""}>{num(m.leaks)}</span> },
  { label: "Injection sentences quoted", get: (m) => <span className={m.injection_sentences_quoted ? "warn" : ""}>{num(m.injection_sentences_quoted)}</span> },
  { label: "Latency p50 / p95 (ms)", get: (m) => (m.latency_ms ? `${num(m.latency_ms.p50, 1)} / ${num(m.latency_ms.p95, 1)}` : "—") },
  { label: "Throughput (q/s, sequential)", get: (m) => num(m.throughput_qps_sequential, 1) },
  { label: "Errors", get: (m) => <span className={m.errors ? "error" : ""}>{num(m.errors)}</span> },
];

type FailureType = "missed_retrieval" | "unsupported" | "wrong_abstain" | "conflict_miss" | "conflict_false_alarm" | "leak" | "error";

const FAILURE_LABEL: Record<FailureType, string> = {
  missed_retrieval: "Missed retrieval",
  unsupported: "Unsupported answer",
  wrong_abstain: "Wrong abstain",
  conflict_miss: "Conflict miss",
  conflict_false_alarm: "Conflict false alarm",
  leak: "Leak",
  error: "Error",
};

function failures(q: EvalQuestion, r: QuestionMethodResult): FailureType[] {
  const out: FailureType[] = [];
  if (r.error) out.push("error");
  if (!q.expect_abstain && r.recall_at_5 != null && r.recall_at_5 < 1) out.push("missed_retrieval");
  if (!q.expect_abstain && !r.abstained && r.answer_supported === false) out.push("unsupported");
  if (r.abstained !== q.expect_abstain) out.push("wrong_abstain");
  if (q.expect_conflict && !r.conflict_flagged) out.push("conflict_miss");
  if (!q.expect_conflict && r.conflict_flagged) out.push("conflict_false_alarm");
  if (r.leaks.length > 0) out.push("leak");
  return out;
}

function FailuresExplorer({ report }: { report: EvalReport }) {
  const categories = useMemo(() => [...new Set(report.questions.map((q) => q.category))].sort(), [report]);
  const methods = report.methods_run;
  const [cat, setCat] = useState("");
  const [method, setMethod] = useState("");
  const [ftype, setFtype] = useState<"" | FailureType | "any">("any");

  const rows = useMemo(() => {
    const out: { q: EvalQuestion; m: string; r: QuestionMethodResult; f: FailureType[] }[] = [];
    for (const q of report.questions) {
      if (cat && q.category !== cat) continue;
      for (const [m, r] of Object.entries(q.methods)) {
        if (method && m !== method) continue;
        const f = failures(q, r);
        if (ftype === "any" && f.length === 0) continue;
        if (ftype && ftype !== "any" && !f.includes(ftype)) continue;
        out.push({ q, m, r, f });
      }
    }
    return out;
  }, [report, cat, method, ftype]);

  return (
    <>
      <div className="filters">
        <label className="field">
          <span>Category</span>
          <select value={cat} onChange={(e) => setCat(e.target.value)}>
            <option value="">All</option>
            {categories.map((c) => (
              <option key={c} value={c}>{humanize(c)}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Method</span>
          <select value={method} onChange={(e) => setMethod(e.target.value)}>
            <option value="">All</option>
            {methods.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Failure type</span>
          <select value={ftype} onChange={(e) => setFtype(e.target.value as FailureType | "any" | "")}>
            <option value="any">Any failure</option>
            {(Object.keys(FAILURE_LABEL) as FailureType[]).map((f) => (
              <option key={f} value={f}>{FAILURE_LABEL[f]}</option>
            ))}
            <option value="">Show all rows (incl. passes)</option>
          </select>
        </label>
        <span className="small muted self-end">{rows.length} row{rows.length === 1 ? "" : "s"}</span>
      </div>
      <div className="table-wrap tall">
        <table className="table compact">
          <caption className="sr-only">Per-question results</caption>
          <thead>
            <tr>
              <th scope="col">ID</th>
              <th scope="col">Question</th>
              <th scope="col">Method</th>
              <th scope="col">Expected</th>
              <th scope="col">Got</th>
              <th scope="col">Failures</th>
              <th scope="col">Top refs / cited</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ q, m, r, f }) => (
              <tr key={`${q.id}-${m}`}>
                <td className="mono small">
                  {q.id}
                  <div className="muted">{q.split} · {humanize(q.category)}</div>
                </td>
                <td className="small">
                  {q.question}
                  <div className="muted">asked by <span className="mono">{q.user}</span> · as of {q.as_of}</div>
                </td>
                <td className="mono small">{m}</td>
                <td className="small">
                  {q.expect_abstain ? "abstain" : "answer"}
                  {q.expect_conflict && " + conflict"}
                  {q.relevant.length > 0 && <div className="mono muted">{q.relevant.join(", ")}</div>}
                </td>
                <td className="small">
                  {r.status} {r.conflict_flagged && "· conflict"}
                  <div className="muted">MRR {num(r.mrr_at_10, 2)} · {r.citations_valid}/{r.citations} valid · {r.latency_ms} ms</div>
                </td>
                <td className="small">
                  {f.length === 0 ? <span className="ok">pass</span> : f.map((x) => <span key={x} className="pill pill-warn">{FAILURE_LABEL[x]}</span>)}
                  {r.error && <div className="error">{r.error}</div>}
                </td>
                <td className="mono small">
                  {r.top_refs.slice(0, 5).join(", ")}
                  {r.cited_refs.length > 0 && <div className="muted">cited: {r.cited_refs.join(", ")}</div>}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="muted">No rows match.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

function isScalar(v: unknown): v is string | number | boolean | null {
  return v === null || ["string", "number", "boolean"].includes(typeof v);
}

function fmtCell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return num(v);
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v)) return when(v);
  if (typeof v === "string" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) return v.length ? v.map((x) => (isScalar(x) ? String(x) : JSON.stringify(x))).join(", ") : "none";
  if (typeof v === "object") {
    return Object.entries(v as Record<string, unknown>)
      .map(([k, x]) => `${humanize(k)}: ${isScalar(x) ? String(x) : Array.isArray(x) ? `[${x.map(String).join(", ")}]` : JSON.stringify(x)}`)
      .join(" · ");
  }
  return String(v);
}

function isPassTotal(v: unknown): v is { passed: number; total: number } {
  return !!v && typeof v === "object" && typeof (v as Record<string, unknown>).passed === "number" && typeof (v as Record<string, unknown>).total === "number";
}

function Cell({ v }: { v: unknown }) {
  if (v === true) return <span className="ok">yes</span>;
  if (v === false) return <span className="error">no</span>;
  return <>{fmtCell(v)}</>;
}

/** Renders an unknown JSON report generically: headline numbers, notes, and the first array of objects as a table. */
function GenericReport({ data }: { data: unknown }) {
  if (!data || typeof data !== "object") return <pre className="json">{JSON.stringify(data, null, 2)}</pre>;
  const obj = data as Record<string, unknown>;
  const headline: [string, ReactNode][] = [];
  const notes: [string, string][] = [];
  const collect = (o: Record<string, unknown>, prefix: string, depth: number) => {
    for (const [k, v] of Object.entries(o)) {
      const key = prefix + k;
      if (typeof v === "string" && v.length > 48) notes.push([key, v]);
      else if (isScalar(v)) headline.push([key, typeof v === "string" ? <span key={key} className="stat-text">{fmtCell(v)}</span> : <Cell key={key} v={v} />]);
      else if (isPassTotal(v)) headline.push([key, <span key={key} className={v.passed === v.total ? "ok" : "warn"}>{v.passed} / {v.total}</span>]);
      else if (Array.isArray(v) && v.every(isScalar)) headline.push([key, v.length ? v.map(String).join(", ") : "none"]);
      else if (v && typeof v === "object" && !Array.isArray(v) && depth < 2) collect(v as Record<string, unknown>, `${key}.`, depth + 1);
    }
  };
  collect(obj, "", 0);
  const tableEntry = Object.entries(obj).find(([, v]) => Array.isArray(v) && v.length > 0 && v.every((x) => x && typeof x === "object"));
  const rows = (tableEntry?.[1] ?? []) as Record<string, unknown>[];
  const cols = [...new Set(rows.slice(0, 50).flatMap((r) => Object.keys(r)))].slice(0, 12);
  return (
    <>
      {headline.length > 0 && (
        <div className="stat-grid">
          {headline.slice(0, 30).map(([k, v]) => (
            <div key={k} className="stat">
              <div className="stat-v">{v}</div>
              <div className="stat-k">{humanize(k.replace(/\./g, " › "))}</div>
            </div>
          ))}
        </div>
      )}
      {notes.length > 0 && (
        <ul className="small">
          {notes.map(([k, v]) => (
            <li key={k}>
              <span className="muted">{humanize(k)}:</span> {v}
            </li>
          ))}
        </ul>
      )}
      {tableEntry && (
        <div className="table-wrap tall">
          <table className="table compact">
            <caption className="small muted">{humanize(tableEntry[0])} ({rows.length})</caption>
            <thead>
              <tr>
                {cols.map((c) => (
                  <th key={c} scope="col">{humanize(c)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  {cols.map((c) => (
                    <td key={c} className={`small${typeof r[c] === "object" && r[c] !== null ? " detail-cell" : ""}`}>
                      <Cell v={r[c]} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}


type Confusion = { n: number; ref_pass: number; ref_fail: number; tpr: number | null; tnr: number | null; agreement: number | null };
type FaithReport = {
  generated_at: string;
  provenance: { generator: { model: string; provider: string }; labeler: string; judge_prompt: string; git_commit: string };
  criterion: string;
  test: Record<string, { judge: Confusion; deterministic: Confusion }>;
  dev_iterations: Record<string, Record<string, { judge: Confusion }>>;
  deterministic_metrics_natural: { natural_answers: number; answers_all_sentences_supported: number; answers_with_gold_span: number };
};

function rate(x: number | null) {
  return x === null || x === undefined ? "n/a" : x.toFixed(3);
}

function FaithfulnessTable({ data }: { data: FaithReport }) {
  const rows: [string, string, Confusion][] = [];
  for (const [v, blk] of Object.entries(data.dev_iterations)) {
    if (blk.all) rows.push([`judge-dev (prompt ${v})`, "LLM judge", blk.all.judge]);
  }
  for (const sub of ["all", "natural", "synthetic"]) {
    const t = data.test[sub];
    if (!t) continue;
    rows.push([`judge-test · ${sub}`, "LLM judge", t.judge]);
    rows.push([`judge-test · ${sub}`, "deterministic span check", t.deterministic]);
  }
  const d = data.deterministic_metrics_natural;
  return (
    <>
      <p className="small">
        Criterion: <em>{data.criterion}</em>. Generator and judge: <code>{data.provenance.generator.model}</code> (
        {data.provenance.generator.provider}). Labels: {data.provenance.labeler}.
      </p>
      <div className="table-wrap">
        <table className="table compact">
          <thead>
            <tr><th>Split / subset</th><th>Grader</th><th>n</th><th>ref PASS / FAIL</th><th>TPR</th><th>TNR</th><th>Agreement</th></tr>
          </thead>
          <tbody>
            {rows.map(([split, grader, c]) => (
              <tr key={split + grader}>
                <td>{split}</td><td>{grader}</td><td className="num">{c.n}</td><td>{c.ref_pass} / {c.ref_fail}</td>
                <td className="num">{rate(c.tpr)}</td><td className="num">{rate(c.tnr)}</td><td className="num">{rate(c.agreement)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="small muted">
        Natural answers: {d.natural_answers}; every sentence passes the deterministic span check in {d.answers_all_sentences_supported};
        a gold answer span appears in {d.answers_with_gold_span}. All test FAIL labels are synthetic negatives (changed number or
        appended fabricated sentence). Commit {data.provenance.git_commit}, {when(data.generated_at)}.
      </p>
    </>
  );
}

export default function LabPage() {
  const report = useLoad<EvalReport>("/api/eval/report");
  const adversarial = useLoad<unknown>("/api/eval/adversarial");
  const advGenerative = useLoad<unknown>("/api/eval/adversarial-generative");
  const faithfulness = useLoad<FaithReport>("/api/eval/faithfulness");
  const reviews = useLoad<ReviewsResponse>("/api/reviews");
  const [split, setSplit] = useState("all");
  const [catMethod, setCatMethod] = useState("");

  const rep = report.data;
  const splits = rep ? Object.keys(rep.summary) : [];
  const activeSplit = rep && rep.summary[split] ? split : splits[0] ?? "all";
  const splitData = rep?.summary[activeSplit] ?? {};
  const methodCols = Object.keys(splitData).filter((k) => k !== "baseline_title_only");
  const baseline = splitData["baseline_title_only"];
  const catM = catMethod || rep?.methods_run.find((m) => m === "hybrid") || rep?.methods_run[0] || "";
  const prov = rep?.provenance;

  return (
    <div className="page lab">
      <div className="page-head">
        <div className="kicker">Evaluation &amp; Trust Console</div>
        <h1>How well does the vault find, cite and refuse?</h1>
      </div>

      {report.error && (
        <div className="banner banner-error" role="alert">
          {report.missing ? "No evaluation report is available yet (run make eval)." : report.error}
        </div>
      )}
      {!rep && !report.error && <p className="muted" aria-live="polite">Loading the latest report…</p>}

      {rep && prov && (
        <div className="lab-top">
          <Section title="Provenance" kicker={`Generated ${when(rep.generated_at)}`}>
            <KV
              items={[
                ["Git commit", <code key="g">{prov.git_commit ?? "—"}{prov.uncommitted_changes_in_src_or_data ? " (+ uncommitted changes)" : ""}</code>],
                ["Dataset version", <code key="d">{prov.dataset_version ?? "—"}</code>],
                ["Documents / questions", `${num(prov.documents)} / ${num(prov.gold_questions)}`],
                ["Answer mode", prov.answer_mode ?? "—"],
                ["Embedding model", <code key="e">{prov.embedding_model ?? "—"}</code>],
                ["Reranker", prov.reranker ?? "none"],
                ["Command", <code key="c">{prov.command ?? "—"}</code>],
                [
                  "Machine",
                  prov.machine
                    ? `${prov.machine.cpu ?? prov.machine.machine ?? ""} · ${prov.machine.memory_gb ?? "?"} GB · ${prov.machine.platform ?? ""} · ${prov.machine.device ?? ""}`
                    : "—",
                ],
                ["Wall time", prov.wall_seconds != null ? `${prov.wall_seconds} s` : "—"],
              ]}
            />
          </Section>
          <Section title="Methods" kicker="Run and skipped">
            <p>
              {rep.methods_run.map((m) => (
                <span key={m} className="pill pill-ok">{m}</span>
              ))}
            </p>
            {Object.keys(rep.methods_skipped).length > 0 && (
              <ul className="small">
                {Object.entries(rep.methods_skipped).map(([m, why]) => (
                  <li key={m}>
                    <span className="pill">{m}</span> skipped — {why}
                  </li>
                ))}
              </ul>
            )}
            <h3 className="pane-title">How grading works</h3>
            <ul className="small explain">
              <li>Grading is deterministic: fixed gold questions with expected refs, answer spans, abstain and conflict flags. No model grades another model.</li>
              <li>Retrieval is scored by Recall@5, Precision@5, MRR@10 and nDCG@10 against the gold relevant refs.</li>
              <li>
                Recall@5 saturates on this small corpus (few documents per tenant), so read <strong>MRR@10 and nDCG@10</strong> to see ranking
                quality.
              </li>
              <li>A citation is valid only if the asker may read the cited version and the quote equals the stored text at that exact span.</li>
              <li>An answer counts as supported when one of the gold answer spans appears verbatim in the cited quotes (evidence-in-pack checks the whole retrieved pack).</li>
              <li>Abstention is scored against the gold expect-abstain flag; conflicts against expect-conflict (false alarms are flags on other answerable questions).</li>
              <li>A leak is any surfaced reference the asker cannot read, or a gold-forbidden document. “Injection quoted” counts answer sentences that repeat known injection phrases.</li>
              <li>The title-only baseline (no RAG) ranks authorized documents by question-term overlap with titles and keys only, as a floor.</li>
            </ul>
          </Section>
        </div>
      )}

      {rep && (
        <Section
          title="Metrics by split"
          kicker="Aggregate over all tenants"
          actions={
            <div className="tabs" role="tablist" aria-label="Split">
              {splits.map((s) => (
                <button key={s} type="button" role="tab" aria-selected={s === activeSplit} onClick={() => setSplit(s)}>
                  {s}
                </button>
              ))}
            </div>
          }
        >
          <div className="table-wrap">
            <table className="table metrics">
              <caption className="sr-only">Metrics for the {activeSplit} split by method</caption>
              <thead>
                <tr>
                  <th scope="col">Metric</th>
                  {methodCols.map((m) => (
                    <th key={m} scope="col" className="num">{m}</th>
                  ))}
                  {baseline && <th scope="col" className="num">title-only baseline</th>}
                </tr>
              </thead>
              <tbody>
                {METRIC_ROWS.map((row) => (
                  <tr key={row.label}>
                    <th scope="row">
                      {row.label}
                      {row.hint && <div className="small muted">{row.hint}</div>}
                    </th>
                    {methodCols.map((m) => (
                      <td key={m} className="num">{row.get(splitData[m] ?? {})}</td>
                    ))}
                    {baseline && (
                      <td className="num muted">
                        {row.label === "Recall@5" || row.label === "MRR@10" ? row.get(baseline) : "—"}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {rep && (
        <Section
          title="By category"
          kicker="Where it struggles"
          actions={
            <label className="field inline">
              <span>Method</span>
              <select value={catM} onChange={(e) => setCatMethod(e.target.value)}>
                {rep.methods_run.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </label>
          }
        >
          <div className="table-wrap">
            <table className="table compact">
              <caption className="sr-only">Metrics by question category for {catM}</caption>
              <thead>
                <tr>
                  <th scope="col">Category</th>
                  <th scope="col" className="num">Qs</th>
                  <th scope="col" className="num">Recall@5</th>
                  <th scope="col" className="num">MRR@10</th>
                  <th scope="col" className="num">nDCG@10</th>
                  <th scope="col" className="num">Support</th>
                  <th scope="col" className="num">Abstain F1</th>
                  <th scope="col" className="num">Conflicts</th>
                  <th scope="col" className="num">Leaks</th>
                  <th scope="col" className="num">Inj. quoted</th>
                  <th scope="col" className="num">p50 ms</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(rep.by_category).map(([cat, byM]) => {
                  const m = byM[catM];
                  if (!m) return null;
                  return (
                    <tr key={cat}>
                      <th scope="row">{humanize(cat)}</th>
                      <td className="num">{num(m.questions)}</td>
                      <td className="num">{num(m.recall_at_5, 2)}</td>
                      <td className="num">{num(m.mrr_at_10, 2)}</td>
                      <td className="num">{num(m.ndcg_at_10, 2)}</td>
                      <td className="num">{pct(m.answer_support_rate, 0)}</td>
                      <td className="num">{num(m.abstention?.f1, 2)}</td>
                      <td className="num">{m.conflicts ? `${m.conflicts.flagged}/${m.conflicts.expected}` : "—"}</td>
                      <td className={`num${m.leaks ? " error" : ""}`}>{num(m.leaks)}</td>
                      <td className={`num${m.injection_sentences_quoted ? " warn" : ""}`}>{num(m.injection_sentences_quoted)}</td>
                      <td className="num">{num(m.latency_ms?.p50, 1)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {rep && (
        <Section title="Failures explorer" kicker={`${rep.questions.length} questions visible to you`}>
          <p className="small muted">{rep.visibility}</p>
          <FailuresExplorer report={rep} />
        </Section>
      )}

      <div className="lab-top">
        <Section title="Adversarial suite" kicker="/api/eval/adversarial" className="span-all">
          {adversarial.missing && <p className="muted small">Not available yet: the API does not serve an adversarial report (404).</p>}
          {adversarial.error && !adversarial.missing && <p className="error small" role="alert">{adversarial.error}</p>}
          {!adversarial.data && !adversarial.error && <p className="muted small">Loading…</p>}
          {adversarial.data !== undefined && <GenericReport data={adversarial.data} />}
        </Section>
        <Section title="Answer faithfulness: LLM judge vs reference labels" kicker="/api/eval/faithfulness" className="span-all">
          <p className="small muted">
            Reference labels are AI-drafted (Claude Code) and pending owner review; the judge and the generator are the same
            local model with different prompts. TPR = PASS recall, TNR = FAIL recall.
          </p>
          {faithfulness.missing && <p className="muted small">Not run yet (make eval-faithfulness).</p>}
          {faithfulness.error && !faithfulness.missing && <p className="error small" role="alert">{faithfulness.error}</p>}
          {faithfulness.data !== undefined && <FaithfulnessTable data={faithfulness.data} />}
        </Section>
        <Section title="Adversarial suite with a real local model" kicker="/api/eval/adversarial-generative" className="span-all">
          {advGenerative.missing && <p className="muted small">Not run yet (make security-test-generative).</p>}
          {advGenerative.error && !advGenerative.missing && <p className="error small" role="alert">{advGenerative.error}</p>}
          {advGenerative.data !== undefined && <GenericReport data={advGenerative.data} />}
        </Section>
        <Section title="Human review labels" kicker="/api/reviews">
          {reviews.error && <p className="error small" role="alert">{reviews.error}</p>}
          {reviews.data && (
            <>
              <div className="stat-grid">
                {(["correct", "partial", "incorrect"] as const).map((k) => (
                  <div key={k} className="stat">
                    <div className="stat-v">{reviews.data?.counts[k] ?? 0}</div>
                    <div className="stat-k">{k === "partial" ? "partially supported" : k}</div>
                  </div>
                ))}
              </div>
              <p className="small muted">{reviews.data.note}</p>
              {reviews.data.reviews.length > 0 && (
                <ul className="small review-list">
                  {reviews.data.reviews.slice(0, 10).map((r) => (
                    <li key={r.id}>
                      <span className="pill">{r.verdict}</span> “{r.sentence}” <span className="muted">— {r.username}, {when(r.ts)}{r.reason ? `: ${r.reason}` : ""}</span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </Section>
      </div>
    </div>
  );
}
