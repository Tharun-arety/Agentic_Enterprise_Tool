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

/**
 * Refresh, at most once at a time.
 *
 * The backend rotates the refresh token on every use and treats a reused one
 * as theft: presenting a spent token revokes the entire session family. That
 * is the right defence, but it means two refreshes racing each other sign the
 * user out — and there are two callers that can fire together. Mount-time
 * restore runs twice under React's development double-invoke, and any two
 * requests that expire mid-flight each try to refresh on their 401.
 *
 * Sharing one in-flight promise makes the second caller await the first
 * instead of spending a token that is already gone.
 */
let refreshInFlight: Promise<Response> | null = null;

function refreshOnce(): Promise<Response> {
  refreshInFlight ??= fetch(`${API_BASE_URL}/api/auth/refresh`, {
    method: "POST",
    credentials: "include",
    headers: { "X-CSRF-Token": csrf() },
  }).finally(() => {
    refreshInFlight = null;
  });
  // Each caller reads the body, so hand out a clone rather than the one
  // response whose stream the first reader would consume.
  return refreshInFlight.then((response) => response.clone());
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
    let cancelled = false;

    /**
     * Restore the session from the refresh cookie.
     *
     * A 401 means there is genuinely no session and the sign-in screen is the
     * right answer. Any other failure — a rate limit, a cold backend, a
     * dropped connection — means we do not know yet, and treating "do not
     * know" as "signed out" silently throws the user back to the login screen
     * mid-session. Those cases get one retry before we give up.
     */
    const restore = async (retriesLeft: number): Promise<void> => {
      let response: Response;
      try {
        response = await refreshOnce();
      } catch {
        if (retriesLeft > 0 && !cancelled) {
          await new Promise((resolve) => setTimeout(resolve, 1_500));
          return restore(retriesLeft - 1);
        }
        return;
      }

      if (cancelled) return;
      if (response.ok) {
        accept(await response.json());
        return;
      }
      if (response.status !== 401 && retriesLeft > 0) {
        const after = Number(response.headers.get("Retry-After")) || 2;
        await new Promise((resolve) => setTimeout(resolve, Math.min(after, 5) * 1_000));
        if (!cancelled) return restore(retriesLeft - 1);
      }
    };

    void restore(1).finally(() => {
      if (!cancelled) setReady(true);
    });

    return () => {
      cancelled = true;
    };
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
          const refreshed = await refreshOnce();
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

  /*
   * There used to be an eager warm-up here that fetched seven domain endpoints
   * on every session start. The response cache lives in memory, so a full page
   * load threw the previous warm-up away and paid for it again — seven reads
   * before the user had chosen a destination, of which at most one was ever
   * used. The sidebar prefetches on hover and focus instead, which costs one
   * read and only when someone has shown where they are going.
   */

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
    <main className="grid min-h-dvh place-items-center p-6" role="status" aria-live="polite">
      <div className="text-center">
        <div className="bg-sunken mx-auto h-1.5 w-24 animate-pulse rounded-full" />
        <p className="text-ink-faint mt-3 text-xs">Restoring session…</p>
      </div>
    </main>
  );
}

/**
 * The seeded cast, offered as one-click sign-ins.
 *
 * This is a portfolio sandbox, so hiding the demo credentials behind a
 * password field nobody can guess would be theatre. The roles matter to the
 * demo — the approval inbox behaves differently depending on which seat you
 * hold — so the picker makes switching seats the obvious thing to do.
 */
const SEATS = [
  { email: "admin@magnotherm.test", seat: "Admin", note: "sees everything" },
  { email: "engineer@magnotherm.test", seat: "Design engineering", note: "raises changes" },
  { email: "quality@magnotherm.test", seat: "Quality", note: "raises findings" },
  { email: "sysenq@magnotherm.test", seat: "Systems engineering", note: "board seat" },
  { email: "manufacturing@magnotherm.test", seat: "Manufacturing", note: "board seat" },
  { email: "procurement@magnotherm.test", seat: "Procurement", note: "board seat" },
  { email: "controller@magnotherm.test", seat: "Controlling", note: "cost and budget" },
] as const;

const DEMO_PASSWORD = "magnotherm";

function Login({
  onLogin,
}: {
  onLogin: (data: { access_token: string; user: User }) => void;
}) {
  const [email, setEmail] = React.useState<string>(SEATS[0].email);
  const [password, setPassword] = React.useState<string>(DEMO_PASSWORD);
  const [error, setError] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);

  const signIn = React.useCallback(
    async (asEmail: string, withPassword: string) => {
      setError("");
      setSubmitting(true);
      try {
        const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: asEmail, password: withPassword }),
        });
        if (response.ok) {
          onLogin(await response.json());
          return;
        }
        setError(
          response.status === 401
            ? "That email and password do not match a seeded account. Pick a seat below to sign in."
            : `Sign-in failed (${response.status}). Check that the backend is running.`,
        );
      } catch {
        setError("The backend did not respond. Start it on port 8000 and try again.");
      } finally {
        setSubmitting(false);
      }
    },
    [onLogin],
  );

  return (
    <main className="grid min-h-dvh place-items-center p-4 sm:p-6">
      <div className="w-full max-w-3xl">
        <div className="mb-6">
          <p className="eyebrow">Magnotherm · synthetic portfolio sandbox</p>
          <h1 className="mt-2 text-balance text-2xl font-semibold tracking-tight sm:text-3xl">
            Engineering operations for refrigerant-free cooling
          </h1>
          <p className="text-ink-dim mt-2 max-w-xl text-pretty text-sm leading-6">
            Configuration, change, quality, supply and programme records for one
            magnetocaloric product line — with an agent that can read all of it
            and change none of it without your say-so.
          </p>
        </div>

        <div className="grid gap-4 lg:grid-cols-[1fr_18rem]">
          <section className="bg-panel border-rule rounded-panel border">
            <div className="border-rule border-b px-4 py-3">
              <p className="eyebrow">Sign in as</p>
              <h2 className="mt-1 text-sm font-semibold">Pick a seat</h2>
            </div>
            <ul className="divide-rule divide-y">
              {SEATS.map((seat) => (
                <li key={seat.email}>
                  <button
                    type="button"
                    disabled={submitting}
                    onClick={() => void signIn(seat.email, DEMO_PASSWORD)}
                    className="hover:bg-sunken flex w-full items-baseline gap-3 px-4 py-2.5 text-left transition-colors disabled:opacity-50"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium">{seat.seat}</span>
                      <span className="ident text-ink-faint block text-[11px]">{seat.email}</span>
                    </span>
                    <span className="text-ink-faint shrink-0 text-[11px]">{seat.note}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <form
            className="bg-panel border-rule rounded-panel h-fit border p-4"
            onSubmit={(event) => {
              event.preventDefault();
              void signIn(email, password);
            }}
          >
            <p className="eyebrow">Or sign in directly</p>
            <label htmlFor="login-email" className="mt-3 block text-xs font-medium">
              Email
            </label>
            <input
              id="login-email"
              name="email"
              type="email"
              autoComplete="username"
              spellCheck={false}
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="border-rule rounded-chip focus:border-cold mt-1 w-full border bg-transparent px-2.5 py-1.5 text-xs outline-none transition-colors"
            />
            <label htmlFor="login-password" className="mt-3 block text-xs font-medium">
              Password
            </label>
            <input
              id="login-password"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="border-rule rounded-chip focus:border-cold mt-1 w-full border bg-transparent px-2.5 py-1.5 text-xs outline-none transition-colors"
            />
            <button
              type="submit"
              disabled={submitting}
              className="bg-cold text-cold-ink rounded-chip mt-4 w-full py-2 text-xs font-semibold transition-opacity disabled:opacity-50"
            >
              {submitting ? "Signing in…" : "Sign In"}
            </button>
            <p className="text-ink-faint mt-3 text-[11px] leading-4">
              Every seeded account uses the password{" "}
              <span className="ident text-ink-dim">{DEMO_PASSWORD}</span>. No real
              personal or customer data is in this dataset.
            </p>
          </form>
        </div>

        <div aria-live="polite">
          {error && (
            <p role="alert" className="text-breach bg-breach-wash rounded-panel mt-4 px-3 py-2 text-xs">
              {error}
            </p>
          )}
        </div>
      </div>
    </main>
  );
}

export function useAuth() {
  const value = React.useContext(Context);
  if (!value) throw new Error("AuthProvider is missing");
  return value;
}
