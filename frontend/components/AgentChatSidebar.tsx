"use client";

import * as React from "react";
import { Bot, CornerDownLeft, Loader2, User, Wrench } from "lucide-react";

import { Button } from "@/components/ui/button";
import { streamAgent } from "@/lib/agent-stream";
import { cn } from "@/lib/utils";
import type {
  AgentStateFrame,
  BomResponse,
  ChatTurn,
  QmsResponse,
  ToolResultFrame,
} from "@/lib/types";

const SUGGESTIONS = [
  "What is the ECLIPSE 1kW chiller made of?",
  "Trace lot MAG-L-2312 to affected units and quality findings",
  "Show ECR-26-002 impact, CCB status, and cost exposure",
];

const STATUS_LABEL: Record<AgentStateFrame["status"], string> = {
  thinking: "Thinking",
  delegating: "Delegating to",
  calling_tool: "Calling",
  done: "Done",
};

function statusLine(frame: AgentStateFrame): string {
  if (frame.status === "delegating") return `Delegating to ${frame.agent}…`;
  if (frame.status === "calling_tool") return `${frame.agent}: ${frame.detail}…`;
  if (frame.status === "thinking") return `${frame.agent} is thinking…`;
  return `${STATUS_LABEL[frame.status]}`;
}

export function AgentChatSidebar({
  onBom,
  onQms,
}: {
  onBom?: (bom: BomResponse) => void;
  onQms?: (qms: QmsResponse) => void;
}) {
  const [turns, setTurns] = React.useState<ChatTurn[]>([]);
  const [draft, setDraft] = React.useState("");
  const [streaming, setStreaming] = React.useState("");
  const [agentState, setAgentState] = React.useState<AgentStateFrame | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const scrollRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [turns, streaming, agentState]);

  /**
   * Structured tool payloads are routed to the dashboard by tool name. The
   * chat pane never parses the model's prose to find data — the data arrives
   * on its own frame type.
   */
  const applyToolResult = React.useCallback(
    (frame: ToolResultFrame) => {
      if (frame.tool === "get_bom_structure") {
        onBom?.(frame.payload as BomResponse);
      } else if (frame.tool === "query_qms_test_metrics") {
        onQms?.(frame.payload as QmsResponse);
      }
    },
    [onBom, onQms],
  );

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
              applyToolResult(frame.data);
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
            : "Could not reach the agent backend.",
        );
      } finally {
        if (assembled.trim()) {
          setTurns((prev) => [
            ...prev,
            { role: "assistant", content: assembled.trim() },
          ]);
        }
        setStreaming("");
        setAgentState(null);
        setBusy(false);
      }
    },
    [applyToolResult, busy, turns],
  );

  return (
    <aside className="bg-surface border-border flex h-full w-full flex-col border-l">
      <header className="border-border flex items-center gap-2 border-b px-4 py-3">
        <span className="bg-accent/10 text-accent rounded-md p-1.5">
          <Bot className="size-4" />
        </span>
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">Engineering Agent</h2>
          <p className="text-muted-foreground truncate text-[11px]">
            10 domain agents · governed tools
          </p>
        </div>
      </header>

      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {turns.length === 0 && !streaming && (
          <div className="space-y-3">
            <p className="text-muted-foreground text-xs leading-relaxed">
              Ask about product structure, measured performance, or design
              history. The router picks a specialist agent and its tool output
              renders in the dashboard.
            </p>
            <div className="space-y-1.5">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => void send(suggestion)}
                  className="border-border hover:border-accent/50 hover:bg-surface-muted w-full rounded-lg border px-2.5 py-2 text-left text-xs transition"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((turn, index) => (
          <div key={index} className="flex gap-2.5">
            <span
              className={cn(
                "mt-0.5 shrink-0 rounded-md p-1",
                turn.role === "user"
                  ? "bg-surface-muted text-muted-foreground"
                  : "bg-accent/10 text-accent",
              )}
            >
              {turn.role === "user" ? (
                <User className="size-3.5" />
              ) : (
                <Bot className="size-3.5" />
              )}
            </span>
            <p className="min-w-0 flex-1 text-xs leading-relaxed whitespace-pre-wrap">
              {turn.content}
            </p>
          </div>
        ))}

        {streaming && (
          <div className="flex gap-2.5">
            <span className="bg-accent/10 text-accent mt-0.5 shrink-0 rounded-md p-1">
              <Bot className="size-3.5" />
            </span>
            <p className="min-w-0 flex-1 text-xs leading-relaxed whitespace-pre-wrap">
              {streaming}
              <span className="bg-accent ml-0.5 inline-block h-3 w-1 animate-pulse align-middle" />
            </p>
          </div>
        )}

        {agentState && (
          <div
            data-testid="agent-state"
            className="text-accent bg-accent/5 border-accent/20 flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-[11px] font-medium"
          >
            {agentState.status === "calling_tool" ? (
              <Wrench className="size-3 shrink-0" />
            ) : (
              <Loader2 className="size-3 shrink-0 animate-spin" />
            )}
            <span className="truncate">{statusLine(agentState)}</span>
          </div>
        )}

        {error && (
          <p className="text-warning border-warning/30 bg-warning/5 rounded-lg border px-2.5 py-1.5 text-[11px]">
            {error}
          </p>
        )}
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void send(draft);
        }}
        className="border-border border-t p-3"
      >
        <div className="border-border focus-within:border-accent/60 flex items-end gap-2 rounded-lg border px-2.5 py-2 transition">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send(draft);
              }
            }}
            rows={2}
            disabled={busy}
            placeholder="Ask about a part, a serial, or an ECO…"
            className="max-h-32 min-h-[2.5rem] flex-1 resize-none bg-transparent text-xs outline-none disabled:opacity-50"
          />
          <Button
            type="submit"
            disabled={busy || !draft.trim()}
            className="shrink-0 px-2 py-1.5"
            aria-label="Send message"
          >
            {busy ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <CornerDownLeft className="size-3.5" />
            )}
          </Button>
        </div>
      </form>
    </aside>
  );
}
