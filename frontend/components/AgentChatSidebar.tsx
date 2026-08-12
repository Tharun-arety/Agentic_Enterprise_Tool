"use client";

import * as React from "react";
import { CornerDownLeft, Loader2, MessageSquarePlus, Wrench, X } from "lucide-react";

import { useAgentChat } from "@/components/AgentChatProvider";
import { cn } from "@/lib/utils";
import type { AgentStateFrame } from "@/lib/types";

const SUGGESTIONS = [
  "What is the ECLIPSE 1 kW chiller made of?",
  "Trace lot MAG-L-2312 to affected units and quality findings",
  "Show ECR-26-002 impact, CCB status and cost exposure",
];

/** How close to the bottom still counts as following the answer, in pixels. */
const PINNED_SLACK = 48;

function statusLine(frame: AgentStateFrame): string {
  if (frame.status === "delegating") return `Routing to ${frame.agent}…`;
  if (frame.status === "calling_tool") return `${frame.agent} · ${frame.detail}…`;
  if (frame.status === "thinking") return `${frame.agent} is thinking…`;
  return "Done";
}

/**
 * The agent panel. It renders the conversation; it does not own it — the state
 * lives in `AgentChatProvider`, above the router, so changing section does not
 * discard the exchange you changed section to verify.
 */
export function AgentChatSidebar({ onClose }: { onClose?: () => void }) {
  const { turns, draft, setDraft, streaming, agentState, busy, error, send, reset } =
    useAgentChat();
  const scrollRef = React.useRef<HTMLDivElement>(null);

  /**
   * Follow the answer only while the reader is already at the bottom. Scrolling
   * up to re-read an earlier paragraph used to be undone by the next token.
   */
  const pinned = React.useRef(true);

  const trackPinned = React.useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < PINNED_SLACK;
  }, []);

  React.useEffect(() => {
    const el = scrollRef.current;
    if (!el || !pinned.current) return;
    el.scrollTo({ top: el.scrollHeight });
  }, [turns, streaming, agentState]);

  /** Asking is an act of attention: re-pin to the bottom for the reply. */
  const ask = React.useCallback(
    (message: string) => {
      pinned.current = true;
      void send(message);
    },
    [send],
  );

  const hasConversation = turns.length > 0 || Boolean(streaming) || Boolean(error);

  return (
    <aside className="bg-rail border-rule flex h-full min-h-0 w-full flex-col overflow-hidden border-l">
      <header className="border-rule flex shrink-0 items-center gap-2 border-b px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="eyebrow">Governed tools</p>
          <h2 className="mt-1 truncate text-sm font-semibold tracking-tight">
            Engineering agent
          </h2>
        </div>
        {hasConversation && (
          <button
            type="button"
            onClick={() => {
              pinned.current = true;
              reset();
            }}
            aria-label="Clear the conversation"
            title="New conversation"
            className="border-rule rounded-chip hover:bg-sunken border p-1.5 transition-colors"
          >
            <MessageSquarePlus className="size-3.5" aria-hidden="true" />
          </button>
        )}
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close the agent"
            className="border-rule rounded-chip hover:bg-sunken border p-1.5 transition-colors"
          >
            <X className="size-3.5" aria-hidden="true" />
          </button>
        )}
      </header>

      <div
        ref={scrollRef}
        onScroll={trackPinned}
        data-testid="agent-transcript"
        className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain px-4 py-4"
      >
        {turns.length === 0 && !streaming && (
          <div className="space-y-3">
            <p className="text-ink-dim text-pretty text-xs leading-5">
              Ask about product structure, measured performance or design history.
              A router picks the specialist agent; anything that would change a
              record is filed for approval instead of applied. The thread follows
              you between sections and clears only when you reload the view or
              start a new conversation.
            </p>
            <div className="space-y-1.5">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => ask(suggestion)}
                  className="border-rule rounded-chip hover:border-cold hover:bg-sunken w-full border px-2.5 py-2 text-left text-xs leading-5 transition-colors"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((turn, index) => (
          <div key={index} className="min-w-0">
            <p className="eyebrow mb-1">{turn.role === "user" ? "You" : "Agent"}</p>
            <p
              className={cn(
                "min-w-0 whitespace-pre-wrap break-words text-xs leading-5",
                turn.role === "user" && "text-ink-dim",
              )}
            >
              {turn.content}
            </p>
          </div>
        ))}

        {streaming && (
          <div className="min-w-0">
            <p className="eyebrow mb-1">Agent</p>
            <p className="min-w-0 whitespace-pre-wrap break-words text-xs leading-5">
              {streaming}
              <span className="bg-cold ml-0.5 inline-block h-3 w-1 animate-pulse align-middle" />
            </p>
          </div>
        )}

        <div aria-live="polite">
          {agentState && (
            <div
              data-testid="agent-state"
              className="text-cold bg-cold-wash rounded-chip flex items-center gap-2 px-2.5 py-1.5 text-[11px] font-medium"
            >
              {agentState.status === "calling_tool" ? (
                <Wrench className="size-3 shrink-0" aria-hidden="true" />
              ) : (
                <Loader2 className="size-3 shrink-0 animate-spin" aria-hidden="true" />
              )}
              <span className="truncate">{statusLine(agentState)}</span>
            </div>
          )}
          {error && (
            <p role="alert" className="text-breach bg-breach-wash rounded-chip px-2.5 py-1.5 text-[11px] leading-4">
              {error}
            </p>
          )}
        </div>
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          ask(draft);
        }}
        className="border-rule shrink-0 border-t p-3"
      >
        <label htmlFor="agent-prompt" className="sr-only">
          Ask the engineering agent
        </label>
        <div className="border-rule rounded-panel focus-within:border-cold flex items-end gap-2 border px-2.5 py-2 transition-colors">
          <textarea
            id="agent-prompt"
            name="prompt"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                ask(draft);
              }
            }}
            rows={2}
            autoComplete="off"
            placeholder={
              busy
                ? "Answering — send your next question once this finishes…"
                : turns.length
                  ? "Ask a follow-up…"
                  : "Ask about a part, a serial or an ECO…"
            }
            className="max-h-32 min-h-[2.5rem] min-w-0 flex-1 resize-none bg-transparent text-xs leading-5 outline-none"
          />
          <button
            type="submit"
            disabled={busy || !draft.trim()}
            aria-label="Send Message"
            className="bg-cold text-cold-ink rounded-chip shrink-0 p-1.5 transition-opacity disabled:opacity-40"
          >
            {busy ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <CornerDownLeft className="size-3.5" aria-hidden="true" />
            )}
          </button>
        </div>
      </form>
    </aside>
  );
}
