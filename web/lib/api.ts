// Thin client for the Inkfall API, always same-origin (/api is proxied by next.config.ts).
// The UI is never the security boundary: it only reflects what the server allows.

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;

  constructor(status: number, code: string, message: string, requestId: string | null) {
    super(message);
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

function describe(status: number, body: unknown): { code: string; message: string } {
  const obj = (body && typeof body === "object" ? body : {}) as Record<string, unknown>;
  const raw = obj.error ?? obj.detail ?? obj.reason ?? obj.status;
  const code = typeof raw === "string" ? raw : `http_${status}`;
  if (status === 404) return { code, message: "Not found or not authorized." };
  if (status === 401) return { code, message: "Your session has ended. Please choose an identity again." };
  if (status === 429) return { code, message: "Rate limited by the server. Wait a minute and try again." };
  if (status === 422 && Array.isArray(obj.details)) {
    const fields = (obj.details as { loc?: unknown[]; type?: string }[])
      .map((d) => `${(d.loc ?? []).filter((x) => x !== "body").join(".")} (${d.type ?? "invalid"})`)
      .join(", ");
    return { code, message: `The server rejected the request: ${fields || code}.` };
  }
  if (status === 422 && typeof obj.reason === "string") {
    return { code, message: `${String(obj.status ?? "rejected")}: ${obj.reason}` };
  }
  return { code, message: typeof raw === "string" ? raw.replace(/_/g, " ") : `Request failed (HTTP ${status}).` };
}

export async function api<T>(path: string, init?: { method?: string; body?: unknown; signal?: AbortSignal }): Promise<T> {
  const res = await fetch(path, {
    method: init?.method ?? (init?.body === undefined ? "GET" : "POST"),
    headers: init?.body === undefined ? { Accept: "application/json" } : { "Content-Type": "application/json", Accept: "application/json" },
    body: init?.body === undefined ? undefined : JSON.stringify(init.body),
    credentials: "same-origin",
    cache: "no-store",
    signal: init?.signal,
  });
  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = { error: text.slice(0, 200) };
    }
  }
  if (!res.ok) {
    const { code, message } = describe(res.status, body);
    if (res.status === 401 && typeof window !== "undefined" && window.location.pathname.replace(/\/+$/, "") !== "/login") {
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- deliberate full reload: drop all in-memory state from the previous identity
      window.location.assign("/login");
    }
    throw new ApiError(res.status, code, message, res.headers.get("X-Request-ID"));
  }
  return body as T;
}

export function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof DOMException && err.name === "AbortError") return "Request cancelled.";
  if (err instanceof Error) return `Could not reach the API (${err.message}).`;
  return "Unexpected error.";
}

export function todayISO(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function num(v: number | null | undefined, digits = 3): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number.isInteger(v) ? String(v) : v.toFixed(digits);
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function humanize(s: string): string {
  return s.replace(/_/g, " ");
}
