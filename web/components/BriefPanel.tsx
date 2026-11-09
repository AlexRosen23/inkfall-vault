"use client";

import { useCallback, useEffect, useState } from "react";
import { api, errorText, when } from "@/lib/api";
import type { BriefItem, Me, Summary } from "@/lib/types";
import { SummaryStatusBadge } from "./Bits";

export function BriefTray({
  items,
  question,
  onRemove,
  onCreated,
}: {
  items: BriefItem[];
  question: string;
  onRemove: (i: number) => void;
  onCreated: (s: Summary) => void;
}) {
  const [title, setTitle] = useState("");
  const [recipient, setRecipient] = useState("");
  const [state, setState] = useState<{ busy?: boolean; error?: string }>({});

  const create = async () => {
    setState({ busy: true });
    try {
      const s = await api<Summary>("/api/summaries", {
        body: {
          title: title.trim(),
          question: question.slice(0, 500),
          recipient: recipient.trim(),
          items: items.map(({ text, version_id, char_start, char_end, quote }) => ({ text, version_id, char_start, char_end, quote })),
        },
      });
      setState({});
      setTitle("");
      setRecipient("");
      onCreated(s);
    } catch (e) {
      setState({ error: errorText(e) });
    }
  };

  return (
    <div className="brief-tray">
      {items.length === 0 ? (
        <p className="muted small">Add cited answer sentences with “+ Add to brief”. Each item keeps its exact source span.</p>
      ) : (
        <ol className="brief-items">
          {items.map((it, i) => (
            <li key={`${it.version_id}-${it.char_start}-${i}`}>
              <p>{it.text}</p>
              <div className="row small">
                <span className="mono">{it.ref ?? `v${it.version_id}`}</span>
                <span className="mono muted">[{it.char_start}, {it.char_end})</span>
                <button type="button" className="link-btn" onClick={() => onRemove(i)} aria-label={`Remove item ${i + 1} from brief`}>
                  Remove
                </button>
              </div>
            </li>
          ))}
        </ol>
      )}
      <div className="brief-form">
        <label className="field">
          <span>Brief title</span>
          <input value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="field">
          <span>Recipient</span>
          <input value={recipient} maxLength={200} onChange={(e) => setRecipient(e.target.value)} />
        </label>
        <button type="button" className="btn btn-brass" onClick={create} disabled={state.busy || items.length === 0 || !title.trim() || items.length > 20}>
          {state.busy ? "Saving…" : "Save brief as draft"}
        </button>
        {items.length > 20 && <p className="small warn">A brief can hold at most 20 items.</p>}
        {state.error && <p className="small error" role="alert">{state.error}</p>}
      </div>
    </div>
  );
}

function SummaryCard({ s, me, onChanged }: { s: Summary; me: Me; onChanged: (s: Summary) => void }) {
  const [note, setNote] = useState("");
  const [state, setState] = useState<{ busy?: boolean; error?: string }>({});
  const isAuthor = s.author === me.username;
  const isReviewer = me.roles.includes("reviewer");

  const act = async (path: string, body?: unknown) => {
    setState({ busy: true });
    try {
      const out = await api<Summary>(`/api/summaries/${s.id}/${path}`, { method: "POST", body });
      setState({});
      onChanged(out);
    } catch (e) {
      setState({ error: errorText(e) });
    }
  };

  return (
    <li className="summary-card">
      <div className="row between">
        <div>
          <strong>{s.title}</strong> <span className="mono small muted">#{s.id}</span>
        </div>
        <SummaryStatusBadge status={s.status} />
      </div>
      <div className="small muted">
        by <span className="mono">{s.author}</span>
        {s.recipient && <> · for {s.recipient}</>} · {when(s.created_at)}
        {s.approver && (
          <>
            {" "}· decided by <span className="mono">{s.approver}</span> {when(s.decided_at)}
          </>
        )}
      </div>
      {s.question && <p className="small">Q: {s.question}</p>}
      <details>
        <summary className="small">{s.items.length} cited item{s.items.length === 1 ? "" : "s"}</summary>
        <ol className="small brief-items">
          {s.items.map((it, i) => (
            <li key={i}>
              {it.text} <span className="mono muted">{it.ref ?? `v${it.version_id}`} [{it.char_start}, {it.char_end})</span>
            </li>
          ))}
        </ol>
      </details>
      {s.decision_note && <p className="small">Decision note: {s.decision_note}</p>}

      <div className="row wrap">
        {isAuthor && (s.status === "draft" || s.status === "rejected") && (
          <button type="button" className="btn btn-sm" onClick={() => act("submit")} disabled={state.busy}>
            Submit for approval
          </button>
        )}
        {isReviewer && s.status === "pending" && !isAuthor && (
          <>
            <label className="field inline">
              <span className="sr-only">Decision note for brief {s.id}</span>
              <input value={note} maxLength={600} placeholder="Decision note" onChange={(e) => setNote(e.target.value)} />
            </label>
            <button type="button" className="btn btn-sm btn-ok" onClick={() => act("decision", { decision: "approve", note })} disabled={state.busy}>
              Approve
            </button>
            <button type="button" className="btn btn-sm btn-danger" onClick={() => act("decision", { decision: "reject", note })} disabled={state.busy}>
              Reject
            </button>
          </>
        )}
        {isReviewer && s.status === "pending" && isAuthor && (
          <span className="small muted">Awaiting another reviewer — authors cannot approve their own brief.</span>
        )}
        {!isReviewer && s.status === "pending" && <span className="small muted">Awaiting a reviewer.</span>}
        {s.status === "approved" && (isAuthor || s.approver === me.username) && (
          <button type="button" className="btn btn-sm btn-brass" onClick={() => act("release")} disabled={state.busy}>
            Release
          </button>
        )}
      </div>
      {s.status === "released" && s.export_path && (
        <p className="small ok">
          Released {when(s.released_at)} → <code>{s.export_path}</code>. Written to a local outbox; nothing leaves this machine.
        </p>
      )}
      {state.error && <p className="small error" role="alert">{state.error}</p>}
    </li>
  );
}

export function ApprovalsList({ me, refreshKey, onActivity }: { me: Me; refreshKey: number; onActivity: (s: Summary) => void }) {
  const [rows, setRows] = useState<Summary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api<Summary[]>("/api/summaries")
      .then((r) => {
        if (!cancelled) {
          setRows(r);
          setError(null);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(errorText(e));
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey, tick]);

  const changed = useCallback(
    (s: Summary) => {
      setRows((prev) => (prev ?? []).map((x) => (x.id === s.id ? s : x)));
      onActivity(s);
    },
    [onActivity],
  );

  return (
    <div>
      <div className="row between">
        <p className="small muted">
          {me.roles.includes("reviewer")
            ? "You hold the reviewer role: pending briefs by others can be approved or rejected here."
            : "Briefs in your tenant whose every source you can read. A reviewer must approve before release."}
        </p>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setTick((t) => t + 1)}>Refresh</button>
      </div>
      {error && <p className="small error" role="alert">{error}</p>}
      {rows && rows.length === 0 && <p className="muted small">No briefs yet.</p>}
      {rows && rows.length > 0 && (
        <ul className="summary-list">
          {rows.map((s) => (
            <SummaryCard key={s.id} s={s} me={me} onChanged={changed} />
          ))}
        </ul>
      )}
    </div>
  );
}
