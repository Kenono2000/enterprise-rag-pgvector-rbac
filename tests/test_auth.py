"""
tests/test_auth.py
------------------
Unit tests for the app/auth/ layer.

These tests run fully offline — no network calls, no real Google tokens.
JWT signing is done locally with a freshly-generated RSA key pair; JWKS
patching is handled via unittest.mock.patch.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ── PKCE helpers ─────────────────────────────────────────────────────────────
from app.auth.pkce import (
    build_authorization_url,
    decode_pkce_state,
    decode_session_cookie,
    derive_code_challenge,
    encode_pkce_state,
    encode_session_cookie,
    generate_code_verifier,
)

# ── Role mapper ───────────────────────────────────────────────────────────────
from app.auth.role_mapper import KNOWN_ROLES, extract_roles


# ===========================================================================
# PKCE
# ===========================================================================


class TestCodeVerifier:
    def test_default_length(self):
        v = generate_code_verifier()
        assert 43 <= len(v) <= 128

    def test_custom_length(self):
        v = generate_code_verifier(64)
        assert len(v) == 64

    def test_url_safe_chars(self):
        v = generate_code_verifier()
        # URL-safe base64: A-Z a-z 0-9 - _
        assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in v)

    def test_invalid_length(self):
        with pytest.raises(ValueError):
            generate_code_verifier(10)


class TestCodeChallenge:
    def test_s256_derivation(self):
        verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        # Expected: SHA256(verifier) |> base64url strip padding
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        assert derive_code_challenge(verifier) == expected

    def test_different_verifiers_produce_different_challenges(self):
        v1 = generate_code_verifier()
        v2 = generate_code_verifier()
        assert derive_code_challenge(v1) != derive_code_challenge(v2)


class TestBuildAuthorizationUrl:
    def test_basic_url_structure(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
        url, verifier, state = build_authorization_url(redirect_uri="http://localhost:8501/")

        assert "accounts.google.com" in url
        assert "code_challenge=" in url
        assert "code_challenge_method=S256" in url
        assert "response_type=code" in url
        assert "test-client-id" in url
        assert len(verifier) >= 43
        assert len(state) >= 8

    def test_state_is_unique(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
        _, _, state1 = build_authorization_url(redirect_uri="http://localhost:8501/")
        _, _, state2 = build_authorization_url(redirect_uri="http://localhost:8501/")
        assert state1 != state2

    def test_missing_client_id_raises(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
        with pytest.raises(ValueError, match="GOOGLE_CLIENT_ID"):
            build_authorization_url(redirect_uri="http://localhost:8501/")

    def test_hd_param_included(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
        url, _, _ = build_authorization_url(
            redirect_uri="http://localhost:8501/",
            hd="acme.com",
        )
        assert "hd=acme.com" in url


class TestStatelessPkceState:
    def test_encode_and_decode_success(self):
        verifier = generate_code_verifier()
        state = encode_pkce_state(verifier)
        recovered = decode_pkce_state(state)
        assert recovered == verifier

    def test_decode_tampered_state_returns_none(self):
        verifier = generate_code_verifier()
        state = encode_pkce_state(verifier)
        # Tamper with the state
        tampered = state[:-4] + "xxxx"
        assert decode_pkce_state(tampered) is None

    def test_decode_expired_state_returns_none(self):
        verifier = generate_code_verifier()
        state = encode_pkce_state(verifier)
        # Test with max_age_seconds = -1 to simulate expiration
        assert decode_pkce_state(state, max_age_seconds=-1) is None

    def test_decode_invalid_format_returns_none(self):
        assert decode_pkce_state("no_dot_here") is None
        assert decode_pkce_state("") is None
        assert decode_pkce_state(None) is None


# ===========================================================================
# Role mapper
# ===========================================================================



class TestExtractRoles:
    def test_custom_claims_respected(self):
        payload = {"sub": "u1", "app_roles": ["engineer", "hr_manager"]}
        assert set(extract_roles(payload)) == {"engineer", "hr_manager"}

    def test_unknown_roles_filtered(self):
        payload = {"sub": "u1", "app_roles": ["engineer", "super_admin_unknown"]}
        roles = extract_roles(payload)
        assert "super_admin_unknown" not in roles
        assert "engineer" in roles

    def test_no_claims_returns_empty(self):
        payload = {"sub": "u1", "email": "user@unknown-domain.xyz"}
        roles = extract_roles(payload)
        assert roles == []

    def test_email_fallback_domain(self, monkeypatch):
        monkeypatch.setenv("ROLE_MAP_engineer", "@acme.com")
        # Force reload of the cached env map
        import app.auth.role_mapper as rm
        rm._ENV_ROLE_MAP = {}

        payload = {"sub": "u1", "email": "alice@acme.com"}
        roles = extract_roles(payload)
        assert "engineer" in roles

    def test_email_fallback_exact(self, monkeypatch):
        monkeypatch.setenv("ROLE_MAP_finance_executive", "cfo@acme.com")
        import app.auth.role_mapper as rm
        rm._ENV_ROLE_MAP = {}

        payload = {"sub": "u1", "email": "cfo@acme.com"}
        roles = extract_roles(payload)
        assert "finance_executive" in roles

    def test_standard_roles_claim_extracted(self):
        payload = {"sub": "u1", "roles": ["finance_executive"]}
        assert extract_roles(payload) == ["finance_executive"]

    def test_groups_claim_extracted(self):
        payload = {"sub": "u1", "groups": ["compliance_auditor", "executive"]}
        assert extract_roles(payload) == ["compliance_auditor", "executive"]

    def test_cognito_and_realm_access_extracted(self):
        payload = {
            "sub": "u1",
            "cognito:groups": ["engineer"],
            "realm_access": {"roles": ["hr_manager"]},
        }
        assert set(extract_roles(payload)) == {"engineer", "hr_manager"}

    def test_comma_separated_and_case_insensitive(self):
        payload = {"sub": "u1", "roles": "ENGINEER, Finance_Executive "}
        assert extract_roles(payload) == ["engineer", "finance_executive"]

    def test_sql_injection_payloads_filtered(self):
        injection_payloads = [
            "engineer' OR '1'='1",
            "'; DROP TABLE enterprise_documents; --",
            "admin' UNION SELECT * FROM users --",
            "engineer\" OR 1=1 --",
            "' OR 1=1/*",
        ]
        payload = {"sub": "attacker", "roles": injection_payloads}
        assert extract_roles(payload) == []

    def test_all_known_roles_are_valid(self):
        """Sanity check: all KNOWN_ROLES match the DB schema values."""
        expected = {"finance_executive", "compliance_auditor", "hr_manager", "executive", "engineer"}
        assert KNOWN_ROLES == expected


class TestJwksTokenValidation:
    def test_unauthorized_issuer_rejected(self, monkeypatch):
        import jwt as pyjwt
        from app.auth.jwks import verify_jwt_token

        monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
        # Token with unauthorized evil issuer
        fake_token = pyjwt.encode(
            {"iss": "https://evil-attacker.com", "sub": "attacker", "aud": "test-client-id"},
            "secret",
            algorithm="HS256",
        )
        with pytest.raises(pyjwt.InvalidTokenError, match="Unexpected token issuer"):
            verify_jwt_token(fake_token)

    def test_enterprise_issuer_allowed_when_configured(self, monkeypatch):
        from app.auth.jwks import get_allowed_issuers

        monkeypatch.setenv("ENTERPRISE_OIDC_ISSUER", "https://login.microsoftonline.com/tenant-id/v2.0")
        issuers = get_allowed_issuers("my-client-id")
        assert "https://login.microsoftonline.com/tenant-id/v2.0" in issuers


class TestSessionCookie:
    def test_roundtrip_valid_payload(self):
        data = {
            "sub": "user-12345",
            "email": "analyst@example.com",
            "name": "Jane Analyst",
            "roles": ["finance_executive", "compliance_auditor"],
            "id_token": "mock.id.token",
            "refresh_token": "mock.refresh.token",
        }
        cookie = encode_session_cookie(data, ttl_seconds=3600)
        assert isinstance(cookie, str)
        assert "." in cookie

        restored = decode_session_cookie(cookie)
        assert restored == data

    def test_tampered_signature_rejected(self):
        data = {"sub": "user-12345", "roles": ["engineer"]}
        cookie = encode_session_cookie(data)
        b64, sig = cookie.rsplit(".", 1)
        tampered = f"{b64}.{'0' * len(sig)}"
        assert decode_session_cookie(tampered) is None

    def test_expired_cookie_rejected(self):
        data = {"sub": "user-12345"}
        # Negative TTL ensures immediate expiration
        cookie = encode_session_cookie(data, ttl_seconds=-10)
        assert decode_session_cookie(cookie) is None

    def test_malformed_cookie_rejected(self):
        assert decode_session_cookie("") is None
        assert decode_session_cookie("invalid_string_without_dot") is None
        assert decode_session_cookie("invalid.sig") is None


class TestDynamicGoogleCredentials:
    def test_get_credentials_from_secrets_dict(self, monkeypatch):
        import sys
        mock_st = MagicMock()
        mock_st.secrets = {
            "gcp_service_account": {
                "type": "service_account",
                "project_id": "test-project",
                "private_key": "-----BEGIN PRIVATE KEY-----\nMOCK\n-----END PRIVATE KEY-----\n",
                "client_email": "test@test-project.iam.gserviceaccount.com",
            }
        }
        monkeypatch.setitem(sys.modules, "streamlit", mock_st)

        from app.auth.role_mapper import _get_google_credentials_dict
        creds = _get_google_credentials_dict()
        assert creds is not None
        assert creds["project_id"] == "test-project"

    def test_get_credentials_from_json_string(self, monkeypatch):
        import sys
        payload = {
            "type": "service_account",
            "project_id": "json-project",
            "private_key": "dummy_key",
        }
        mock_st = MagicMock()
        mock_st.secrets = {"GOOGLE_CREDENTIALS_JSON": json.dumps(payload)}
        monkeypatch.setitem(sys.modules, "streamlit", mock_st)

        from app.auth.role_mapper import _get_google_credentials_dict
        creds = _get_google_credentials_dict()
        assert creds is not None
        assert creds["project_id"] == "json-project"

    def test_ensure_google_application_credentials_synthesizes_file(self, monkeypatch):
        import sys, os
        payload = {
            "type": "service_account",
            "project_id": "temp-file-project",
            "private_key": "dummy_key",
        }
        mock_st = MagicMock()
        mock_st.secrets = {"gcp_service_account": payload}
        monkeypatch.setitem(sys.modules, "streamlit", mock_st)
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_PATH", raising=False)

        import app.auth.role_mapper as rm
        rm._TEMP_CREDENTIALS_FILE = None
        path = rm.ensure_google_application_credentials()
        assert path is not None
        assert os.path.exists(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data["project_id"] == "temp-file-project"


