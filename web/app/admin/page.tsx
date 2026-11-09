"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Section } from "@/components/Bits";
import { Modal } from "@/components/Modal";
import { hasRole, useSession } from "@/components/Shell";
import { api, errorText, todayISO, when } from "@/lib/api";
import type { AdminDocumentRow, AuditRow, QuarantineRow } from "@/lib/types";

type Load<T> = { data?: T; error?: string };

function useAdminData<T>(path: string, tick: number, enabled: boolean): Load<T> {
  const [state, setState] = useState<Load<T>>({});
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    api<T>(path)
      .then((data) => {
        if (!cancelled) setState({ data });
      })
      .catch((e: unknown) => {
        if (!cancelled) setState({ error: errorText(e) });
      });
    return () => {
      cancelled = true;
    };
  }, [path, tick, enabled]);
  return state;
}

function toBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let bin = "";
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) bin += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  return btoa(bin);
}

const MAX_UPLOAD = 2 * 1024 * 1024;

function UploadForm({ collections, groups, tenantGroups, onDone }: { collections: string[]; groups: string[]; tenantGroups: string[]; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [docKey, setDocKey] = useState("");
  const [title, setTitle] = useState("");
  const [collection, setCollection] = useState(collections[0] ?? "");
  const [docType, setDocType] = useState("memo");
  const [classification, setClassification] = useState("confidential");
  const [acl, setAcl] = useState(groups.join(", "));
  const [effective, setEffective] = useState(() => todayISO());
  const [retention, setRetention] = useState("7y");
  const [state, setState] = useState<{ busy?: boolean; error?: string; ok?: string }>({});

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    if (file.size > MAX_UPLOAD) {
      setState({ error: "File is larger than the 2 MB upload limit." });
      return;
    }
    setState({ busy: true });
    try {
      const content_base64 = toBase64(await file.arrayBuffer());
      const r = await api<{ status: string; version_id: number; version: number; checksum: string; chunks: number; filename: string }>(
        "/api/admin/ingest",
        {
          body: {
            filename: file.name,
            content_base64,
            doc_key: docKey.trim(),
            title: title.trim(),
            collection,
            doc_type: docType.trim() || "memo",
            classification,
            acl_groups: acl.split(",").map((g) => g.trim()).filter(Boolean),
            effective_date: effective,
            retention: retention.trim() || "7y",
          },
        },
      );
      setState({ ok: `Indexed ${r.filename} as ${docKey}@${r.version} (version ${r.version_id}, ${r.chunks} chunks, sha256 ${r.checksum.slice(0, 12)}…).` });
      onDone();
    } catch (err) {
      setState({ error: errorText(err) });
      onDone();
    }
  };

  return (
    <form className="form-grid upload" onSubmit={submit}>
      <label className="field span2">
        <span>File (.md, .txt or .pdf; max 2 MB — anything else is quarantined)</span>
        <input type="file" required onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </label>
      <label className="field">
        <span>Doc key (e.g. CV-NEW-DOC)</span>
        <input required value={docKey} pattern="[A-Z]{2}-[A-Z0-9\-]{2,40}" onChange={(e) => setDocKey(e.target.value.toUpperCase())} />
      </label>
      <label className="field">
        <span>Title</span>
        <input required maxLength={300} value={title} onChange={(e) => setTitle(e.target.value)} />
      </label>
      <label className="field">
        <span>Collection</span>
        <select value={collection} onChange={(e) => setCollection(e.target.value)}>
          {collections.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Type</span>
        <input maxLength={32} value={docType} onChange={(e) => setDocType(e.target.value)} />
      </label>
      <label className="field">
        <span>Classification</span>
        <select value={classification} onChange={(e) => setClassification(e.target.value)}>
          {["public", "internal", "confidential", "restricted"].map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>ACL groups (comma-separated)</span>
        <input required value={acl} onChange={(e) => setAcl(e.target.value)} aria-describedby="acl-groups-hint" />
        {tenantGroups.length > 0 && (
          <small id="acl-groups-hint">Groups in your tenant: {tenantGroups.join(", ")}</small>
        )}
      </label>
      <label className="field">
        <span>Effective date</span>
        <input type="date" required value={effective} onChange={(e) => setEffective(e.target.value)} />
      </label>
      <label className="field">
        <span>Retention</span>
        <input maxLength={120} value={retention} onChange={(e) => setRetention(e.target.value)} />
      </label>
      <div className="span2 row">
        <button type="submit" className="btn btn-brass" disabled={state.busy || !file}>
          {state.busy ? "Uploading…" : "Upload & index"}
        </button>
        <span className="small muted">Tenant is taken from your session. Files that fail type sniffing or extraction are quarantined.</span>
      </div>
      {state.ok && <p className="span2 small ok" role="status">{state.ok}</p>}
      {state.error && <p className="span2 small error" role="alert">{state.error}</p>}
    </form>
  );
}

export default function AdminPage() {
  const { me } = useSession();
  const isAdmin = hasRole(me, "admin");
  const [tick, setTick] = useState(0);
  const audit = useAdminData<AuditRow[]>("/api/admin/audit", tick, isAdmin);
  const quarantine = useAdminData<QuarantineRow[]>("/api/admin/quarantine", tick, isAdmin);
  const registry = useAdminData<AdminDocumentRow[]>("/api/admin/documents", tick, isAdmin);
  const [actionFilter, setActionFilter] = useState("");
  const [confirm, setConfirm] = useState<string | null>(null);
  const [deleteKey, setDeleteKey] = useState("");
  const [del, setDel] = useState<{ busy?: boolean; error?: string; ok?: string }>({});

  const actions = useMemo(() => [...new Set((audit.data ?? []).map((r) => r.action))].sort(), [audit.data]);
  const keys = useMemo(() => {
    const m = new Map<string, AdminDocumentRow[]>();
    for (const r of registry.data ?? []) m.set(r.doc_key, [...(m.get(r.doc_key) ?? []), r]);
    return m;
  }, [registry.data]);

  if (!isAdmin) {
    return (
      <div className="page">
        <div className="state-panel forbidden" role="alert">
          <h1>Forbidden</h1>
          <p>
            The admin console requires the <code>admin</code> role. You are signed in as <strong>{me.display_name}</strong> with roles{" "}
            {me.roles.map((r, i) => (
              <span key={r}>
                {i > 0 && ", "}
                <code>{r}</code>
              </span>
            ))}
            . The server enforces this; the page only reflects it.
          </p>
        </div>
      </div>
    );
  }

  const doDelete = async (key: string) => {
    setDel({ busy: true });
    try {
      const r = await api<{ deleted_versions: number }>(`/api/admin/documents/${encodeURIComponent(key)}`, { method: "DELETE" });
      setDel({ ok: `Deleted ${key} (${r.deleted_versions} version${r.deleted_versions === 1 ? "" : "s"}).` });
      setDeleteKey("");
    } catch (e) {
      setDel({ error: errorText(e) });
    }
    setConfirm(null);
    setTick((t) => t + 1);
  };

  const confirmRows = confirm ? keys.get(confirm) ?? [] : [];

  return (
    <div className="page admin">
      <div className="page-head row between">
        <div>
          <div className="kicker">Records administration · {me.tenant_name}</div>
          <h1>Admin console</h1>
        </div>
        <button type="button" className="btn btn-ghost" onClick={() => setTick((t) => t + 1)}>Refresh all</button>
      </div>

      <Section title="Upload a document" kicker="POST /api/admin/ingest">
        <UploadForm collections={me.collections} groups={me.groups} tenantGroups={me.tenant_groups ?? []} onDone={() => setTick((t) => t + 1)} />
      </Section>

      <Section title="Document registry" kicker="Keys and versions in your tenant">
        <p className="small muted">Content access still follows the ACL: titles of versions you cannot read are withheld by the server.</p>
        {registry.error && <p className="small error" role="alert">{registry.error}</p>}
        {registry.data && (
          <div className="table-wrap">
            <table className="table compact">
              <caption className="sr-only">Document registry</caption>
              <thead>
                <tr>
                  <th scope="col">Doc key</th>
                  <th scope="col">Version</th>
                  <th scope="col">Title</th>
                  <th scope="col">Status</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {registry.data.map((r, i) => (
                  <tr key={`${r.doc_key}-${r.version}`} className={r.deleted ? "row-deleted" : ""}>
                    <td className="mono small">{r.doc_key}</td>
                    <td className="mono small">v{r.version}</td>
                    <td className="small">{r.title ?? <span className="muted">hidden: not readable by you</span>}</td>
                    <td>
                      <span className={r.deleted ? "pill pill-warn" : "pill"}>{r.deleted ? "deleted" : r.status}</span>
                      {r.readable_by_you && <span className="pill pill-ok">readable</span>}
                    </td>
                    <td>
                      {!r.deleted && registry.data?.findIndex((x) => x.doc_key === r.doc_key) === i && (
                        <button type="button" className="btn btn-sm btn-danger" onClick={() => setConfirm(r.doc_key)}>
                          Delete…
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <form
          className="row wrap delete-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (deleteKey.trim()) setConfirm(deleteKey.trim());
          }}
        >
          <label className="field inline">
            <span>Delete by doc key</span>
            <input value={deleteKey} onChange={(e) => setDeleteKey(e.target.value.toUpperCase())} />
          </label>
          <button type="submit" className="btn btn-danger btn-sm" disabled={!deleteKey.trim()}>Delete…</button>
        </form>
        {del.ok && <p className="small ok" role="status">{del.ok}</p>}
        {del.error && <p className="small error" role="alert">{del.error}</p>}
      </Section>

      <Section title="Quarantine" kicker="Rejected uploads">
        {quarantine.error && <p className="small error" role="alert">{quarantine.error}</p>}
        {quarantine.data && quarantine.data.length === 0 && <p className="small muted">Nothing quarantined.</p>}
        {quarantine.data && quarantine.data.length > 0 && (
          <div className="table-wrap">
            <table className="table compact">
              <caption className="sr-only">Quarantined uploads</caption>
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">File</th>
                  <th scope="col">Reason</th>
                  <th scope="col">Size</th>
                  <th scope="col">SHA-256</th>
                  <th scope="col">By</th>
                </tr>
              </thead>
              <tbody>
                {quarantine.data.map((q) => (
                  <tr key={q.id}>
                    <td className="small">{when(q.ts)}</td>
                    <td className="mono small">{q.filename}</td>
                    <td className="small warn">{q.reason}</td>
                    <td className="small">{q.byte_size.toLocaleString()} B</td>
                    <td className="mono small">{q.sha256.slice(0, 16)}…</td>
                    <td className="mono small">{q.uploaded_by}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section
        title="Audit log"
        kicker="Most recent events in your tenant"
        actions={
          <label className="field inline">
            <span>Action</span>
            <select value={actionFilter} onChange={(e) => setActionFilter(e.target.value)}>
              <option value="">All</option>
              {actions.map((a) => (
                <option key={a} value={a}>{a}</option>
              ))}
            </select>
          </label>
        }
      >
        {audit.error && <p className="small error" role="alert">{audit.error}</p>}
        {audit.data && (
          <div className="table-wrap tall">
            <table className="table compact">
              <caption className="sr-only">Audit log</caption>
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">User</th>
                  <th scope="col">Action</th>
                  <th scope="col">Outcome</th>
                  <th scope="col">Detail</th>
                  <th scope="col">Request</th>
                </tr>
              </thead>
              <tbody>
                {audit.data
                  .filter((r) => !actionFilter || r.action === actionFilter)
                  .map((r) => (
                    <tr key={r.id}>
                      <td className="small nowrap">{when(r.ts)}</td>
                      <td className="mono small">{r.username ?? "—"}</td>
                      <td className="mono small">{r.action}</td>
                      <td>
                        <span className={r.outcome === "denied" || r.outcome === "quarantined" ? "pill pill-warn" : "pill"}>{r.outcome}</span>
                      </td>
                      <td className="mono small detail-cell">{Object.keys(r.detail).length ? JSON.stringify(r.detail) : "—"}</td>
                      <td className="mono small">{r.request_id}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {confirm && (
        <Modal labelledBy="confirm-del-h" onEscape={() => setConfirm(null)} role="alertdialog" className="confirm">
          <h2 id="confirm-del-h">Delete {confirm}?</h2>
          <p>
            This soft-deletes <span className="mono">{confirm}</span>
            {confirmRows.length > 0 && ` (${confirmRows.length} version${confirmRows.length === 1 ? "" : "s"})`}: its versions are marked
            deleted and its chunks, search index rows and embeddings are removed, so it can no longer be retrieved or cited. The action is
            recorded in the audit log.
          </p>
          <div className="row">
            <button type="button" className="btn btn-danger" onClick={() => doDelete(confirm)} disabled={del.busy}>
              {del.busy ? "Deleting…" : "Delete document"}
            </button>
            <button type="button" className="btn" onClick={() => setConfirm(null)} data-autofocus>
              Cancel
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
