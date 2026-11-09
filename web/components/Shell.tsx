"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, errorText, routePath } from "@/lib/api";
import type { Me, SystemInfo } from "@/lib/types";

interface SessionValue {
  me: Me;
  system: SystemInfo | null;
}

const SessionContext = createContext<SessionValue | null>(null);

export function useSession(): SessionValue {
  const v = useContext(SessionContext);
  if (!v) throw new Error("useSession outside an authenticated page");
  return v;
}

export function hasRole(me: Me, role: string): boolean {
  return me.roles.includes(role);
}

const NAV = [
  { href: "/", label: "Workbench" },
  { href: "/library", label: "Library" },
  { href: "/lab", label: "Evaluation lab" },
  { href: "/admin", label: "Admin" },
];

function Footer() {
  return (
    <footer className="site-footer">
      Fictional data. Decision support, not legal advice. Not affiliated with any real organization.
    </footer>
  );
}

function SystemStrip({ system }: { system: SystemInfo | null }) {
  if (!system) return <div className="system-strip muted">System status unavailable.</div>;
  return (
    <div className="system-strip" aria-label="System status">
      <span>
        <span className="k">Embeddings</span>{" "}
        <span className={system.embedding.status === "ready" ? "ok" : "warn"}>{system.embedding.status}</span>{" "}
        <code>{system.embedding.model_id}</code>
      </span>
      <span>
        <span className="k">Generation</span>{" "}
        {system.generation_backends.length === 0 && <span className="muted">none detected</span>}
        {system.generation_backends.map((b) => (
          <span key={b.name} className="backend" title={b.detail || b.base_url}>
            <span className={b.available ? "dot dot-ok" : "dot dot-off"} aria-hidden="true" />
            {b.name}
            {b.available && b.chosen_model ? <code> {b.chosen_model}</code> : <span className="muted"> offline</span>}
          </span>
        ))}
      </span>
      <span>
        <span className="k">Reranker</span> {system.reranker.downloaded ? "downloaded" : "not downloaded"}
      </span>
      <span>
        <span className="k">Dataset</span> <code>{system.dataset_version ?? "—"}</code>
        {system.documents != null && <span className="muted"> · {system.documents} docs</span>}
      </span>
    </div>
  );
}

function Header({ me, system }: SessionValue) {
  const pathname = usePathname();
  const [busy, setBusy] = useState(false);

  const switchIdentity = async () => {
    setBusy(true);
    try {
      await api("/api/auth/logout", { method: "POST" });
    } catch {
      /* the session may already be gone; go to login either way */
    }
    // Full reload so no state from the previous identity survives in memory.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- deliberate full reload: drop all in-memory state from the previous identity
    window.location.assign("/login");
  };

  return (
    <header className="site-header">
      <div className="header-row">
        <Link href="/" className="brand">
          <span className="brand-mark" aria-hidden="true">◆</span> The Inkfall Vault
        </Link>
        <nav aria-label="Primary" className="primary-nav">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} aria-current={routePath(pathname) === n.href ? "page" : undefined}>
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="identity">
          <div className="identity-text">
            <span className="tenant">{me.tenant_name}</span>
            <span>
              <strong>{me.display_name}</strong> <span className="muted">· {me.title}</span>
            </span>
            <span className="chips-inline">
              <span className="pill pill-brass" title="Clearance">clearance: {me.clearance}</span>
              {me.roles.map((r) => (
                <span key={r} className="pill">{r}</span>
              ))}
            </span>
          </div>
          <button type="button" className="btn btn-ghost" onClick={switchIdentity} disabled={busy}>
            Switch identity
          </button>
        </div>
      </div>
      <SystemStrip system={system} />
    </header>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const isLogin = routePath(pathname) === "/login";
  const [session, setSession] = useState<SessionValue | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (isLogin) return;
    let cancelled = false;
    api<Me>("/api/auth/me")
      .then(async (me) => {
        let system: SystemInfo | null = null;
        try {
          system = await api<SystemInfo>("/api/system");
        } catch {
          system = null;
        }
        if (!cancelled) {
          setSession({ me, system });
          setError(null);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(errorText(e));
      });
    return () => {
      cancelled = true;
    };
  }, [isLogin, attempt]);

  if (isLogin) {
    return (
      <>
        <a className="skip-link" href="#main">Skip to content</a>
        <main id="main" tabIndex={-1}>{children}</main>
        <Footer />
      </>
    );
  }

  return (
    <>
      <a className="skip-link" href="#main">Skip to content</a>
      {session ? <Header me={session.me} system={session.system} /> : <div className="site-header placeholder" />}
      <main id="main" tabIndex={-1}>
        {session ? (
          <SessionContext.Provider value={session}>{children}</SessionContext.Provider>
        ) : error ? (
          <div className="state-panel" role="alert">
            <p>{error}</p>
            <button type="button" className="btn" onClick={() => setAttempt((a) => a + 1)}>Retry</button>{" "}
            <Link className="btn btn-ghost" href="/login">Choose an identity</Link>
          </div>
        ) : (
          <div className="state-panel" aria-live="polite">Opening the vault…</div>
        )}
      </main>
      <Footer />
    </>
  );
}
