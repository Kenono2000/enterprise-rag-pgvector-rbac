"""
app/auth package
Consolidates JWKS token verification, PKCE helpers, and role mapping.
"""

from app.auth.jwks import verify_google_token, verify_jwt_token, get_allowed_issuers
from app.auth.pkce import (
    build_authorization_url,
    decode_pkce_state,
    decode_session_cookie,
    derive_code_challenge,
    encode_pkce_state,
    encode_session_cookie,
    exchange_code_for_tokens,
    exchange_code_for_tokens_sync,
    generate_code_verifier,
)
from app.auth.role_mapper import (
    KNOWN_ROLES,
    extract_roles,
    ensure_google_application_credentials,
)

__all__ = [
    "KNOWN_ROLES",
    "build_authorization_url",
    "decode_pkce_state",
    "decode_session_cookie",
    "derive_code_challenge",
    "encode_pkce_state",
    "encode_session_cookie",
    "exchange_code_for_tokens",
    "exchange_code_for_tokens_sync",
    "generate_code_verifier",
    "verify_google_token",
    "verify_jwt_token",
    "get_allowed_issuers",
    "extract_roles",
    "ensure_google_application_credentials",
]
