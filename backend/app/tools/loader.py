"""Imports every domain's tool module so `TOOL_REGISTRY` is fully populated.

Registration is an import side effect, so a tool that nobody imports simply does
not exist — the agent would route to a spoke whose toolset is empty and answer
from nothing. One import site makes that impossible to forget.

This lives in its own module rather than in `app/tools/__init__.py` because the
domains import `app.tools.registry`; putting domain imports in the package
`__init__` would make that a cycle.
"""

from app.domains.ecm import tools as ecm_tools  # noqa: F401
from app.domains.knowledge import tools as knowledge_tools  # noqa: F401
from app.domains.pdm import tools as pdm_tools  # noqa: F401
from app.domains.qms import tools as qms_tools  # noqa: F401
from app.domains.procurement import tools as procurement_tools  # noqa: F401
from app.domains import enterprise_tools  # noqa: F401

__all__ = ["ecm_tools", "knowledge_tools", "pdm_tools", "qms_tools"]
