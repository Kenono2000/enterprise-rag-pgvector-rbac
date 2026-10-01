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
import logging
import os
import urllib.parse
from typing import Optional
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(), override=True)

import streamlit as st

from app.auth import (
    verify_google_token,
    build_authorization_url,
    decode_pkce_state,
    exchange_code_for_tokens_sync,
    extract_roles,
)
from app.db import DatabaseManager, generate_embedding, chat_completion


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    value = os.getenv(key)
    if not value:
        try:
            value = st.secrets.get(key)  # type: ignore[attr-defined]
        except Exception:
            pass
    return value


def run_async(coro):
    """Run an async coroutine from synchronous Streamlit context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _get_redirect_uri() -> str:
    uri = _secret("GOOGLE_REDIRECT_URI")
    if not uri:
        # Fallback: derive from Streamlit's own URL if running on Cloud
        # In local dev this becomes http://localhost:8501/
        uri = "http://localhost:8501/"
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

    # Persist identity in session_state
    st.session_state["authenticated"] = True
    st.session_state["id_token"] = id_token
    st.session_state["user_sub"] = payload.get("sub")
    st.session_state["user_email"] = payload.get("email", "")
    st.session_state["user_name"] = payload.get("name", payload.get("email", ""))
    st.session_state["user_picture"] = payload.get("picture", "")
    st.session_state["app_roles"] = roles

    # Remove ?code= from URL (cleaner UX, prevents double-exchange on refresh)
    st.query_params.clear()

    st.rerun()



def _clear_auth() -> None:
    for key in [
        "authenticated", "id_token", "user_sub", "user_email",
        "user_name", "user_picture", "app_roles",
    ]:
        st.session_state.pop(key, None)


def _is_authenticated() -> bool:
    return bool(st.session_state.get("authenticated"))


# ---------------------------------------------------------------------------
# UI Sections
# ---------------------------------------------------------------------------


def _render_sign_in_page() -> None:
    """Show the sign-in card when the user is not authenticated."""
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

        # Direct styled button targeting top window:
        # Avoids iframe issues, executes in one click, and ensures top-level browser navigation.
        st.markdown(
            f"""
            <a href="{auth_url}" target="_top" style="
                display: block;
                width: 100%;
                text-align: center;
                background-color: #FF4B4B;
                color: white !important;
                padding: 0.65rem 1rem;
                border-radius: 0.5rem;
                text-decoration: none;
                font-weight: 600;
                font-size: 1rem;
                border: none;
                box-shadow: 0 1px 2px rgba(0,0,0,0.1);
            ">
                🔐 Sign in with Google
            </a>
            """,
            unsafe_allow_html=True,
        )


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
        if roles:
            for r in roles:
                st.badge(r, icon="🔑")
        else:
            st.warning("No application roles assigned.\nContact your administrator.")
        st.divider()
        with st.expander("🔑 Copy Google ID Token"):
            st.code(st.session_state.get("id_token", ""), language="text")
            st.caption("Paste into Swagger UI (`/docs`) → **Authorize** button.")
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

    st.subheader("2. Secure Grounded Retrieval")
    question = st.text_input(
        "Enter Question:",
        value="What were the Q3 financial results and margins?",
    )

    if st.button("🚀 Execute Zero-Trust Vector Search", type="primary"):
        if not roles:
            st.error(
                "⛔ Your Google account has no application roles assigned. "
                "Ask an administrator to set `app_roles` custom claims in Firebase."
            )
            return

        with st.status("Executing Zero-Trust Vector Search…", expanded=True) as status:
            st.write("Generating embedding via OpenAI…")

            async def perform_search():
                await DatabaseManager.get_pool()
                query_vector = await generate_embedding(question)
                rows = await DatabaseManager.secure_search(query_vector, roles)

                if not rows:
                    return None

                context = "\n\n".join(
                    [f"[{r['title']}]: {r['content']}" for r in rows]
                )
                prompt = f"Answer strictly using context:\n\n{context}\n\nQuestion: {question}"
                answer = await chat_completion(prompt)
                return {
                    "answer": answer,
                    "rows": rows,
                    "avg_conf": sum(float(r["similarity"]) for r in rows) / len(rows),
                }

            result = run_async(perform_search())

            # Show the RBAC SQL for transparency
            roles_sql = ", ".join(f"'{r}'" for r in roles)
            sql_query = (
                f"SELECT * FROM enterprise_documents\n"
                f"WHERE allowed_roles ?| ARRAY[{roles_sql}]\n"
                f"ORDER BY embedding <=> <vector> LIMIT 3"
            )
            st.code(sql_query, language="sql")

            if not result:
                status.update(label="Access Denied", state="error", expanded=True)
                st.error("No authorized documentation found matching your security credentials.")
                st.warning(
                    f"🛡️ **Security Note:** The roles `{roles}` are not authorised "
                    "to access any stored documents."
                )
            else:
                status.update(label="Authorization Verified", state="complete", expanded=True)
                st.success("✅ Authorization Verified: Document Grounded Successfully")

                st.markdown("### Grounded Answer")
                st.write(result["answer"])

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Citations Found", len(result["rows"]))
                with col2:
                    st.metric("Avg Confidence", f"{result['avg_conf']:.3f}")
                with col3:
                    st.metric("RLS Policy", "Active", delta="Protected")

                st.markdown("### 📚 Authorized Citations")
                for doc in result["rows"]:
                    with st.container(border=True):
                        c1, c2 = st.columns([3, 1])
                        with c1:
                            st.markdown(f"**{doc['title']}**")
                            st.caption(f"ID: `{doc['document_id']}`")
                        with c2:
                            st.code(f"Sim: {float(doc['similarity']):.3f}")
                        with st.expander("View Source Snippet", expanded=True):
                            st.text(doc["content"])

                import datetime
                with st.expander("📊 View Audit Citation & Scopes", expanded=True):
                    st.json({
                        "user_sub": st.session_state.get("user_sub"),
                        "user_email": st.session_state.get("user_email"),
                        "authorized_roles_evaluated": roles,
                        "confidence_score": result["avg_conf"],
                        "data_leakage_prevented": True,
                        "auth_method": "google_oauth2_pkce",
                        "engine": "pgvector-rls-production",
                        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    st.set_page_config(
        page_title="Zero-Trust RAG | Ken Wong",
        page_icon="🛡️",
        layout="centered",
    )

    # Handle the OAuth callback before rendering anything else
    _handle_oauth_callback()

    if not _is_authenticated():
        _render_sign_in_page()
    else:
        _render_user_header()
        _render_rag_interface()


if __name__ == "__main__":
    main()
else:
    # Streamlit runs the module directly — call main() at module level
    main()
