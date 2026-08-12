"""Every read tool must return something the rest of the system can carry.

A tool result travels three places: into the model's context as JSON, into
`tool_invocations.result` as JSONB, and out to the browser on an SSE frame. All
three need plain JSON, and nothing checked it.

`list_change_requests` returned a list of Pydantic models. The serialisation
step only handled a payload that *was* a model, so a list of them passed
straight through: the model saw `repr()` output, and persisting the invocation
raised "Object of type ChangeRequestOut is not JSON serializable" — which the
caller reported as the tool simply not being called. A whole class of question
("which change requests are urgent") had no working answer.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.tools.loader  # noqa: F401 - registration is an import side effect
from app.core.principal import SYSTEM_PRINCIPAL
from app.tools.registry import TOOL_REGISTRY, run_tool

#: Read tools taking no required arguments — callable against an empty database
#: and therefore checkable wholesale.
NO_ARGUMENT_READ_TOOLS = sorted(
    name
    for name, spec in TOOL_REGISTRY.items()
    if not spec.mutates and not spec.parameters.get("required")
)


def test_there_are_argument_free_read_tools_to_check() -> None:
    """Guard the guard: a filter that matches nothing would pass silently."""
    assert len(NO_ARGUMENT_READ_TOOLS) >= 5


@pytest.mark.parametrize("tool_name", NO_ARGUMENT_READ_TOOLS)
async def test_read_tool_results_are_json_serialisable(
    session: AsyncSession, tool_name: str
) -> None:
    result = await run_tool(session, tool_name, {}, actor=SYSTEM_PRINCIPAL)

    assert isinstance(result, dict), f"{tool_name} must return a mapping"
    # The real assertion. `json.dumps` with no `default=` is exactly what the
    # JSONB column and the SSE encoder do, so anything it refuses is broken.
    json.dumps(result)


async def test_a_tool_returning_a_list_of_models_is_flattened(
    session: AsyncSession,
) -> None:
    """The specific shape that broke: a list of Pydantic models."""
    result = await run_tool(
        session, "list_change_requests", {}, actor=SYSTEM_PRINCIPAL
    )
    rows = result["requests"]
    assert isinstance(rows, list)
    assert all(isinstance(row, dict) for row in rows), (
        "rows must be reduced to dicts, not left as model instances"
    )
    json.dumps(result)


async def test_an_over_filtered_list_explains_itself(session: AsyncSession) -> None:
    """An empty result caused by filters must say so.

    A model asked for urgent change requests once added `status="Under review"`
    unprompted; the only urgent request was `Converted`, the pair matched
    nothing, and the answer became a confident "none are marked urgent".
    """
    result = await run_tool(
        session,
        "list_change_requests",
        {"status": "Under review", "priority": "Urgent"},
        actor=SYSTEM_PRINCIPAL,
    )
    assert result["count"] == 0
    assert "hint" in result, "an empty filtered result must explain the filters"
    json.dumps(result)
