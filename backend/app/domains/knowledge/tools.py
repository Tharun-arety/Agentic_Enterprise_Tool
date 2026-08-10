"""Knowledge tools, registered for both the agent graph and the MCP server."""

from __future__ import annotations

from app.domains.knowledge.service import search_engineering_knowledge
from app.tools.registry import ToolSpec, register

register(
    ToolSpec(
        name="search_engineering_knowledge",
        domain="knowledge",
        description=(
            "Semantic search over unstructured engineering knowledge: "
            "engineering change orders (ECOs), test-failure write-ups, and spec "
            "excerpts. Use this for questions about *why* a design is the way it "
            "is, what changed and when, or past failures — anything not answered "
            "by structured BOM or test data."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language description of what to find.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of documents to return (1-10).",
                    "minimum": 1,
                    "maximum": 10,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=search_engineering_knowledge,
    )
)
