"use client";

import { useId, useState } from "react";
import { api, errorText } from "@/lib/api";
import type { AnswerSentence, AskResult, Citation } from "@/lib/types";
import { CitationChip, StatusBadge, SupportBadge } from "./Bits";

type Verdict = "correct" | "incorrect" | "partial";

function ReviewForm({ result, sentence }: { result: AskResult; sentence: AnswerSentence }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [verdict, setVerdict] = useState<Verdict>("correct");
  const [reason, setReason] = useState("");
  const [state, setState] = useState<{ busy?: boolean; saved?: number; error?: string }>({});
  const c = sentence.citations[0];
  if (!c) return null;

  const submit = async () => {
    setState({ busy: true });
    try {
      const r = await api<{ id: number }>("/api/reviews", {
        body: {
          request_id: result.request_id,
          question: result.question,
          answer_mode: result.mode,
          sentence: sentence.text,
          version_id: c.version_id,
          char_start: c.char_start,
          char_end: c.char_end,
          quote: c.quote,
          verdict,
          reason,
        },
      });
      setState({ saved: r.id });
      setOpen(false);
    } catch (e) {
      setState({ error: errorText(e) });
    }
  };

  if (state.saved && !open) {
    return (
      <span className="small ok">
        Label #{state.saved} saved ({verdict}) — local demo label, not externally audited.{" "}
        <button type="button" className="link-btn" onClick={() => setOpen(true)}>Add another</button>
      </span>
    );
  }
  if (!open) {
    return (
      <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOpen(true)}>
        Review
      </button>
    );
  }
  return (
    <fieldset className="review-form">
      <legend>Human review label</legend>
      <div className="radio-row" role="radiogroup" aria-label="Verdict">
        {(
          [
            ["correct", "Correct"],
            ["partial", "Partially supported"],
            ["incorrect", "Incorrect"],
          ] as const
        ).map(([v, label]) => (
          <label key={v} className="radio">
            <input type="radio" name={`${id}-verdict`} value={v} checked={verdict === v} onChange={() => setVerdict(v)} />
            {label}
          </label>
        ))}
      </div>
      <label className="field">
        <span>Reason</span>
        <input type="text" maxLength={600} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why? (optional)" />
      </label>
      <div className="row">
        <button type="button" className="btn btn-brass btn-sm" onClick={submit} disabled={state.busy}>
          {state.busy ? "Saving…" : "Save label"}
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOpen(false)}>Cancel</button>
        <span className="small muted">Local demo labels, not externally audited. Labels the first citation ({c.pid}).</span>
      </div>
      {state.error && <p className="small error" role="alert">{state.error}</p>}
    </fieldset>
  );
}

export function AnswerPanel({
  result,
  onVerify,
  onAddToBrief,
  inBrief,
}: {
  result: AskResult;
  onVerify: (s: AnswerSentence, c: Citation) => void;
  onAddToBrief: (s: AnswerSentence) => void;
  inBrief: (s: AnswerSentence) => boolean;
}) {
  const generated = result.mode === "generative";
  return (
    <div className="answer">
      <div className="answer-top">
        <StatusBadge status={result.status} />
        <span className="small muted">
          as of {result.as_of} · {result.retrieval.method} · {result.latency_ms} ms · request <code>{result.request_id}</code>
        </span>
      </div>
      <div className={`mode-banner ${generated ? "mode-generated" : "mode-extractive"}`} role="note">
        <span className="mode-tag">{generated ? "GENERATED" : "EXTRACTIVE"}</span>
        <span>{result.mode_label}</span>
      </div>
      {result.generation.requested && !generated && result.generation.status && (
        <p className="small warn">Local model requested: {result.generation.status}{result.generation.rejected_reason ? ` (${result.generation.rejected_reason})` : ""}. Showing extractive evidence.</p>
      )}

      {result.abstained ? (
        <div className="abstain" role="status">
          <h3>The vault abstained</h3>
          <p className="abstain-reason">{result.abstain_reason}</p>
          {result.trust.gaps.length > 0 && (
            <>
              <h4>Evidence gaps</h4>
              <ul>
                {result.trust.gaps.map((g) => (
                  <li key={g}>{g}</li>
                ))}
              </ul>
            </>
          )}
          <p className="small muted">Abstaining is the intended outcome when the authorized evidence does not answer the question.</p>
        </div>
      ) : (
        <ol className="sentences">
          {result.answer.map((s, i) => (
            <li key={i} className={`sentence support-row-${s.support}`}>
              <p className="sentence-text">{s.text}</p>
              <div className="sentence-meta">
                <div className="chip-row">
                  {s.citations.map((c) => (
                    <CitationChip key={`${c.pid}-${c.char_start}`} c={c} onOpen={(cc) => onVerify(s, cc)} />
                  ))}
                </div>
                {generated && <SupportBadge support={s.support} />}
              </div>
              {generated && s.notes.length > 0 && (
                <ul className="notes small">
                  {s.notes.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              )}
              <div className="sentence-actions">
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => onAddToBrief(s)}
                  disabled={s.citations.length === 0 || inBrief(s)}
                >
                  {inBrief(s) ? "In brief" : "+ Add to brief"}
                </button>
                <ReviewForm result={result} sentence={s} />
              </div>
            </li>
          ))}
          {result.answer.length === 0 && <li className="muted">No answer sentences were produced.</li>}
        </ol>
      )}
    </div>
  );
}
