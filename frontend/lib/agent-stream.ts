/**
 * SSE client for POST /api/chat.
 *
 * The browser's built-in `EventSource` only issues GET requests, and this
 * endpoint needs a JSON body, so the stream is read off `fetch` and the SSE
 * frames are parsed by hand.
 */

import { API_BASE_URL } from "./api";
import type { AgentEvent, ChatTurn } from "./types";
import { getAccessToken } from "./auth-store";

const KNOWN_EVENTS = new Set([
  "agent_state",
  "token",
  "tool_result",
  "final",
  "error",
]);

function parseFrame(raw: string): AgentEvent | null {
  let eventName = "message";
  const dataLines: string[] = [];

  for (const line of raw.split("\n")) {
    // Comment / keep-alive ping. sse-starlette emits these to hold the
    // connection open through proxies; they carry no payload.
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }

  if (dataLines.length === 0 || !KNOWN_EVENTS.has(eventName)) return null;

  try {
    return {
      event: eventName,
      data: JSON.parse(dataLines.join("\n")),
    } as AgentEvent;
  } catch {
    console.warn("Unparseable SSE payload:", dataLines);
    return null;
  }
}

export async function* streamAgent(
  message: string,
  history: ChatTurn[],
  signal?: AbortSignal,
): AsyncGenerator<AgentEvent> {
  const response = await fetch(`${API_BASE_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(getAccessToken()?{Authorization:`Bearer ${getAccessToken()}`}:{}) },
    credentials: "include",
    body: JSON.stringify({ message, history }),
    signal,
  });

  if (!response.ok || !response.body) {
    throw new Error(
      `Agent request failed: ${response.status} ${response.statusText}`,
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      // Normalise CRLF so a single split rule works regardless of how the
      // server terminates its lines.
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const frame = parseFrame(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        if (frame) yield frame;
        boundary = buffer.indexOf("\n\n");
      }
    }

    // A final frame with no trailing blank line still deserves delivery.
    const tail = parseFrame(buffer);
    if (tail) yield tail;
  } finally {
    reader.releaseLock();
  }
}
