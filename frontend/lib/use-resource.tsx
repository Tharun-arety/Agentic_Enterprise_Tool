"use client";

import * as React from "react";
import { useAuth } from "@/components/AuthProvider";
import { ErrorNotice, LoadingView } from "@/components/ui/states";

/**
 * One backend read, with its loading and failure states.
 *
 * Every domain view needs the same three-state handling, and duplicating it
 * fourteen times is how the states drift apart. Pass `null` as the path to
 * hold a read back until a dependency resolves.
 */

export interface Resource<T> {
  data: T | null;
  error: string;
  refreshing: boolean;
  reload: () => void;
}

/**
 * Turn a thrown fetch failure into a sentence.
 *
 * `request` throws `"<status>: <raw body>"`, and the raw body is FastAPI's
 * JSON envelope. Printing that puts `{"detail":…,"request_id":…}` on screen,
 * which is the same failure the rest of this rebuild is about. Pull the detail
 * out, and say what to do about the statuses that have an obvious next step.
 */
function readable(reason: unknown): string {
  const text = String(reason instanceof Error ? reason.message : reason).replace(
    /^Error:\s*/,
    "",
  );
  const [, status = "", body = ""] = /^(\d{3}):\s*([\s\S]*)$/.exec(text) ?? [];
  if (!status) return text;

  let detail = body.trim();
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    if (typeof parsed.detail === "string") detail = parsed.detail;
  } catch {
    // Not JSON — the body is already the best message available.
  }

  switch (status) {
    case "401":
      return "Your session expired. Reload the page to sign in again.";
    case "403":
      return `${detail} Sign in as admin to see everything.`;
    case "404":
      return "That record is not in this dataset.";
    case "429":
      return "Too many requests in a row. Wait a moment, then reload this view.";
    default:
      return detail || `The request failed with status ${status}.`;
  }
}

export function useResource<T>(path: string | null): Resource<T> {
  const { request } = useAuth();
  const [data, setData] = React.useState<T | null>(null);
  const [error, setError] = React.useState("");
  const [refreshing, setRefreshing] = React.useState(false);
  const [nonce, setNonce] = React.useState(0);

  React.useEffect(() => {
    if (!path) return;
    let active = true;
    request<T>(path, nonce > 0 ? { cache: "reload" } : {})
      .then((value) => {
        if (!active) return;
        setData(value);
        setError("");
      })
      .catch((reason) => {
        if (active) setError(readable(reason));
      })
      .finally(() => {
        if (active) setRefreshing(false);
      });
    return () => {
      active = false;
    };
  }, [path, request, nonce]);

  // The spinner is turned on here rather than in the effect: it is a reaction
  // to the click, and starting it inside the effect body makes React re-render
  // twice for one user action.
  const reload = React.useCallback(() => {
    setRefreshing(true);
    setNonce((value) => value + 1);
  }, []);

  return { data, error, refreshing, reload };
}

/**
 * Narrows a resource to its loaded value. Children is a function because the
 * whole job here is to hand down a value that does not exist yet.
 */
export function Loaded<T>({
  resource,
  children,
  loading,
}: {
  resource: Resource<T>;
  children: (data: T) => React.ReactNode;
  loading?: React.ReactNode;
}) {
  if (resource.error) {
    return <ErrorNotice message={resource.error} onRetry={resource.reload} />;
  }
  if (resource.data === null) return <>{loading ?? <LoadingView />}</>;
  return <>{children(resource.data)}</>;
}
