"use client";

import * as React from "react";

import { streamAgent } from "@/lib/agent-stream";
import type { AgentStateFrame, ChatTurn, ToolResultFrame } from "@/lib/types";

/**
 * The agent conversation, held above the router.
 *
 * It used to live inside `AgentChatSidebar`, which `Shell` renders and every
 * route mounts its own copy of — so moving from product data to a unit's test
 * record unmounted the panel and threw the conversation away, along with any
 * answer still streaming. Verifying an answer against another department is
 * the normal way to use this thing; losing the question in the act of checking
 * it was the defect.
 *
 * Mounted inside `AuthProvider`, which swaps `children` for the sign-in screen
 * when there is no session, so signing out ends the conversation rather than
 * handing it to the next seat.
 */

interface AgentChatValue {
  turns: ChatTurn[];
  draft: string;
  setDraft: (value: string) => void;
  streaming: string;
  agentState: AgentStateFrame | null;
  busy: boolean;
  error: string | null;
  /** The last structured tool payload; prose is never parsed for data. */
  lastToolResult: ToolResultFrame | null;
  send: (message: string) => Promise<void>;
  reset: () => void;
}

const Context = React.createContext<AgentChatValue | null>(null);

export function AgentChatProvider({ children }: { children: React.ReactNode }) {
  const [turns, setTurns] = React.useState<ChatTurn[]>([]);
  const [draft, setDraft] = React.useState("");
  const [streaming, setStreaming] = React.useState("");
  const [agentState, setAgentState] = React.useState<AgentStateFrame | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [lastToolResult, setLastToolResult] = React.useState<ToolResultFrame | null>(null);

  const send = React.useCallback(
    async (message: string) => {
      const text = message.trim();
      if (!text || busy) return;

      setBusy(true);
      setError(null);
      setDraft("");
      const history = turns.slice(-10);
      setTurns((prev) => [...prev, { role: "user", content: text }]);

      let assembled = "";
      try {
        for await (const frame of streamAgent(text, history)) {
          switch (frame.event) {
            case "agent_state":
              setAgentState(frame.data);
              break;
            case "tool_result":
              setLastToolResult(frame.data);
              break;
            case "token":
              assembled += frame.data.text;
              setStreaming(assembled);
              break;
            case "final":
              // The final frame is authoritative; the streamed text was a
              // preview of it.
              assembled = frame.data.text || assembled;
              break;
            case "error":
              setError(frame.data.message);
              break;
          }
        }
      } catch (cause) {
        setError(
          cause instanceof Error
            ? cause.message
            : "The agent backend did not respond. Reload the view and ask again.",
        );
      } finally {
        if (assembled.trim()) {
          setTurns((prev) => [...prev, { role: "assistant", content: assembled.trim() }]);
        }
        setStreaming("");
        setAgentState(null);
        setBusy(false);
      }
    },
    [busy, turns],
  );

  /**
   * Clearing is deliberate, never incidental: the reload control in the title
   * block and the panel's own button are the only two ways to reach it.
   */
  const reset = React.useCallback(() => {
    setTurns([]);
    setDraft("");
    setStreaming("");
    setAgentState(null);
    setError(null);
    setLastToolResult(null);
  }, []);

  const value = React.useMemo(
    () => ({
      turns,
      draft,
      setDraft,
      streaming,
      agentState,
      busy,
      error,
      lastToolResult,
      send,
      reset,
    }),
    [turns, draft, streaming, agentState, busy, error, lastToolResult, send, reset],
  );

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useAgentChat() {
  const value = React.useContext(Context);
  if (!value) throw new Error("AgentChatProvider is missing");
  return value;
}
