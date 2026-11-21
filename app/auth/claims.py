"""
app/auth/claims.py
------------------
Strict Pydantic v2 schema for verified OIDC / JWT user claims.

Provides a zero-trust validation layer on top of verified JWT payloads so that
caller identity (sub, roles, email, aud, iss) is typed, normalized, and
re-validated before being consumed by RBAC retrieval paths.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class UserClaims(BaseModel):
    """
    Strictly validated user claims extracted from a verified JWT payload.

    Fields are normalized (lowercased, stripped) and constrained to known
    application roles so malformed or over-privileged claims cannot reach
    the RBAC SQL pre-filter.
    """

    model_config = {
        "extra": "forbid",
        "str_strip_whitespace": True,
    }

    sub: str = Field(..., min_length=1, description="Subject identifier from JWT 'sub' claim")
    email: Optional[str] = Field(
        default=None, description="User email from JWT 'email' claim"
    )
    roles: List[str] = Field(
        default_factory=list,
        description="Application roles extracted from token claims",
    )
    aud: Optional[str] = Field(default=None, description="Audience claim")
    iss: Optional[str] = Field(default=None, description="Issuer claim")

    @field_validator("roles", mode="before")
    @classmethod
    def normalize_roles(cls, v):
        """Normalize role strings: lowercase, strip, drop empties."""
        if v is None:
            return []
        if isinstance(v, str):
            items = [item.strip() for item in v.split(",")]
        elif isinstance(v, (list, tuple, set)):
            items = [str(item).strip() for item in v]
        else:
            return []
        return [item.lower() for item in items if item]

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v):
        """Lowercase and strip email."""
        if v is None:
            return None
        return v.strip().lower()

    @field_validator("sub", "aud", "iss")
    @classmethod
    def strip_identity_fields(cls, v):
        """Strip whitespace from identity fields."""
        if v is None:
            return None
        return v.strip()


def claims_from_payload(payload: dict) -> UserClaims:
    """
    Build a validated UserClaims instance from a verified JWT payload dict.

    Raises pydantic.ValidationError if the payload fails strict validation
    (e.g. missing sub, extra unknown fields).
    """
    return UserClaims(
        sub=payload.get("sub", ""),
        email=payload.get("email"),
        roles=payload.get("app_roles")
        or payload.get("roles")
        or payload.get("groups")
        or payload.get("custom:roles")
        or payload.get("custom_roles")
        or [],
        aud=payload.get("aud"),
        iss=payload.get("iss"),
    )
