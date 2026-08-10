"""FastAPI dependencies: the database session and the current principal."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.principal import ActorType, Principal
from app.core.db import get_session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.security import TokenError, decode_access_token
from app.domains.identity.models import AccessTokenRevocation, Role, User

# auto_error=False so a missing header reaches our own handler and produces a
# message that says which endpoint needed a token, rather than a bare 403.
_bearer = HTTPBearer(auto_error=False, description="JWT from POST /api/auth/login")


def _unauthorised(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Principal:
    """The signed-in user, as a `Principal`. 401 when absent or invalid."""
    if credentials is None:
        raise _unauthorised("This endpoint requires a bearer token. Sign in first.")

    try:
        claims = decode_access_token(credentials.credentials)
    except TokenError as exc:
        raise _unauthorised(str(exc)) from exc

    try:
        user_id = uuid.UUID(claims["sub"])
    except (KeyError, ValueError) as exc:
        raise _unauthorised("Token is missing a usable subject claim.") from exc

    jti = claims.get("jti")
    if jti and await session.get(AccessTokenRevocation, jti):
        raise _unauthorised("Token has been revoked.")
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorised("This account no longer exists or has been disabled.")
    # Live roles win over the short-lived token claim so revocation takes
    # effect immediately without waiting for refresh.
    return Principal(
        actor_type=ActorType.HUMAN,
        user_id=user_id,
        email=user.email,
        roles=tuple(user.roles),
        token_id=jti,
        token_expires_at=claims.get("exp"),
    )


async def optional_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal | None:
    """The signed-in user if there is one, else None. Never raises.

    For read endpoints that are open in this showcase but should still attribute
    the request when a token happens to be present.
    """
    if credentials is None:
        return None
    try:
        # optional authentication is retained only for non-API reuse; API
        # routes are protected by the request boundary middleware.
        claims = decode_access_token(credentials.credentials)
        return Principal(actor_type=ActorType.HUMAN,user_id=uuid.UUID(claims["sub"]),email=claims.get("email"),roles=tuple(claims.get("roles",[])),token_id=claims.get("jti"),token_expires_at=claims.get("exp"))
    except HTTPException:
        return None


def require_roles(*roles: Role) -> Callable[[Principal], Principal]:
    """Dependency factory: the caller must hold at least one of `roles`.

    `admin` satisfies every check, via `Principal.has_role`.
    """

    async def dependency(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Principal:
        if not any(principal.has_role(role) for role in roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Requires one of: "
                    + ", ".join(role.value for role in roles)
                    + f". You hold: {', '.join(principal.roles) or 'no roles'}."
                ),
            )
        return principal

    return dependency
