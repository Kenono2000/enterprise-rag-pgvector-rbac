"""
app/auth/jwks.py
----------------
Fetches Google's public JWKS and verifies Google/Firebase ID tokens (RS256).

Google publishes two JWKS endpoints depending on the token issuer:
  - Standard Google OAuth 2.0 (accounts.google.com):
      https://www.googleapis.com/oauth2/v3/certs
  - Firebase / Google Identity Platform (securetoken.google.com/<project-id>):
      https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com

The verifier auto-selects the endpoint from the token's `iss` claim.
JWKS are cached in memory and refreshed on key-miss (handles Google's key rotation).
"""

from __future__ import annotations

import os
import time
import logging
from typing import Any, Dict, List, Optional

import httpx
import jwt  # PyJWT
from jwt import PyJWKClient, InvalidTokenError, ExpiredSignatureError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GOOGLE_ACCOUNTS_JWKS = "https://www.googleapis.com/oauth2/v3/certs"
FIREBASE_JWKS = (
    "https://www.googleapis.com/service_accounts/v1/jwk/"
    "securetoken@system.gserviceaccount.com"
)

EXPECTED_ISSUERS = {
    "accounts.google.com",
    "https://accounts.google.com",
}


def get_allowed_issuers(audience: Optional[str] = None) -> set[str]:
    """Return the set of valid token issuers allowed by the application."""
    issuers = set(EXPECTED_ISSUERS)
    if audience:
        issuers.add(f"https://securetoken.google.com/{audience}")

    custom_issuer = os.getenv("OIDC_ISSUER") or os.getenv("ENTERPRISE_OIDC_ISSUER")
    if custom_issuer:
        norm = custom_issuer.rstrip("/")
        issuers.add(norm)
        issuers.add(f"{norm}/")
    return issuers


# ---------------------------------------------------------------------------
# JWKS Client (one per issuer, cached at module level)
# ---------------------------------------------------------------------------

_jwks_clients: Dict[str, PyJWKClient] = {}


def _get_jwks_client(issuer: str) -> PyJWKClient:
    """Return a cached PyJWKClient for the given issuer, creating one if needed."""
    if issuer not in _jwks_clients:
        custom_jwks = os.getenv("OIDC_JWKS_URI") or os.getenv("ENTERPRISE_JWKS_URI")
        custom_issuer = (os.getenv("OIDC_ISSUER") or os.getenv("ENTERPRISE_OIDC_ISSUER") or "").rstrip("/")

        if custom_jwks and (not custom_issuer or issuer.rstrip("/") == custom_issuer):
            jwks_uri = custom_jwks
        elif "securetoken.google.com" in issuer:
            jwks_uri = FIREBASE_JWKS
        elif issuer.rstrip("/") in {iss.rstrip("/") for iss in EXPECTED_ISSUERS}:
            jwks_uri = GOOGLE_ACCOUNTS_JWKS
        elif custom_jwks:
            jwks_uri = custom_jwks
        else:
            jwks_uri = f"{issuer.rstrip('/')}/.well-known/jwks.json"

        _jwks_clients[issuer] = PyJWKClient(
            jwks_uri,
            cache_jwk_set=True,
            lifespan=3600,  # re-fetch keys after 1 hour
        )
        logger.info("Created JWKS client for issuer=%s uri=%s", issuer, jwks_uri)

    return _jwks_clients[issuer]


# ---------------------------------------------------------------------------
# Token verification
# ---------------------------------------------------------------------------

def _peek_issuer(token: str) -> str:
    """Decode the JWT header+payload without verification to read `iss`."""
    unverified = jwt.decode(
        token,
        options={"verify_signature": False},
        algorithms=["RS256"],
    )
    iss = unverified.get("iss", "")
    if not iss:
        raise InvalidTokenError("Token missing 'iss' claim")
    return iss


def verify_jwt_token(
    token: str,
    *,
    audience: Optional[str] = None,
    allowed_issuers: Optional[set[str]] = None,
) -> Dict[str, Any]:
    """
    Verify a Google, Firebase, or Enterprise OIDC ID token (RS256).

    Parameters
    ----------
    token:
        Raw Bearer token string.
    audience:
        Expected `aud` claim. Defaults to GOOGLE_CLIENT_ID or OIDC_CLIENT_ID.
    allowed_issuers:
        Optional set of allowed `iss` claim values.

    Returns
    -------
    dict
        Decoded, verified JWT payload.

    Raises
    ------
    jwt.InvalidTokenError / subclasses on any failure.
    """
    audience = audience or os.getenv("GOOGLE_CLIENT_ID") or os.getenv("OIDC_CLIENT_ID")
    if not audience:
        raise InvalidTokenError(
            "Audience is not set (GOOGLE_CLIENT_ID / OIDC_CLIENT_ID missing) — cannot verify token."
        )

    iss = _peek_issuer(token)
    expected_set = allowed_issuers or get_allowed_issuers(audience)
    if iss not in expected_set and iss.rstrip("/") not in {x.rstrip("/") for x in expected_set}:
        raise InvalidTokenError(f"Unexpected token issuer: {iss}")

    client = _get_jwks_client(iss)

    try:
        signing_key = client.get_signing_key_from_jwt(token)
    except Exception as exc:
        # Key may have been rotated; clear cache and retry once
        logger.warning("JWKS key miss, refreshing cache: %s", exc)
        client.fetch_data()
        signing_key = client.get_signing_key_from_jwt(token)

    payload = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=audience,
        leeway=60,  # 60s tolerance for clock skew between IdP servers and local machine
        options={"require": ["exp", "iat", "sub", "iss"]},
    )

    logger.debug("Token verified: sub=%s email=%s", payload.get("sub"), payload.get("email"))
    return payload


# Backwards compatibility alias
verify_google_token = verify_jwt_token

