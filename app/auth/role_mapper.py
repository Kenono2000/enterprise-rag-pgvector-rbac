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

import json
import logging
import os
import tempfile
from typing import Any, Dict, List, Optional

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
# Dynamic Google & Firebase credentials resolver
# ---------------------------------------------------------------------------

_TEMP_CREDENTIALS_FILE: Optional[str] = None


def _get_google_credentials_dict() -> Optional[Dict[str, Any]]:
    """
    Retrieve Google / Firebase service account dictionary.
    Checks Streamlit secrets first, then environment variables.
    """
    # 1. Check Streamlit secrets (Streamlit Cloud deployment)
    try:
        import streamlit as st

        # Standard dictionary sections in secrets.toml
        for sec in ("gcp_service_account", "firebase_service_account", "google_credentials"):
            if hasattr(st, "secrets") and sec in st.secrets:
                return dict(st.secrets[sec])

        # Raw JSON string in secrets
        if hasattr(st, "secrets") and "GOOGLE_CREDENTIALS_JSON" in st.secrets:
            return json.loads(st.secrets["GOOGLE_CREDENTIALS_JSON"])

        # Flattened keys at the root of secrets (support lowercase or uppercase)
        if hasattr(st, "secrets"):
            has_sec_proj = "project_id" in st.secrets or "PROJECT_ID" in st.secrets
            has_sec_pk = "private_key" in st.secrets or "PRIVATE_KEY" in st.secrets
            if has_sec_proj and has_sec_pk:
                sa_keys = [
                    "type", "project_id", "private_key_id", "private_key",
                    "client_email", "client_id", "auth_uri", "token_uri",
                    "auth_provider_x509_cert_url", "client_x509_cert_url", "universe_domain"
                ]
                creds: Dict[str, Any] = {}
                for k in sa_keys:
                    val = st.secrets.get(k) if k in st.secrets else st.secrets.get(k.upper())
                    if val is not None:
                        if k == "private_key" and isinstance(val, str):
                            val = val.replace("\\n", "\n")
                        creds[k] = val
                if "type" not in creds:
                    creds["type"] = "service_account"
                return creds
    except Exception:
        pass

    # 2. Check JSON string in environment variable
    raw_env_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if raw_env_json:
        try:
            return json.loads(raw_env_json)
        except Exception:
            pass

    # 3. Check individual fields present in environment (e.g. from .env file)
    has_project_id = os.getenv("project_id") or os.getenv("PROJECT_ID")
    has_private_key = os.getenv("private_key") or os.getenv("PRIVATE_KEY")
    if has_project_id and has_private_key:
        sa_keys = [
            "type", "project_id", "private_key_id", "private_key",
            "client_email", "client_id", "auth_uri", "token_uri",
            "auth_provider_x509_cert_url", "client_x509_cert_url", "universe_domain"
        ]
        creds: Dict[str, Any] = {}
        for k in sa_keys:
            val = os.getenv(k) if os.getenv(k) is not None else os.getenv(k.upper())
            if val is not None:
                if k == "private_key":
                    # Fix escaped newlines in PEM private key
                    val = val.replace("\\n", "\n")
                creds[k] = val
        if "type" not in creds:
            creds["type"] = "service_account"
        return creds

    return None


def ensure_google_application_credentials() -> Optional[str]:
    """
    Ensure GOOGLE_APPLICATION_CREDENTIALS points to a valid file.
    If running in Streamlit Cloud without a local file, synthesizes an
    ephemeral temporary JSON file from st.secrets and sets the environment variable.
    """
    global _TEMP_CREDENTIALS_FILE

    # 1. Existing valid file from environment variable
    existing = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if existing and os.path.exists(existing):
        return existing

    # 2. Check local fallback candidate files
    candidates = [
        os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH"),
        "service_account.json",
        "firebase-service-account.json",
        os.path.join(os.path.dirname(__file__), "..", "..", "service_account.json"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            abs_path = os.path.abspath(path)
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = abs_path
            return abs_path

    # 3. Synthesize temporary file from st.secrets / env dictionary
    if _TEMP_CREDENTIALS_FILE and os.path.exists(_TEMP_CREDENTIALS_FILE):
        return _TEMP_CREDENTIALS_FILE

    creds_dict = _get_google_credentials_dict()
    if creds_dict:
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
                json.dump(creds_dict, tmp)
                _TEMP_CREDENTIALS_FILE = tmp.name
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _TEMP_CREDENTIALS_FILE
            logger.info("Created ephemeral credentials file at %s", _TEMP_CREDENTIALS_FILE)
            return _TEMP_CREDENTIALS_FILE
        except Exception as exc:
            logger.warning("Failed creating ephemeral credentials file: %s", exc)

    return None


# ---------------------------------------------------------------------------
# Firebase Admin SDK user claims helper
# ---------------------------------------------------------------------------

def _init_firebase_admin() -> bool:
    """
    Initialize Firebase Admin SDK once.
    Priority:
    1. Dynamic credentials dictionary from st.secrets (Streamlit Cloud).
    2. Local service account JSON file (Local development).
    3. Application Default Credentials (ADC).
    """
    if firebase_admin._apps:
        return True

    # 1. Dynamic credentials from st.secrets / env dictionary
    creds_dict = _get_google_credentials_dict()
    if creds_dict:
        try:
            cred = credentials.Certificate(creds_dict)
            firebase_admin.initialize_app(cred)
            logger.info("Initialized Firebase Admin SDK dynamically from secrets dictionary")
            return True
        except Exception as exc:
            logger.warning("Failed initializing Firebase with credentials dictionary: %s", exc)

    # 2. Fallback to local files & environment paths
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

    # 3. Application Default Credentials (ADC)
    try:
        firebase_admin.initialize_app()
        logger.info("Initialized Firebase Admin SDK using Application Default Credentials")
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
    # 1 — Extract and validate roles from verified JWT claims (app_roles, roles, groups)
    claim_candidates: List[Any] = []
    
    # Standard OIDC / OAuth2 & Firebase claim locations
    if "app_roles" in token_payload:
        claim_candidates.append(token_payload["app_roles"])
    if "roles" in token_payload:
        claim_candidates.append(token_payload["roles"])
    if "groups" in token_payload:
        claim_candidates.append(token_payload["groups"])
    if "cognito:groups" in token_payload:
        claim_candidates.append(token_payload["cognito:groups"])
    if isinstance(token_payload.get("realm_access"), dict) and "roles" in token_payload["realm_access"]:
        claim_candidates.append(token_payload["realm_access"]["roles"])

    extracted: set[str] = set()
    for candidate in claim_candidates:
        if isinstance(candidate, str):
            for item in candidate.split(","):
                norm = item.strip().lower()
                if norm in KNOWN_ROLES:
                    extracted.add(norm)
        elif isinstance(candidate, (list, tuple, set)):
            for item in candidate:
                if isinstance(item, str):
                    norm = item.strip().lower()
                    if norm in KNOWN_ROLES:
                        extracted.add(norm)

    if extracted:
        resolved = sorted(list(extracted))
        logger.debug(
            "Roles from verified token claims: %s  sub=%s",
            resolved,
            token_payload.get("sub"),
        )
        return resolved

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
