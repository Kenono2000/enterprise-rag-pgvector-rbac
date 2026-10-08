"""
app/auth/pkce.py
----------------
OAuth 2.0 PKCE (RFC 7636) helpers for the Google OAuth 2.0 authorization
code flow with a Web Application client.

PKCE Flow Summary
-----------------
1. Client generates a random ``code_verifier`` (43–128 URL-safe chars).
2. Client computes  ``code_challenge = BASE64URL(SHA256(code_verifier))``.
3. Client redirects the user to Google's authorization endpoint, including
   ``code_challenge`` and ``code_challenge_method=S256``.
4. Google redirects back to ``redirect_uri`` with ``?code=<auth_code>``.
5. Client POSTs (code, code_verifier, redirect_uri, client_id) to Google's
   token endpoint — NO client_secret required.
6. Google returns ``{id_token, access_token, refresh_token}``.

This module is used by:
  - ``streamlit_app.py`` (browser-initiated PKCE flow via session_state)
  - Possibly a future SPA / CLI tool
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import urllib.parse
from typing import Dict, Optional

import httpx

# ---------------------------------------------------------------------------
# Google OAuth 2.0 endpoints
# ---------------------------------------------------------------------------

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

# Default OAuth 2.0 scopes: openid + email + profile
# Add "https://www.googleapis.com/auth/cloud-platform" if you need GCP APIs.
DEFAULT_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------

def generate_code_verifier(length: int = 64) -> str:
    """
    Generate a cryptographically-random PKCE code verifier (RFC 7636 §4.1).

    Length must be between 43 and 128 characters.
    Uses URL-safe base64 encoding without padding.
    """
    if not 43 <= length <= 128:
        raise ValueError("code_verifier length must be between 43 and 128")
    raw = secrets.token_bytes(length)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")[:length]


def derive_code_challenge(code_verifier: str) -> str:
    """
    Compute the S256 code challenge from the verifier (RFC 7636 §4.2).

    code_challenge = BASE64URL(SHA256(ASCII(code_verifier)))
    """
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# ---------------------------------------------------------------------------
# Stateless HMAC-signed OAuth state helpers
# ---------------------------------------------------------------------------

def _get_hmac_secret() -> bytes:
    """Return a consistent secret key derived from environment configuration."""
    raw = os.getenv("SESSION_SECRET") or os.getenv("GOOGLE_CLIENT_ID") or "enterprise-rag-default-key"
    return hashlib.sha256(raw.encode("utf-8")).digest()


def encode_pkce_state(code_verifier: str, nonce: Optional[str] = None) -> str:
    """
    Encode the code_verifier and a creation timestamp into a tamper-proof,
    HMAC-signed state string. This allows stateless, zero-storage PKCE verification
    that survives server restarts, process recycles, and module reloads.
    """
    import json
    import time
    payload = {
        "v": code_verifier,
        "t": int(time.time()),
        "n": nonce or secrets.token_hex(8),
    }
    raw_json = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    b64_data = base64.urlsafe_b64encode(raw_json).rstrip(b"=").decode("ascii")
    sig = hmac.new(_get_hmac_secret(), b64_data.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{b64_data}.{sig}"


def decode_pkce_state(state: str, max_age_seconds: int = 300) -> Optional[str]:
    """
    Verify the HMAC signature and timestamp of the returned OAuth state,
    returning the original code_verifier if valid and not expired (default: 5 min).
    Returns None if signature is invalid, state is malformed, or state is expired.
    """
    import json
    import time
    if not state or "." not in state:
        return None

    b64_data, sig = state.rsplit(".", 1)
    expected_sig = hmac.new(_get_hmac_secret(), b64_data.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None

    # Restore base64 padding
    rem = len(b64_data) % 4
    if rem:
        b64_data += "=" * (4 - rem)

    try:
        payload = json.loads(base64.urlsafe_b64decode(b64_data.encode("ascii")).decode("utf-8"))
        if not isinstance(payload, dict):
            return None
        created_at = payload.get("t", 0)
        if time.time() - created_at > max_age_seconds:
            return None  # expired
        return payload.get("v")
    except Exception:
        return None


def encode_session_cookie(data: dict, ttl_seconds: int = 43200) -> str:
    """
    Encode session data into a compressed, HMAC-SHA256 signed, URL-safe base64 string
    suitable for HTTP cookies. Default TTL is 12 hours (43200s).
    """
    import json
    import time
    import zlib
    now = int(time.time())
    payload = {
        "d": data,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    raw_json = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    compressed = zlib.compress(raw_json)
    b64_data = base64.urlsafe_b64encode(compressed).rstrip(b"=").decode("ascii")
    sig = hmac.new(_get_hmac_secret(), b64_data.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{b64_data}.{sig}"


def decode_session_cookie(cookie_str: str) -> Optional[dict]:
    """
    Verify the HMAC signature, decompression, and expiration timestamp of a session cookie string.
    Returns the decoded session data dict if valid and unexpired, or None otherwise.
    """
    import json
    import time
    import zlib
    if not cookie_str or "." not in cookie_str:
        return None

    b64_data, sig = cookie_str.rsplit(".", 1)
    expected_sig = hmac.new(_get_hmac_secret(), b64_data.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None

    # Restore base64 padding
    rem = len(b64_data) % 4
    if rem:
        b64_data += "=" * (4 - rem)

    try:
        compressed = base64.urlsafe_b64decode(b64_data.encode("ascii"))
        raw_json = zlib.decompress(compressed).decode("utf-8")
        payload = json.loads(raw_json)
        if not isinstance(payload, dict):
            return None
        if time.time() > payload.get("exp", 0):
            return None  # expired
        return payload.get("d")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Authorization URL builder
# ---------------------------------------------------------------------------

def _normalize_redirect_uri(uri: str) -> str:
    """Defensively clean accidental duplicate scheme prefixes (e.g. https://https://)."""
    while uri.startswith("https://https://"):
        uri = uri[8:]
    while uri.startswith("http://http://"):
        uri = uri[7:]
    return uri


def build_authorization_url(
    *,
    redirect_uri: str,
    state: Optional[str] = None,
    scopes: Optional[list[str]] = None,
    client_id: Optional[str] = None,
    login_hint: Optional[str] = None,
    hd: Optional[str] = None,
) -> tuple[str, str, str]:
    """
    Build a Google authorization URL with PKCE.

    Returns
    -------
    (authorization_url, code_verifier, state)
        The returned ``state`` cryptographically embeds and signs the ``code_verifier``
        using HMAC-SHA256, allowing stateless verification upon return.

    Parameters
    ----------
    redirect_uri:
        Must exactly match a URI registered in the Google Cloud Console.
    state:
        CSRF token. Auto-generated as signed PKCE state if not supplied.
    scopes:
        OAuth 2.0 scopes. Defaults to openid + email + profile.
    client_id:
        Google OAuth 2.0 client ID. Defaults to GOOGLE_CLIENT_ID env var.
    login_hint:
        Pre-fill the Google sign-in email field.
    hd:
        Restrict to a G Suite / Workspace hosted domain (e.g. "acme.com").
    """
    client_id = client_id or os.getenv("GOOGLE_CLIENT_ID")
    if not client_id:
        raise ValueError("GOOGLE_CLIENT_ID is not set")

    code_verifier = generate_code_verifier()
    code_challenge = derive_code_challenge(code_verifier)
    # Default to cryptographically signed stateless PKCE state
    state = state or encode_pkce_state(code_verifier)
    clean_redirect_uri = _normalize_redirect_uri(redirect_uri)

    params: Dict[str, str] = {
        "client_id": client_id,
        "response_type": "code",
        "scope": " ".join(scopes or DEFAULT_SCOPES),
        "redirect_uri": clean_redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",   # request refresh_token
        "prompt": "consent",        # always show consent to get refresh_token
    }
    if login_hint:
        params["login_hint"] = login_hint
    if hd:
        params["hd"] = hd

    url = GOOGLE_AUTH_ENDPOINT + "?" + urllib.parse.urlencode(params)
    return url, code_verifier, state



# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------

def _get_client_secret() -> Optional[str]:
    """Retrieve client secret from environment variables or Streamlit secrets."""
    secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not secret:
        try:
            import streamlit as st
            secret = st.secrets.get("GOOGLE_CLIENT_SECRET")
        except Exception:
            pass
    return secret


async def exchange_code_for_tokens(
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
) -> Dict[str, str]:
    """
    Exchange an authorization code for Google tokens via the PKCE token endpoint.

    Returns
    -------
    dict
        Contains at minimum ``id_token``, ``access_token``, ``token_type``.
        May also contain ``refresh_token`` and ``expires_in``.

    Raises
    ------
    httpx.HTTPStatusError
        If Google returns a non-2xx response.
    """
    client_id = client_id or os.getenv("GOOGLE_CLIENT_ID")
    if not client_id:
        raise ValueError("GOOGLE_CLIENT_ID is not set")

    client_secret = _get_client_secret()

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _normalize_redirect_uri(redirect_uri),
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    if client_secret:
        data["client_secret"] = client_secret

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            GOOGLE_TOKEN_ENDPOINT,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code >= 400:
            try:
                err_body = response.json()
            except Exception:
                err_body = response.text
            raise RuntimeError(f"Google token endpoint returned {response.status_code}: {err_body}")
        return response.json()


def exchange_code_for_tokens_sync(
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    client_id: Optional[str] = None,
) -> Dict[str, str]:
    """
    Synchronous version of ``exchange_code_for_tokens`` for use in
    Streamlit (which runs outside an async event loop).
    """
    client_id = client_id or os.getenv("GOOGLE_CLIENT_ID")
    if not client_id:
        raise ValueError("GOOGLE_CLIENT_ID is not set")

    client_secret = _get_client_secret()

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _normalize_redirect_uri(redirect_uri),
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    if client_secret:
        data["client_secret"] = client_secret


    with httpx.Client(timeout=15) as client:
        response = client.post(
            GOOGLE_TOKEN_ENDPOINT,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code >= 400:
            try:
                err_body = response.json()
            except Exception:
                err_body = response.text
            raise RuntimeError(f"Google token endpoint returned {response.status_code}: {err_body}")
        return response.json()

