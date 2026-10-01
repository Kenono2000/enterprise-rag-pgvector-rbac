"""
app/auth/role_mapper.py
-----------------------
Maps Google Identity Platform / Firebase custom claims to application roles.

Expected custom claim format in the Firebase ID token:
    {
      "app_roles": ["finance_executive", "engineer"]   ← preferred
    }

If app_roles is absent, a fallback heuristic maps email domains and specific
addresses to roles.  This is intentionally simple — production deployments
should always use Firebase custom claims set via the Admin SDK.

Setup (Firebase Admin SDK — run once per user, or on sign-up):
    import firebase_admin
    from firebase_admin import auth as fb_auth

    fb_auth.set_custom_user_claims(uid, {"app_roles": ["engineer"]})
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import firebase_admin
from firebase_admin import auth as fb_auth, credentials

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Application roles (must match allowed_roles values stored in PostgreSQL)
# ---------------------------------------------------------------------------

KNOWN_ROLES = frozenset(
    ["finance_executive", "compliance_auditor", "hr_manager", "executive", "engineer"]
)

# ---------------------------------------------------------------------------
# Firebase Admin SDK user claims helper
# ---------------------------------------------------------------------------

def _init_firebase_admin() -> bool:
    """Initialize Firebase Admin SDK once if service credentials exist."""
    if firebase_admin._apps:
        return True

    candidates = [
        os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH"),
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
        "service_account.json",
        "firebase-service-account.json",
        os.path.join(os.path.dirname(__file__), "..", "..", "service_account.json"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            try:
                cred = credentials.Certificate(path)
                firebase_admin.initialize_app(cred)
                logger.info("Initialized Firebase Admin SDK with credentials from: %s", path)
                return True
            except Exception as exc:
                logger.warning("Failed initializing Firebase with %s: %s", path, exc)

    try:
        firebase_admin.initialize_app()
        return True
    except Exception as exc:
        logger.debug("Firebase default credentials not available: %s", exc)
        return False


def _get_firebase_claims_by_email(email: str) -> List[str]:
    """Retrieve app_roles custom claims directly from Firebase by user email."""
    if not _init_firebase_admin():
        return []

    try:
        user = fb_auth.get_user_by_email(email)
        claims = user.custom_claims or {}
        raw_roles = claims.get("app_roles")
        if raw_roles and isinstance(raw_roles, list):
            roles = [r for r in raw_roles if isinstance(r, str) and r in KNOWN_ROLES]
            if roles:
                return roles
    except Exception as exc:
        logger.debug("Could not fetch Firebase claims for %s: %s", email, exc)

    return []

# ---------------------------------------------------------------------------
# Fallback: email-domain / email-address → role mapping
# Read from env for flexibility:  ROLE_MAP_engineer=@acme.com,dev@partner.com
# ---------------------------------------------------------------------------

def _load_env_role_map() -> Dict[str, List[str]]:
    """
    Build a {email_pattern: [roles]} map from env vars of the form:
        ROLE_MAP_<ROLE>=pattern1,pattern2
    Example:
        ROLE_MAP_engineer=@acme.com
        ROLE_MAP_finance_executive=cfo@acme.com,vp-finance@acme.com
    """
    mapping: Dict[str, List[str]] = {}
    for key, value in os.environ.items():
        if key.startswith("ROLE_MAP_"):
            role = key[len("ROLE_MAP_"):].lower()
            for pattern in value.split(","):
                pattern = pattern.strip()
                if pattern:
                    mapping.setdefault(pattern, []).append(role)
    return mapping


def _get_env_role_map() -> Dict[str, List[str]]:
    return _load_env_role_map()


def _fallback_roles_from_email(email: str) -> List[str]:
    """Return roles based on the user's email using the env-configured map."""
    roles: List[str] = []
    email_lower = email.lower()
    for pattern, mapped_roles in _get_env_role_map().items():
        pattern_lower = pattern.lower()
        # Exact match or domain suffix match (@example.com)
        if email_lower == pattern_lower or (
            pattern_lower.startswith("@") and email_lower.endswith(pattern_lower)
        ):
            roles.extend(mapped_roles)
    return list(set(roles))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_roles(token_payload: Dict[str, Any]) -> List[str]:
    """
    Extract application roles from a verified Google/Firebase ID token payload.

    Priority:
    1. ``app_roles`` custom claim (Firebase custom claims set via Admin SDK).
    2. Fallback: email-domain mapping from environment variables.
    3. Empty list — caller will get a 403 from the RBAC SQL filter.

    Parameters
    ----------
    token_payload:
        Decoded, verified JWT payload dict.

    Returns
    -------
    list[str]
        Validated application role strings.
    """
    # 1 — Firebase custom claims
    raw_roles = token_payload.get("app_roles")
    if raw_roles and isinstance(raw_roles, list):
        roles = [r for r in raw_roles if isinstance(r, str) and r in KNOWN_ROLES]
        if roles:
            logger.debug(
                "Roles from custom claims: %s  sub=%s",
                roles,
                token_payload.get("sub"),
            )
            return roles
        logger.warning(
            "app_roles claim present but contained no recognised roles: %s",
            raw_roles,
        )

    # 2 — Look up Firebase custom claims via Firebase Admin SDK
    email = token_payload.get("email", "")
    if email:
        fb_roles = _get_firebase_claims_by_email(email)
        if fb_roles:
            logger.info("Roles from Firebase Admin SDK for %s: %s", email, fb_roles)
            return fb_roles

    # 3 — Email-domain fallback
    email = token_payload.get("email", "")
    if email:
        roles = _fallback_roles_from_email(email)
        if roles:
            logger.debug(
                "Roles from email fallback: %s  email=%s", roles, email
            )
            return roles

    logger.info(
        "No roles resolved for sub=%s email=%s — returning empty list",
        token_payload.get("sub"),
        email,
    )
    return []
