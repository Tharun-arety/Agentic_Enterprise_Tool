"""Authentication endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hmac
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import current_principal
from app.core.principal import Principal
from app.core.config import get_settings
from app.core.security import create_access_token, hash_token, new_csrf_token, new_refresh_token
from app.domains.identity.models import AccessTokenRevocation, RefreshSession, User
from app.domains.identity.schemas import LoginRequest, LogoutResponse, RefreshResponse, TokenResponse, UserOut
from app.domains.identity.service import AuthError, authenticate

router = APIRouter(prefix="/api/auth", tags=["identity"])


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenResponse:
    _validate_origin(request)
    try:
        user = await authenticate(session, payload.email, payload.password)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    token, expires_in = create_access_token(
        subject=user.id, email=user.email, roles=list(user.roles)
    )
    await _issue_refresh(response, session, user)
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserOut.model_validate(user),
    )


def _validate_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in get_settings().cors_origins:
        raise HTTPException(status_code=403, detail="Origin is not allowed.")


def _set_refresh_cookies(response: Response, token: str, csrf: str) -> None:
    settings = get_settings()
    max_age = settings.refresh_expiry_days * 86400
    response.set_cookie(settings.refresh_cookie_name, token, max_age=max_age, httponly=True, secure=settings.cookie_secure, samesite="strict", path="/api/auth")
    response.set_cookie(settings.csrf_cookie_name, csrf, max_age=max_age, httponly=False, secure=settings.cookie_secure, samesite="strict", path="/")


async def _issue_refresh(response: Response, session: AsyncSession, user: User, *, family_id=None) -> tuple[RefreshSession, str]:
    settings = get_settings()
    raw = new_refresh_token()
    row = RefreshSession(user_id=user.id, family_id=family_id or __import__("uuid").uuid4(), token_hash=hash_token(raw), expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_expiry_days))
    session.add(row)
    await session.commit()
    _set_refresh_cookies(response, raw, new_csrf_token())
    return row, raw


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    refresh_cookie: Annotated[str | None, Cookie(alias=get_settings().refresh_cookie_name)] = None,
    csrf_cookie: Annotated[str | None, Cookie(alias=get_settings().csrf_cookie_name)] = None,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> RefreshResponse:
    _validate_origin(request)
    if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
        raise HTTPException(status_code=403, detail="CSRF validation failed.")
    if not refresh_cookie:
        raise HTTPException(status_code=401, detail="Refresh cookie is missing.")
    row = (await session.execute(select(RefreshSession).where(RefreshSession.token_hash == hash_token(refresh_cookie)))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None or row.revoked_at is not None or row.expires_at <= now:
        if row is not None:
            await session.execute(__import__("sqlalchemy").update(RefreshSession).where(RefreshSession.family_id == row.family_id).values(revoked_at=now))
            await session.commit()
        raise HTTPException(status_code=401, detail="Refresh session is invalid or expired.")
    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Account is unavailable.")
    row.revoked_at = now
    replacement, _ = await _issue_refresh(response, session, user, family_id=row.family_id)
    row.replaced_by_id = replacement.id
    await session.commit()
    token, expires_in = create_access_token(subject=user.id, email=user.email, roles=list(user.roles))
    return RefreshResponse(access_token=token, expires_in=expires_in, user=UserOut.model_validate(user))


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    response: Response,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    refresh_cookie: Annotated[str | None, Cookie(alias=get_settings().refresh_cookie_name)] = None,
) -> LogoutResponse:
    if refresh_cookie:
        row = (await session.execute(select(RefreshSession).where(RefreshSession.token_hash == hash_token(refresh_cookie)))).scalar_one_or_none()
        if row and row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
            await session.commit()
    if principal.token_id and principal.token_expires_at:
        session.add(AccessTokenRevocation(jti=principal.token_id, expires_at=datetime.fromtimestamp(principal.token_expires_at, timezone.utc)))
        await session.commit()
    settings = get_settings()
    response.delete_cookie(settings.refresh_cookie_name, path="/api/auth")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    return LogoutResponse()


@router.get("/me", response_model=UserOut)
async def me(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserOut:
    """Resolve the token back to the live user record.

    Read from the database rather than echoed from the token claims: a role
    revoked or an account disabled after the token was issued must take effect
    here, not at the next login.
    """
    user = (
        await session.execute(select(User).where(User.id == principal.user_id))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account no longer exists or has been disabled.",
        )
    return UserOut.model_validate(user)
