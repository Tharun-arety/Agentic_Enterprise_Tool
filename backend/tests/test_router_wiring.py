"""Route handlers call their services correctly.

There is no HTTP-level suite, so nothing exercised the seam between a FastAPI
handler and the service beneath it. Adding a `priority` filter between the
existing `status` and `limit` parameters silently re-bound the router's
positional `limit` of 50 onto it, and the change board screen started reporting
"Unknown priority 50" — while all 133 other tests passed.

These call the handlers directly with their declared defaults. That is not a
substitute for an HTTP suite, but it does cover argument binding, which is
where that break lived.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.ecm.router import list_requests
from app.domains.qms.router import list_ncrs


async def test_listing_change_requests_uses_its_defaults(session: AsyncSession) -> None:
    assert await list_requests(session) == []


async def test_listing_change_requests_accepts_a_priority(session: AsyncSession) -> None:
    assert await list_requests(session, priority="Urgent") == []


async def test_an_unknown_priority_is_refused_rather_than_ignored(
    session: AsyncSession,
) -> None:
    # The limit leaking into `priority` produced exactly this message, so the
    # error path is worth pinning too.
    with pytest.raises(Exception) as raised:
        await list_requests(session, priority="50")
    assert "Unknown priority" in str(raised.value)


async def test_listing_non_conformances_uses_its_defaults(session: AsyncSession) -> None:
    assert await list_ncrs(session) == []

