"""
tests/test_role_sanitization_contract.py
----------------------------------------
Regression suite pinning the *unified* role-sanitization contract.

The Zero-Trust RBAC invariant ("defense-in-depth role sanitization shared by
every retrieval path") historically lived as six duplicated copies of the same
list comprehension: ``app/db/manager.py``, the Azure / GCP / Databricks cloud
adapters, and the two REST legacy-header paths (``app/main.py``,
``app/api/rag.py``). Duplication let the contract drift between engines — a
silent divergence would mean one backend enforces a stricter role grammar than
the others. This suite pins the *single canonical implementation*
(``app.auth.role_mapper.sanitize_roles_for_query``) from every call site so
any future divergence fails CI immediately.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.auth.role_mapper import KNOWN_ROLES, sanitize_roles_for_query
from app.db.adapters import (
    AzureSearchAdapter,
    DatabricksSearchAdapter,
    GCPSearchAdapter,
    PgvectorSearchAdapter,
)
from app.db.manager import DatabaseManager

# Every role the application knows how to pronounce.
KNOWN_ROLE_SAMPLE = sorted(KNOWN_ROLES)[0]

MALICIOUS_PAYLOADS = [
    "'; DROP TABLE documents; --",
    "' OR '1'='1",
    "admin\" OR 1=1 --",
    "engineer; --",
    "role with space",
    "role\nnewline",
    "tab\trole",
    "123-leading-digit",
    "-dash-leading",
    "",
    "   ",
]

NON_STRING_CLAIMS = [None, 42, 3.14, True, {"role": "engineer"}, ["nested"]]


# ==============================================================================
# Canonical contract (app/auth/role_mapper.py)
# ==============================================================================


class TestCanonicalSanitizationContract:
    def test_known_roles_survive_intact(self):
        roles = ["engineer", "admin", "finance_executive"]
        assert sanitize_roles_for_query(roles) == roles

    def test_identifier_roles_survive(self):
        assert sanitize_roles_for_query(["my_custom_role"]) == ["my_custom_role"]

    def test_whitespace_is_stripped(self):
        assert sanitize_roles_for_query(["  engineer  "]) == ["engineer"]

    def test_malicious_payloads_are_dropped(self):
        for payload in MALICIOUS_PAYLOADS:
            assert sanitize_roles_for_query([payload]) == [], payload

    def test_non_string_claims_are_dropped(self):
        assert sanitize_roles_for_query(NON_STRING_CLAIMS) == []

    def test_mixed_input_keeps_only_valid_roles(self):
        mixed = ["engineer", "'; DROP TABLE", "", None, "finance_executive", "bad role"]
        assert sanitize_roles_for_query(mixed) == ["engineer", "finance_executive"]

    def test_empty_iterable_returns_empty(self):
        assert sanitize_roles_for_query([]) == []

    def test_non_iterable_input_fails_closed(self):
        """A non-list claim (string, dict, None) must never explode or pass."""
        assert sanitize_roles_for_query("engineer") == []
        assert sanitize_roles_for_query(None) == []
        assert sanitize_roles_for_query({"role": "engineer"}) == []

    def test_all_known_roles_accepted(self):
        # Sanitization preserves input order (sets iterate nondeterministically),
        # so compare membership rather than list equality.
        result = sanitize_roles_for_query(list(KNOWN_ROLES))
        assert set(result) == set(KNOWN_ROLES)
        assert len(result) == len(KNOWN_ROLES)

    def test_returns_new_list_not_input_alias(self):
        original = ["engineer"]
        result = sanitize_roles_for_query(original)
        assert result == original
        assert result is not original


# ==============================================================================
# DatabaseManager delegation (pgvector path)
# ==============================================================================


class TestDatabaseManagerDelegatesToCanonical:
    def test_manager_method_matches_canonical(self):
        for sample in (["engineer"], MALICIOUS_PAYLOADS, NON_STRING_CLAIMS, [], None):
            assert DatabaseManager.sanitize_roles_for_query(sample) == sanitize_roles_for_query(sample)

    @pytest.mark.asyncio
    async def test_manager_secure_search_fail_closed_on_all_malicious(self):
        """All-malicious roles sanitize to [] -> short-circuit without pool access."""
        with patch.object(DatabaseManager, "get_pool", new_callable=AsyncMock) as mock_pool:
            results = await DatabaseManager.secure_search(
                query_vector=[0.1] * 1536,
                user_roles=MALICIOUS_PAYLOADS,
                limit=5,
            )
        assert results == []
        mock_pool.assert_not_called()

    @pytest.mark.asyncio
    async def test_manager_hybrid_search_fail_closed_on_all_malicious(self):
        with patch.object(DatabaseManager, "get_pool", new_callable=AsyncMock) as mock_pool:
            results = await DatabaseManager.hybrid_search(
                query_text="q",
                query_vector=[0.1] * 1536,
                user_roles=MALICIOUS_PAYLOADS,
                limit=5,
            )
        assert results == []
        mock_pool.assert_not_called()


# ==============================================================================
# Cloud adapters (Azure / GCP / Databricks) share the identical contract
# ==============================================================================


class TestCloudAdaptersShareCanonicalContract:
    @pytest.mark.asyncio
    async def test_azure_adapter_fail_closed_on_malicious(self):
        with patch("app.db.azure_search.get_search_client") as mock_client_factory:
            results = await AzureSearchAdapter().search(
                query_text="secret",
                query_vector=[0.1] * 1536,
                user_roles=MALICIOUS_PAYLOADS,
                limit=3,
            )
        assert results == []
        mock_client_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_gcp_adapter_fail_closed_on_malicious(self):
        with patch("app.db.gcp_search.get_gcp_vector_client") as mock_client_factory:
            results = await GCPSearchAdapter().search(
                query_text="secret",
                query_vector=[0.1] * 1536,
                user_roles=MALICIOUS_PAYLOADS,
                limit=3,
            )
        assert results == []
        mock_client_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_databricks_adapter_fail_closed_on_malicious(self):
        with patch("app.db.databricks_search.get_databricks_vector_client") as mock_client_factory:
            results = await DatabricksSearchAdapter().search(
                query_text="secret",
                query_vector=[0.1] * 1536,
                user_roles=MALICIOUS_PAYLOADS,
                limit=3,
            )
        assert results == []
        mock_client_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_azure_adapter_passes_sanitized_roles_to_engine(self):
        """Sanitized (valid) roles must reach the OData filter construction."""
        captured = {}

        class _FakeClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *exc):
                return False
            async def search(self, **kwargs):
                captured["filter"] = kwargs["filter"]
                async def _aiter():
                    return
                    yield
                return _aiter()

        with patch("app.db.azure_search.get_search_client", return_value=_FakeClient()):
            await AzureSearchAdapter().search(
                query_text="q",
                query_vector=[0.1] * 1536,
                user_roles=["engineer", "'; DROP TABLE"],
                limit=3,
            )
        assert "engineer" in captured["filter"]
        assert "DROP" not in captured["filter"]

    @pytest.mark.asyncio
    async def test_gcp_adapter_restricts_use_sanitized_roles(self):
        captured = {}

        class _FakeGCP:
            async def find_neighbors(self, query_vector, restricts, limit):
                captured["restricts"] = restricts
                return []

        with patch("app.db.gcp_search.get_gcp_vector_client", return_value=_FakeGCP()):
            await GCPSearchAdapter().search(
                query_text="q",
                query_vector=[0.1] * 1536,
                user_roles=["engineer", "x; DROP"],
                limit=3,
            )
        assert captured["restricts"][0]["allowList"] == ["engineer"]

    @pytest.mark.asyncio
    async def test_databricks_adapter_filters_use_sanitized_roles(self):
        import json

        captured = {}

        class _FakeDatabricks:
            async def query_index(self, **kwargs):
                captured["filters_json"] = kwargs["filters_json"]
                return []

        with patch("app.db.databricks_search.get_databricks_vector_client", return_value=_FakeDatabricks()):
            await DatabricksSearchAdapter().search(
                query_text="q",
                query_vector=[0.1] * 1536,
                user_roles=["engineer", "x; DROP"],
                limit=3,
            )
        filters = json.loads(captured["filters_json"])
        assert filters == {"allowed_roles": "engineer"}

    @pytest.mark.asyncio
    async def test_pgvector_adapter_delegates_to_manager_sanitization(self):
        """The pgvector adapter must inherit the same contract via secure_search."""
        with patch.object(DatabaseManager, "secure_search", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []
            await PgvectorSearchAdapter().search(
                query_text="q",
                query_vector=[0.1] * 1536,
                user_roles=MALICIOUS_PAYLOADS,
                limit=3,
            )
        # secure_search is called with the *raw* roles; its own fail-closed
        # sanitization (pinned above) handles the filtering.
        mock_search.assert_awaited_once()


# ==============================================================================
# REST legacy-header paths (app/main.py, app/api/rag.py)
# ==============================================================================


class TestRestLegacyHeaderPathsShareContract:
    @pytest.fixture()
    def client(self):
        from app.main import app
        from fastapi.testclient import TestClient

        return TestClient(app)

    def _post(self, client, path, roles_header):
        import json

        return client.post(
            path,
            json={"question": "What is zero trust?"},
            headers={"X-User-Roles": json.dumps(roles_header)},
        )

    def test_main_query_drops_malicious_header_roles(self, client):
        with patch("app.main.generate_embedding", new_callable=AsyncMock) as mock_emb, patch(
            "app.main.DatabaseManager.secure_search", new_callable=AsyncMock
        ) as mock_search, patch(
            "app.main.chat_completion", new_callable=AsyncMock
        ) as mock_chat, patch(
            "app.main.DatabaseManager.check_token_limit", new_callable=AsyncMock
        ) as mock_limit, patch(
            "app.main.DatabaseManager.record_token_consumption", new_callable=AsyncMock
        ):
            mock_emb.return_value = [0.1] * 1536
            mock_search.return_value = []
            mock_chat.return_value = "mock answer"
            mock_limit.return_value = (True, 0, 50000, True, None)

            response = self._post(client, "/api/v1/query", MALICIOUS_PAYLOADS + ["engineer"])
            assert response.status_code == 200
            body = response.json()
            # Only the valid role survives; every payload is dropped.
            assert body["authorized_roles_evaluated"] == ["engineer"]

    def test_api_rag_query_drops_malicious_header_roles(self, client):
        with patch("app.api.rag.generate_embedding", new_callable=AsyncMock) as mock_emb, patch(
            "app.api.rag.DatabaseManager.secure_search", new_callable=AsyncMock
        ) as mock_search, patch(
            "app.api.rag.chat_completion", new_callable=AsyncMock
        ) as mock_chat, patch(
            "app.api.rag.DatabaseManager.check_token_limit", new_callable=AsyncMock
        ) as mock_limit, patch(
            "app.api.rag.DatabaseManager.record_token_consumption", new_callable=AsyncMock
        ):
            mock_emb.return_value = [0.1] * 1536
            mock_search.return_value = []
            mock_chat.return_value = "mock answer"
            mock_limit.return_value = (True, 0, 50000, True, None)

            response = self._post(client, "/api/v1/query", MALICIOUS_PAYLOADS + ["engineer"])
            assert response.status_code == 200
            body = response.json()
            assert body["authorized_roles_evaluated"] == ["engineer"]

    def test_main_query_empty_after_sanitization_returns_no_hits(self, client):
        """All-malicious header roles sanitize to [] -> no authorized docs."""
        with patch("app.main.generate_embedding", new_callable=AsyncMock) as mock_emb, patch(
            "app.main.DatabaseManager.secure_search", new_callable=AsyncMock
        ) as mock_search, patch(
            "app.main.chat_completion", new_callable=AsyncMock
        ) as mock_chat, patch(
            "app.main.DatabaseManager.check_token_limit", new_callable=AsyncMock
        ) as mock_limit, patch(
            "app.main.DatabaseManager.record_token_consumption", new_callable=AsyncMock
        ):
            mock_emb.return_value = [0.1] * 1536
            mock_search.return_value = []
            mock_chat.return_value = "mock answer"
            mock_limit.return_value = (True, 0, 50000, True, None)

            response = self._post(client, "/api/v1/query", MALICIOUS_PAYLOADS)
            assert response.status_code == 200
            body = response.json()
            assert body["authorized_roles_evaluated"] == []
            assert body["citations"] == []

    def test_malformed_header_json_still_rejected_401(self, client):
        """Non-JSON X-User-Roles header must not 500 (legacy compat contract)."""
        response = client.post(
            "/api/v1/query",
            json={"question": "hi"},
            headers={"X-User-Roles": "not-json"},
        )
        assert response.status_code in (400, 401, 422)
