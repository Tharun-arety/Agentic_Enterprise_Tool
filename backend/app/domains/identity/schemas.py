"""Identity wire contracts."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    # A plain string rather than `EmailStr`. Format-validating a login address
    # buys nothing — one that is malformed simply matches no stored user — and
    # `email-validator` rejects the `.test` TLD that RFC 6761 reserves for
    # exactly the demo accounts this project seeds.
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    roles: list[str]
    is_active: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class RefreshResponse(TokenResponse):
    rotated: bool = True


class LogoutResponse(BaseModel):
    status: str = "signed_out"
