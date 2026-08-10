"""The tool registry: one declaration, several consumers.

*   `app.tools.mcp_server` registers these on an MCP server so any MCP client
    can call them over stdio.
*   `app.agents.graph` calls them **in-process**. Round-tripping through a
    subprocess for a call that lives in the same service would add latency and
    a failure mode for no benefit.

Each `ToolSpec` carries a hand-written JSON schema because OpenAI function
calling needs one; the MCP layer derives its own from the typed signatures.

Domains register into `TOOL_REGISTRY` through `register()`. The dependency runs
domain -> registry, never the reverse, so a domain package does not need to know
it is exposed as a tool.
"""

from __future__ import annotations

import logging
import asyncio
import uuid
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.principal import SYSTEM_PRINCIPAL, ActorType, Principal

if TYPE_CHECKING:
    from app.domains.identity.models import Role

logger = logging.getLogger(__name__)

ToolHandler = Callable[..., Awaitable[Any]]


class ToolError(Exception):
    """Raised when a tool cannot answer — e.g. unknown part or serial.

    Surfaced back to the model as the tool result rather than raised through the
    graph, so the agent can recover by rephrasing or telling the user.
    """


class ToolSpec:
    """One tool: its schema, its read/preview handler, and its optional applier.

    For a read tool, `handler` answers the question and that is all.

    For a mutating tool, `handler` is a **preview**: it computes what would
    change and returns a `ProposalPreview` without writing, and `applier` is the
    function that actually performs the write once a human approves. Splitting
    them is what makes the approval meaningful — the reviewer is shown a diff
    produced by the same code path that will later execute it.
    """

    __slots__ = (
        "name",
        "description",
        "parameters",
        "handler",
        "domain",
        "applier",
        "required_role",
        "timeout_seconds",
        "result_schema",
        "sensitivity",
    )

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: ToolHandler,
        domain: str,
        applier: ToolHandler | None = None,
        required_role: "Role | None" = None,
        timeout_seconds: float = 15.0,
        result_schema: type | None = None,
        sensitivity: str = "internal",
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.domain = domain
        self.applier = applier
        self.required_role = required_role
        self.timeout_seconds = timeout_seconds
        self.result_schema = result_schema
        self.sensitivity = sensitivity
        if (applier is None) != (required_role is None):
            raise ValueError(
                f"Tool {name!r}: `applier` and `required_role` must be given "
                "together. A mutation with no named approving role could be "
                "approved by anyone, which defeats the point of the queue."
            )

    @property
    def mutates(self) -> bool:
        """True when calling this tool changes data rather than reading it."""
        return self.applier is not None

    def as_openai_tool(self) -> dict[str, Any]:
        """The shape OpenAI function calling expects in `tools=[...]`."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


TOOL_REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> ToolSpec:
    """Add a tool to the registry, rejecting duplicate names.

    A silent overwrite would mean two domains claiming one name and the loser
    simply never being called — the kind of bug that only shows up as an agent
    giving a confidently wrong answer.
    """
    if spec.name in TOOL_REGISTRY:
        raise ValueError(
            f"Tool {spec.name!r} is already registered by the "
            f"{TOOL_REGISTRY[spec.name].domain!r} domain."
        )
    TOOL_REGISTRY[spec.name] = spec
    return spec


def tools_for_domain(domain: str) -> list[ToolSpec]:
    """Every tool a given domain's agent is allowed to see."""
    return [spec for spec in TOOL_REGISTRY.values() if spec.domain == domain]


async def run_tool(
    session: AsyncSession,
    name: str,
    arguments: dict[str, Any],
    *,
    actor: Principal = SYSTEM_PRINCIPAL,
    correlation_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Execute a registered tool and return its result as a plain dict.

    A read tool runs and returns its data. A **mutating** tool does not: its
    handler runs as a preview, and the result is filed as an `AgentProposal`
    awaiting human approval. The agent gets back the proposal id and the diff,
    which is what it should tell the user it has prepared — not that the change
    is done.

    Tool-level failures (unknown part, empty table) come back as
    `{"error": ...}` rather than raising, so the model can read the message and
    correct itself instead of the whole request collapsing.
    """
    spec = TOOL_REGISTRY.get(name)
    if spec is None:
        return {"error": f"Unknown tool {name!r}."}

    try:
        result = await asyncio.wait_for(
            spec.handler(session, **arguments), timeout=spec.timeout_seconds
        )
        if spec.result_schema is not None:
            result = spec.result_schema.model_validate(result)
    except TimeoutError:
        logger.warning("Tool %s timed out after %.1fs", name, spec.timeout_seconds)
        return {"error": f"{name} timed out after {spec.timeout_seconds:.1f}s."}
    except ToolError as exc:
        logger.info("Tool %s declined: %s", name, exc)
        return {"error": str(exc)}
    except TypeError as exc:
        logger.warning("Tool %s called with bad arguments %r: %s", name, arguments, exc)
        return {"error": f"Invalid arguments for {name}: {exc}"}

    payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
    if not isinstance(payload, dict):
        payload = {"result": payload}
    if not spec.mutates:
        return payload

    # Imported lazily: app.core.proposals imports the registry back when it
    # resolves a proposal's applier.
    from app.core.proposals import file_proposal

    if actor.actor_type is ActorType.SYSTEM:
        # Nothing filed a proposal on behalf of a named actor, which means this
        # is a direct call bypassing the agent path. Refuse rather than write.
        return {
            "error": (
                f"{name!r} changes data and must be called by a named agent so "
                "the resulting proposal has an author."
            )
        }

    assert spec.required_role is not None  # guaranteed by ToolSpec.__init__
    proposal = await file_proposal(
        session,
        actor=actor,
        tool_name=name,
        arguments=arguments,
        summary=payload.get("summary", f"Proposed {name}"),
        preview=payload,
        required_role=spec.required_role,
        correlation_id=correlation_id,
    )
    return {
        "status": "awaiting_approval",
        "proposal_id": str(proposal.id),
        "required_role": proposal.required_role,
        "summary": proposal.summary,
        "preview": payload,
    }
