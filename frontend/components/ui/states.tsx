import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Empty and failed states.
 *
 * An empty screen says what would put something on it; an error says what to
 * do next. Neither apologises — the interface reports, it does not emote.
 */

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="border-rule px-6 py-12 text-center">
      <p className="text-sm font-semibold">{title}</p>
      {body && (
        <p className="text-ink-dim mx-auto mt-1.5 max-w-md text-pretty text-xs leading-5">
          {body}
        </p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorNotice({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="border-breach/40 bg-breach-wash rounded-panel border p-4"
    >
      <p className="text-breach text-sm font-semibold">This view could not load</p>
      <p className="text-ink-dim mt-1 break-words text-xs leading-5">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="border-rule-strong rounded-chip hover:bg-sunken mt-3 border px-2.5 py-1 text-xs font-semibold transition-colors"
        >
          Try Again
        </button>
      )}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("bg-sunken rounded-panel animate-pulse", className)}
      aria-hidden="true"
    />
  );
}

/** Standard loading body for a domain view. */
export function LoadingView() {
  return (
    <div className="space-y-4" role="status" aria-live="polite">
      <span className="sr-only">Loading…</span>
      <Skeleton className="h-24" />
      <Skeleton className="h-64" />
    </div>
  );
}
