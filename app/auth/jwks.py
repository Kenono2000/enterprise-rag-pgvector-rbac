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


# ---------------------------------------------------------------------------
# JWKS Client (one per issuer, cached at module level)
# ---------------------------------------------------------------------------

_jwks_clients: Dict[str, PyJWKClient] = {}


def _get_jwks_client(issuer: str) -> PyJWKClient:
    """Return a cached PyJWKClient for the given issuer, creating one if needed."""
    if issuer not in _jwks_clients:
        if "securetoken.google.com" in issuer:
            jwks_uri = FIREBASE_JWKS
        else:
            jwks_uri = GOOGLE_ACCOUNTS_JWKS

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


def verify_google_token(
    token: str,
    *,
    audience: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Verify a Google or Firebase ID token (RS256).

    Parameters
    ----------
    token:
        Raw Bearer token string.
    audience:
        Expected `aud` claim. Defaults to GOOGLE_CLIENT_ID from the environment.
        For Firebase tokens this should be the Firebase project ID.

    Returns
    -------
    dict
        Decoded, verified JWT payload.

    Raises
    ------
    jwt.InvalidTokenError / subclasses on any failure.
    """
    audience = audience or os.getenv("GOOGLE_CLIENT_ID")
    if not audience:
        raise InvalidTokenError(
            "GOOGLE_CLIENT_ID is not set — cannot verify token audience."
        )

    iss = _peek_issuer(token)
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
        leeway=60,  # 60s tolerance for clock skew between Google servers and local machine
        options={"require": ["exp", "iat", "sub", "iss"]},
    )

    # Validate issuer explicitly (PyJWT checks aud but not iss by default unless configured)
    if payload.get("iss") not in EXPECTED_ISSUERS | {
        f"https://securetoken.google.com/{audience}"
    }:
        raise InvalidTokenError(f"Unexpected token issuer: {payload.get('iss')}")

    logger.debug("Token verified: sub=%s email=%s", payload.get("sub"), payload.get("email"))
    return payload
