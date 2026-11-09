"use client";

import { useCallback, useMemo, useRef, useState, type FormEvent } from "react";
import { AnswerPanel } from "@/components/AnswerPanel";
import { Section } from "@/components/Bits";
import { ApprovalsList, BriefTray } from "@/components/BriefPanel";
import { DocumentInspector, type InspectTarget } from "@/components/DocumentInspector";
import { EvidenceGraph } from "@/components/EvidenceGraph";
import { useSession } from "@/components/Shell";
import { TrustInspector } from "@/components/TrustInspector";
import { api, errorText, todayISO } from "@/lib/api";
import type { AnswerSentence, AskResult, BriefItem, Citation, Passage, Summary } from "@/lib/types";

const SUGGESTED: Record<string, string[]> = {
  lanternfield: [
    "What notice is required to terminate the Brightwater supply agreement for convenience?",
    "What hourly rate applies to Calderwood partners?",
    "How long must client files be retained after a matter closes?",
  ],
  corvane: [
    "What uptime has Orion committed to?",
    "How long did the September 14 Orion outage last?",
    "How much notice do we have to give if we don't want the Vantor dispatch contract to roll over?",
  ],
  pellmoor: ["How long must financial records be kept?", "What is the quote threshold for purchases?"],
};

const STAGES = [
  { id: "scope", label: "Scope" },
  { id: "ask", label: "Ask" },
  { id: "verify", label: "Verify" },
  { id: "compare", label: "Compare" },
  { id: "brief", label: "Brief" },
  { id: "approve", label: "Approve & release" },
] as const;
type Stage = (typeof STAGES)[number]["id"];

type Method = "bm25" | "dense" | "hybrid" | "rerank";
type GenMode = "extractive" | "generative" | "lmstudio" | "ollama";

export default function WorkbenchPage() {
  const { me, system } = useSession();
  const [collection, setCollection] = useState("");
  const [asOf, setAsOf] = useState(() => todayISO());
  const [method, setMethod] = useState<Method>("hybrid");
  const [history, setHistory] = useState(false);
  const [genMode, setGenMode] = useState<GenMode>("extractive");
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AskResult | null>(null);
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);
  const [inspect, setInspect] = useState<{ key: number; target: InspectTarget } | null>(null);
  const [brief, setBrief] = useState<BriefItem[]>([]);
  const [done, setDone] = useState<Set<Stage>>(new Set());
  const [summariesKey, setSummariesKey] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const inspectSeq = useRef(0);

  const mark = useCallback((s: Stage) => {
    setDone((prev) => (prev.has(s) ? prev : new Set(prev).add(s)));
  }, []);

  const backends = (system?.generation_backends ?? []).filter((b) => b.available);
  const suggestions = SUGGESTED[me.tenant] ?? [];
  const current = STAGES.find((s) => !done.has(s.id))?.id;

  const ask = async (e?: FormEvent) => {
    e?.preventDefault();
    const q = question.trim();
    if (!q || asking) return;
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setAsking(true);
    setAskError(null);
    try {
      const body: Record<string, unknown> = { question: q, as_of: asOf || null, method, include_history: history, generate: genMode };
      if (collection) body.collection = collection;
      const r = await api<AskResult>("/api/ask", { body, signal: ctrl.signal });
      setResult(r);
      mark("scope");
      mark("ask");
    } catch (err) {
      setAskError(errorText(err));
    } finally {
      setAsking(false);
      abortRef.current = null;
    }
  };

  const open = (target: InspectTarget) => {
    inspectSeq.current += 1;
    setInspect({ key: inspectSeq.current, target });
  };

  const verify = (s: AnswerSentence, c: Citation) =>
    open({ versionId: c.version_id, span: { start: c.char_start, end: c.char_end }, sentence: s, citation: c });

  const openCitation = (c: Citation, context?: string) =>
    open({ versionId: c.version_id, span: { start: c.char_start, end: c.char_end }, citation: c, context: context ?? c.quote });

  const openPassage = (p: Passage) =>
    open({ versionId: p.version_id, span: { start: p.char_start, end: p.char_end }, context: `${p.pid} · ${p.heading} (retrieval rank ${p.rank})` });

  const briefKey = (s: AnswerSentence) => {
    const c = s.citations[0];
    return c ? `${s.text}|${c.version_id}|${c.char_start}` : s.text;
  };
  const briefKeys = useMemo(() => new Set(brief.map((b) => `${b.text}|${b.version_id}|${b.char_start}`)), [brief]);

  const addToBrief = (s: AnswerSentence) => {
    const c = s.citations[0];
    if (!c || briefKeys.has(briefKey(s))) return;
    setBrief((b) => [...b, { text: s.text, version_id: c.version_id, char_start: c.char_start, char_end: c.char_end, quote: c.quote, ref: c.ref }]);
  };

  const onSummaryCreated = (s: Summary) => {
    setBrief([]);
    mark("brief");
    setSummariesKey((k) => k + 1);
    void s;
  };

  const onSummaryActivity = useCallback(
    (s: Summary) => {
      if (s.status === "approved" || s.status === "released") mark("approve");
    },
    [mark],
  );

  const docsInAnswer = useMemo(() => {
    const seen = new Map<number, Passage>();
    for (const p of result?.sources ?? []) if (!seen.has(p.version_id)) seen.set(p.version_id, p);
    return [...seen.values()];
  }, [result]);

  return (
    <div className="workbench">
      <nav className="stepper" aria-label="Workflow stages">
        <ol>
          {STAGES.map((s, i) => (
            <li key={s.id} className={done.has(s.id) ? "done" : s.id === current ? "current" : ""}>
              <a href={`#stage-${s.id}`} aria-current={s.id === current ? "step" : undefined}>
                <span className="step-n" aria-hidden="true">{done.has(s.id) ? "✓" : i + 1}</span>
                {s.label}
                <span className="sr-only">{done.has(s.id) ? " (done)" : s.id === current ? " (current)" : ""}</span>
              </a>
            </li>
          ))}
        </ol>
      </nav>

      <div className="wb-grid">
        <div className="wb-left">
          <Section id="stage-scope" kicker="1 · Scope" title="Set the evidence scope">
            <div className="form-grid">
              <label className="field">
                <span>Collection</span>
                <select value={collection} onChange={(e) => setCollection(e.target.value)}>
                  <option value="">All my collections</option>
                  {me.collections.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>As of</span>
                <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
              </label>
              <label className="field">
                <span>Retrieval method</span>
                <select value={method} onChange={(e) => setMethod(e.target.value as Method)}>
                  <option value="hybrid">hybrid (BM25 + dense, fused)</option>
                  <option value="bm25">bm25 (lexical)</option>
                  <option value="dense">dense (embeddings)</option>
                  <option value="rerank">rerank (cross-encoder{system && !system.reranker.downloaded ? ", not downloaded" : ""})</option>
                </select>
              </label>
              <label className="field">
                <span>Answer mode</span>
                <select value={genMode} onChange={(e) => setGenMode(e.target.value as GenMode)}>
                  <option value="extractive">Extractive (no model)</option>
                  {backends.length > 0 && <option value="generative">Local model (auto)</option>}
                  {backends.map((b) =>
                    b.name === "lmstudio" || b.name === "ollama" ? (
                      <option key={b.name} value={b.name}>
                        Local model: {b.name}{b.chosen_model ? ` · ${b.chosen_model}` : ""}
                      </option>
                    ) : null,
                  )}
                </select>
              </label>
              <label className="check">
                <input type="checkbox" checked={history} onChange={(e) => setHistory(e.target.checked)} />
                Include historical (superseded) versions
              </label>
            </div>
            {genMode !== "extractive" && (
              <p className="small warn" role="note">
                A local model can take about 1–2 minutes. Every generated sentence is checked against its cited passages; unsupported
                sentences are labelled.
              </p>
            )}
          </Section>

          <Section id="stage-ask" kicker="2 · Ask" title="Ask the vault">
            <form onSubmit={ask}>
              <label className="field">
                <span>Question</span>
                <textarea
                  rows={4}
                  maxLength={500}
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void ask();
                  }}
                  aria-describedby="ask-hint"
                />
              </label>
              <div id="ask-hint" className="small muted">{question.length}/500 · ⌘/Ctrl + Enter to ask</div>
              <div className="row">
                <button type="submit" className="btn btn-brass" disabled={asking || !question.trim()}>
                  {asking ? "Searching…" : "Ask"}
                </button>
                {asking && (
                  <button type="button" className="btn btn-ghost" onClick={() => abortRef.current?.abort()}>
                    Cancel
                  </button>
                )}
              </div>
            </form>
            {suggestions.length > 0 && (
              <div className="suggest">
                <div className="small muted">Suggested for {me.tenant_name}</div>
                <ul>
                  {suggestions.map((q) => (
                    <li key={q}>
                      <button type="button" className="link-btn" onClick={() => setQuestion(q)}>{q}</button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Section>
        </div>

        <div className="wb-center">
          <Section id="stage-verify" kicker="3 · Verify" title="Answer & citations">
            {askError && <div className="banner banner-error" role="alert">{askError}</div>}
            {asking && (
              <p className="muted" aria-live="polite">
                {genMode === "extractive" ? "Retrieving authorized evidence…" : "Retrieving evidence and running the local model (may take 1–2 minutes)…"}
              </p>
            )}
            {!result && !asking && !askError && (
              <p className="muted">Ask a question. Answers are built only from documents your identity is authorized to read.</p>
            )}
            {result && (
              <AnswerPanel result={result} onVerify={verify} onAddToBrief={addToBrief} inBrief={(s) => briefKeys.has(briefKey(s))} />
            )}
          </Section>

          {result && docsInAnswer.length > 0 && (
            <Section id="stage-compare" kicker="4 · Compare" title="Documents behind this answer">
              <ul className="doc-rows">
                {docsInAnswer.map((p) => (
                  <li key={p.version_id}>
                    <div>
                      <span className="mono">{p.ref}</span> <span className="muted small">· {p.doc_type} · effective {p.effective_date}</span>
                      {!p.in_force && <span className="pill pill-warn">historical</span>}
                      <div className="small">{p.title}</div>
                    </div>
                    <div className="row">
                      <button type="button" className="btn btn-ghost btn-sm" onClick={() => open({ versionId: p.version_id })}>Open</button>
                      <button type="button" className="btn btn-ghost btn-sm" onClick={() => open({ versionId: p.version_id, initialTab: "compare" })}>
                        Compare versions
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </Section>
          )}
        </div>

        <aside className="wb-right" aria-label="Trust inspector">
          <Section title="Trust inspector" kicker="Diagnostics">
            {result ? <TrustInspector result={result} onOpenCitation={openCitation} /> : <p className="muted small">Run a question to inspect coverage, conflicts and retrieval.</p>}
          </Section>
        </aside>
      </div>

      {result && (
        <Section title="Evidence graph" kicker="Retrieval map" className="graph-section">
          <EvidenceGraph graph={result.graph} sources={result.sources} onOpenDocument={(vid) => open({ versionId: vid })} onOpenPassage={openPassage} />
        </Section>
      )}

      <div className="wb-bottom">
        <Section id="stage-brief" kicker="5 · Brief" title={`Brief tray (${brief.length})`}>
          <BriefTray items={brief} question={result?.question ?? question} onRemove={(i) => setBrief((b) => b.filter((_, j) => j !== i))} onCreated={onSummaryCreated} />
        </Section>
        <Section id="stage-approve" kicker="6 · Approve & release" title="Approvals">
          <ApprovalsList me={me} refreshKey={summariesKey} onActivity={onSummaryActivity} />
        </Section>
      </div>

      {inspect && (
        <DocumentInspector
          key={inspect.key}
          target={inspect.target}
          onClose={() => setInspect(null)}
          onCompared={() => mark("compare")}
          onVerified={inspect.target.citation ? () => mark("verify") : undefined}
        />
      )}
    </div>
  );
}
