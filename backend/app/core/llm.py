"""Model client used by every LangGraph node.

Three operations, which is all the graph needs:

*   `classify`  — one call constrained by a JSON schema (router intent).
*   `call_tools` — one call that may request tool invocations.
*   `stream_text` — token-by-token final answer.

`StubModelClient` implements the same interface with fixture responses. It
exists so the graph wiring, the SSE framing, and the whole frontend can be
verified before an API key is available — the real model call is then the only
unverified link, rather than everything downstream of it.

Deliberately absent: `temperature`, `top_p`, and friends. Some newer models
reject non-default sampling parameters outright, and the defaults are correct
for this workload. Leaving them unset keeps the code portable across whatever
model id ends up in .env.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class TokenUsage:
    """Mutable per-run usage shared by concurrently executing domain agents."""

    input_tokens: int = 0
    output_tokens: int = 0


class ToolCall:
    """One tool invocation requested by the model."""

    __slots__ = ("id", "name", "arguments")

    def __init__(self, id: str, name: str, arguments: dict[str, Any]) -> None:
        self.id = id
        self.name = name
        self.arguments = arguments


class ToolTurn:
    """The model's reply to a tool-enabled call."""

    __slots__ = ("content", "tool_calls", "raw_message")

    def __init__(
        self,
        content: str | None,
        tool_calls: list[ToolCall],
        raw_message: dict[str, Any],
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls
        self.raw_message = raw_message


class ModelClient(ABC):
    @abstractmethod
    async def classify(
        self,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        schema_name: str,
        usage: TokenUsage | None = None,
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def call_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        usage: TokenUsage | None = None,
    ) -> ToolTurn: ...

    @abstractmethod
    def stream_text(
        self, messages: list[dict[str, Any]], usage: TokenUsage | None = None
    ) -> AsyncIterator[str]: ...


class OpenAIModelClient(ModelClient):
    def __init__(self) -> None:
        from openai import AsyncOpenAI

        settings = get_settings()
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_model
        self._synthesis_model = settings.synthesis_model
        self._fallback = StubModelClient()

    def _log_usage(
        self, node: str, model: str, response: Any, counter: TokenUsage | None = None
    ) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        if counter is not None:
            counter.input_tokens += int(usage.prompt_tokens or 0)
            counter.output_tokens += int(usage.completion_tokens or 0)
        logger.info(
            "tokens node=%s model=%s prompt=%s completion=%s total=%s",
            node,
            model,
            usage.prompt_tokens,
            usage.completion_tokens,
            usage.total_tokens,
        )

    async def classify(
        self,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        schema_name: str,
        usage: TokenUsage | None = None,
    ) -> dict[str, Any]:
        try:
            settings = get_settings()
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                reasoning_effort=settings.openai_reasoning_effort,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "strict": True,
                        "schema": schema,
                    },
                },
                max_completion_tokens=min(768, settings.agent_token_budget),
                timeout=settings.model_timeout_seconds,
            )
        except Exception:  # noqa: BLE001 - live provider degradation is recoverable
            logger.exception("OpenAI router call failed; using deterministic router fallback")
            return await self._fallback.classify(messages, schema, schema_name, usage)
        self._log_usage("router", self._model, response, usage)
        content = response.choices[0].message.content or "{}"
        return json.loads(content)

    async def call_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        usage: TokenUsage | None = None,
    ) -> ToolTurn:
        settings = get_settings()
        reserved = min(3840, settings.agent_token_budget)
        calls = max(1, 3 * settings.agent_max_tool_iterations)
        completion_limit = max(128, (settings.agent_token_budget - reserved) // calls)
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                tools=tools,
                reasoning_effort=settings.openai_reasoning_effort,
                max_completion_tokens=completion_limit,
                timeout=settings.model_timeout_seconds,
            )
        except Exception:  # noqa: BLE001 - live provider degradation is recoverable
            logger.exception("OpenAI tool call failed; using deterministic tool fallback")
            return await self._fallback.call_tools(messages, tools, usage)
        self._log_usage("spoke", self._model, response, usage)
        message = response.choices[0].message

        calls: list[ToolCall] = []
        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                logger.warning(
                    "Model emitted unparseable arguments for %s: %r",
                    call.function.name,
                    call.function.arguments,
                )
                arguments = {}
            calls.append(ToolCall(call.id, call.function.name, arguments))

        # Rebuilt explicitly rather than via model_dump(): the API rejects the
        # extra fields the SDK attaches to a response message.
        raw: dict[str, Any] = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            raw["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in message.tool_calls
            ]
        return ToolTurn(message.content, calls, raw)

    async def stream_text(  # type: ignore[override]
        self,
        messages: list[dict[str, Any]],
        usage: TokenUsage | None = None,
    ) -> AsyncIterator[str]:
        emitted = False
        settings = get_settings()
        try:
            stream = await self._client.chat.completions.create(
                model=self._synthesis_model,
                messages=messages,
                stream=True,
                stream_options={"include_usage": True},
                reasoning_effort=settings.openai_reasoning_effort,
                max_completion_tokens=min(
                    settings.openai_synthesis_max_tokens,
                    settings.agent_token_budget,
                ),
                timeout=settings.model_timeout_seconds,
            )
            async for chunk in stream:
                if chunk.usage is not None:
                    self._log_usage("synthesizer", self._synthesis_model, chunk, usage)
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    emitted = True
                    yield delta
        except Exception:
            logger.exception("OpenAI synthesis failed")
            if emitted:
                raise
            async for delta in self._fallback.stream_text(messages, usage):
                yield delta


class StubModelClient(ModelClient):
    """Deterministic fixture client for key-free verification.

    Routes on keywords, requests exactly the tool its intent implies, and
    renders a short answer from whatever the tools returned. It exercises every
    edge of the graph and every SSE frame type without touching the network.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    @staticmethod
    def _last_user_text(messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user" and isinstance(message.get("content"), str):
                return message["content"]
        return ""

    async def classify(
        self,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        schema_name: str,
        usage: TokenUsage | None = None,
    ) -> dict[str, Any]:
        self.calls.append("classify")
        text = self._last_user_text(messages).lower()
        if any(word in text for word in ("bom", "made of", "component", "assembly")):
            return {"intent": "pdm", "rationale": "stub: BOM keywords"}
        if any(word in text for word in ("test", "metric", "serial", "performance")):
            return {"intent": "qms", "rationale": "stub: QMS keywords"}
        if any(word in text for word in ("why", "eco", "change", "failure")):
            return {"intent": "knowledge", "rationale": "stub: knowledge keywords"}
        return {"intent": "general", "rationale": "stub: no keyword match"}

    async def call_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        usage: TokenUsage | None = None,
    ) -> ToolTurn:
        self.calls.append("call_tools")
        # A tool result already in the transcript means this is the second pass;
        # stop requesting tools so the loop terminates exactly as it would live.
        if any(message.get("role") == "tool" for message in messages):
            return ToolTurn("Stub summary of tool output.", [], {
                "role": "assistant",
                "content": "Stub summary of tool output.",
            })

        tool_name = tools[0]["function"]["name"]
        text = self._last_user_text(messages)
        arguments = self._arguments_for(tool_name, text)
        call = ToolCall("stub-call-1", tool_name, arguments)
        return ToolTurn(
            None,
            [call],
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(arguments),
                        },
                    }
                ],
            },
        )

    @staticmethod
    def _arguments_for(tool_name: str, text: str) -> dict[str, Any]:
        if tool_name == "get_bom_structure":
            match = re.search(r"\b([A-Z]{3}-[A-Z]{3}-\d{3,4})\b", text.upper())
            return {"part_number": match.group(1) if match else "ECL-SYS-1000"}
        if tool_name == "query_qms_test_metrics":
            match = re.search(r"\b(ECL-M-\d{3})\b", text.upper())
            return {"serial_number": match.group(1) if match else "ECL-M-104"}
        return {"query": text or "engineering knowledge", "limit": 5}

    async def stream_text(  # type: ignore[override]
        self,
        messages: list[dict[str, Any]],
        usage: TokenUsage | None = None,
    ) -> AsyncIterator[str]:
        self.calls.append("stream_text")
        for word in "This is a stubbed synthesis of the retrieved data.".split():
            yield word + " "


_client: ModelClient | None = None


def get_model_client() -> ModelClient:
    """Real client when a key is configured, stub otherwise."""
    global _client
    if _client is None:
        settings = get_settings()
        if settings.has_openai_key:
            _client = OpenAIModelClient()
            logger.info(
                "Model client: OpenAI (retrieval=%s, synthesis=%s).",
                settings.openai_model,
                settings.synthesis_model,
            )
        else:
            _client = StubModelClient()
            logger.warning(
                "Model client: STUB. OPENAI_API_KEY is not set, so /api/chat "
                "returns canned responses. The graph, tools and streaming are "
                "real; only the language model is not."
            )
    return _client


def set_model_client(client: ModelClient | None) -> None:
    """Override the client (used by the verification harness)."""
    global _client
    _client = client
