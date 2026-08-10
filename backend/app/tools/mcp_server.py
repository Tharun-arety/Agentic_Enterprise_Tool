"""Private stdio MCP surface generated from the identical LangGraph registry."""
from __future__ import annotations
import asyncio,logging
from typing import Any
from mcp.server import MCPServer
from app.core.db import dispose_engine,get_session_factory
from app.core.principal import agent_principal
from app.tools import loader  # noqa: F401
from app.tools.registry import TOOL_REGISTRY,run_tool
logging.basicConfig(level=logging.INFO)
server=MCPServer(name="magnotherm-toolchain",version="0.7.0",instructions="Private stdio access to domain-scoped Magnotherm tools. Mutations create human approval proposals; they never apply directly.")

def _handler(tool_name:str):
    async def invoke(arguments:dict[str,Any])->dict[str,Any]:
        """Call with the argument object declared by the tool's JSON schema."""
        async with get_session_factory()() as session: return await run_tool(session,tool_name,arguments,actor=agent_principal("MCP Client"))
    invoke.__name__=tool_name
    return invoke

for _spec in TOOL_REGISTRY.values():
    server.add_tool(_handler(_spec.name),name=_spec.name,description=f"[{_spec.domain}; {_spec.sensitivity}] {_spec.description}",structured_output=True)

async def _main():
    try: await server.run_stdio_async()
    finally: await dispose_engine()
if __name__=="__main__": asyncio.run(_main())
