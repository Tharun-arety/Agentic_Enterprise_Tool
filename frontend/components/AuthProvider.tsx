"use client";

import * as React from "react";
import { API_BASE_URL } from "@/lib/api";
import { setAccessToken } from "@/lib/auth-store";

type User = { email: string; full_name: string; roles: string[] };
type Auth = {
  user: User | null;
  ready: boolean;
  token: string | null;
  request: <T>(path: string, init?: RequestInit) => Promise<T>;
  prefetch: (path: string) => void;
  logout: () => Promise<void>;
};

const Context = React.createContext<Auth | null>(null);
const responseCache = new Map<string, { expires: number; value: unknown }>();
const inFlight = new Map<string, Promise<unknown>>();
const CACHE_MS = 30_000;
const WARM_PATHS = [
  "/api/showcase",
  "/api/parts/ECL-SYS-1000/bom?bom_type=MBOM",
  "/api/qms/ECL-M-104",
  "/api/procurement/stock-risk",
  "/api/ecm/requests",
  "/api/controlling/rollup/ECL-SYS-1000?batch_size=10",
  "/api/knowledge/ingestion",
];

function csrf() {
  return (
    document.cookie
      .split("; ")
      .find((entry) => entry.startsWith("mt_csrf="))
      ?.split("=")
      .slice(1)
      .join("=") ?? ""
  );
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = React.useState<string | null>(null);
  const [user, setUser] = React.useState<User | null>(null);
  const [ready, setReady] = React.useState(false);

  const accept = React.useCallback(
    (data: { access_token: string; user: User }) => {
      responseCache.clear();
      inFlight.clear();
      setToken(data.access_token);
      setAccessToken(data.access_token);
      setUser(data.user);
    },
    [],
  );

  React.useEffect(() => {
    fetch(`${API_BASE_URL}/api/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: { "X-CSRF-Token": csrf() },
    })
      .then(async (response) => {
        if (response.ok) accept(await response.json());
      })
      .finally(() => setReady(true));
  }, [accept]);

  const request = React.useCallback(
    async <T,>(path: string, init: RequestInit = {}): Promise<T> => {
      const method = (init.method ?? "GET").toUpperCase();
      const cacheable = method === "GET";
      const force = init.cache === "reload" || init.cache === "no-store";
      const cached = responseCache.get(path);
      if (cacheable && !force && cached && cached.expires > Date.now()) {
        return cached.value as T;
      }
      if (cacheable && !force && inFlight.has(path)) {
        return inFlight.get(path) as Promise<T>;
      }

      const operation = (async () => {
        const headers = new Headers(init.headers);
        if (token) headers.set("Authorization", `Bearer ${token}`);
        if (
          init.body &&
          !headers.has("Content-Type") &&
          !(init.body instanceof FormData)
        ) {
          headers.set("Content-Type", "application/json");
        }
        let response = await fetch(`${API_BASE_URL}${path}`, {
          ...init,
          headers,
          credentials: "include",
        });
        if (response.status === 401) {
          const refreshed = await fetch(`${API_BASE_URL}/api/auth/refresh`, {
            method: "POST",
            credentials: "include",
            headers: { "X-CSRF-Token": csrf() },
          });
          if (refreshed.ok) {
            const data = await refreshed.json();
            accept(data);
            headers.set("Authorization", `Bearer ${data.access_token}`);
            response = await fetch(`${API_BASE_URL}${path}`, {
              ...init,
              headers,
              credentials: "include",
            });
          }
        }
        if (!response.ok) {
          throw new Error(`${response.status}: ${await response.text()}`);
        }
        const value = (await response.json()) as T;
        if (cacheable) {
          responseCache.set(path, { expires: Date.now() + CACHE_MS, value });
        } else {
          responseCache.clear();
        }
        return value;
      })();

      if (cacheable) inFlight.set(path, operation);
      try {
        return await operation;
      } finally {
        if (cacheable) inFlight.delete(path);
      }
    },
    [token, accept],
  );

  const prefetch = React.useCallback(
    (path: string) => {
      void request(path).catch(() => undefined);
    },
    [request],
  );

  React.useEffect(() => {
    if (!token) return;
    const timer = window.setTimeout(() => {
      WARM_PATHS.forEach(prefetch);
    }, 150);
    return () => window.clearTimeout(timer);
  }, [token, prefetch]);

  const logout = React.useCallback(async () => {
    if (token) {
      await fetch(`${API_BASE_URL}/api/auth/logout`, {
        method: "POST",
        credentials: "include",
        headers: { Authorization: `Bearer ${token}` },
      });
    }
    responseCache.clear();
    inFlight.clear();
    setToken(null);
    setAccessToken(null);
    setUser(null);
  }, [token]);

  if (!ready) return <LoadingSession />;
  if (!user) return <Login onLogin={accept} />;
  return (
    <Context.Provider value={{ user, ready, token, request, prefetch, logout }}>
      {children}
    </Context.Provider>
  );
}

function LoadingSession() {
  return (
    <main className="grid min-h-dvh place-items-center p-6">
      <div className="text-center">
        <div className="bg-accent/15 mx-auto size-8 animate-pulse rounded-lg" />
        <p className="text-muted-foreground mt-3 text-xs">Restoring session…</p>
      </div>
    </main>
  );
}

function Login({
  onLogin,
}: {
  onLogin: (data: { access_token: string; user: User }) => void;
}) {
  const [email, setEmail] = React.useState("admin@magnotherm.test");
  const [password, setPassword] = React.useState("magnotherm");
  const [error, setError] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  return (
    <main className="grid min-h-dvh place-items-center p-6">
      <form
        className="bg-surface border-border w-full max-w-sm space-y-4 rounded-xl border p-6 shadow-xl"
        onSubmit={async (event) => {
          event.preventDefault();
          setError("");
          setSubmitting(true);
          try {
            const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
              method: "POST",
              credentials: "include",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ email, password }),
            });
            if (response.ok) onLogin(await response.json());
            else setError("Sign-in failed");
          } finally {
            setSubmitting(false);
          }
        }}
      >
        <div>
          <p className="text-accent text-xs font-semibold uppercase tracking-widest">Magnotherm</p>
          <h1 className="mt-1 text-xl font-semibold">Enterprise toolchain</h1>
          <p className="text-muted-foreground mt-1 text-xs">Synthetic portfolio sandbox</p>
        </div>
        <label className="block text-xs">
          Email
          <input className="border-border bg-background mt-1 w-full rounded-md border p-2" value={email} onChange={(event) => setEmail(event.target.value)} />
        </label>
        <label className="block text-xs">
          Password
          <input type="password" className="border-border bg-background mt-1 w-full rounded-md border p-2" value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
        {error && <p className="text-warning text-xs">{error}</p>}
        <button disabled={submitting} className="bg-accent text-accent-foreground w-full rounded-md p-2 text-sm font-semibold disabled:opacity-60">
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}

export function useAuth() {
  const value = React.useContext(Context);
  if (!value) throw new Error("AuthProvider is missing");
  return value;
}
