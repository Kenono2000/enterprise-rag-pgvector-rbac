"""
streamlit_app.py
----------------
Zero-Trust Enterprise RAG demo with Google OAuth 2.0 PKCE authentication.

PKCE Flow (browser → Google → back to this page)
-------------------------------------------------
1. User clicks "Sign in with Google".
2. App builds an authorization URL with a code_verifier + code_challenge,
   stores them in st.session_state, then redirects the browser via st.link_button.
3. Google redirects to this Streamlit app's URL with ?code=<auth_code>&state=<csrf>.
4. On the next script rerun (Streamlit re-runs on URL params), the app detects
   the ?code= param, exchanges it for tokens, verifies the ID token, and stores
   the user identity in session_state.
5. The PKCE state is cleared so the token is never exchanged twice.

Environment / Secrets required
--------------------------------
    GOOGLE_CLIENT_ID        — OAuth 2.0 Web Application client ID
    GOOGLE_REDIRECT_URI     — Must match a registered redirect URI in Google Cloud Console
                              e.g. https://enterprise-rag-pgvector-rbac.streamlit.app/
                              or   http://localhost:8501/ for local dev
    DATABASE_URL            — PostgreSQL connection string (can also be in st.secrets)
    OPENAI_API_KEY          — Optional; mock responses used if absent

Streamlit secrets (secrets.toml or Streamlit Cloud UI):
    [default]
    GOOGLE_CLIENT_ID = "..."
    GOOGLE_REDIRECT_URI = "..."
    DATABASE_URL = "..."
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.parse
from typing import Optional
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(), override=True)

import streamlit as st
import streamlit.components.v1 as components

from app.auth import (
    KNOWN_ROLES,
    verify_google_token,
    build_authorization_url,
    decode_pkce_state,
    decode_session_cookie,
    encode_session_cookie,
    exchange_code_for_tokens_sync,
    extract_roles,
    ensure_google_application_credentials,
)
from app.db import DatabaseManager, generate_embedding, chat_completion, chat_completion_stream_sync
from app.observability import tracer
import time


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ensure Google credentials exist (dynamically from st.secrets with local fallback)
ensure_google_application_credentials()

# ---------------------------------------------------------------------------
# SessionIdleManager & Cookie Configuration (SOC-2 / HIPAA Compliance)
# ---------------------------------------------------------------------------
IDLE_TIMEOUT_SECONDS = 15 * 60       # 15 minutes inactivity limit
MAX_SESSION_SECONDS = 12 * 3600      # 12 hours absolute session ceiling
SESSION_COOKIE_NAME = "enterprise_rag_session"


# ---------------------------------------------------------------------------
# Server-side PKCE state store
# ---------------------------------------------------------------------------
# WHY THIS EXISTS:
# When st.link_button navigates the browser to Google, and Google redirects back
# with ?code=..., Streamlit treats the returning request as a brand-new session.
# st.session_state is completely wiped, so any code_verifier / oauth_state stored
# there is gone — causing the "OAuth state mismatch" error.
#
# FIX: store {state_token -> code_verifier} in a module-level dict on the server.
# The module persists for the lifetime of the Streamlit process, surviving the
# browser round-trip. The state token is cryptographically random (128-bit), so
# it cannot be guessed — this preserves CSRF protection without session_state.
#
# Each entry is cleaned up immediately after a successful or failed exchange.
# ---------------------------------------------------------------------------
import threading
import time as _time

_pkce_store_lock = threading.Lock()
# {state_token: {"verifier": str, "created_at": float}}
_pkce_store: dict[str, dict] = {}
_PKCE_TTL_SECONDS = 300  # discard dangling entries after 5 minutes


def _pkce_store_put(state: str, verifier: str) -> None:
    with _pkce_store_lock:
        _pkce_store[state] = {"verifier": verifier, "created_at": _time.monotonic()}
        # Evict expired entries (keeps memory bounded)
        expired = [
            k for k, v in _pkce_store.items()
            if _time.monotonic() - v["created_at"] > _PKCE_TTL_SECONDS
        ]
        for k in expired:
            del _pkce_store[k]


def _pkce_store_pop(state: str) -> str | None:
    with _pkce_store_lock:
        entry = _pkce_store.pop(state, None)
        if entry is None:
            return None
        if _time.monotonic() - entry["created_at"] > _PKCE_TTL_SECONDS:
            return None  # expired
        return entry["verifier"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _secret(key: str) -> Optional[str]:
    """Read a config value from env vars or Streamlit secrets (in that order)."""
    value = os.getenv(key) or os.getenv(key.upper())
    if not value:
        try:
            value = st.secrets.get(key) or st.secrets.get(key.upper())  # type: ignore[attr-defined]
        except Exception:
            pass
    return value


def _is_google_auth_required() -> bool:
    """Check if Google OAuth is strictly required (defaults to False if explicitly configured as false)."""
    val = _secret("REQUIRE_GOOGLE_AUTH")
    if val is None:
        return False
    return str(val).strip().lower() in ("true", "1", "yes")



def run_async(coro):
    """
    Thread-safe async runner preventing event loop collision in Streamlit worker threads.
    If current thread's loop is already running, executes in an isolated worker thread pool.
    """
    import concurrent.futures
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(asyncio.run, coro).result()
        elif loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coro).result()


@st.cache_resource
def get_shared_db_pool():
    """
    Cached connection pool shared safely across Streamlit sessions.
    Prevents connection pool exhaustion under concurrent multi-user load.
    """
    return run_async(DatabaseManager.get_pool())


def _get_redirect_uri() -> str:
    uri = _secret("GOOGLE_REDIRECT_URI")
    if not uri:
        # Fallback: derive from Streamlit's own URL if running on Cloud
        # In local dev this becomes http://localhost:8501/
        uri = "http://localhost:8501/"
    # Defensive normalization: strip accidental duplicated protocol schemes (e.g. https://https://)
    while uri.startswith("https://https://"):
        uri = uri[8:]
    while uri.startswith("http://http://"):
        uri = uri[7:]
    return uri


# ---------------------------------------------------------------------------
# PKCE session management
# ---------------------------------------------------------------------------


def _handle_oauth_callback() -> None:
    """
    Detect ?code= in the query params and exchange it for tokens.
    Must be called before any other rendering so session state is populated.

    The code_verifier is retrieved from the server-side _pkce_store (not
    session_state) because Streamlit resets session_state when the browser
    navigates away to Google and back.
    """
    params = st.query_params
    code = params.get("code")
    returned_state = params.get("state")

    if not code:
        return  # Not a callback — nothing to do

    # Retrieve and validate the code_verifier.
    # 1. First attempt: decode from stateless HMAC-signed state (immune to restarts/reloads).
    # 2. Second attempt: fallback to server-side memory store.
    code_verifier = None
    if returned_state:
        code_verifier = decode_pkce_state(returned_state)
        if not code_verifier:
            code_verifier = _pkce_store_pop(returned_state)

    if not code_verifier:
        st.error(
            "⚠️ Sign-in session expired or state mismatch. "
            "This can happen if the sign-in took more than 5 minutes "
            "or the page was refreshed mid-flow. Please sign in again."
        )
        _clear_auth()
        st.query_params.clear()
        return

    with st.spinner("Exchanging authorization code for tokens…"):
        try:
            tokens = exchange_code_for_tokens_sync(
                code=code,
                code_verifier=code_verifier,
                redirect_uri=_get_redirect_uri(),
            )
        except Exception as exc:
            st.error(f"Token exchange failed: {exc}")
            _clear_auth()
            st.query_params.clear()
            return

    id_token = tokens.get("id_token")
    if not id_token:
        st.error("Google did not return an ID token.")
        _clear_auth()
        st.query_params.clear()
        return

    # Verify the ID token via Google JWKS
    try:
        payload = verify_google_token(id_token)
    except Exception as exc:
        st.error(f"Token verification failed: {exc}")
        _clear_auth()
        st.query_params.clear()
        return

    roles = extract_roles(payload)
    logger.info("Extracted roles 1: %s", roles)

    # Persist identity and session credentials in session_state
    now = _time.time()
    st.session_state["authenticated"] = True
    st.session_state["id_token"] = id_token
    st.session_state["access_token"] = tokens.get("access_token", "")
    st.session_state["refresh_token"] = tokens.get("refresh_token", "")
    st.session_state["token_exp"] = payload.get("exp", 0)
    st.session_state["token_iat"] = payload.get("iat", 0)
    st.session_state["auth_time"] = payload.get("auth_time", payload.get("iat", now))
    st.session_state["login_time"] = now
    st.session_state["last_activity"] = now
    st.session_state["user_sub"] = payload.get("sub")
    st.session_state["user_email"] = payload.get("email", "")
    st.session_state["user_name"] = payload.get("name", payload.get("email", ""))
    st.session_state["user_picture"] = payload.get("picture", "")
    st.session_state["app_roles"] = roles

    # Stage HMAC-signed cookie to persist session across browser refreshes (F5)
    session_payload = {
        "sub": payload.get("sub"),
        "email": payload.get("email", ""),
        "name": payload.get("name", payload.get("email", "")),
        "picture": payload.get("picture", ""),
        "roles": roles,
        "id_token": id_token,
        "access_token": tokens.get("access_token", ""),
        "refresh_token": tokens.get("refresh_token", ""),
        "token_exp": payload.get("exp", 0),
        "token_iat": payload.get("iat", 0),
        "auth_time": payload.get("auth_time", payload.get("iat", now)),
        "login_time": now,
        "last_activity": now,
    }
    st.session_state["_cookie_to_set"] = encode_session_cookie(session_payload, ttl_seconds=MAX_SESSION_SECONDS)
    st.session_state.pop("_just_signed_out", None)

    # Remove ?code= from URL (cleaner UX, prevents double-exchange on refresh)
    st.query_params.clear()

    st.rerun()


def _clear_auth() -> None:
    for key in [
        "authenticated", "id_token", "access_token", "refresh_token",
        "token_exp", "token_iat", "auth_time", "login_time", "last_activity",
        "user_sub", "user_email", "user_name", "user_picture", "app_roles",
        "_cookie_to_set",
    ]:
        st.session_state.pop(key, None)
    st.session_state["_cookie_to_clear"] = True
    st.session_state["_just_signed_out"] = True


def _is_authenticated() -> bool:
    return bool(st.session_state.get("authenticated"))


def _check_session_lifecycle() -> bool:
    """
    Evaluate SessionIdleManager invariants:
    1. Inactivity timeout (15 mins)
    2. Absolute session ceiling (12 hours)
    Returns True if session is valid, False if terminated.
    """
    if not _is_authenticated():
        return True

    now = _time.time()
    last_act = st.session_state.get("last_activity", now)
    login_t = st.session_state.get("login_time", now)

    # 1. Inactivity Timeout Check (SOC-2 / HIPAA mandate)
    if now - last_act > IDLE_TIMEOUT_SECONDS:
        logger.warning("Session terminated: user idle for > 15 minutes.")
        _clear_auth()
        st.session_state["session_expired_reason"] = "idle_timeout"
        st.rerun()
        return False

    # 2. Absolute Session Ceiling Check
    if now - login_t > MAX_SESSION_SECONDS:
        logger.warning("Session terminated: absolute session ceiling (12h) reached.")
        _clear_auth()
        st.session_state["session_expired_reason"] = "max_session"
        st.rerun()
        return False

    # Update activity timestamp on user interaction/rerun
    st.session_state["last_activity"] = now
    return True


def _refresh_id_token_sync(refresh_token: str) -> Optional[dict]:
    """Exchange a refresh token with Google OAuth 2.0 to silently mint a fresh ID token."""
    import httpx
    client_id = _secret("GOOGLE_CLIENT_ID")
    client_secret = _secret("GOOGLE_CLIENT_SECRET")
    if not client_id or not refresh_token:
        return None

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    if client_secret:
        data["client_secret"] = client_secret

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                "https://oauth2.googleapis.com/token",
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code >= 400:
                logger.warning("Token refresh rejected (%s): %s", resp.status_code, resp.text)
                return None
            return resp.json()
    except Exception as exc:
        logger.warning("Token refresh network failure: %s", exc)
        return None


def _get_browser_cookie(name: str) -> Optional[str]:
    """Read a cookie from incoming HTTP/WebSocket request headers via st.context.cookies."""
    try:
        if hasattr(st, "context") and hasattr(st.context, "cookies"):
            return st.context.cookies.get(name)
    except Exception:
        pass
    return None


def _restore_session_from_cookie() -> bool:
    """
    Attempt to rehydrate an authenticated session from the HMAC-signed browser cookie.
    Survives browser reloads (F5) and restores session_state without signing in again.
    """
    if _is_authenticated():
        return True

    if st.session_state.get("_just_signed_out"):
        return False

    cookie_val = _get_browser_cookie(SESSION_COOKIE_NAME)
    if not cookie_val:
        return False

    session_data = decode_session_cookie(cookie_val)
    if not session_data or not isinstance(session_data, dict):
        return False

    now = _time.time()
    last_act = session_data.get("last_activity", now)
    login_t = session_data.get("login_time", now)

    # 1. Inactivity check (15 mins)
    if now - last_act > IDLE_TIMEOUT_SECONDS:
        logger.info("Cookie session rejected: inactive for > 15m")
        st.session_state["session_expired_reason"] = "idle_timeout"
        st.session_state["_cookie_to_clear"] = True
        return False

    # 2. Absolute session ceiling (12h)
    if now - login_t > MAX_SESSION_SECONDS:
        logger.info("Cookie session rejected: exceeded 12h ceiling")
        st.session_state["session_expired_reason"] = "max_session"
        st.session_state["_cookie_to_clear"] = True
        return False

    id_token = session_data.get("id_token", "")
    token_exp = session_data.get("token_exp", 0)
    refresh_token = session_data.get("refresh_token", "")

    # 3. Check if ID token is close to expiry or expired (within 60s of exp)
    if token_exp and (now >= token_exp - 60):
        if refresh_token:
            refreshed = _refresh_id_token_sync(refresh_token)
            if refreshed and "id_token" in refreshed:
                id_token = refreshed["id_token"]
                try:
                    p = verify_google_token(id_token)
                    token_exp = p.get("exp", 0)
                    session_data["roles"] = extract_roles(p)
                except Exception:
                    pass
                session_data["id_token"] = id_token
                session_data["token_exp"] = token_exp
                st.session_state["_cookie_to_set"] = encode_session_cookie(
                    session_data, ttl_seconds=int(max(0, MAX_SESSION_SECONDS - (now - login_t)))
                )
            else:
                logger.warning("Silent token refresh during session restoration failed")
                st.session_state["_cookie_to_clear"] = True
                return False
        else:
            st.session_state["_cookie_to_clear"] = True
            return False

    # Rehydrate session state
    st.session_state["authenticated"] = True
    st.session_state["id_token"] = id_token
    st.session_state["access_token"] = session_data.get("access_token", "")
    st.session_state["refresh_token"] = refresh_token
    st.session_state["token_exp"] = token_exp
    st.session_state["token_iat"] = session_data.get("token_iat", 0)
    st.session_state["auth_time"] = session_data.get("auth_time", now)
    st.session_state["login_time"] = login_t
    st.session_state["last_activity"] = now
    st.session_state["user_sub"] = session_data.get("sub")
    st.session_state["user_email"] = session_data.get("email", "")
    st.session_state["user_name"] = session_data.get("name", "")
    st.session_state["user_picture"] = session_data.get("picture", "")
    st.session_state["app_roles"] = session_data.get("roles", [])
    logger.info("Session restored from secure browser cookie for %s", session_data.get("email"))
    return True


def _render_session_tracker_component() -> None:
    """Inject client-side DOM activity monitor and session cookie syncer into the browser."""
    cookie_to_set = st.session_state.pop("_cookie_to_set", None)
    set_cookie_js = ""
    if cookie_to_set:
        set_cookie_js = f"""
            try {{
                const cVal = "{cookie_to_set}";
                const maxAge = {MAX_SESSION_SECONDS};
                const cookieStr = "{SESSION_COOKIE_NAME}=" + cVal + "; path=/; max-age=" + maxAge + "; SameSite=Lax";
                document.cookie = cookieStr;
                if (window.parent && window.parent.document) {{
                    window.parent.document.cookie = cookieStr;
                    try {{ window.parent.localStorage.setItem("{SESSION_COOKIE_NAME}", cVal); }} catch(e) {{}}
                }}
            }} catch(e) {{
                console.error("[SessionTracker] Cookie write error:", e);
            }}
        """

    components.html(
        f"""
        <script>
        (function() {{
            {set_cookie_js}

            let lastActivity = Date.now();
            const IDLE_LIMIT_MS = 15 * 60 * 1000; // 15 mins
            const WARN_LIMIT_MS = 13 * 60 * 1000; // 13 mins
            let warned = false;

            function onActivity() {{
                lastActivity = Date.now();
                warned = false;
            }}

            ['mousedown', 'keydown', 'scroll', 'touchstart'].forEach(function(evt) {{
                try {{
                    window.parent.document.addEventListener(evt, onActivity, {{ passive: true }});
                }} catch(e) {{}}
                document.addEventListener(evt, onActivity, {{ passive: true }});
            }});

            setInterval(function() {{
                const idle = Date.now() - lastActivity;
                if (idle >= WARN_LIMIT_MS && !warned) {{
                    warned = true;
                    console.warn("[SessionIdleManager] Warning: 2 minutes remaining before inactivity timeout.");
                }}
                if (idle >= IDLE_LIMIT_MS) {{
                    console.error("[SessionIdleManager] Inactivity limit reached (15m). Terminating session.");
                    try {{
                        const clearCookie = "{SESSION_COOKIE_NAME}=; path=/; max-age=0; SameSite=Lax";
                        document.cookie = clearCookie;
                        if (window.parent && window.parent.document) {{
                            window.parent.document.cookie = clearCookie;
                            try {{ window.parent.localStorage.removeItem("{SESSION_COOKIE_NAME}"); }} catch(e) {{}}
                        }}
                    }} catch(e) {{}}
                    window.parent.location.reload();
                }}
            }}, 5000);
        }})();
        </script>
        """,
        height=0,
        width=0,
    )


# ---------------------------------------------------------------------------
# UI Sections
# ---------------------------------------------------------------------------


def _render_sign_in_page() -> None:
    """Show the sign-in card when the user is not authenticated."""
    # Clear cookie in browser if sign-out or session expiration occurred
    if st.session_state.pop("_cookie_to_clear", None):
        components.html(
            f"""
            <script>
            (function() {{
                try {{
                    const clearCookie = "{SESSION_COOKIE_NAME}=; path=/; max-age=0; SameSite=Lax";
                    document.cookie = clearCookie;
                    if (window.parent && window.parent.document) {{
                        window.parent.document.cookie = clearCookie;
                        try {{ window.parent.localStorage.removeItem("{SESSION_COOKIE_NAME}"); }} catch(e) {{}}
                    }}
                }} catch(e) {{}}
            }})();
            </script>
            """,
            height=0,
            width=0,
        )

    # Check if user was signed out by SessionIdleManager
    expired_reason = st.session_state.pop("session_expired_reason", None)
    if expired_reason == "idle_timeout":
        st.warning(
            "⚠️ **Session Terminated:** You have been automatically signed out due to "
            "15 minutes of inactivity (SOC-2 / HIPAA compliance mandate). Please sign in again."
        )
    elif expired_reason == "max_session":
        st.warning(
            "⚠️ **Session Terminated:** Maximum session duration (12 hours) reached. Please sign in again."
        )

    # Check whether Google OAuth is strictly required
    google_auth_required = _is_google_auth_required()

    if google_auth_required:
        st.markdown(
            """
            <div style="text-align:center;padding:2rem 0">
                <h1>🛡️ Zero-Trust Enterprise RAG</h1>
                <p style="color:gray">Sign in with your Google account to access the secured knowledge base.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.divider()

        col_l, col_c, col_r = st.columns([1, 2, 1])
        with col_c:
            client_id = _secret("GOOGLE_CLIENT_ID")
            if not client_id:
                st.error(
                    "**GOOGLE_CLIENT_ID** is not configured.\n\n"
                    "Add it to your `.env` file or Streamlit secrets."
                )
                return

            try:
                auth_url, code_verifier, state = build_authorization_url(
                    redirect_uri=_get_redirect_uri(),
                )
                # Store in server-side dict — survives the browser round-trip to Google.
                _pkce_store_put(state, code_verifier)
            except Exception as exc:
                st.error(f"Failed to build authorization URL: {exc}")
                return

            # Native link button opens Google OAuth in a new tab (target="_blank"):
            # This complies with Streamlit Community Cloud iframe sandboxing (which allows popups
            # but disallows top-frame navigation via target="_top").
            st.link_button(
                "🔐 Sign in with Google",
                auth_url,
                type="primary",
                use_container_width=True,
            )
    else:
        # Development / Permissive RBAC Simulator mode
        st.markdown(
            """
            <div style="text-align:center;padding:1.5rem 0">
                <h1>🛡️ Zero-Trust Enterprise RAG</h1>
                <span style="background-color:#ffeeba;color:#856404;padding:4px 10px;border-radius:12px;font-size:0.85rem;font-weight:600;">
                    DEVELOPMENT RBAC SIMULATOR (REQUIRE_GOOGLE_AUTH=false)
                </span>
                <p style="color:gray;margin-top:0.5rem">
                    Google OAuth is disabled for this environment. Select or enter test user roles below to evaluate zero-trust retrieval policies.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.divider()

        col_l, col_c, col_r = st.columns([1, 2, 1])
        with col_c:
            with st.form("dev_login_form"):
                dev_email = st.text_input(
                    "👤 Test User Identity (Email)",
                    value="dev-engineer@enterprise.internal",
                    help="Simulated email identity for audit trails and RBAC evaluation.",
                )
                
                sorted_roles = sorted(list(KNOWN_ROLES))
                selected_roles = st.multiselect(
                    "🔑 Application Roles",
                    options=sorted_roles,
                    default=["engineer"],
                    help="Roles that will be evaluated directly against PostgreSQL allowed_roles arrays.",
                )

                custom_role = st.text_input(
                    "➕ Add Custom Role (Optional)",
                    placeholder="e.g. security_auditor",
                    help="Add any additional or non-standard role claim.",
                )

                submitted = st.form_submit_button(
                    "🚀 Enter Knowledge Workspace",
                    type="primary",
                    use_container_width=True,
                )

                if submitted:
                    effective_roles = list(selected_roles)
                    if custom_role and custom_role.strip():
                        clean_custom = custom_role.strip().lower()
                        if clean_custom not in effective_roles:
                            effective_roles.append(clean_custom)

                    now = _time.time()
                    st.session_state["authenticated"] = True
                    st.session_state["id_token"] = "mock-dev-token-require-google-auth-false"
                    st.session_state["access_token"] = "mock-dev-access-token"
                    st.session_state["refresh_token"] = ""
                    st.session_state["token_exp"] = now + MAX_SESSION_SECONDS
                    st.session_state["token_iat"] = now
                    st.session_state["auth_time"] = now
                    st.session_state["login_time"] = now
                    st.session_state["last_activity"] = now
                    st.session_state["user_sub"] = f"dev-user-{dev_email}"
                    st.session_state["user_email"] = dev_email
                    st.session_state["user_name"] = dev_email.split("@")[0].replace(".", " ").title()
                    st.session_state["user_picture"] = ""
                    st.session_state["app_roles"] = effective_roles
                    st.session_state.pop("_just_signed_out", None)
                    st.rerun()

    st.divider()
    st.caption(
        "Architected by **Ken Wong** | "
        "[LinkedIn](https://linkedin.com/in/kenwong-architect) | "
        "[GitHub](https://github.com/Kenono2000/enterprise-rag-pgvector-rbac)"
    )


def _render_user_header() -> None:
    """Show the signed-in user's identity in the sidebar."""
    with st.sidebar:
        picture = st.session_state.get("user_picture", "")
        name = st.session_state.get("user_name", "")
        email = st.session_state.get("user_email", "")
        roles = st.session_state.get("app_roles", [])
        if not roles and email:
            roles = extract_roles({"sub": st.session_state.get("user_sub", ""), "email": email})
            logger.info("Extracted roles 2: %s", roles)
            st.session_state["app_roles"] = roles

        if picture:
            st.image(picture, width=64)
        st.markdown(f"**{name}**")
        st.caption(email)
        st.divider()
        st.markdown("**Application Roles**")
        google_auth_required = _is_google_auth_required()
        if not google_auth_required:
            sorted_known = sorted(list(KNOWN_ROLES))
            # Merge current roles with known roles for multi-select options
            all_opts = sorted(list(set(sorted_known + roles)))
            new_roles = st.multiselect(
                "Modify Active Roles (Dev Mode)",
                options=all_opts,
                default=roles if all(r in all_opts for r in roles) else sorted_known[:1],
                help="Switch roles live to simulate different access levels without logging out.",
                key="dev_sidebar_role_select",
            )
            if new_roles != roles:
                st.session_state["app_roles"] = new_roles
                st.rerun()
        else:
            if roles:
                for r in roles:
                    st.badge(r, icon="🔑")
            else:
                st.warning("No application roles assigned.\nContact your administrator.")

        st.divider()
        if google_auth_required:
            with st.expander("🔑 Copy Google ID Token"):
                st.code(st.session_state.get("id_token", ""), language="text")
                st.caption("Paste into Swagger UI (`/docs`) → **Authorize** button.")

            st.divider()
            st.markdown("**⏱️ Session & Token Security**")
            now = _time.time()
            token_exp = st.session_state.get("token_exp", 0)
            mins_left = max(0, int((token_exp - now) / 60)) if token_exp else 60
            login_mins_ago = int((now - st.session_state.get("login_time", now)) / 60)

            st.caption(f"• **Session**: Active ({login_mins_ago}m elapsed)")
            st.caption(f"• **ID Token TTL**: ~{mins_left}m remaining")
            st.caption("• **Idle Timeout**: 15m limit (SOC-2)")
        else:
            with st.expander("🛠️ Dev Mode Active"):
                st.caption(
                    "Google authentication is disabled (`REQUIRE_GOOGLE_AUTH=false`). "
                    "Use the role picker above to simulate any RBAC access level in realtime."
                )


        if st.session_state.get("refresh_token"):
            st.caption("• **Refresh Token**: Stored (Offline Access)")
            if st.button("🔄 Silent Token Refresh", use_container_width=True):
                with st.spinner("Exchanging refresh token for fresh ID token..."):
                    refreshed = _refresh_id_token_sync(st.session_state["refresh_token"])
                    if refreshed and "id_token" in refreshed:
                        new_id = refreshed["id_token"]
                        payload = verify_google_token(new_id)
                        st.session_state["id_token"] = new_id
                        st.session_state["token_exp"] = payload.get("exp", 0)
                        st.session_state["app_roles"] = extract_roles(payload)
                        now_t = _time.time()
                        st.session_state["last_activity"] = now_t
                        st.session_state["_cookie_to_set"] = encode_session_cookie({
                            "sub": st.session_state.get("user_sub"),
                            "email": st.session_state.get("user_email"),
                            "name": st.session_state.get("user_name"),
                            "picture": st.session_state.get("user_picture"),
                            "roles": st.session_state.get("app_roles", []),
                            "id_token": new_id,
                            "access_token": st.session_state.get("access_token", ""),
                            "refresh_token": st.session_state.get("refresh_token", ""),
                            "token_exp": payload.get("exp", 0),
                            "token_iat": payload.get("iat", 0),
                            "auth_time": st.session_state.get("auth_time", now_t),
                            "login_time": st.session_state.get("login_time", now_t),
                            "last_activity": now_t,
                        }, ttl_seconds=MAX_SESSION_SECONDS)
                        st.success("✅ ID token refreshed silently!")
                        st.rerun()
                    else:
                        st.error("Failed to refresh token: server rejected grant.")

        st.divider()
        if st.button("Sign out", use_container_width=True):
            _clear_auth()
            st.rerun()


def _render_rag_interface() -> None:
    """Main RAG search UI — only shown when authenticated."""
    roles: list[str] = st.session_state.get("app_roles", [])
    if not roles and st.session_state.get("user_email"):
        roles = extract_roles({"sub": st.session_state.get("user_sub", ""), "email": st.session_state.get
        ("user_email")})
        logger.info("Extracted roles 3: %s", roles)
        st.session_state["app_roles"] = roles


    st.title("🛡️ Zero-Trust Enterprise RAG")
    google_auth_required = _is_google_auth_required()
    if google_auth_required:
        st.markdown(
            "Authenticated via Google OAuth 2.0 PKCE. "
            "Your role claims are enforced **inside the SQL query** — the LLM never sees "
            "documents outside your access domain."
        )
        st.subheader("1. Identity & Access")
        st.info(
            f"🔑 **Verified Google Identity:** `{st.session_state.get('user_email', 'unknown')}`  \n"
            f"📋 **Active JWT Role Claims:** `{roles}`"
        )
    else:
        st.markdown(
            "Running in **Development RBAC Simulation Mode** (`REQUIRE_GOOGLE_AUTH=false`). "
            "Your simulated role claims are enforced **inside the SQL query** — the LLM never sees "
            "documents outside your active role domain."
        )
        st.subheader("1. Identity & Access")
        st.info(
            f"👤 **Simulated User Identity:** `{st.session_state.get('user_email', 'dev-user')}`  \n"
            f"📋 **Active Evaluated Roles:** `{roles}`"
        )


    # -------------------------------------------------------------
    # 2. Interactive Conversational Chat Interface
    # -------------------------------------------------------------
    st.subheader("💬 Enterprise Knowledge Chat")
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": "👋 Hello! Ask me any questions about enterprise documentation. Access is automatically governed by your verified roles.",
                "citations": [],
                "sql": None,
            }
        ]
    with st.sidebar:
        if st.button("🗑️ Clear Chat History", use_container_width=True):
            st.session_state.messages = [
                {
                    "role": "assistant",
                    "content": "👋 Chat history cleared. How can I help you?",
                    "citations": [],
                    "sql": None,
                }
            ]
            st.rerun()

    # Render chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("citations"):
                with st.expander("📚 Sources & Citations", expanded=False):
                    for cit in msg["citations"]:
                        st.markdown(f"- **{cit.get('title', 'Document')}** (Confidence: `{float(cit.get('similarity', 0.0)):.2f}`)")
                        st.caption(cit.get("content", "")[:250] + "...")
            if msg.get("sql"):
                with st.expander("🔍 Executed RBAC Query", expanded=False):
                    st.code(msg["sql"], language="sql")

    # Chat input
    if prompt_input := st.chat_input("Ask a question about internal documentation..."):
        t_start_chat = time.perf_counter()
        st.session_state.messages.append({"role": "user", "content": prompt_input})
        with st.chat_message("user"):
            st.markdown(prompt_input)


        with st.chat_message("assistant"):
            with st.status("Querying knowledge base...", expanded=True) as status:
                async def perform_search():
                    await DatabaseManager.get_pool()
                    emb = await generate_embedding(prompt_input)
                    rows = await DatabaseManager.hybrid_search(prompt_input, emb, roles, limit=3)
                    if not rows:
                        rows = await DatabaseManager.secure_search(emb, roles, limit=3)
                    if not rows:
                        return None
                    context = "\n\n".join(
                        f"[Doc: {r['title']}, Chunk {r.get('chunk_index', 0)}]:\n{r['content']}"
                        for r in rows
                    )
                    system_prompt = (
                        "You are an enterprise zero-trust AI assistant.\n"
                        "Answer the user's question by synthesizing information from the authorized context chunks below.\n"
                        "Cite sources in the format [Doc: <Title>, Chunk <Index>].\n"
                        "Only state 'I do not have sufficient information in the authorized documents to answer this question.' "
                        "if the authorized context is completely silent or irrelevant to the question."
                    )
                    prompt = f"{system_prompt}\n\nContext:\n{context}\n\nQuestion: {prompt_input}\nAnswer:"
                    return {
                        "prompt": prompt,
                        "rows": rows,
                        "avg_conf": sum(float(r["similarity"]) for r in rows) / len(rows),
                    }


                result = run_async(perform_search())
                roles_repr = json.dumps(roles)
                sql_query = (
                    "-- 1. Dense Vector Retrieval (HNSW Cosine Similarity)\n"
                    "SELECT c.id, d.document_id, d.title, c.chunk_index, c.content,\n"
                    "       1 - (c.embedding <=> $1::vector) AS similarity\n"
                    "FROM document_chunks c\n"
                    "JOIN documents d ON c.document_id = d.id\n"
                    "WHERE d.allowed_roles ?| $2::text[]\n"
                    "ORDER BY c.embedding <=> $1::vector LIMIT 6;\n\n"
                    "-- 2. Sparse Full-Text Retrieval (GIN tsvector / ts_rank)\n"
                    "SELECT c.id, d.document_id, d.title, c.chunk_index, c.content,\n"
                    "       ts_rank(c.tsv, plainto_tsquery('english', $3)) AS text_rank\n"
                    "FROM document_chunks c\n"
                    "JOIN documents d ON c.document_id = d.id\n"
                    "WHERE d.allowed_roles ?| $2::text[]\n"
                    "  AND c.tsv @@ plainto_tsquery('english', $3)\n"
                    "ORDER BY text_rank DESC LIMIT 6;\n\n"
                    "-- 3. Reciprocal Rank Fusion: RRF_Score = sum( 1 / (60 + rank) )\n"
                    f"-- Parameter bindings: $1=<1536-dim vector>, $2={roles_repr}, $3={json.dumps(prompt_input)}"
                )
                if not result:
                    status.update(label="Access Denied / Not Found", state="error", expanded=False)
                    response_text = (
                        "⚠️ No authorized documentation found matching your security credentials. "
                        f"The roles `{roles}` are not authorized to access matching documents."
                    )
                    st.markdown(response_text)
                    citations = []
                else:
                    status.update(label="Response Streaming", state="complete", expanded=False)
                    response_text = st.write_stream(chat_completion_stream_sync(result["prompt"]))
                    citations = result["rows"]

                chat_duration_ms = round((time.perf_counter() - t_start_chat) * 1000, 2)
                tracer.record_chat_interaction(
                    question=prompt_input,
                    answer=response_text,
                    roles=roles,
                    duration_ms=chat_duration_ms,
                    model="gpt-4o",
                )


            if citations:
                with st.expander("📚 Sources & Citations", expanded=False):
                    for row in citations:
                        rrf_str = f", RRF: `{float(row.get('rrf_score', 0.0)):.4f}`" if "rrf_score" in row else ""
                        st.markdown(
                            f"- **{row['title']}** (Chunk {row.get('chunk_index', 0)}, Confidence: `{float(row['similarity']):.2f}`{rrf_str})"
                        )
                        st.caption(row["content"][:250] + "...")
            with st.expander("🔍 Executed RBAC Query (Hybrid & RRF)", expanded=False):
                st.code(sql_query, language="sql")

        st.session_state.messages.append({
            "role": "assistant",
            "content": response_text,
            "citations": citations,
            "sql": sql_query,
        })

    # Educational Architectural Deep Dive
    st.divider()
    with st.expander("🎓 Cryptographic Token & Session Architecture (Deep Dive)", expanded=False):
        st.markdown(
            """
            ### 🛡️ Enterprise Token Architecture & Session Security
            
            This application implements the standard three-tier cryptographic security model:

            | Token Type | Purpose | Standard Lifetime | Storage Location |
            | :--- | :--- | :--- | :--- |
            | **ID Token (OIDC)** | Cryptographic user identity & verified `app_roles` | 15–60 min | Streamlit Session State (In-Memory) |
            | **Access Token (OAuth 2.0)** | Scoped authorization bearer token for APIs | 15–60 min | Ephemeral client memory |
            | **Refresh Token (OAuth 2.0)** | Silent minting of new tokens without credentials | 30 days | Identity Provider DB / Server Session |

            #### ⏱️ SessionIdleManager & Regulatory Compliance (SOC-2 / HIPAA)
            1. **15-Minute Inactivity Timeout**: Monitors keyboard, mouse, and touch events in the browser. If 15 minutes of zero interaction elapse, the session is terminated and client credentials are wiped.
            2. **12-Hour Absolute Session Ceiling**: Regardless of user activity, sessions cannot exceed 12 hours without re-authentication.
            3. **Silent Token Refresh**: When the short-lived ID token approaches expiration, the client silently contacts Google's `/token` endpoint with the refresh token to extend access without interrupting the user.
            4. **In-Database RBAC Defense**: Even with a valid cryptographic token, users can only access documents where `allowed_roles ?| $user_roles`.
            """
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    st.set_page_config(
        page_title="Zero-Trust RAG | Ken Wong",
        page_icon="🛡️",
        layout="centered",
    )

    # 1. Handle the OAuth callback if ?code= is in URL params
    _handle_oauth_callback()

    # 2. Rehydrate session from secure browser cookie if unauthenticated (survives browser refresh)
    _restore_session_from_cookie()

    # 3. Evaluate SessionIdleManager invariants (inactivity timeout & max session lifetime)
    if not _check_session_lifecycle():
        return

    if not _is_authenticated():
        _render_sign_in_page()
    else:
        # Inject client-side DOM activity tracking & cookie syncer
        _render_session_tracker_component()
        _render_user_header()
        _render_rag_interface()


if __name__ == "__main__":
    main()
else:
    # Streamlit runs the module directly — call main() at module level
    main()
